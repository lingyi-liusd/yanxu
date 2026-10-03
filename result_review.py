"""Append-only human review receipts over registered Result/Evidence snapshots.

No source files, URLs or models are accessed. ``matched`` records a human's
reported byte-version comparison. Only digest format and string equality are
checked; this does not establish that either hash came from actual source
bytes, or that the service obtained a source. It is never independent
scientific verification.
The caller resolves the project, authenticates the human, checks integer
``ifRev`` (reject bool/string), and owns the transaction/history/revision/SSE.
Use a coherent read transaction for target/prepare and BEGIN IMMEDIATE around
ifRev, prepare/save and the outer writes. This module never commits or updates
Result/Evidence, and exposes no receipt update/delete operation. Backup restore
is a separate outer workflow, not a review operation.
"""
import datetime
import hashlib
import json
import re
import secrets
import sqlite3
from collections.abc import Mapping


CONSENT = 'human-result-review-v1'
SCIENTIFIC_STATUS = 'NOT_ASSESSED'
REVIEW_BOUNDARY = ('来源评估为人工声明；服务仅检查登记版本与人工填写版本的格式和字符串相等性，'
                  '未读取来源文件或URL、未调用模型。matched不证明服务取得或检查过来源字节，'
                  '也不代表科学核验；科学状态固定NOT_ASSESSED。')
SOURCE_ASSESSMENTS = ('matched', 'missing', 'mismatch', 'unavailable', 'symbolic')
REVIEW_KINDS = ('source', 'software', 'scientific')
CONCLUSIONS = ('accepted', 'rejected', 'needs_more')
COLUMNS = ('id', 'project_id', 'result_id', 'evidence_id', 'target_hash',
           'source_ref', 'source_version', 'checked_source_version',
           'source_assessment', 'review_kind', 'criteria', 'reviewer',
           'conclusion', 'notes', 'scientific_status', 'created_at')


class ReviewError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def schema(c):
    """Create only the receipt table/index; do not commit the caller's work."""
    c.execute('''CREATE TABLE IF NOT EXISTS result_reviews (
      id TEXT PRIMARY KEY NOT NULL, project_id TEXT NOT NULL,
      result_id TEXT NOT NULL, evidence_id TEXT, target_hash TEXT NOT NULL,
      source_ref TEXT NOT NULL, source_version TEXT NOT NULL,
      checked_source_version TEXT NOT NULL,
      source_assessment TEXT NOT NULL CHECK (source_assessment IN
        ('matched','missing','mismatch','unavailable','symbolic')),
      review_kind TEXT NOT NULL CHECK (review_kind IN ('source','software','scientific')),
      criteria TEXT NOT NULL CHECK (length(trim(criteria)) > 0 AND length(criteria) <= 4000),
      reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0 AND length(reviewer) <= 4000),
      conclusion TEXT NOT NULL CHECK (conclusion IN ('accepted','rejected','needs_more')),
      notes TEXT NOT NULL CHECK (length(trim(notes)) > 0 AND length(notes) <= 4000),
      scientific_status TEXT NOT NULL CHECK (scientific_status = 'NOT_ASSESSED'),
      created_at TEXT NOT NULL,
      CHECK (source_assessment != 'matched' OR
        (length(source_version) = 71 AND substr(source_version,1,7) = 'sha256:' AND
         substr(source_version,8) NOT GLOB '*[^0-9a-fA-F]*' AND
         checked_source_version = source_version))
    )''')
    # IDs/timestamps are not content: re-preparing a receipt must not duplicate it.
    c.execute('''CREATE UNIQUE INDEX IF NOT EXISTS idx_result_reviews_content
      ON result_reviews (project_id,result_id,ifnull(evidence_id,''),target_hash,
        source_ref,source_version,checked_source_version,source_assessment,
        review_kind,criteria,reviewer,conclusion,notes,scientific_status)''')
    c.execute('''CREATE INDEX IF NOT EXISTS idx_result_reviews_target
      ON result_reviews (project_id,result_id,created_at,id)''')


