"""Isolated browser fixture; fixed synthetic analysis, never invokes a model."""
import argparse
import datetime
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True)
    parser.add_argument('--port', required=True, type=int)
    args = parser.parse_args()
    directory = pathlib.Path(args.data).resolve()
    if directory == ROOT or directory == pathlib.Path.home(): raise SystemExit('必须使用隔离临时目录')
    directory.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ,RESEARCH_DESK_DATA_DIR=str(directory),PORT=str(args.port))
    subprocess.run([sys.executable,str(ROOT/'launcher.py'),'--no-open','--port',str(args.port)],env=env,check=True)
    token = (directory/'api-token').read_text().strip()
    base = 'http://127.0.0.1:'+str(args.port)
    def request(path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base+path,data=data,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        return json.load(urllib.request.urlopen(req))
    request('/api/action',{'collection':'projects','item':{'id':'manager-demo','name':'隔离测试 · 自主管理交接','goal':'核对交接协议；固定测试回包不是科学结果','stages':['验证']}})
    request('/api/action',{'collection':'tasks','item':{'id':'demo-task','project':'manager-demo','title':'核查合成测试记录','status':'受阻','note':'没有运行研究实验，不得宣称科学PASS'}})
    signature = request('/api/project/manager?project_id=manager-demo')['source_hash']
    output = {'summary':'固定合成测试回包：任务受阻，科学结果未知。','changes':'建立测试项目基线。',
              'risks':'尚无真实实验依据。','next_step':'只读核对合成测试记录并报告未知。','human_decision':'确认一次只读核查，不授权研究实验。'}
    with sqlite3.connect(directory/'manager.sqlite3') as c:
        c.execute("INSERT OR REPLACE INTO policies VALUES('manager-demo',1,1,1)")
        job = c.execute("INSERT INTO jobs(project,signature,generation,state,available,input,output,day) VALUES('manager-demo',?,1,'succeeded',0,'{}',?,?)",
                        (signature,json.dumps(output),datetime.date.today().isoformat())).lastrowid
        c.execute("INSERT INTO handoffs(job_id,project,signature,state,suggestion) VALUES(?,'manager-demo',?,'draft',?)",(job,signature,output['next_step']))
    print('Fixture ready: '+base+' ; synthetic model output; daily budget exhausted; no real model calls')
