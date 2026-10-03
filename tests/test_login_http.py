import unittest
import test_agent_gateway as support

class LoginHTTPTests(unittest.TestCase):
    setUp=support.AgentGatewayCase.setUp
    tearDown=support.AgentGatewayCase.tearDown
    request=support.AgentGatewayCase.request
    def test_login_requires_human_scope_and_enabled_connection(self):
        body={'if_revision':0,'consent':'codex-browser-login-v1'}
        self.assertEqual(self.request('/api/agent-connection/login',body,token=self.agent_token)[0],401)
        self.assertEqual(self.request('/api/agent-connection/login',body)[0],400)
        code,_,status=self.request('/api/agent-connection')
        self.assertEqual(code,200);self.assertFalse(status['enabled'])
        self.assertNotIn('auth_url',status);self.assertEqual(status['revision'],0)

if __name__=='__main__':unittest.main()