def _text(value, name, empty=False):
    if not isinstance(value, str) or len(value) > 4000 or (not empty and not value.strip()):
        raise ReviewError(name + ' 必须为' + ('字符串' if empty else '非空字符串') + '，最多4000字')
    return value


def _project_id(project):
    return _text(project.get('id') if isinstance(project, Mapping) else project, 'project_id')


def _rows(c, sql, args):
    cursor = c.execute(sql, args)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def target(c, project, result_id):
    """Read this project's result and exact action/ref/version evidence matches.

    ``evidence`` is the unique raw row or None; ``evidence_candidates`` is the
    complete, stable ID-ordered candidate list. ``evidence_id`` is set only for
    a unique match; missing/ambiguous matches are explicitly marked.
    target_hash is lowercase SHA256 of canonical JSON
    {project_id,result,evidence}, UTF-8, sorted keys, compact separators. Receipt
    history and rev are excluded, so adding a review cannot invalidate another
    draft's object hash. The outer API still checks its own current ifRev.
    """
    pid = _project_id(project)
    rid = _text(result_id, 'result_id')
    results = _rows(c, 'SELECT * FROM action_results WHERE project_id=? AND id=?', (pid, rid))
    if not results:
        raise ReviewError('当前项目中找不到 Result', 404)
    result = results[0]
    evidence = []
    if all(result.get(key) for key in ('action_id', 'source_ref', 'source_version')):
        evidence = _rows(c, '''SELECT * FROM evidence WHERE project_id=? AND action_id=?
          AND source_ref=? AND source_version=? ORDER BY id''',
          (pid, result['action_id'], result['source_ref'], result['source_version']))
    snapshot = {'project_id': pid, 'result': result, 'evidence': evidence}
    signature = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
    association = 'unique' if len(evidence) == 1 else ('missing' if not evidence else 'ambiguous')
    reviews = _rows(c, '''SELECT * FROM result_reviews WHERE project_id=? AND result_id=?
      ORDER BY created_at DESC,id DESC''', (pid, rid))
    # Match the outer server's revision readback; a standalone DB has rev 0.
    try:
        revision = c.execute("SELECT v FROM meta WHERE k='rev'").fetchone()
    except sqlite3.OperationalError:
        revision = None
    return dict(snapshot, evidence=evidence[0] if len(evidence) == 1 else None,
        evidence_candidates=evidence, target_hash=signature,
        source_ref=result['source_ref'], source_version=result['source_version'],
        reviews=reviews, rev=int(revision[0]) if revision else 0,
        evidence_id=evidence[0]['id'] if len(evidence) == 1 else None,
        evidence_association=association,
        association_note={'unique': '按同项目、同Action、同来源及版本唯一关联',
                          'missing': '0项匹配，无法唯一关联Evidence',
                          'ambiguous': '多项匹配，无法唯一关联Evidence；需人工指定ID'}[association],
        scientific_status=SCIENTIFIC_STATUS, boundary=REVIEW_BOUNDARY)


