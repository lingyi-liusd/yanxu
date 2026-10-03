"""Manual, isolated live-UI demo of the actual stdio MCP -> Gateway path.

Use only with a throwaway Research Desk data dir/project. It pauses while the
browser is checked for Running, then records a software-only INCONCLUSIVE
result and finishes. No scientific project data is touched.
"""
import datetime
import json
import os
import pathlib
import subprocess
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = os.environ['RESEARCH_DESK_BASE_URL']
DATA = pathlib.Path(os.environ['RESEARCH_DESK_DATA_DIR'])
PROJECT = os.environ['RESEARCH_DESK_PROJECT_ID']
TASK = os.environ['RESEARCH_DESK_TASK_ID']
HUMAN_TOKEN = (DATA/'api-token').read_text().strip()


def human(path, body=None):
    payload = None if body is None else json.dumps(body,ensure_ascii=False).encode()
    request = urllib.request.Request(BASE+path,data=payload,headers={'Authorization':'Bearer '+HUMAN_TOKEN,'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=10) as response:
        return json.loads(response.read())


connection=human('/api/agents/connect',{'project_id':PROJECT,'name':'Codex','permission':'EXECUTE'})
agent_token=connection['token']


def mcp(name,arguments):
    env=os.environ.copy()
    env['RESEARCH_DESK_AGENT_TOKEN']=agent_token
    lines=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{}},
           {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':name,'arguments':arguments}}]
    run=subprocess.run(['node',str(ROOT/'mcp-server.js')],input='\n'.join(json.dumps(x,ensure_ascii=False) for x in lines)+'\n',text=True,capture_output=True,env=env,timeout=12,check=True)
    result=next(json.loads(line)['result'] for line in run.stdout.splitlines() if json.loads(line).get('id')==2)
    if result.get('isError'): raise RuntimeError(result['content'][0]['text'])
    return json.loads(result['content'][0]['text'])


context=mcp('research.get_project_context',{})
assert context['project']['id']==PROJECT
claim=mcp('research.claim_action',{'task_id':TASK,'reason':'验证真实 MCP→Gateway→SSE→Today 链路','expected_output':'软件集成测试记录','budget':{'max_progress_reports':3}})
aid=claim['action_id']
mcp('research.report_activity',{'action_id':aid,'phase':'start','summary':'Codex 已连接，开始核对软件事件链'})
mcp('research.report_activity',{'action_id':aid,'phase':'progress','summary':'握手与 Running 状态已写入事件流'})
print('DEMO_RUNNING',datetime.datetime.now().astimezone().isoformat(timespec='seconds'),'agent=Codex','action='+aid,flush=True)
input('Inspect Today in browser, then press Enter to finish demo: ')
result=mcp('research.record_result',{'action_id':aid,'outcome':'INCONCLUSIVE','summary':'软件事件链路已验证；不构成任何科研 PASS','source_ref':'tests/demo_ai_native.py','source_version':'2026-09-30','evidence_title':'软件链路演示回执'})
focus=human('/api/research-focus?scope='+PROJECT)
assert not focus['needs_generation'] and focus['focus']
print('DEMO_FINISHED',datetime.datetime.now().astimezone().isoformat(timespec='seconds'),'result='+result['result_id'],'evidence='+result['evidence_id'],'focus='+focus['focus']['focus_id'],'status='+result['delivery_status'],flush=True)
