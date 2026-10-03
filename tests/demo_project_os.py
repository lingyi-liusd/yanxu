"""Populate an explicitly isolated Research Desk database for three-project UI QA.

Start server.py with RESEARCH_DESK_DATA_DIR pointing to a directory whose name
contains project-os-demo, then run this script with DEMO_BASE_URL set to its URL.
This utility refuses the default user database and never prints Agent tokens.
"""

import json
import os
import pathlib
import urllib.request


directory = pathlib.Path(os.environ['RESEARCH_DESK_DATA_DIR']).resolve()
if 'project-os-demo' not in directory.name:
    raise SystemExit('Refusing to seed a non-demo data directory')
base = os.environ.get('DEMO_BASE_URL', 'http://127.0.0.1:8877').rstrip('/')
human_token = (directory / 'api-token').read_text().strip()


def request(path, body=None, token=human_token):
    payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=payload, headers={
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read()), int(response.headers.get('X-Rev') or 0)


def action(collection, item):
    _, revision = request('/api/state?slim=1')
    body = {'collection': collection, 'item': item, 'ifRev': revision,
            'actor': 'human', 'summary': '隔离演示数据：' + item.get('name', item.get('title', item['id']))}
    request('/api/action', dict(body, dry=True))
    request('/api/action', body)


projects = [
    {'id': 'demo-research', 'name': '动态车队安全边界', 'type': 'Research',
     'description': '核对动态车队控制中的安全边界。',
     'goal': '形成来源明确、可复核的安全边界结论。',
     'success_definition': '关键条件被独立核验，并记录适用范围。',
     'current_state': '理论条件仍有一个开放缺口。',
     'constraints': ['不得把仿真通过写成物理安全证明'], 'stages': ['问题界定', '理论核验', '结果复核']},
    {'id': 'demo-software', 'name': '账户登录 v1.2', 'type': 'Software',
     'description': '交付稳定的账户登录与回调流程。',
     'goal': '完成登录回调修复并通过端到端测试。',
     'success_definition': '测试通过，回归风险可接受。',
     'current_state': 'OAuth callback 存在竞态条件。',
     'constraints': ['不改动现有用户会话格式'], 'stages': ['定位', '修复', '发布检查']},
    {'id': 'demo-product', 'name': '移动端入门体验', 'type': 'Product',
     'description': '改进新用户首次使用流程。',
     'goal': '明确引导方案并完成小范围验证。',
     'success_definition': '完成设计、反馈收集和方案决策。',
     'current_state': '设计稿已完成，反馈尚未充分。',
     'constraints': ['上线前须获得产品负责人确认'], 'stages': ['发现问题', '设计方案', '验证反馈']},
]

tasks = [
    {'id': 'research-boundary', 'project': 'demo-research', 'title': '核对边界条件',
     'status': '受阻', 'priority': 'P0', 'stage': '理论核验', 'note': '证明条件待独立复核。'},
    {'id': 'software-callback', 'project': 'demo-software', 'title': '修复 callback 竞态',
     'status': '进行中', 'priority': 'P0', 'stage': '修复', 'note': '需要保留现有 session 格式。'},
    {'id': 'product-feedback', 'project': 'demo-product', 'title': '整理首轮用户反馈',
     'status': '进行中', 'priority': 'P1', 'stage': '验证反馈', 'note': '区分观察事实与设计判断。'},
]

state, _ = request('/api/state?slim=1')
if state['projects']:
    raise SystemExit('Demo directory is not empty; refusing to alter it')
for item in projects:
    action('projects', item)
for item in tasks:
    action('tasks', item)

for pid, title, outcome, artifact_type in (
    ('demo-research', '复核边界来源', 'inconclusive', 'report'),
    ('demo-software', '修复登录回调竞态', 'partial', 'code'),
    ('demo-product', '整理首次使用反馈', 'partial', 'design'),
):
    connection, _ = request('/api/agents/connect', {
        'project_id': pid, 'name': 'Codex', 'type': 'coding_agent', 'permission': 'EXECUTE'})
    token = connection['token']
    request('/api/agent/context', token=token)
    claim, _ = request('/api/agent/activity', {
        'phase': 'claim', 'title': title, 'goal': title,
        'reason': '隔离演示项目需要展示可追溯执行链',
        'expected_output': '带版本来源的成果与结果',
        'success_condition': '登记来源并复核',
        'failure_condition': '来源缺失或验证失败',
    }, token)
    aid = claim['action_id']
    request('/api/agent/activity', {'phase': 'start', 'action_id': aid,
                                  'summary': '开始处理：' + title}, token)
    request('/api/agent/artifact', {'action_id': aid, 'type': artifact_type,
        'title': title + '产物', 'reference': 'fixtures/' + pid + '/output.md',
        'source_version': 'demo-v1', 'summary': '仅用于隔离 UI 验收'}, token)
    request('/api/agent/result', {'action_id': aid, 'outcome': outcome,
        'summary': '已记录阶段产物，仍需后续核验',
        'source_ref': 'tests/demo_project_os.py', 'source_version': 'demo-v1'}, token)
    if pid == 'demo-software':
        request('/api/agent/decision-request', {'question': '是否延期支付模块？',
            'context': '登录回调尚未完成全量回归。',
            'options': ['延期', '维持排期'], 'impact': '影响 v1.2 发布范围',
            'blocking': True}, token)

print('Seeded 3 isolated projects at ' + base)
