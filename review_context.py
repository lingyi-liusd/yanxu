"""Explicit review-record dependencies. No database, transport or authorization changes."""
import copy

SCHEMA = 'yanxu-review-context-v1'
KEYS = ('tasks', 'decisions', 'results')
BOUNDARY = '仅含当前项目信息与人明确选取的登记记录；未选记录不发送、不作为失效依赖。材料是本次保存的快照，不扫描文件。输出仍未核验。'


def selection(value):
    if not isinstance(value, dict) or set(value) != set(KEYS):
        raise ValueError('评审记录范围须明确提供 tasks、decisions 和 results')
    result = {}
    for key in KEYS:
        ids = value[key]
        if not isinstance(ids, list) or len(ids) > 20 or any(not isinstance(i, str) or not i or len(i) > 200 for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('每类评审记录最多选取 20 个不同的有效 ID')
        result[key] = sorted(ids)
    return result


def freeze(pack, selected):
    selected = selection(selected)
    result = {'schema': SCHEMA, 'project': copy.deepcopy(pack['project']), 'selection': selected,
              'boundary': BOUNDARY}
    for key in KEYS:
        rows = pack.get(key)
        if not isinstance(rows, list) or any(not isinstance(r, dict) or not isinstance(r.get('id'), str) for r in rows):
            raise ValueError('评审上下文记录结构不正确：' + key)
        available = {r['id']: r for r in rows}
        if len(available) != len(rows):
            raise ValueError('评审上下文包含重复记录：' + key)
        if any(identifier not in available for identifier in selected[key]):
            raise ValueError('选取的评审记录不属于当前项目或已不存在：' + key)
        result[key] = [copy.deepcopy(available[i]) for i in selected[key]]
    return result


def validate_snapshot(context):
    if context.get('schema') == SCHEMA:
        if {k: v for k, v in context.items() if k != 'context_hash'} != freeze(context, context.get('selection')):
            raise ValueError('评审上下文快照与明确选取的记录范围不一致')
