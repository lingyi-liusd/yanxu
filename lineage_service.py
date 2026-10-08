"""Human-facing references; never changes Decision, Action, Result or evidence status."""


def trace(entries, rooms, actions, results):
    result=[]
    for entry in entries:
        reference=entry.get('review_ref')
        if not reference:continue
        room=next((r for r in rooms if r['id']==reference.get('room_id') and r['project_id']==reference.get('space_id')),None)
        matched=bool(room and any(a['id']==entry['id'] and a['source_version']==reference.get('source_version') for a in room.get('adoptions',[])))
        linked_actions=[]
        for action in actions:
            if action.get('task_id')!=entry['id']:continue
            linked_actions.append({'id':action['id'],'status':action['status'],'version':action['version'],
                'goal':action['goal'],'results':[r for r in results if r['action_id']==action['id']]})
        result.append({'entry_id':entry['id'],'title':entry.get('title') or entry.get('question'),'review_ref':reference,
                       'origin_available':matched,'material_refs':entry.get('material_refs',[]),
                       'recheck_conditions':entry.get('review_conditions',''),'actions':linked_actions,
                       'boundary':'引用表示接续关系；模型建议、人工采纳、行动交付与结果核验分别保留，不互相替代。'})
    return result
