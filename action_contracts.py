"""Lossless, bounded action contracts. Validation is not execution authority."""
import hashlib
import json

TEXT_FIELDS = ('goal','reason','expected_output','success_condition','failure_condition','stop_condition')


def validate(contract, management=False):
    if not isinstance(contract,dict):
        raise ValueError('行动契约必须是对象')
    required=set(TEXT_FIELDS)|{'scope','budget'}
    optional={'dependencies','dependency_policy'}
    if management and (required-set(contract) or set(contract)-required-optional):
        raise ValueError('只读核查须完整目标、理由、产出、判据、预算和停止条件')
    value=dict(contract)
    for key in TEXT_FIELDS:
        text=value.get(key)
        limit=400 if key=='goal' else 4000
        if not isinstance(text,str) or not text.strip() or len(text)>limit:
            raise ValueError(key+' 须为非空文本，最多'+str(limit)+'字；不会截断条件')
    scope=value.get('scope','project_action')
    if scope not in ('project_action','read_only_review') or management and scope!='read_only_review':
        raise ValueError('不支持的行动范围')
    budget=value.get('budget')
    limit=20 if management else 100
    if (not isinstance(budget,dict) or set(budget)!={'max_progress_reports'}
            or type(budget['max_progress_reports']) is not int
            or not 1<=budget['max_progress_reports']<=limit):
        raise ValueError('行动进度预算须为1–'+str(limit)+'次整数')
    deps=value.get('dependencies',[])
    if (not isinstance(deps,list) or len(deps)>64 or any(not isinstance(d,str) or not d or len(d)>200 for d in deps)
            or len(set(deps))!=len(deps)):
        raise ValueError('依赖须为最多64个不重复的任务ID')
    if value.get('dependency_policy','recorded') not in ('recorded','all_completed'):
        raise ValueError('依赖策略须为 recorded 或 all_completed')
    # In particular do not strip the approved strings or append a policy note.
    return value


def digest(contract):
    raw=json.dumps(contract,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return 'sha256:'+hashlib.sha256(raw.encode('utf-8')).hexdigest()
