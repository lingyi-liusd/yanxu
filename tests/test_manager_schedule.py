"""Synthetic clock and model: cadence/unlimited checks never invoke real Codex."""
import copy
import datetime
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agent_manager import Manager


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.values={'project':{'id':'p','goal':'保留原目标'},'tasks':[]}
        self.calls=[]
        # Keep the 25 quarter-hour calls within one local date in every timezone.
        self.now=datetime.datetime(2033,5,18,8,0).timestamp()
        self.clock=patch('agent_manager.time.time',side_effect=lambda:self.now)
        self.clock.start()
        self.m=self.make()

    def tearDown(self):
        self.clock.stop();self.tmp.cleanup()

    def make(self):
        def runner(snapshot):
            self.calls.append(snapshot)
            return {key:'未核验' for key in ('summary','changes','risks','next_step','human_decision')}
        return Manager(self.tmp.name,lambda _:copy.deepcopy(self.values),lambda *a:None,runner,debounce=0)

    def enable(self,minutes=30):
        return self.m.configure('p',{'enabled':True,'max_calls_per_day':None,
            'summary_interval_minutes':minutes,'consent':'codex-project-records-v1',
            'schedule_consent':'scheduled-codex-management-v1'})

    def schedule(self,minutes=30,**extra):
        return self.m.configure_schedule('p',dict(project_id='p',max_calls_per_day=None,
            summary_interval_minutes=minutes,if_schedule_revision=self.m.status('p')['schedule_revision'],
            schedule_consent='scheduled-codex-management-v1',**extra))

    def test_default_ui_policy_is_unlimited_but_disabled(self):
        s=self.m.status('p');self.assertIsNone(s['max_calls_per_day'])
        self.assertEqual(s['summary_interval_minutes'],30);self.assertFalse(s['enabled'])
        self.m.tick();self.assertFalse(self.calls)

    def test_time_gate_coalesces_latest_changes_and_empty_windows_skip(self):
        self.enable();self.m.tick();self.assertFalse(self.calls)
        for title in ('a','b','c'):
            self.values['tasks']=[{'id':'t','title':title}];self.m.tick()
        self.now+=1799;self.m.tick();self.assertFalse(self.calls)
        self.now+=1;self.m.tick();self.assertEqual(len(self.calls),1)
        self.assertEqual(self.calls[0]['current']['tasks'][0]['title'],'c')
        self.now+=1800;self.m.tick();self.assertEqual(len(self.calls),1)
        next_due=self.m.status('p')['next_summary_at'];self.assertIsNotNone(next_due)
        self.values['tasks'][0]['title']='after-empty-window';self.m.tick()
        self.assertEqual(len(self.calls),1)
        self.now+=1800;self.m.tick();self.assertEqual(len(self.calls),2)

    def test_unlimited_does_not_stop_at_four_or_twenty_and_usage_is_kept(self):
        self.enable(15)
        for i in range(25):
            self.values['tasks']=[{'id':'t','title':str(i)}];self.now+=900;self.m.tick()
        s=self.m.status('p');self.assertEqual(len(self.calls),25);self.assertEqual(s['used_today'],25)
        self.assertIsNone(s['max_calls_per_day']);self.assertIsNone(s['resume_brief']['handoff']['management_budget']['remaining_calls'])
        self.assertTrue(s['resume_brief']['handoff']['management_budget']['unlimited'])

    def test_daily_usage_rolls_over_without_erasing_previous_calls(self):
        self.now=datetime.datetime(2033,5,18,23,30).timestamp()
        self.enable(15)
        for title in ('before-midnight','after-midnight'):
            self.values['tasks']=[{'id':'t','title':title}]
            self.now+=900;self.m.tick()
            self.assertEqual(self.m.status('p')['used_today'],1)
        self.assertEqual(len(self.calls),2)
        with self.m.db() as c:
            rows=c.execute('SELECT day,count(*) FROM call_usage GROUP BY day ORDER BY day').fetchall()
        self.assertEqual([(r[0],r[1]) for r in rows],[('2033-05-18',1),('2033-05-19',1)])

    def test_cap_and_schedule_change_preserves_generation_queue_failure_and_usage(self):
        self.m.configure('p',{'enabled':True,'max_calls_per_day':1,'consent':'codex-project-records-v1'})
        def fail(snapshot):
            self.calls.append(snapshot);raise RuntimeError('synthetic fail')
        self.m.runner=fail;self.m.tick()
        self.values['tasks']=[{'id':'pending'}];self.m.tick()
        before=self.m.status('p');queued=before['jobs'][0]['id']
        with self.m.db() as c:gen=c.execute('SELECT generation FROM policies').fetchone()[0]
        preview=self.schedule(15,dry=True);self.assertTrue(preview['preview'])
        self.assertEqual(self.m.status('p')['max_calls_per_day'],1)
        self.schedule(15)
        with self.m.db() as c:self.assertEqual(c.execute('SELECT generation FROM policies').fetchone()[0],gen)
        self.assertEqual(self.m.status('p')['jobs'][0]['id'],queued)
        self.assertEqual(self.m.status('p')['used_today'],1)
        self.m.tick();self.assertEqual(len(self.calls),1)
        self.m.runner=self.make().runner;self.now+=900;self.m.tick()
        self.assertEqual(len(self.calls),2);self.m.tick();self.assertEqual(len(self.calls),2)
        self.assertTrue(any(j['state']=='failed' for j in self.m.status('p')['jobs']))

    def test_revision_invalid_intervals_and_consent_are_checked(self):
        self.enable();old_revision=self.m.status('p')['schedule_revision'];self.schedule(60)
        with self.assertRaises(ValueError):
            self.m.configure_schedule('p',{'max_calls_per_day':None,'summary_interval_minutes':15,
                'if_schedule_revision':old_revision,'schedule_consent':'scheduled-codex-management-v1'})
        for interval in (0,-1,1441,1.5,True,'15',None):
            with self.assertRaises(ValueError):self.schedule(interval)
        with self.assertRaises(ValueError):self.m.configure('p',{'enabled':True,'max_calls_per_day':None,'summary_interval_minutes':30,'consent':'codex-project-records-v1'})

    def test_restart_keeps_schedule_and_pause_still_stops_new_calls(self):
        self.enable(60);before=self.m.status('p');self.m=self.make()
        self.assertEqual(self.m.status('p')['next_summary_at'],before['next_summary_at'])
        self.now+=3599;self.m.tick();self.assertFalse(self.calls)
        self.m.configure('p',{'enabled':False,'max_calls_per_day':None,'summary_interval_minutes':60})
        self.now+=3601;self.m.tick();self.assertFalse(self.calls)
        self.assertIsNone(self.m.status('p')['max_calls_per_day'])

    def test_failed_scheduled_summary_never_retries_same_input(self):
        self.enable(15)
        def fail(snapshot):self.calls.append(snapshot);raise RuntimeError('synthetic fail')
        self.m.runner=fail;self.now+=900;self.m.tick()
        for _ in range(4):self.now+=900;self.m.tick()
        self.assertEqual(len(self.calls),1);self.assertEqual(self.m.status('p')['jobs'][0]['state'],'failed')

    def test_legacy_schema_and_explicit_limit_remain_compatible(self):
        self.tmp.cleanup();self.tmp=tempfile.TemporaryDirectory()
        with sqlite3.connect(Path(self.tmp.name)/'manager.sqlite3') as c:
            c.execute('CREATE TABLE policies(project TEXT PRIMARY KEY,enabled INTEGER,budget INTEGER,generation INTEGER DEFAULT 0)')
            c.execute('INSERT INTO policies VALUES(?,?,?,?)',('p',1,4,7))
        self.m=self.make();s=self.m.status('p')
        self.assertEqual(s['base_calls_per_day'],4);self.assertEqual(s['summary_interval_minutes'],0)
        with self.m.db() as c:self.assertEqual(c.execute('SELECT generation FROM policies').fetchone()[0],7)


if __name__=='__main__':unittest.main()
