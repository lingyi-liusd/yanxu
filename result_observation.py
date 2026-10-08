"""Source-bound suggestions for existing watches. Pure reads; no model or polling authorization."""
import copy
import hashlib
import json

SCHEMA = 'yanxu.result-observation-resolution.v1'
RULE_KEYS = ('question', 'keywords', 'interval_minutes')
BOUNDARY = '仅根据已登记的采纳、行动和结果关联提出候选；未判断原因、科学有效性或重要性。仅修改现有来源的规则，原结果与判断保留。'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def rule(value):
    if not isinstance(value, dict) or set(value) != set(RULE_KEYS):
        raise ValueError('观察调整只能提供关注问题、关键词和检查间隔')
    question, keywords, interval = value['question'], value['keywords'], value['interval_minutes']
    if not isinstance(question, str) or len(question) > 1000:
        raise ValueError('关注问题最多 1000 字')
    if (not isinstance(keywords, list) or len(keywords) > 12 or any(not isinstance(k, str) or not k.strip() or len(k) > 80 for k in keywords)
            or type(interval) is not int or not 15 <= interval <= 1440):
        raise ValueError('关键词最多 12 个，每个 80 字；检查间隔需为 15–1440 分钟')
    return {'question': question.strip(), 'keywords': [k.strip() for k in keywords], 'interval_minutes': interval}


def target(watch):
    return {'object_rev': watch.get('object_rev', 0), 'config_version': watch['config_version'],
            'rule': rule({k: watch.get(k, '' if k == 'question' else None) for k in RULE_KEYS}),
            'url': watch['url'], 'decision_ids': watch['decision_ids'], 'enabled': watch['enabled'],
            'auto_push': watch.get('auto_push', False), 'push_target': watch.get('push_target', 'project')}


def proposals(project, tasks, decisions, rooms, actions, results, watches):
    """Explicit adoption/decision/source links only. No title/keyword coincidence matching."""
    pid = project['id']; tasks = {t['id']: t for t in tasks if t.get('project') == pid}
    decisions = {d['id']: d for d in decisions if d.get('project') == pid}
    actions = {a['id']: a for a in actions}
    rooms = {(r['project_id'], r['id']): r for r in rooms}
    candidates = []
    for result in results:
        action = actions.get(result['action_id']); task = tasks.get(action.get('task_id')) if action else None
        if result.get('project_id') != pid or not action or action.get('project_id') != pid or not task or not task.get('review_ref'):
            continue
        ref = task['review_ref']; room = rooms.get((ref.get('space_id'), ref.get('room_id')))
        if not room or not any(a['id'] == task['id'] and a['source_version'] == ref.get('source_version') for a in room.get('adoptions', [])):
            continue
        original = room.get('review_of') or {}; change = room.get('source_change') or {}
        decision_ids = set()
        if original.get('project') == pid and original.get('id') in decisions:
            decision_ids.add(original['id'])
        if change.get('project_id') == pid:
            decision_ids.update(i for i in change.get('decision_ids', []) if i in decisions)
        for watch in watches:
            if watch.get('project_id') != pid:
                continue
            linked = sorted(decision_ids.intersection(watch['decision_ids']))
            direct = change.get('project_id') == pid and change.get('watch_id') == watch['id']
            if not linked and not direct:
                continue
            source = {'project': project, 'result': result, 'action': action, 'task': task,
                      'review_ref': ref, 'recheck_conditions': task.get('review_conditions', ''),
                      'relation': {'decision_ids': linked, 'source_watch_id': watch['id'] if direct else ''},
                      'decisions': [decisions[i] for i in linked]}
            source_hash = digest(source)
            if any(r['source_hash'] == source_hash and r['source']['result']['id'] == result['id'] for r in watch.get('result_adjustments', [])):
                continue
            original_rule = target(watch)
            # Quote the registered result, without inferring a cause or a monitoring strategy.
            addition = '\n复核已登记结果：' + result['summary']
            question = original_rule['rule']['question'] + addition
            proposed = dict(original_rule['rule'], question=question) if len(question) <= 1000 else copy.deepcopy(original_rule['rule'])
            notice = ('建议将这条登记结果纳入关注问题；请核对复核条件，决定修改或维持原规则。'
                      if len(question) <= 1000 else '结果摘要超过关注问题上限；请明确选取相关摘录或维持原规则，未自动截断。')
            candidates.append({'id': digest({'project': pid, 'result': result['id'], 'watch': watch['id']})[:32],
                               'watch_id': watch['id'], 'watch_name': watch['name'], 'source': copy.deepcopy(source),
                               'source_hash': source_hash, 'target': copy.deepcopy(original_rule),
                               'basis_hash': digest({'source_hash': source_hash, 'target': original_rule}),
                               'proposed': proposed, 'notice': notice, 'can_resolve': len(watch.get('result_adjustments', [])) < 50, 'boundary': BOUNDARY})
    return candidates


