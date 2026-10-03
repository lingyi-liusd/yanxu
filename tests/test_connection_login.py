import pathlib
import sys
import tempfile
import time
import unittest
from unittest import mock
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from test_agent_connection import FakeRPC
import agent_connection as runtime

class LoginRPC(FakeRPC):
    signed_in = False
    url = 'https://auth.openai.com/authorize?state=private'
    def call(self, method, params, timeout=15):
        if method == 'account/read':
            self.calls.append((method, params))
            return {'account':{'type':'chatgpt'} if self.signed_in else None}
        if method == 'account/login/start':
            self.calls.append((method, params))
            return {'loginId':'login-1','authUrl':self.url}
        return super().call(method,params,timeout)

class LoginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.profile = mock.patch.object(runtime,'profile',return_value={})
        self.profile.start()
        self.conn = runtime.Connection(self.tmp.name,factory=LoginRPC)
        self.body = {'if_revision':1,'consent':'codex-browser-login-v1'}
    def tearDown(self):
        self.conn.close()
        if self.conn.worker:self.conn.worker.join(timeout=2)
        self.profile.stop();self.tmp.cleanup()
    def enable(self):
        self.conn.configure({'enabled':True,'if_revision':0,'consent':'codex-persistent-management-v1'})
        end=time.monotonic()+3
        while not self.conn.client and time.monotonic()<end:time.sleep(.01)
        self.assertIsNotNone(self.conn.client)
    def test_login_reuses_pending_and_promotes_only_after_account_read(self):
        self.enable();c=self.conn
        self.assertEqual(c.state,'needs_login');self.assertFalse(c.available())
        first=c.login(self.body);self.assertEqual(c.login(self.body),first)
        self.assertEqual([m for m,_ in c.client.calls].count('account/login/start'),1)
        self.assertNotIn('private',str(c.status()))
        client=c.client;client.signed_in=True;c.wake.set()
        end=time.monotonic()+3
        while not c.authenticated and time.monotonic()<end:time.sleep(.01)
        self.assertTrue(c.authenticated);self.assertEqual(c.state,'idle')
        self.assertIs(c.client,client);self.assertIsNone(c.login_url)
        self.assertNotIn('turn/start',[m for m,_ in client.calls])
        self.assertEqual(c.revision,1)
    def test_revision_consent_and_pause_gate(self):
        self.enable()
        for body in ({'if_revision':1},dict(self.body,if_revision=0)):
            with self.assertRaises(ValueError):self.conn.login(body)
        client=self.conn.client
        self.conn.configure({'enabled':False,'if_revision':1})
        with self.assertRaises(ValueError):self.conn.login(dict(self.body,if_revision=2))
        self.assertNotIn('account/login/start',[m for m,_ in client.calls])
    def test_untrusted_url_rejected_without_storage(self):
        self.enable();self.conn.client.url='https://auth.openai.com.evil.test/token'
        with self.assertRaisesRegex(RuntimeError,'安全'):self.conn.login(self.body)
        self.assertIsNone(self.conn.login_url)
    def test_failure_can_be_restarted_explicitly_not_automatically(self):
        self.enable();c=self.conn;c.login(self.body);client=c.client
        client.events.put({'method':'account/login/completed','params':{'loginId':'login-1','success':False,'error':'secret'}})
        end=time.monotonic()+3
        while c.login_url and time.monotonic()<end:time.sleep(.01)
        self.assertIsNone(c.login_url);self.assertEqual(c.state,'needs_login')
        self.assertEqual([m for m,_ in client.calls].count('account/login/start'),1)
        c.login(self.body)
        self.assertEqual([m for m,_ in client.calls].count('account/login/start'),2)

if __name__=='__main__':unittest.main()
