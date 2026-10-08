"""Readable observation coverage and change briefs, without model inference."""
import datetime
import time


def epoch(value):
    try:
        return datetime.datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return 0


def coverage(watches, alerts, now=None):
    now = time.time() if now is None else now
    groups = {}
    for watch in watches:
        topic = watch.get('question') or watch['name']
        group = groups.setdefault(topic, {'question': topic, 'sources': [], 'changes': []})
        last = epoch(watch.get('last_checked'))
        successful = epoch((watch.get('snapshot') or {}).get('captured_at'))
        if watch.get('error'):
            status, message = 'failed', watch['error']
        elif not successful:
            status, message = 'not_checked', '尚无成功材料；不能判断是否有变化'
        elif now - successful > max(900, watch['interval_minutes'] * 60 * 2):
            status, message = 'stale', '成功材料已过期，本次覆盖不完整'
        else:
            status = 'covered'
            message = {'baseline': '已有基线，尚无前版本可比较', 'unchanged': '本次成功覆盖，未发现文字变化',
                       'filtered': '本次有文字变化，但未匹配关注关键词', 'changed': '本次有符合条件的文字变化'}.get(watch.get('last_result'), '已有成功材料，检查结果见变化记录')
        group['sources'].append({'id': watch['id'], 'name': watch['name'], 'url': watch['url'],
                                 'status': status, 'message': message, 'last_checked': watch.get('last_checked'),
                                 'last_success': (watch.get('snapshot') or {}).get('captured_at'),
                                 'automatic': watch['enabled'], 'due': bool(watch['enabled'] and watch.get('next_check', 0) < now)})
    for alert in alerts:
        watch = next((w for w in watches if w['id'] == alert['watch_id']), None)
        if watch and alert.get('status') != 'dismissed':
            groups[watch.get('question') or watch['name']]['changes'].append(alert['id'])
    for group in groups.values():
        group['covered'] = sum(s['status'] == 'covered' for s in group['sources'])
        group['total'] = len(group['sources'])
        group['summary'] = ('有未归档的变化记录，影响仍待确认' if group['changes'] else
                            '成功覆盖范围内暂未发现待处理变化；仍需检查未覆盖来源' if group['covered'] < group['total'] and group['covered'] else
                            '成功覆盖范围内暂未发现待处理变化' if group['covered'] else
                            '尚未完成有效观察，不能判断是否有变化')
        group['complete'] = group['covered'] == group['total']
        group['boundary'] = '仅覆盖所列来源和成功读取的时间；暂停、休眠或服务退出可能造成缺口，不代表整个行业。'
    return list(groups.values())


def change_brief(alert, watch, decisions):
    related = [d for d in decisions if d['id'] in alert.get('decision_ids', [])]
    return {'question': watch.get('question') or watch['name'],
            'summary': '关注来源的文字发生变化：' + watch['name'],
            'relevance': ('变化匹配关键词：' + '、'.join(watch['keywords']) if watch['keywords'] else '该来源被明确选入观察范围；具体影响尚待确认'),
            'basis': '本摘要由文字差异与用户配置生成，未使用模型判断重要性。',
            'affected_decisions': [{'id': d['id'], 'title': d.get('title') or d.get('question', ''),
                                    'status': 'needs_review', 'original_status': d.get('status'),
                                    'reason': '这项判断关联的观察来源有变化；原判断保留，尚未认定失效'} for d in related],
            'next_step': '可以直接阅读或归档；需要取舍时再评估影响。',
            'coverage': '差异仅来自两次成功保存的文字版本，完整来源历史未承诺留存。'}