def _validated(c, project, body):
    if not isinstance(body, Mapping):
        raise ReviewError('审查内容必须为对象')
    pid = _project_id(project)
    if 'project_id' in body and body['project_id'] != pid:
        raise ReviewError('审查 project_id 与当前项目不一致')
    if body.get('consent') != CONSENT:
        raise ReviewError('需要明确人工审查 consent=' + CONSENT)
    current = target(c, pid, body.get('result_id'))
    if _text(body.get('target_hash'), 'target_hash') != current['target_hash']:
        raise ReviewError('审查对象已变化，请刷新页面重新审查', 409)
    source_version = _text(body.get('source_version'), 'source_version', empty=True)
    if source_version != current['result'].get('source_version'):
        raise ReviewError('来源登记版本已变化，请刷新页面重新审查', 409)
    source_ref = current['result']['source_ref']
    if 'source_ref' in body and body['source_ref'] != source_ref:
        raise ReviewError('来源引用与当前 Result 不一致', 409)
    eid = body.get('evidence_id')
    if eid is not None:
        _text(eid, 'evidence_id')
        if eid not in {row['id'] for row in current['evidence_candidates']}:
            raise ReviewError('Evidence 必须同项目、同Action、同来源及版本')
    else:
        eid = current['evidence_id']
    checked = _text(body.get('checked_source_version'), 'checked_source_version', empty=True)
    assessment = _text(body.get('source_assessment'), 'source_assessment')
    if assessment not in SOURCE_ASSESSMENTS:
        raise ReviewError('source_assessment 必须为 matched|missing|mismatch|unavailable|symbolic')
    if assessment == 'matched' and not (
            re.fullmatch(r'sha256:[0-9a-fA-F]{64}', source_version)
            and re.fullmatch(r'sha256:[0-9a-fA-F]{64}', checked)
            and source_version == checked):
        raise ReviewError('matched 人工声明仅允许两个相等的 sha256:64hex 版本字符串；'
                          '服务未读取来源，符号版本不可冒充字节匹配')
    kind = _text(body.get('review_kind'), 'review_kind')
    conclusion = _text(body.get('conclusion'), 'conclusion')
    if kind not in REVIEW_KINDS or conclusion not in CONCLUSIONS:
        raise ReviewError('review_kind 或 conclusion 无效')
    if body.get('scientific_status', SCIENTIFIC_STATUS) != SCIENTIFIC_STATUS:
        raise ReviewError('人工收据科学状态固定 NOT_ASSESSED')
    return {'project_id': pid, 'result_id': current['result']['id'], 'evidence_id': eid,
            'target_hash': current['target_hash'], 'source_ref': source_ref,
            'source_version': source_version, 'checked_source_version': checked,
            'source_assessment': assessment, 'review_kind': kind,
            'criteria': _text(body.get('criteria'), 'criteria'),
            'reviewer': _text(body.get('reviewer'), 'reviewer'),
            'conclusion': conclusion, 'notes': _text(body.get('notes'), 'notes'),
            'scientific_status': SCIENTIFIC_STATUS, 'consent': CONSENT}


def prepare(c, project, body):
    """Validate a human draft without writing; checked version must be supplied.

    An explicitly supplied empty checked_source_version can record a source
    that the human could not obtain. It is never filled from registered data.
    consent stays in the returned transport dict for save's revalidation; it
    is not a table column. ifRev and dry, if supplied, belong to the caller.
    """
    receipt = _validated(c, project, body)
    receipt['id'] = 'review-' + secrets.token_hex(12)
    receipt['created_at'] = datetime.datetime.now().astimezone().isoformat(timespec='microseconds')
    return receipt


def save(c, receipt):
    """Revalidate and INSERT once, without committing; duplicates return 409."""
    if not isinstance(receipt, Mapping) or set(receipt) != set(COLUMNS) | {'consent'}:
        raise ReviewError('收据字段不完整或包含未知字段')
    validated = _validated(c, receipt['project_id'], receipt)
    if any(receipt[key] != value for key, value in validated.items()):
        raise ReviewError('收据与当前审查对象不一致', 409)
    _text(receipt['id'], 'id')
    created_at = _text(receipt['created_at'], 'created_at')
    try:
        parsed = datetime.datetime.fromisoformat(created_at)
        if parsed.utcoffset() is None:
            raise ValueError('missing timezone')
    except ValueError:
        raise ReviewError('created_at 必须为带时区的 ISO 时间') from None
    try:
        c.execute('INSERT INTO result_reviews (' + ','.join(COLUMNS) + ') VALUES ('
                  + ','.join('?' for _ in COLUMNS) + ')', [receipt[key] for key in COLUMNS])
    except sqlite3.IntegrityError as exc:
        raise ReviewError('收据重复或违反审查约束', 409) from exc
    return dict(receipt)
