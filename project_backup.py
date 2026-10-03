"""Versioned project records and transactional history. No user files are copied."""
import copy
import hashlib
import json
import secrets
import datetime

TABLES = ('agents', 'actions', 'action_results', 'artifacts', 'evidence',
          'decision_requests', 'proposals', 'project_events', 'action_contracts', 'action_recoveries','result_reviews')
ADDITIVE_TABLES = {'action_contracts','action_recoveries','result_reviews'}
FORMAT = 'research-desk-project-backup'
VERSION = 1

def records(c, credentials=True):
    tables = {}
    for table in TABLES:
        columns = [r[1] for r in c.execute('PRAGMA table_info(' + table + ')')]
        rows = [dict(zip(columns, r)) for r in c.execute('SELECT * FROM ' + table)]
        if table == 'agents' and not credentials:
            for row in rows:
                row.pop('token_hash', None)
                row['last_seen'] = None
                row['status'] = 'configured'
        tables[table] = rows
    return tables

def envelope(c):
    return {'format': FORMAT, 'version': VERSION, 'schema_version': 1,
            'created_at': datetime.datetime.now().astimezone().isoformat(),
            'credentials_included': False,
            'state': json.loads(c.execute('SELECT body FROM state WHERE id=1').fetchone()[0]),
            'gateway': records(c, credentials=False)}

def history(c, actor, summary):
    body = c.execute('SELECT body FROM state WHERE id=1').fetchone()[0]
    c.execute('INSERT INTO history(body,time,actor,summary,gateway_body) VALUES(?,?,?,?,?)',
              (body, datetime.datetime.now().isoformat(timespec='seconds'), actor, summary[:240],
               json.dumps(records(c), ensure_ascii=False)))

def normalized(tables):
    if (not isinstance(tables,dict) or set(tables)-set(TABLES)
            or set(TABLES)-set(tables)-ADDITIVE_TABLES):
        raise ValueError('备份缺少完整的 Agent 项目记录')
    return dict({k:[] for k in ADDITIVE_TABLES},**tables)

def validate(state, tables, c, portable=False):
    tables=normalized(tables)
    projects = {p['id'] for p in state['projects']}
    tasks = {t['id'] for t in state['tasks']}
    for table in TABLES:
        if not isinstance(tables[table], list): raise ValueError('备份集合必须为数组')
        cols = {r[1] for r in c.execute('PRAGMA table_info(' + table + ')')}
        if portable and table == 'agents': cols -= {'token_hash'}
        ids = set()
        for row in tables[table]:
            if not isinstance(row, dict) or set(row) != cols:
                raise ValueError('备份字段不完整或版本不兼容：' + table)
            if row['id'] in ids: raise ValueError('备份存在重复 ID：' + table)
            ids.add(row['id'])
            if row['project_id'] not in projects and table != 'project_events':
                raise ValueError('备份包含不存在的项目引用：' + table)
    actions = {a['id']: a['project_id'] for a in tables['actions']}
    agents = {a['id']: a['project_id'] for a in tables['agents']}
    for table in ('action_results', 'artifacts', 'evidence', 'decision_requests', 'proposals','action_contracts','action_recoveries'):
        for row in tables[table]:
            aid = row.get('action_id')
            if aid and actions.get(aid) != row['project_id']:
                raise ValueError('备份行动引用不一致：' + table)
    for row in tables['actions']:
        if row.get('agent_id') and agents.get(row['agent_id']) != row['project_id']:
            raise ValueError('备份 Agent 引用不一致')
    results={r['id']:r['project_id'] for r in tables['action_results']}
    evidence={r['id']:r['project_id'] for r in tables['evidence']}
    for row in tables['result_reviews']:
        if results.get(row['result_id'])!=row['project_id'] or row['evidence_id'] and evidence.get(row['evidence_id'])!=row['project_id']:
            raise ValueError('备份复核对象引用不一致')

def restore(c, state, tables, portable=False):
    tables=normalized(tables)
    validate(state, tables, c, portable)
    rows = copy.deepcopy(tables)
    if portable:
        for a in rows['agents']:
            # Portable backups contain records, never an active authentication credential.
            a['token_hash'] = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
            a['last_seen'] = None
            a['status'] = 'configured'
    for table in reversed(TABLES): c.execute('DELETE FROM ' + table)
    for table in TABLES:
        columns = [r[1] for r in c.execute('PRAGMA table_info(' + table + ')')]
        for row in rows[table]:
            c.execute('INSERT INTO ' + table + '(' + ','.join(columns) + ') VALUES(' + ','.join('?' for _ in columns) + ')',
                      [row[name] for name in columns])
    # A backup or rollback restores records, never the fact that a worker has
    # read the new context. Existing tokens still have to handshake again.
    c.execute('UPDATE agent_protocols SET handshake_at=NULL')

def delete_project(c, project_id):
    for table in TABLES: c.execute('DELETE FROM ' + table + ' WHERE project_id=?', (project_id,))
