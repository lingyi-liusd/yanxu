#!/usr/bin/env python3
"""Run an isolated synthetic portfolio demo; no source reading or model calls."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def run(port=None):
    if port is None:
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
    if not 1024 <= port <= 65535:
        raise ValueError('Port must be between 1024 and 65535')
    with tempfile.TemporaryDirectory(prefix='yanxu-public-demo-') as directory:
        data = Path(directory)
        env = dict(os.environ, RESEARCH_DESK_DATA_DIR=str(data), PORT=str(port),
                   OPEN_BROWSER='0', RESEARCH_DESK_RELEASE='2026.10.08-source-preview.1-demo')
        for key in ('RESEARCH_FOCUS_API_URL', 'RESEARCH_FOCUS_API_KEY', 'RESEARCH_FOCUS_MODEL'):
            env.pop(key, None)
        # All feature policies start disabled in this new profile. No credentials are copied.
        with (data/'server.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable, str(ROOT/'server.py')], cwd=ROOT,
                                       env=env, stdout=log, stderr=log)
        base = 'http://127.0.0.1:' + str(port)
        try:
            def request(path, body=None, token=None):
                payload = None if body is None else json.dumps(body, ensure_ascii=False).encode()
                value = urllib.request.Request(base+path, data=payload, headers={
                    'Authorization':'Bearer '+(token or (data/'api-token').read_text().strip()),
                    'Content-Type':'application/json'})
                with urllib.request.urlopen(value, timeout=10) as response:
                    return json.load(response), int(response.headers.get('X-Rev') or 0)

            deadline = time.monotonic()+15
            while time.monotonic()<deadline:
                if process.poll() is not None:
                    raise RuntimeError('Demo server exited; '+(data/'server.log').read_text()[-1000:])
                if (data/'api-token').exists():
                    try:
                        request('/api/state')
                        break
                    except OSError:
                        pass
                time.sleep(.1)
            else:
                raise RuntimeError('Demo server startup timed out')

            project_id = 'portfolio-demo'
            today = datetime.date.today()
            day = lambda offset: (today+datetime.timedelta(days=offset)).isoformat()
            ops = [
                {'collection':'projects','item':{'id':project_id,'name':'示例 · 个人作品发布',
                 'description':'合成示例：把一个个人工具整理成可运行、可追溯的开源作品。',
                 'goal':'完成介绍、演示和测试记录，让陌生人能够理解并体验项目。',
                 'success_definition':'能启动示例、找到成果依据，并识别尚未验证的范围。',
                 'current_state':'介绍草稿已保存；演示正在整理；Windows 原生运行尚未验证。',
                 'constraints':['人工合成记录，不代表真人测试或模型输出','保留未验证项，不虚构用户数或收益'],
                 'type':'产品设计','stages':['梳理','实现','验证','发布']}},
                {'collection':'projects','item':{'id':'writing-demo','name':'示例 · 技术文章',
                 'description':'独立的第二个合成项目。','goal':'完成一篇解释本机项目接续的文章。',
                 'stages':['选题','草稿','修改']}},
            ]
            tasks = [
                ('problem','整理问题与核心使用场景','已完成','梳理',-3,-2,[],'记录目标用户和长期工作接续的困扰。'),
                ('prototype','完成三栏原型与数据流','已完成','实现',-2,-1,['problem'],'合成示例中的完成记录，未声明真实验收。'),
                ('demo','整理一个可直接体验的演示','进行中','验证',0,1,['prototype'],'下一步：打开 Today、项目状态和结果来源，确认展示清晰。'),
                ('windows','记录 Windows 安装与退出反馈','待开始','验证',1,3,['demo'],'NOT_RUN：没有 Windows 真机反馈，不把包检查当作运行通过。'),
                ('publish','完善介绍并发布测试版','待开始','发布',2,4,['demo'],'以公开 beta 说明范围。用户收益尚未测试。')]
            for tid,title,status,stage,start,end,deps,note in tasks:
                ops.append({'collection':'tasks','item':{'id':tid,'project':project_id,'title':title,
                            'status':status,'stage':stage,'priority':'P1' if tid=='demo' else 'P2',
                            'start':day(start),'end':day(end),'deps':deps,'note':note,
                            'completed':day(end) if status=='已完成' else ''}})
            ops.append({'collection':'tasks','item':{'id':'writing-outline','project':'writing-demo',
                        'title':'列出文章的三个要点','status':'待开始','priority':'P2','stage':'选题'}})
            _,revision = request('/api/state')
            body = {'ifRev':revision,'ops':ops,'actor':'human','summary':'创建人工合成演示记录'}
            request('/api/action',dict(body,dry=True))
            request('/api/action',body)

            # Use the real project-scoped HTTP workflow with a synthetic, non-model worker.
            connection,_ = request('/api/agents/connect',{'project_id':project_id,
                                    'name':'示例记录器 · 无模型调用','permission':'EXECUTE','contract_mode':'strict_v2'})
            agent_token = connection['token']
            context,_ = request('/api/agent/context',token=agent_token)
            claim,_ = request('/api/agent/activity',{'phase':'claim','task_id':'prototype',
                'context_hash':context['management']['resume_brief']['source_hash'],
                'goal':'记录人工合成的原型整理结果','reason':'演示成果与来源版本的关联',
                'expected_output':'一条带合成来源版本的部分完成记录',
                'success_condition':'保存记录并保留未验证项','failure_condition':'无法登记或丢失来源版本',
                'dependencies':[],'dependency_policy':'recorded','budget':{'max_progress_reports':2},
                'stop_condition':'登记一次结果后结束，不读取来源或调用模型'},token=agent_token)
            aid=claim['action_id']
            request('/api/agent/activity',{'phase':'start','action_id':aid,
                    'summary':'整理示例介绍与界面流程；全部内容为人工合成。'},token=agent_token)
            source='examples/portfolio-brief.md'
            version=hashlib.sha256((ROOT/source).read_bytes()).hexdigest()
            request('/api/agent/artifact',{'action_id':aid,'type':'document','title':'示例 · 产品介绍草稿',
                    'reference':source,'source_version':version,'summary':'人工合成的作品介绍，用于界面走查。'},token=agent_token)
            request('/api/agent/result',{'action_id':aid,'outcome':'partial',
                    'summary':'示例：介绍与界面流程已整理；Windows 原生运行和用户收益仍待验证。',
                    'source_ref':source,'source_version':version,'evidence_title':'合成示例说明',
                    'provenance':'Synthetic fixture; manually scripted; no model calls or user research.'},token=agent_token)
            status,_=request('/api/project/manager?project_id='+project_id)
            if status['enabled'] or status['used_today']:
                raise RuntimeError('Demo must leave AI disabled and model use at zero')
            print('续芽 synthetic demo: '+base,flush=True)
            print('选择「示例 · 个人作品发布」。合成记录 / AI disabled / model calls = 0.',flush=True)
            print('Ctrl-C stops the demo and removes its temporary profile.',flush=True)
            process.wait()
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=None)
    args=parser.parse_args()
    try:
        run(args.port)
    except KeyboardInterrupt:
        print('\nDemo stopped.')
    except (OSError,ValueError,RuntimeError) as error:
        print(str(error),file=sys.stderr)
        raise SystemExit(1)
