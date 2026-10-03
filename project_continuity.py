"""Source-bound continuity view, derived on read; no model, writes or authorization."""
import json
import re

SECTIONS = ('project', 'tasks', 'files', 'decisions', 'actions', 'results',
            'artifacts', 'evidence', 'proposals', 'file_observations')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def objects(section, value):
    if section == 'project':
        return {str(value.get('id', 'project')): value} if value else {}
    return {str(row.get('id') or row.get('path') or canonical(row)): row for row in (value or [])}


def describe(row):
    return row.get('title') or row.get('goal') or row.get('question') or row.get('name') or row.get('summary') or row.get('path') or row.get('id') or '未命名记录'


def digest(value):
    """Only comparable sha256 versions; labels/commit IDs cannot be compared to bytes."""
    text = str(value or '').removeprefix('sha256:').lower()
    return text if re.fullmatch('[0-9a-f]{64}', text) else None


def source_watch(source):
    watch = []
    for observed in source.get('file_observations', []):
        path = observed.get('path')
        linked = []
        for section in ('results', 'evidence', 'artifacts'):
            for row in source.get(section, []):
                # No filename, substring, directory or Action-based inferred dependencies.
                if not path or (row.get('source_ref') or row.get('reference')) != path:
                    continue
                expected = digest(row.get('source_version'))
                actual = digest(observed.get('observed_version')) if observed.get('state') == 'present' else None
                status = ('MATCH' if expected == actual else 'VERSION_CHANGED') if expected and actual else 'UNKNOWN'
                linked.append({'section': section, 'id': row.get('id'), 'title': describe(row),
                               'source_version': row.get('source_version'), 'version_status': status,
                               'verification_status': row.get('verification_status', 'UNKNOWN')})
        attention = [r for r in linked if r['version_status'] != 'MATCH']
        if observed.get('state') != 'present' or not observed.get('matches_registered') or attention:
            watch.append({'path': path, 'observation': observed, 'linked_records': linked,
                          'review_record_count': len(attention),
                          'status': 'NEEDS_REVIEW',
                          'boundary': '仅直接引用匹配；版本匹配不证明结论正确，版本变化不等于结论错误。没有登记关联不代表没有影响。'})
    return watch


def build(source, signature, baseline=None):
    old = json.loads(baseline['input']) if baseline else None
    changes = []
    if old is not None:
        for section in SECTIONS:
            before, after = objects(section, old.get(section)), objects(section, source.get(section))
            for key in sorted(set(before) | set(after)):
                a, b = before.get(key), after.get(key)
                if canonical(a) == canonical(b):
                    continue
                fields = sorted(k for k in set(a or {}) | set(b or {})
                                if (k in (a or {})) != (k in (b or {}))
                                or canonical((a or {}).get(k)) != canonical((b or {}).get(k)))
                changes.append({'section': section, 'id': key,
                                'kind': 'added' if a is None else 'removed' if b is None else 'updated',
                                'title': describe(b or a), 'fields': fields,
                                'before': a, 'after': b})
    results = source.get('results', [])
    # Explicit status only. A word in an AI summary never becomes a negative finding.
    negative = [r for r in results if str(r.get('outcome', '')).lower() in ('failure', 'fail')
                or str(r.get('normalized_status', '')).upper() in ('FAIL', 'FAILURE')]
    unverified = [r for r in results if r.get('verification_status') != 'VERIFIED']
    active = [a for a in source.get('actions', []) if a.get('status') in ('claimed', 'running')]
    decisions = [d for d in source.get('decisions', []) if d.get('status') in ('pending', '待决', '讨论中', '未决', '待处理')]
    return {'mode': 'local-records', 'source_hash': signature,
            'baseline': {'job_id': baseline['id'], 'source_hash': baseline['signature'],
                         'finished': baseline['finished']} if baseline else None,
            'changes': changes, 'active_actions': active, 'negative_results': negative,
            'source_watch': source_watch(source),
            'unverified_results': unverified, 'pending_decisions': decisions,
            'boundary': '对比上次成功总结的登记输入，不是上次访问；记录变化不证明因果或科学正确。来源移出当前登记快照不等于原文件删除。负结果列表只归集显式failure/FAIL状态，不从摘要推测；部分结果中的限制仍保留在原文中。未核验结果和负结果不会因交付完成而升级；建议不是授权。'}


