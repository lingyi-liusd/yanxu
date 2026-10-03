"""Lossless registered-snapshot partitioning; summaries remain unverified.

This is not a file reader or a permission grant. Atomic records are never cut.
Every plan is tied to the complete serialized snapshot, not a moving cursor.
"""
import hashlib
import json

TARGET_BYTES = 72000
ATOMIC_MAX_BYTES = 145000


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def plan(source):
    base = {k: source[k] for k in ('project', 'workspace_scope') if k in source}
    if len(encode(base).encode()) > TARGET_BYTES:
        raise ValueError('项目说明或工作区说明过大，无法完整分批；未截断或发送')
    units = []
    for section, value in sorted(source.items()):
        if section in base:
            continue
        if isinstance(value, list):
            units.extend((section, index, item) for index, item in enumerate(value))
            if not value:
                units.append((section, None, []))
        else:
            units.append((section, None, value))
    batches, current, covered = [], dict(base), []

    def append_value(target, section, index, value):
        if index is None:
            target[section] = value
        else:
            target[section] = target.get(section, []) + [value]

    def flush():
        batches.append({'current':current, 'records':covered,
                        'input_sha256':digest(current)})

    for section, index, item in units:
        record={'section':section, 'index':index, 'sha256':digest(item)}
        trial = dict(current)
        append_value(trial, section, index, item)
        if len(encode({'current':trial,'records':covered+[record]}).encode()) > TARGET_BYTES:
            if covered:
                flush()
                current, covered = dict(base), []
            trial = dict(current)
            append_value(trial, section, index, item)
            if len(encode({'current':trial,'records':[record]}).encode()) > ATOMIC_MAX_BYTES:
                raise ValueError('单条登记记录过大，无法完整分批；未截断或发送（'+section+'）')
        current = trial
        covered.append(record)
    if covered or not batches:
        flush()
    return {'source_hash':digest(source), 'batches':batches,
            'record_units':len(units), 'base_sha256':digest(base)}


def groups(items, base):
    """Bound reducer input too; never silently shorten a model response."""
    grouped, current = [], []
    for item in items:
        trial = current + [item]
        if len(encode({'current':base, 'partial_summaries':trial}).encode()) > TARGET_BYTES:
            if current:
                grouped.append(current)
                current = []
            if len(encode({'current':base, 'partial_summaries':[item]}).encode()) > TARGET_BYTES:
                raise ValueError('分批回包过大，无法完整汇总；原回包已保留，未截断或重试')
        current.append(item)
    if current:
        grouped.append(current)
    if len(items) > 1 and len(grouped) == len(items):
        raise ValueError('分批回包未能压缩到可汇总范围；原回包已保留，未自动重试')
    return grouped
