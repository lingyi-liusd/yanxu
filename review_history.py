"""Explicit historical snapshots become materials in a new review, never a stale-run bypass."""
import hashlib
import json
import re
from urllib.parse import quote

SCHEMA = 'yanxu.review-history.v1'
KEYS = ('materials', 'tasks', 'decisions', 'results')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def selection(value):
    if not isinstance(value, dict) or set(value) != set(KEYS):
        raise ValueError('请明确选取历史材料、任务、判断和结果范围')
    result = {}
    for key in KEYS:
        ids = value[key]
        if not isinstance(ids, list) or len(ids) > 12 or any(not isinstance(i, str) or not i or len(i) > 200 for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('历史快照 ID 不合法或重复')
        result[key] = sorted(ids)
    if not 1 <= sum(map(len, result.values())) <= 12:
        raise ValueError('请选择 1–12 份历史快照')
    return result


def reason(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError('请填写仍使用历史快照的理由，最多 2000 字')
    return value.strip()


def reference(receipt, key, identifier, version):
    return ('yanxu://room/' + quote(receipt['room_id'], safe='') + '/snapshot/' + key + '/' + quote(identifier, safe='')
            + '?context_sha256=' + receipt['context_hash'] + '&record_sha256=' + version)


def freeze(source, request):
    if not isinstance(request, dict) or set(request) != {'room_id', 'expected_rev', 'context_hash', 'selection', 'reason'}:
        raise ValueError('历史快照请求字段不正确')
    if source['active']:
        raise ValueError('原评审仍在运行，请先等待结束或停止')
    if (request['room_id'] != source['id'] or type(request['expected_rev']) is not int
            or request['expected_rev'] != source.get('object_rev', 0) or request['context_hash'] != source['context']['context_hash']):
        raise ValueError('历史来源对象或版本已变化，请重新查看原评审')
    selected = selection(request['selection'])
    receipt = {'schema': SCHEMA, 'project_id': source['project_id'], 'room_id': source['id'],
               'object_rev': source.get('object_rev', 0), 'context_hash': source['context']['context_hash'],
               'reason': reason(request['reason']), 'selection': selected, 'bindings': [],
               'source_used_calls': source['used_calls'], 'source_max_calls': source['max_calls']}
    materials = []
    for key in KEYS:
        rows = source.get('materials', []) if key == 'materials' else source['context'].get(key, [])
        available = {row['id']: row for row in rows}
        if len(available) != len(rows) or any(i not in available for i in selected[key]):
            raise ValueError('所选历史快照不在原评审范围内：' + key)
        for identifier in selected[key]:
            row = available[identifier]
            content = row['content'] if key == 'materials' else canonical(row)
            version = hashlib.sha256(content.encode()).hexdigest()
            title = row['title'] if key == 'materials' else {'tasks': '历史任务', 'decisions': '历史判断', 'results': '历史结果'}[key] + ' · ' + identifier[:12]
            mid = 'M' + str(len(materials) + 1)
            materials.append({'id': mid, 'title': title, 'content': content, 'reference': reference(receipt, key, identifier, version)})
            receipt['bindings'].append({'material_id': mid, 'kind': key, 'id': identifier, 'version': version,
                                        'original_title': row.get('title', ''), 'original_reference': row.get('reference', '') if key == 'materials' else ''})
    return materials, receipt


def validate(room):
    """Check portable receipt consistency; provenance remains UNVERIFIED, without live-source dependency."""
    receipt = room['history_source']
    keys = {'schema', 'project_id', 'room_id', 'object_rev', 'context_hash', 'reason', 'selection', 'bindings', 'source_used_calls', 'source_max_calls'}
    if not isinstance(receipt, dict) or set(receipt) != keys or receipt['schema'] != SCHEMA:
        raise ValueError('历史快照收据格式不正确')
    if (receipt['project_id'] != room['project_id'] or receipt['room_id'] == room['id']
            or not isinstance(receipt['room_id'], str) or not receipt['room_id'] or len(receipt['room_id']) > 200
            or type(receipt['object_rev']) is not int or receipt['object_rev'] < 0
            or not isinstance(receipt['context_hash'], str) or not re.fullmatch(r'[0-9a-f]{64}', receipt['context_hash'])
            or type(receipt['source_max_calls']) is not int or not 1 <= receipt['source_max_calls'] <= 18
            or type(receipt['source_used_calls']) is not int or not 0 <= receipt['source_used_calls'] <= receipt['source_max_calls']):
        raise ValueError('历史快照来源、版本或消耗记录不正确')
    if receipt['reason'] != reason(receipt['reason']) or receipt['selection'] != selection(receipt['selection']):
        raise ValueError('历史快照范围或理由不一致')
    expected = [(key, identifier) for key in KEYS for identifier in receipt['selection'][key]]
    if not isinstance(receipt['bindings'], list) or len(expected) != len(receipt['bindings']) or len(expected) != len(room['materials']):
        raise ValueError('历史快照与材料数量不一致')
    for number, ((key, identifier), binding, material) in enumerate(zip(expected, receipt['bindings'], room['materials']), 1):
        if not isinstance(binding, dict) or set(binding) != {'material_id', 'kind', 'id', 'version', 'original_title', 'original_reference'}:
            raise ValueError('历史快照材料映射不正确')
        if (binding['material_id'] != 'M' + str(number) or material['id'] != binding['material_id'] or binding['kind'] != key
                or binding['id'] != identifier or material['version'] != binding['version']
                or material['reference'] != reference(receipt, key, identifier, binding['version'])
                or not isinstance(binding['original_title'], str) or len(binding['original_title']) > (200 if key == 'materials' else 4000)
                or not isinstance(binding['original_reference'], str) or len(binding['original_reference']) > 2000):
            raise ValueError('历史快照材料或来源版本不一致')
        if key == 'materials':
            if material['title'] != binding['original_title']:
                raise ValueError('历史材料标题不一致')
        else:
            try:
                row = json.loads(material['content'])
            except ValueError as error:
                raise ValueError('历史记录快照格式不正确') from error
            if (not isinstance(row, dict) or row.get('id') != identifier or canonical(row) != material['content']
                    or row.get('title', '') != binding['original_title'] or binding['original_reference']
                    or (key != 'results' and row.get('project') != room['project_id'])):
                raise ValueError('历史记录快照对象或项目不一致')