def next_navigation(source, signature, continuity, plans=()):
    """One explainable, record-bound navigation choice, never execution approval."""
    project = source.get('project') or {}
    tasks = [t for t in source.get('tasks', []) if not t.get('noteType')
             and (not project.get('id') or t.get('project', project['id']) == project['id'])]
    rank = lambda t: ({'P0':0, 'P1':1, 'P2':2, 'P3':3}.get(t.get('priority'), 2),
                      str(t.get('end') or '9999-12-31'), str(t.get('id') or ''))
    opened = sorted([t for t in tasks if t.get('status') != '已完成'], key=rank)
    by_id = {t.get('id'):t for t in tasks}

    def dependencies(task):
        return [{'id':key, 'title':describe(by_id[key]) if key in by_id else '当前任务范围未找到',
                 'status':by_id[key].get('status', 'UNKNOWN') if key in by_id else 'UNKNOWN',
                 'found':key in by_id} for key in task.get('deps', [])]

    pending, active = continuity['pending_decisions'], continuity['active_actions']
    blockers = [t for t in opened if t.get('status') == '受阻']
    ready = [p for p in plans if p.get('ready') and not p.get('orphaned')]
    results = sorted(source.get('results', []), key=lambda r:(str(r.get('created_at') or ''), str(r.get('id') or '')), reverse=True)
    review_ids = {r.get('id') for item in continuity['source_watch'] for r in item['linked_records']
                  if r.get('section') == 'results' and r.get('version_status') != 'MATCH'}
    affected = next((r for r in results if r.get('id') in review_ids), None)
    current = next((t for t in opened if t.get('status') == '进行中'), None)
    deps_clear = next((t for t in opened if all(d['status'] == '已完成' for d in dependencies(t))), None)
    target, row, section, reason = None, None, None, 'review'
    if pending:
        row, section, reason = pending[0], 'decisions', 'decision'
        summary, label = '先处理待决定事项；简报不能代替人的批准。', '查看待决定事项'
    elif active:
        row, section, reason = active[0], 'actions', 'active_action'
        summary, label = '先查看原行动与最近报告，不要另起重复工作。', '查看原行动与进度'
    elif not str(project.get('goal') or '').strip():
        row, section, reason = project, 'project', 'goal_missing'
        summary, label = '先补齐项目目标，再核对下一步有没有走偏。', ''
    elif blockers:
        row, section, reason = blockers[0], 'tasks', 'blocker'
        summary, label = '先查看已标记受阻的任务及缺失条件，不自动重跑。', '查看阻塞任务'
    elif ready:
        row, section, reason = ready[0], 'management_handoffs', 'approved_review'
        summary, label = '先核对已批准核查的范围、当前版本与原契约。', ''
    elif affected:
        row, section, reason = affected, 'results', 'source_review'
        summary, label = '这个结果直接引用的来源需要复核；版本变化不等于结论错误。', '查看需复核的结果'
    elif current:
        row, section, reason = current, 'tasks', 'task_current'
        summary, label = '先接续已标记进行中的任务，核对原记录与依赖。', '继续查看这项任务'
    elif results:
        row, section = results[0], 'results'
        summary, label = '先核对最近结果与来源，保留失败、未知和适用条件。', '核对最近结果与来源'
    elif deps_clear:
        row, section, reason = deps_clear, 'tasks', 'task_ready'
        summary, label = '这项未完成任务没有已登记的未完成前置项；先查看，不自动执行。', '继续查看这项任务'
    elif opened:
        row, section, reason = opened[0], 'tasks', 'task_dependencies'
        summary, label = '前置任务未完成或未找到，先核对依赖。', '查看任务与依赖'
    else:
        summary, label = ('任务已标记完成，下一步补上结果和依据。' if tasks else '目标已记录，下一步明确任务和行动的范围。'), ''
    if label and row and row.get('id'):
        view, kind = {'decisions':('project','decision'), 'actions':('actions','action'),
                      'tasks':('project','task'), 'results':('evidence','result')}[section]
        target = {'view':view, 'kind':kind, 'id':row['id'], 'label':label}
    basis = []
    if row is not None:
        record = {'section':section, 'id':row.get('id'), 'title':describe(row)}
        record.update({k:row[k] for k in ('status','outcome','verification_status','source_ref','source_version') if k in row})
        basis.append(record)
    source_checks = [{'path':item['path'], 'observation_state':item['observation'].get('state'),
                      'observed_version':item['observation'].get('observed_version') if item['observation'].get('state') == 'present' else None,
                      'record_version':r.get('source_version'), 'version_status':r.get('version_status')}
                     for item in continuity['source_watch'] for r in item['linked_records']
                     if section == 'results' and r.get('section') == 'results' and r.get('id') == row.get('id')]
    return {'schema_version':1, 'mode':'local-records', 'project_id':project.get('id'), 'source_hash':signature,
            'rule':reason, 'summary':summary, 'target':target, 'basis_records':basis,
            'dependencies':dependencies(row) if section == 'tasks' else [], 'source_checks':source_checks,
            'task_counts':{'total':len(tasks), 'completed':len(tasks)-len(opened)},
            'boundary':'这是登记记录给出的只读入口，不是AI新判断、执行许可或科学核验。仅直接引用的来源关联，不推断因果或完整影响范围。'}


