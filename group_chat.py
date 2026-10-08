"""Persistent human-owned groups; individual replies retain immutable room contracts."""
import copy
import hashlib
import json

CONSENT = 'group-chat-message-v1'
SCHEMA = 'yanxu.group-chat-source.v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def member_ids(value, allow_empty=True):
    if not isinstance(value, list) or len(value) > 6 or (not allow_empty and not value) or any(not isinstance(x, str) or not x for x in value) or len(set(value)) != len(value):
        raise ValueError('请选择最多6位不同模型成员')
    return value


def timeline(group, rooms):
    by_id = {r['id']: r for r in rooms}
    rows = []
    for entry in group['entries']:
        rows.append(dict(entry, kind='human', author='你', verification_status='HUMAN_NOTE'))
        room = by_id.get(entry.get('room_id'))
        if not room:
            continue
        rows.extend(dict(copy.deepcopy(m), room_id=room['id']) for m in room['messages'] if m['kind'] == 'agent')
        for index, failure in enumerate(room['failures']):
            rows.append({'id': room['id'] + '-failure-' + str(index), 'kind': 'system', 'room_id': room['id'],
                         'author': '系统', 'content': failure['message'], 'created_at': failure['created_at'], 'verification_status': 'UNKNOWN'})
        if room['status'] in ('stopped', 'interrupted'):
            rows.append({'id': room['id'] + '-stop', 'kind': 'system', 'room_id': room['id'], 'author': '系统',
                         'content': '该轮已停止或中断；外部是否消耗仍需对账，未自动重跑。', 'created_at': room['updated_at'], 'verification_status': 'UNKNOWN'})
    return rows


def freeze(group, rooms, count):
    if type(count) is not int or not 0 <= count <= 20:
        raise ValueError('本次上下文请选择最近0–20条消息')
    # Record the actual bounded history, never silently shorten individual replies.
    history = timeline(group, rooms)[-count:] if count else []
    source = {'schema': SCHEMA, 'group_id': group['id'], 'project_id': group['project_id'],
              'group_revision': group.get('object_rev', 0), 'group_name': group['name'],
              'history_count': count, 'history': history}
    if len(json.dumps(source, ensure_ascii=False).encode()) > 200000:
        raise ValueError('选取的群聊记录超过200KB，请减少消息条数或新建群聊；原记录保留')
    return dict(source, source_hash=digest(source))


def validate_source(source, project):
    fields = {'schema', 'group_id', 'project_id', 'group_revision', 'group_name', 'history_count', 'history', 'source_hash'}
    if not isinstance(source, dict) or set(source) != fields or source['schema'] != SCHEMA or source['project_id'] != project:
        raise ValueError('群聊发送快照的结构或空间不正确')
    if not isinstance(source['group_id'], str) or not source['group_id'] or not isinstance(source['group_name'], str) or not 0 < len(source['group_name']) <= 80:
        raise ValueError('群聊发送快照身份不正确')
    if type(source['group_revision']) is not int or source['group_revision'] < 1 or type(source['history_count']) is not int or not 0 <= source['history_count'] <= 20:
        raise ValueError('群聊发送快照版本或范围不正确')
    if not isinstance(source['history'], list) or len(source['history']) > source['history_count']:
        raise ValueError('群聊历史消息范围不正确')
    for row in source['history']:
        if not isinstance(row, dict) or row.get('project_id', project) != project or row.get('kind') not in ('human', 'agent', 'system') or not isinstance(row.get('id'), str):
            raise ValueError('群聊历史消息身份不正确')
        if row['kind'] == 'agent':
            value = row.get('output')
            if not isinstance(value, dict) or set(value) != {'position', 'evidence', 'objections', 'next_step'} or any(not isinstance(x, str) or len(x) > 6000 for x in value.values()):
                raise ValueError('群聊历史模型回复结构不正确')
        elif not isinstance(row.get('content'), str) or len(row['content']) > 4000:
            raise ValueError('群聊历史文字不正确')
    if source['source_hash'] != digest({k: v for k, v in source.items() if k != 'source_hash'}) or len(json.dumps(source, ensure_ascii=False).encode()) > 200100:
        raise ValueError('群聊发送快照版本不一致')