def resolution(candidate, choice, after, reason, created_at):
    if choice not in ('keep', 'modify'):
        raise ValueError('请选择维持原规则或修改规则')
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise ValueError('请填写处理理由，最多 2000 字')
    after = rule(after); before = candidate['target']['rule']
    if (choice == 'keep' and after != before) or (choice == 'modify' and after == before):
        raise ValueError('维持原规则不能改字段；没有修改请明确选择维持原规则')
    return {'schema': SCHEMA, 'proposal_id': candidate['id'], 'project_id': candidate['source']['project']['id'],
            'watch_id': candidate['watch_id'], 'source': candidate['source'], 'source_hash': candidate['source_hash'],
            'target': candidate['target'], 'basis_hash': candidate['basis_hash'], 'before': before, 'after': after,
            'resolution': choice, 'reason': reason.strip(), 'created_at': created_at,
            'verification_status': 'UNVERIFIED', 'scientific_result': 'NOT_ASSESSED'}


def validate_receipts(watch):
    receipts = watch.get('result_adjustments', [])
    if not isinstance(receipts, list) or len(receipts) > 50:
        raise ValueError('观察调整历史格式不正确或超过 50 条')
    seen = set()
    fields = {'schema', 'proposal_id', 'project_id', 'watch_id', 'source', 'source_hash', 'target', 'basis_hash', 'before', 'after',
              'resolution', 'reason', 'created_at', 'verification_status', 'scientific_result'}
    for receipt in receipts:
        if not isinstance(receipt, dict) or set(receipt) != fields or receipt['schema'] != SCHEMA:
            raise ValueError('观察调整收据格式不正确')
        source, original = receipt['source'], receipt['target']
        if (not isinstance(source, dict) or set(source) != {'project', 'result', 'action', 'task', 'review_ref', 'recheck_conditions', 'relation', 'decisions'}
                or not isinstance(original, dict) or set(original) != {'object_rev', 'config_version', 'rule', 'url', 'decision_ids', 'enabled', 'auto_push', 'push_target'}):
            raise ValueError('观察调整的来源或目标结构不正确')
        if (any(not isinstance(source[k], dict) for k in ('project', 'result', 'action', 'task', 'review_ref'))
                or not isinstance(source['decisions'], list) or any(not isinstance(d, dict) or not isinstance(d.get('id'), str) for d in source['decisions'])
                or not isinstance(original['decision_ids'], list) or any(not isinstance(i, str) for i in original['decision_ids'])):
            raise ValueError('观察调整的来源记录结构不正确')
        if (receipt['project_id'] != watch['project_id'] or receipt['watch_id'] != watch['id']
                or source['project'].get('id') != watch['project_id'] or source['task'].get('project') != watch['project_id']
                or source['result'].get('project_id') != watch['project_id'] or source['action'].get('project_id') != watch['project_id']
                or source['task'].get('id') != source['action'].get('task_id') or source['result'].get('action_id') != source['action'].get('id')
                or source['review_ref'] != source['task'].get('review_ref') or any(d.get('project') != watch['project_id'] for d in source['decisions'])
                or source['recheck_conditions'] != source['task'].get('review_conditions', '')
                or receipt['source_hash'] != digest(source) or receipt['basis_hash'] != digest({'source_hash': receipt['source_hash'], 'target': original})
                or receipt['proposal_id'] != digest({'project': watch['project_id'], 'result': source['result'].get('id'), 'watch': watch['id']})[:32]
                or receipt['before'] != rule(original['rule']) or receipt['after'] != rule(receipt['after'])
                or receipt['verification_status'] != 'UNVERIFIED' or receipt['scientific_result'] != 'NOT_ASSESSED'):
            raise ValueError('观察调整的来源、版本或范围不一致')
        relation = source['relation']
        if (not isinstance(relation, dict) or set(relation) != {'decision_ids', 'source_watch_id'}
                or not isinstance(relation['decision_ids'], list) or relation['decision_ids'] != sorted({d['id'] for d in source['decisions']})
                or any(i not in original['decision_ids'] for i in relation['decision_ids'])
                or relation['source_watch_id'] not in ('', watch['id']) or not (relation['decision_ids'] or relation['source_watch_id'])):
            raise ValueError('观察调整缺少明确关联')
        for key in ('object_rev', 'config_version'):
            if type(original[key]) is not int or original[key] < 1:
                raise ValueError('观察调整目标版本不正确')
        if type(original['enabled']) is not bool or type(original['auto_push']) is not bool or original['url'] != watch['url'] or original['push_target'] not in ('project', 'personal'):
            raise ValueError('观察调整不能替换来源或运行范围')
        rebuilt = resolution({'id': receipt['proposal_id'], 'watch_id': watch['id'], 'source': source, 'source_hash': receipt['source_hash'], 'target': original, 'basis_hash': receipt['basis_hash']}, receipt['resolution'], receipt['after'], receipt['reason'], receipt['created_at'])
        if rebuilt != receipt or not isinstance(receipt['created_at'], str) or not receipt['created_at']:
            raise ValueError('观察调整处理理由或记录不一致')
        key = (source['result']['id'], receipt['source_hash'])
        if key in seen:
            raise ValueError('同一来源版本不能重复处理观察建议')
        seen.add(key)