def resume_brief(source, signature, continuity, plans=()):
    """A record-derived handoff, not a model conclusion or permission to execute."""
    project = source.get('project') or {}
    active = continuity['active_actions']
    pending = continuity['pending_decisions']
    results = sorted(source.get('results', []), key=lambda r: (str(r.get('created_at') or ''), str(r.get('id') or '')), reverse=True)
    latest = results[0] if results else None
    ready = [p for p in plans if p.get('ready') and not p.get('orphaned')]
    navigation = next_navigation(source, signature, continuity, plans)
    # State what is recorded; never infer completion, correctness or a new scientific plan.
    now = ('有%d个行动正在推进，接手前先核对原行动。' % len(active) if active else
           '最近有结果记录，但没有正在推进的行动。' if latest else
           '有未完成的任务记录；任务状态不是结论核验。' if navigation['task_counts']['total'] > navigation['task_counts']['completed'] else
           '任务已标记完成，但尚无结果登记。' if navigation['task_counts']['total'] else
           '项目目标已记录，尚未登记任务或行动。' if str(project.get('goal') or '').strip() else '尚无行动或结果记录，先补齐项目目标和当前状态。')
    caution = ('仍有%d条结果未独立核验。' % len(continuity['unverified_results'])
               if continuity['unverified_results'] else '核验状态来自登记，接手仍需核对适用条件。')
    if continuity['negative_results']:
        caution += '另有%d条失败记录，不能遗漏。' % len(continuity['negative_results'])
    elif results:
        caution += '失败和限制仍需查看原记录。'
    else:
        caution = '尚无结果可判断；不能从任务完成推断结论成立。'
    next_step, reason = navigation['summary'], navigation['rule']
    fields = ('id','goal','why_now','expected_output','success_condition','failure_condition',
              'dependencies','agent_id','status','budget','stop_condition','activity_reports','version','progress_reports_used')
    result_fields = ('id','action_id','summary','outcome','normalized_status','verification_status',
                     'source_ref','source_version','created_at','provenance','artifact_path')
    select = lambda row, keys: {k:row[k] for k in keys if k in row}
    open_tasks = [select(t, ('id','title','status','deps','stage','priority')) for t in source.get('tasks', [])
                  if t.get('status') != '已完成' and not t.get('noteType')
                  and (not project.get('id') or t.get('project', project['id']) == project['id'])]
    target = navigation['target']
    checks = []
    if not str(project.get('goal') or '').strip():
        checks.append({'code':'GOAL_MISSING','text':'项目目标还没写清楚，接手者无法核对是否走偏。'})
    if pending:
        checks.append({'code':'DECISION_PENDING','text':'有待决定事项，简报不能代替人的批准。'})
    if active:
        checks.append({'code':'WORK_IN_PROGRESS','text':'已有Agent在推进；先看原行动，不要另开相同工作。'})
    incomplete = [a.get('id') for a in active if any(not a.get(k) for k in ('expected_output','stop_condition','success_condition','failure_condition'))]
    if incomplete:
        checks.append({'code':'CONTRACT_INCOMPLETE','text':'部分活跃行动的产出、判据或停止条件没写全。','action_ids':incomplete})
    if continuity['source_watch']:
        checks.append({'code':'SOURCE_REVIEW','text':'已观察来源存在缺失或版本待复核；这不代表结论已经错误。','count':len(continuity['source_watch'])})
    if continuity['negative_results']:
        checks.append({'code':'NEGATIVE_RETAINED','text':'失败记录随交接保留，不能只带走成功结果。','count':len(continuity['negative_results'])})
    if continuity['unverified_results']:
        checks.append({'code':'UNVERIFIED','text':'AI报告的结果还不能直接当成已核验事实。','count':len(continuity['unverified_results'])})
    handoff = {'project_id':project.get('id'), 'source_hash':signature,
        'goal':project.get('goal') or '', 'success_definition':project.get('success_definition') or '',
        'description':project.get('description') or '',
        'recorded_state':project.get('current_state') or '',
        'constraints':project.get('constraints') or project.get('frozen_constraints') or [],
        'frozen_constraints':project.get('frozen_constraints') or [],
        'workspace':project.get('workspace') or project.get('workspace_path') or '',
        'active_actions':[select(a, fields) for a in active],
        'latest_result':select(latest, result_fields) if latest else None,
        'negative_results':[select(r, result_fields) for r in continuity['negative_results']],
        'uncertain_results':[select(r,result_fields) for r in results if str(r.get('outcome','')).lower() in ('partial','inconclusive','unknown')],
        'historical_negative_records':[select(change['before'],result_fields) for change in continuity['changes']
            if change['section']=='results' and change['kind']=='removed' and
            (str((change['before'] or {}).get('outcome','')).lower() in ('failure','fail') or
             str((change['before'] or {}).get('normalized_status','')).upper() in ('FAIL','FAILURE'))],
        'artifacts':[select(a, ('id','title','reference','path','source_ref','source_version','verification_status')) for a in source.get('artifacts', [])],
        'pending_decisions':[select(d, ('id','question','title','status','context','impact')) for d in pending],
        'open_tasks':open_tasks,
        'next_navigation':navigation,
        'source_review':continuity['source_watch'],
        'ready_review_ids':[p['id'] for p in ready],
        'record_checks':checks,
        'checks_scope':'仅当前登记目标、行动契约、决策、结果状态和已观察来源；没有发现问题不代表项目安全、科学闭合或可以执行。',
        'entrypoint':'先调用 project.get_context，核对project_id、management.resume_brief.source_hash和原契约；新认领project.claim_action时传context_hash为此hash。快照已变则重新读取。',
        'boundary':'这是登记记录的交接，不是新授权或独立核验。保留负结果、未知和原预算；不要因换Agent重跑实验，不接管其他Agent的活跃行动。新方向或超出原契约的工作须人确认。来源正文不随本简报导出。'}
    return {'mode':'local-records', 'source_hash':signature,
            'cards':[{'label':'现在到哪了','text':now, 'detail':active[0].get('goal','') if active else (latest or {}).get('summary','')}, {'label':'哪些还不能当真','text':caution},
                     {'label':'下一步做什么','text':next_step,'target':target}],
            'next_reason':reason, 'next_explanation':navigation, 'handoff':handoff,
            'counts':{'active':len(active),'pending':len(pending),'unverified':len(continuity['unverified_results']),
                      'negative':len(continuity['negative_results']),'open_tasks':len(open_tasks)},
            'boundary':'按当前登记整理，不调用模型；一份简报不代表资料完整或可以直接执行。'}
