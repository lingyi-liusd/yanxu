import unittest, json, os, threading, subprocess, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import test_agent_gateway as gateway
class ConnectionBoundaries(unittest.TestCase):
 setUp=gateway.AgentGatewayCase.setUp
 tearDown=gateway.AgentGatewayCase.tearDown
 request=gateway.AgentGatewayCase.request
 agent=gateway.AgentGatewayCase.agent
 mcp=gateway.AgentGatewayCase.mcp
 def test_retries_do_not_duplicate_action_or_result(self):
  body={'title':'retry fixture','reason':'test','expected_output':'one result'}
  code,_,claim=self.agent('activity',dict(body,phase='claim'));self.assertEqual(code,200)
  self.assertEqual(self.agent('activity',dict(body,phase='claim'))[0],409)
  aid=claim['action_id'];self.agent('activity',{'phase':'start','action_id':aid,'summary':'start'})
  result={'action_id':aid,'outcome':'failure','summary':'negative fixture','source_ref':'isolated://retry','source_version':'v1'}
  self.assertEqual(self.agent('result',result)[0],200);self.assertEqual(self.agent('result',result)[0],409)
  records=self.request('/api/backup')[2]['gateway'];self.assertEqual(len(records['actions']),1);self.assertEqual(len(records['action_results']),1)
 def test_disconnected_status_keeps_action_and_context_reconnects(self):
  aid=self.agent('activity',{'phase':'claim','title':'connection fixture','reason':'test','expected_output':'record'})[2]['action_id']
  self.agent('activity',{'phase':'start','action_id':aid,'summary':'start'})
  import sqlite3
  with sqlite3.connect(self.dir/'desk.sqlite3') as c:c.execute("UPDATE agents SET last_seen='2000-01-01T00:00:00+00:00'")
  self.assertFalse(self.request('/api/agents')[2]['agents'][0]['connected'])
  self.assertEqual(self.request('/api/backup')[2]['gateway']['actions'][0]['status'],'running')
  self.assertEqual(self.agent('context')[0],200)
  self.assertTrue(self.request('/api/agents')[2]['agents'][0]['connected'])
 def test_mcp_network_failure_and_recovery(self):
  self.assertIn('project',self.mcp('project.get_context'))
  self.proc.terminate();self.proc.wait(timeout=3)
  env=os.environ.copy();env.update(RESEARCH_DESK_BASE_URL=self.base,RESEARCH_DESK_AGENT_TOKEN=self.agent_token)
  msg={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'project.get_context','arguments':{}}}
  run=subprocess.run(['node',str(gateway.ROOT/'mcp-server.js')],input=json.dumps(msg)+'\n',text=True,capture_output=True,env=env,timeout=3)
  self.assertTrue(json.loads(run.stdout)['result']['isError'])
  import sys
  env.update(RESEARCH_DESK_DATA_DIR=str(self.dir),PORT=str(self.port))
  self.proc=subprocess.Popen([sys.executable,str(gateway.ROOT/'server.py')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  for attempt in range(30):
   try:
    if self.request('/api/state')[0]==200:break
   except Exception:time.sleep(.1)
  self.assertEqual(self.mcp('project.get_context')['project']['id'],'p1')
class TimeoutCase(unittest.TestCase):
 def test_hung_server_returns_bounded_error(self):
  class Silent(BaseHTTPRequestHandler):
   def do_GET(self):time.sleep(.6)
   def log_message(self,*args):pass
  server=ThreadingHTTPServer(('127.0.0.1',0),Silent);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  env=os.environ.copy();env.update(RESEARCH_DESK_AGENT_TOKEN='disposable-fixture',RESEARCH_DESK_BASE_URL='http://127.0.0.1:'+str(server.server_port),RESEARCH_DESK_HTTP_TIMEOUT_MS='100')
  msg={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'project.get_context','arguments':{}}}
  try:
   run=subprocess.run(['node',str(gateway.ROOT/'mcp-server.js')],input=json.dumps(msg)+'\n',text=True,capture_output=True,env=env,timeout=3)
   out=json.loads(run.stdout)['result'];self.assertTrue(out['isError']);self.assertIn('超时',out['content'][0]['text'])
  finally:server.shutdown();server.server_close()
