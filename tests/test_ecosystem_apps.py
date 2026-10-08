"""Independent app spaces and durable source deliveries. Synthetic source/executor only."""
import copy
import json
import threading
import unittest
import urllib.request
import agent_gateway
import ecosystem
import project_backup
import test_ecosystem as core_support
import test_ecosystem_http as http_support

D=ecosystem.APP_SPACES['discussion']
R=ecosystem.APP_SPACES['radar']

class AppsCase(unittest.TestCase):
    setUp=core_support.EcosystemCase.setUp
    tearDown=core_support.EcosystemCase.tearDown
    connect=core_support.EcosystemCase.connect
    rev=core_support.EcosystemCase.rev
    bump=core_support.EcosystemCase.bump
    post=core_support.EcosystemCase.post
    snapshot=core_support.EcosystemCase.snapshot

    def initialize(self):
        with self.connect() as c: rev=self.rev(c)
        body={'ifRev':rev}
        self.eco.init_apps(dict(body,dry=True))
        self.assertFalse(self.eco.apps('discussion')['initialized'])
        self.eco.init_apps(body)

    def source(self, project=R, **values):
        return self.post('watch.save',project,name='合成产品动态',url='https://example.org/news',interval_minutes=60,
                         enabled=False,auto_push=True,push_target='personal',**values)

    def check(self, watch, value):
        self.eco.fetcher=lambda url:self.snapshot(value)
        self.eco.check_watch(watch['project_id'],watch['id'])

    def deliver(self):
        self.initialize();w=self.source();self.check(w,'合成 v1');self.check(w,'合成 v2')
        return self.eco.view(R)['alerts'][0],self.eco.view(D)['inbox'][0]

    def role(self):
        return self.post('profile.save',D,name='合成核查者',engine='codex',model='model-a',instructions='仅检查合成输入')

    def room(self, incoming):
        p=self.role()
        return self.post('room.create',D,title='合成讨论',question='变化是否值得进一步核查？',profile_ids=[p['id']],max_rounds=1,max_calls=1,inbox_id=incoming['id'])

    def test_independent_init_dry_idempotency_and_private_views(self):
        self.initialize()
        before=self.eco.apps('radar')
        self.eco.init_apps({'ifRev':before['rev']})
        self.assertEqual(before,self.eco.apps('radar'))
        self.assertNotIn(D,[p['id'] for p in before['spaces']])
        self.assertIn(R,[p['id'] for p in before['spaces']])
        self.assertIn('p1',[p['id'] for p in before['spaces']])
        with self.connect() as c:
            state=self.gateway.state(c)
        self.assertEqual([p['id'] for p in ecosystem.desk_state(state)['projects']],['p1','p2'])
        with self.assertRaisesRegex(ValueError,'已变化'):
            self.eco.init_apps({'ifRev':0})

    def test_baseline_filters_failure_and_no_model_until_confirmation(self):
        self.initialize();w=self.source(keywords=['模型'])
        self.check(w,'v1');self.check(w,'v1');self.check(w,'v1\n普通更新')
        self.assertEqual(self.eco.view(D)['inbox'],[])
        self.check(w,'v1\n模型更新')
        self.assertEqual(self.eco.view(D)['unread_count'],1)
        self.assertEqual(self.eco.view(D)['rooms'],[])
        self.assertEqual(self.executor.calls,[])
        old=self.eco.view(D)['inbox']
        self.eco.fetcher=lambda url:(_ for _ in ()).throw(ValueError('合成断网'))
        self.eco.check_watch(R,w['id'])
        self.assertEqual(old,self.eco.view(D)['inbox'])
        self.assertEqual(self.executor.calls,[])

    def test_manual_repeated_and_concurrent_delivery_deduplicates(self):
        alert,incoming=self.deliver()
        result=self.post('alert.push',R,id=alert['id'],target=D)
        self.assertEqual(result['id'],incoming['id'])
        self.assertEqual(self.eco.view(D)['unread_count'],1)
        errors=[]
        def push():
            try:
                with self.connect() as c:
                    c.execute('BEGIN IMMEDIATE');self.eco.push(c,alert,D)
            except Exception as e:errors.append(e)
        workers=[threading.Thread(target=push) for _ in range(4)]
        for t in workers:t.start()
        for t in workers:t.join()
        self.assertEqual(errors,[]);self.assertEqual(len(self.eco.view(D)['inbox']),1)
        self.post('inbox.review',D,id=incoming['id'],status='seen')
        self.post('alert.push',R,id=alert['id'],target=D)
        self.assertEqual(self.eco.view(D)['unread_count'],0)
        self.assertEqual(self.executor.calls,[])

    def test_recipient_identity_and_atomic_dry_conversion(self):
        alert,incoming=self.deliver()
        with self.assertRaisesRegex(ValueError,'只能推送'):
            self.post('alert.push',R,id=alert['id'],target='p2')
        with self.assertRaises(agent_gateway.GatewayError):
            self.post('inbox.review','p2',id=incoming['id'],status='seen')
        p=self.role();before=self.eco.view(D)
        body={'operation':'room.create','project_id':D,'ifRev':before['rev'],'title':'复核','question':'问题','profile_ids':[p['id']],'inbox_id':incoming['id']}
        self.eco.post(dict(body,dry=True));self.assertEqual(before,self.eco.view(D))
        room=self.eco.post(body)['item']
        self.assertEqual(room['source_version'],incoming['source_version'])
        self.assertEqual(room['source_change'],incoming['source_change'])
        self.assertEqual(room['status'],'draft');self.assertEqual(room['used_calls'],0)
        self.assertEqual(self.executor.calls,[])
        with self.assertRaisesRegex(ValueError,'已创建讨论'):
            self.eco.post(dict(body,ifRev=self.eco.view(D)['rev']))
        self.assertEqual(self.eco.view(D)['inbox'][0]['room_id'],room['id'])
        self.post('room.start',D,id=room['id'],consent='discussion-project-records-v1')
        self.eco.run_room(D,room['id'])
        self.assertEqual(len(self.executor.calls),1)
        self.assertIn('合成 v2',self.executor.calls[0]['prompt'])

    def test_human_adoption_can_handoff_to_explicit_project_with_version_guard(self):
        _,incoming=self.deliver();room=self.room(incoming)
        with self.assertRaisesRegex(ValueError,'回写项目记录已变化'):
            self.post('room.adopt',D,id=room['id'],title='复核任务',rationale='合成计划，尚未核验',target='task',target_project_id='p1',target_context_hash='old')
        target=self.eco.view('p1')['context']['context_hash']
        saved=self.post('room.adopt',D,id=room['id'],title='复核任务',rationale='合成计划，尚未核验',target='task',target_project_id='p1',target_context_hash=target)
        self.assertEqual(saved['adoptions'][0]['target_project_id'],'p1')
        self.assertEqual(self.eco.view(D)['context']['tasks'],[])
        self.assertEqual(self.eco.view('p1')['context']['tasks'][0]['verification_status'],'UNVERIFIED')
        self.assertEqual(self.executor.calls,[])

    def test_disabled_push_and_configuration_change_discard_inflight(self):
        self.initialize();w=self.source()
        self.check(w,'v1')
        self.post('watch.save',R,id=w['id'],name=w['name'],url=w['url'],auto_push=False,push_target='personal')
        self.check(w,'v2');self.assertEqual(self.eco.view(D)['inbox'],[])
        def fetch(url):
            self.post('watch.save',R,id=w['id'],name=w['name'],url=url,auto_push=True,push_target='personal')
            return self.snapshot('v3')
        self.eco.fetcher=fetch;self.eco.check_watch(R,w['id'])
        self.assertEqual(len(self.eco.view(R)['alerts']),1);self.assertEqual(self.eco.view(D)['inbox'],[])

    def test_restart_restore_and_source_deletion_preserve_delivery(self):
        alert,incoming=self.deliver();room=self.room(incoming)
        self.eco.start()
        self.assertEqual(self.eco.view(D)['inbox'][0]['source_version'],incoming['source_version'])
        self.assertEqual(self.executor.calls,[])
        with self.connect() as c:
            backup=project_backup.envelope(c)
            project_backup.restore(c,backup['state'],backup['gateway'],portable=True)
            project_backup.delete_project(c,R)
            state=self.gateway.state(c);state['projects']=[p for p in state['projects'] if p['id']!=R]
            c.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(state),))
            later=project_backup.envelope(c)
            project_backup.validate(later['state'],later['gateway'],c,portable=True)
        saved=self.eco.view(D)['inbox'][0]
        self.assertFalse(saved['origin_available']);self.assertEqual(saved['room_id'],room['id'])
        self.assertEqual(saved['source_change']['after_hash'],alert['after_hash'])

    def test_backup_tamper_rejected_and_desk_state_cannot_destroy_apps(self):
        _,incoming=self.deliver();self.room(incoming)
        with self.connect() as c:
            backup=project_backup.envelope(c)
            state=self.gateway.state(c)
            preserved=ecosystem.preserve_app_state(ecosystem.desk_state(state),state)
            self.assertEqual(preserved,state)
            with self.assertRaisesRegex(ValueError,'不能'):
                ecosystem.preserve_app_state(state,state)
            for kind in ('inbox','room'):
                records=copy.deepcopy(backup['gateway']);row=next(r for r in records['ecosystem_items'] if r['kind']==kind)
                item=json.loads(row['body']);item['source_change']['added']='被修改的摘录';row['body']=json.dumps(item)
                with self.assertRaises(ValueError):
                    project_backup.validate(backup['state'],records,c,portable=True)

