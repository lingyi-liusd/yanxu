"""Behavioral checks using synthetic records/executors; no accounts or real model calls."""
import copy
import hashlib
import json
import pathlib
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import agent_gateway
import ecosystem
import project_backup
import radar_fetch


class Executor:
    def __init__(self):
        self.calls = []
        self.accepted = []
        self.error = False
        self.hook = None

    def status(self, project):
        return {'connected': True, 'authenticated': True, 'model_selection': {'models': [{'model': 'model-a'}, {'model': 'model-b'}]}}

    def analyze(self, snapshot, project, generation, purpose, **options):
        with options['send_guard']():
            self.calls.append({'project': project, 'prompt': options['prompt_override'], 'model': options['model_override']})
        if self.hook:
            self.hook()
        if options['cancelled']():
            raise RuntimeError('stopped')
        if self.error:
            raise RuntimeError('synthetic failure')
        return {'position': '合成建议', 'evidence': 'fixture / 未核验', 'objections': '尚未通过真实用户测试', 'next_step': '保留待验证项'}

    def accept(self, *args):
        self.accepted.append(args)


class EcosystemCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tmp.name) / 'test.sqlite3'
        self.emitted = []
        self.executor = Executor()
        with self.connect() as c:
            c.execute('CREATE TABLE state(id INTEGER PRIMARY KEY,body TEXT)')
            c.execute('CREATE TABLE meta(k TEXT PRIMARY KEY,v TEXT)')
            c.execute('CREATE TABLE history(id INTEGER PRIMARY KEY AUTOINCREMENT,body TEXT,time TEXT,actor TEXT,summary TEXT,gateway_body TEXT)')
            state = {'projects': [{'id': p, 'name': p, 'goal': '独立目标 ' + p} for p in ('p1', 'p2')], 'tasks': [], 'files': [], 'decisions': []}
            c.execute('INSERT INTO state VALUES(1,?)', (json.dumps(state),))
            c.execute("INSERT INTO meta VALUES('rev','0')")
            agent_gateway.schema(c)
        self.gateway = agent_gateway.Gateway(self.connect, self.rev, self.bump, lambda state: None, lambda pid: {'focus': None})
        self.eco = ecosystem.Ecosystem(self.connect, self.gateway, self.rev, self.bump, lambda *args: self.emitted.append(args), self.executor)
        # Execute explicit launches deterministically; all side-effect boundaries remain real.
        self.eco.launch = lambda *args: None

    def tearDown(self):
        self.eco.stop.set()
        self.tmp.cleanup()

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path)
        try:
            with c:
                yield c
        finally:
            c.close()

    def rev(self, c):
        return int(c.execute("SELECT v FROM meta WHERE k='rev'").fetchone()[0])

    def bump(self, c):
        value = self.rev(c) + 1
        c.execute("UPDATE meta SET v=? WHERE k='rev'", (str(value),))
        return value

    def post(self, op, project='p1', **values):
        with self.connect() as c:
            rev = self.rev(c)
        return self.eco.post(dict(project_id=project, ifRev=rev, operation=op, **values))['item']

    def profile(self, model='model-a', project='p1', agent=None):
        return self.post('profile.save', project, name='角色 ' + model, instructions='指出证据缺口', engine='external' if agent else 'codex', model=model, agent_id=agent or '')

    def room(self, profiles, max_rounds=2, max_calls=None):
        return self.post('room.create', title='方案讨论', question='如何继续这个项目？', profile_ids=[p['id'] for p in profiles], max_rounds=max_rounds, max_calls=max_calls or len(profiles) * max_rounds)

    def start(self, room):
        return self.post('room.start', id=room['id'], consent='discussion-project-records-v1')

    def get(self, item, kind):
        with self.connect() as c:
            return self.eco.item(c, item['project_id'], item['id'], kind)

    def external(self, name='外部 Agent', project='p1', permission='PROPOSE'):
        aid = name + '-' + project
        with self.connect() as c:
            c.execute('INSERT INTO agents VALUES(?,?,?,?,?,?,?,?,?,?,?)', (aid, project, name, 'external', permission, hashlib.sha256(aid.encode()).hexdigest(), '[]', 'online', None, ecosystem.stamp(), ecosystem.stamp()))
            c.execute('INSERT INTO agent_protocols VALUES(?,?,?)', (aid, 'strict_v2', ecosystem.stamp()))
        return {'id': aid, 'project_id': project, 'permission': permission}

    def test_dry_revision_context_and_tenant_boundaries(self):
        p = self.profile()
        before = self.eco.view('p1')
        body = dict(operation='room.create', project_id='p1', ifRev=before['rev'], title='讨论', question='问题', profile_ids=[p['id']], max_rounds=1)
        preview = self.eco.post(dict(body, dry=True))
        self.assertTrue(preview['preview'])
        self.assertEqual(self.eco.view('p1'), before)
        room = self.eco.post(body)['item']
        with self.assertRaisesRegex(ValueError, '已变化'):
            self.eco.post(body)
        self.assertEqual(self.eco.view('p2')['rooms'], [])
        with self.assertRaises(agent_gateway.GatewayError):
            self.post('room.stop', 'p2', id=room['id'])
        self.assertEqual(before['context']['context_hash'], self.eco.view('p1')['context']['context_hash'])

    def test_first_round_independent_then_prior_context_and_model_selection(self):
        room = self.start(self.room([self.profile('model-a'), self.profile('model-b')]))
        self.eco.run_room('p1', room['id'])
        result = self.get(room, 'room')
        self.assertEqual(result['status'], 'round_complete')
        self.assertEqual(result['used_calls'], 2)
        self.assertEqual([c['model'] for c in self.executor.calls], ['model-a', 'model-b'])
        self.assertNotIn('合成建议', self.executor.calls[1]['prompt'])
        self.start(result)
        self.eco.run_room('p1', room['id'])
        final = self.get(room, 'room')
        self.assertEqual(final['status'], 'completed')
        self.assertEqual(final['used_calls'], 4)
        self.assertIn('合成建议', self.executor.calls[2]['prompt'])
        self.assertTrue(all(m['verification_status'] == 'UNVERIFIED' for m in final['messages']))
        with self.assertRaises(ValueError):
            self.start(final)

    def test_external_agent_identity_duplicate_reply_and_budget(self):
        a, b = self.external('a'), self.external('b')
        room = self.start(self.room([self.profile(agent=a['id']), self.profile(agent=b['id'])], max_calls=3))
        request_a = self.eco.agent_get(a)['requests'][0]
        request_b = self.eco.agent_get(b)['requests'][0]
        self.assertEqual(request_a['previous_messages'], [])
        self.assertEqual(self.eco.agent_get(self.external(project='p2'))['requests'], [])
        output = {key: '未核验的合成回复' for key in ecosystem.REPLY_SCHEMA['required']}
        with self.assertRaises(agent_gateway.GatewayError):
            self.eco.agent_reply(a, dict(request_b, output=output))
        self.eco.agent_reply(a, dict(request_a, output=output))
        self.assertEqual(self.eco.agent_get(b)['requests'][0]['previous_messages'], [])
        with self.assertRaises(ValueError):
            self.eco.agent_reply(a, dict(request_a, output=output))
        self.eco.agent_reply(b, dict(request_b, output=output))
        final = self.get(room, 'room')
        self.assertEqual(final['used_calls'], 2)
        with self.assertRaisesRegex(ValueError, '预算'):
            self.start(final)

    def test_stopping_discards_late_output_and_keeps_consumed_budget(self):
        room = self.start(self.room([self.profile()]))
        self.executor.hook = lambda: self.post('room.stop', id=room['id'])
        self.eco.run_room('p1', room['id'])
        final = self.get(room, 'room')
        self.assertEqual(final['status'], 'stopped')
        self.assertEqual(final['used_calls'], 1)
        self.assertEqual(final['messages'], [])
        with self.assertRaises(ValueError):
            self.start(final)

    def test_failure_no_automatic_replay_and_restart_keeps_outputs(self):
        room = self.start(self.room([self.profile()]))
        self.executor.error = True
        self.eco.run_room('p1', room['id'])
        failed = self.get(room, 'room')
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['used_calls'], 1)
        self.assertEqual(len(self.executor.calls), 1)
        self.assertEqual(len(failed['failures']), 1)
        with self.assertRaises(ValueError):
            self.start(failed)
        active = self.start(self.room([self.profile()]))
        self.eco.start()
        self.assertEqual(self.get(active, 'room')['status'], 'interrupted')
        self.assertEqual(self.get(failed, 'room')['failures'], failed['failures'])
        self.assertEqual(len(self.executor.calls), 1)

    def test_adoption_is_human_versioned_idempotent_and_unverified(self):
        room = self.start(self.room([self.profile()], max_rounds=1))
        self.eco.run_room('p1', room['id'])
        adopted = self.post('room.adopt', id=room['id'], title='执行一个真实用户访谈', rationale='采用小范围验证；模型建议尚未验证', target='task')
        context = self.eco.view('p1')['context']
        self.assertEqual(context['tasks'][0]['verification_status'], 'UNVERIFIED')
        self.assertEqual(context['tasks'][0]['source_ref'], 'yanxu://room/' + room['id'])
        self.assertEqual(context['tasks'][0]['source_version'], adopted['adoptions'][0]['source_version'])
        with self.assertRaises(ValueError):
            self.post('room.adopt', id=room['id'], title='重复', rationale='重复', target='task')
        self.assertEqual(self.eco.view('p2')['context']['tasks'], [])
        with self.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM evidence').fetchone()[0], 0)

    def test_changed_project_context_blocks_send_and_adoption(self):
        room = self.room([self.profile()])
        with self.connect() as c:
            state = self.gateway.state(c)
            state['projects'][0]['goal'] = '新目标'
            c.execute('UPDATE state SET body=? WHERE id=1', (json.dumps(state),))
            self.bump(c)
        self.assertTrue(self.eco.view('p1')['rooms'][0]['context_stale'])
        with self.assertRaisesRegex(ValueError, '上下文已变化'):
            self.start(room)
        self.assertEqual(self.executor.calls, [])

    def test_active_external_request_is_withheld_after_context_change(self):
        agent=self.external('stale')
        room=self.start(self.room([self.profile(agent=agent['id'])]))
        self.assertEqual(len(self.eco.agent_get(agent)['requests']),1)
        with self.connect() as c:
            state=self.gateway.state(c);state['projects'][0]['goal']='新目标'
            c.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(state),));self.bump(c)
        result=self.eco.agent_get(agent)
        self.assertEqual(result['requests'],[]);self.assertEqual(result['warnings'][0]['room_id'],room['id'])

    def test_scheduler_only_launches_enabled_due_sources_and_expires_rooms(self):
        paused=self.watch();due=self.watch()
        due=self.post('watch.save',id=due['id'],name=due['name'],url=due['url'],enabled=True,interval_minutes=60,consent='radar-public-source-v1')
        room=self.start(self.room([self.profile()]))
        with self.connect() as c:
            due['next_check']=0;self.eco.save(c,due,'watch')
            paused['next_check']=0;self.eco.save(c,paused,'watch')
            room['deadline']=0;self.eco.save(c,room,'room')
        calls=[];self.eco.launch=lambda *args:calls.append(args)
        self.eco.tick()
        self.assertEqual(calls,[('p1','watch',due['id'])])
        self.assertEqual(self.get(room,'room')['status'],'failed')
        self.assertEqual(self.get(room,'room')['used_calls'],0)
        self.eco.stop.set();self.eco.tick();self.assertEqual(len(calls),1)

    def watch(self, keywords=None):
        return self.post('watch.save', name='竞品更新', url='https://example.org/news', keywords=keywords or [], interval_minutes=60, enabled=False)

    def snapshot(self, value):
        return {'url': 'https://example.org/news', 'text': value, 'hash': hashlib.sha256(value.encode()).hexdigest(), 'bytes': len(value)}

    def check(self, watch, value):
        self.eco.fetcher = lambda url: self.snapshot(value)
        self.eco.check_watch('p1', watch['id'])

    def test_radar_baseline_diff_no_change_keywords_failure_and_handoff(self):
        watch = self.watch(['模型'])
        self.check(watch, '原记录')
        self.assertEqual(self.eco.view('p1')['alerts'], [])
        self.check(watch, '原记录')
        self.assertEqual(self.eco.view('p1')['alerts'], [])
        self.check(watch, '原记录\n一般更新')
        self.assertEqual(self.eco.view('p1')['alerts'], [])
        self.check(watch, '原记录\n一般更新\n模型更新')
        alert = self.eco.view('p1')['alerts'][0]
        self.assertIn('模型更新', alert['added'])
        self.assertEqual(alert['verification_status'], 'UNVERIFIED')
        self.assertNotEqual(alert['before_hash'], alert['after_hash'])
        before = self.get(watch, 'watch')['snapshot']
        self.eco.fetcher = mock.Mock(side_effect=ValueError('fetch failed'))
        self.eco.check_watch('p1', watch['id'])
        self.assertEqual(self.get(watch, 'watch')['snapshot'], before)
        self.assertEqual(self.get(watch, 'watch')['error'], 'fetch failed')
        room = self.post('room.create', title='变化复核', question='影响何处？', profile_ids=[self.profile()['id']], max_rounds=1, alert_id=alert['id'])
        self.assertEqual(room['source_change']['after_hash'], alert['after_hash'])
        self.assertEqual(self.eco.view('p2')['alerts'], [])
        self.assertNotIn('text', self.eco.view('p1')['watches'][0]['snapshot'])

    def test_reconfigured_watch_discards_inflight_fetch(self):
        watch = self.watch()
        def fetch(url):
            self.post('watch.save', id=watch['id'], name='暂停', url=url, enabled=False, interval_minutes=60)
            return self.snapshot('晚到的文字')
        self.eco.fetcher = fetch
        self.eco.check_watch('p1', watch['id'])
        self.assertNotIn('snapshot', self.get(watch, 'watch'))

    def test_backup_restore_keeps_records_but_revokes_execution_and_polling(self):
        room = self.start(self.room([self.profile()]))
        watch = self.watch()
        self.post('watch.save', id=watch['id'], name=watch['name'], url=watch['url'], enabled=True, interval_minutes=60, consent='radar-public-source-v1')
        with self.connect() as c:
            backup = project_backup.envelope(c)
            project_backup.restore(c, backup['state'], backup['gateway'], portable=True)
        self.assertEqual(self.get(room, 'room')['status'], 'interrupted')
        self.assertFalse(self.get(watch, 'watch')['enabled'])
        with self.connect() as c:
            state = self.gateway.state(c)
            project_backup.delete_project(c, 'p1')
            self.assertEqual(self.eco.items(c, 'p1'), [])
            legacy = copy.deepcopy(backup['gateway'])
            legacy.pop('ecosystem_items')
            project_backup.validate(state, legacy, c, portable=True)

    def test_public_reader_rejects_private_resolution_and_bad_urls(self):
        for value in ('file:///etc/passwd', 'http://127.0.0.1/', 'https://user:password@example.org/', 'http://localhost/', 'http://example.org:8080/', 'http://[::1]/'):
            with self.assertRaises(ValueError):
                radar_fetch.source_url(value)
        with mock.patch.object(radar_fetch.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 80))]):
            with mock.patch.object(radar_fetch.socket, 'create_connection') as connect:
                with self.assertRaisesRegex(ValueError, '非公开'):
                    radar_fetch.fetch_source('http://example.org/')
                connect.assert_not_called()

    def test_backup_rejects_hostile_url_corrupt_context_and_cross_project_role(self):
        self.room([self.profile()]);self.watch()
        with self.connect() as c:
            backup=project_backup.envelope(c)
            for attack in ('url','context','participant'):
                payload=copy.deepcopy(backup['gateway'])
                rows=payload['ecosystem_items']
                row=next(r for r in rows if r['kind']==('watch' if attack=='url' else 'room'))
                item=json.loads(row['body'])
                if attack=='url':item['url']='javascript:alert(1)'
                elif attack=='context':item['context']['project']['goal']='forged goal'
                else:item['participants'][0]['project_id']='p2'
                row['body']=json.dumps(item)
                with self.assertRaises(ValueError):
                    project_backup.validate(backup['state'],payload,c,portable=True)


if __name__ == '__main__':
    unittest.main()