class AppsHTTPCase(unittest.TestCase):
    setUp=http_support.EcosystemHTTPCase.setUp
    tearDown=http_support.EcosystemHTTPCase.tearDown
    request=http_support.EcosystemHTTPCase.request

    def test_standalone_shells_human_api_and_legacy_state_preservation(self):
        for app in ('discussion','radar'):
            with urllib.request.urlopen(self.base+'/apps/'+app+'/') as response:
                page=response.read().decode();self.assertEqual(response.status,200)
            self.assertIn('STANDALONE_APP',page);self.assertNotIn('研序 · Agent 操作约定',page)
        self.assertEqual(self.request('/api/apps?app=discussion',token=self.agent_token)[0],401)
        _,_,meta=self.request('/api/apps?app=discussion')
        code,_,dry=self.request('/api/apps',{'ifRev':meta['rev'],'dry':True});self.assertEqual(code,200,dry)
        _,_,meta=self.request('/api/apps?app=discussion');self.assertFalse(meta['initialized'])
        code,_,value=self.request('/api/apps',{'ifRev':meta['rev']});self.assertEqual(code,200,value)
        _,rev,state=self.request('/api/state');self.assertNotIn(D,[p['id'] for p in state['projects']])
        code,_,value=self.request('/api/state',{'state':state,'ifRev':rev});self.assertEqual(code,200,value)
        _,_,meta=self.request('/api/apps?app=discussion');self.assertTrue(meta['initialized'])
        _,_,backup=self.request('/api/backup');self.assertIn(D,[p['id'] for p in backup['state']['projects']])

if __name__=='__main__':unittest.main()
