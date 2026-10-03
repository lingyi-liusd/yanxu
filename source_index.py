"""Persistent inventory and bounded content batches. No model or scientific writes."""
import hashlib
import json
import os
import pathlib
import stat

READ_LIMIT = 2 * 1024 * 1024
SCAN_LIMIT = 50000


def schema(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS source_index(
        project TEXT, reference TEXT, fingerprint TEXT, state TEXT, size INTEGER,
        version TEXT, offset INTEGER DEFAULT 0, accepted INTEGER DEFAULT 0,
        PRIMARY KEY(project,reference));
        CREATE TABLE IF NOT EXISTS coverage(project TEXT PRIMARY KEY, body TEXT);
    ''')
    if 'reading_details' not in [r[1] for r in c.execute('PRAGMA table_info(source_index)')]:
        c.execute("ALTER TABLE source_index ADD COLUMN reading_details TEXT DEFAULT '{}'")


def inventory(scope, walk, excluded, text_types, allowed):
    items, errors, seen = {}, [], set()
    count = 0
    for folder in json.loads(scope['folders']):
        try:
            for path in walk(folder, SCAN_LIMIT, allowed):
                count += 1
                if count > SCAN_LIMIT:
                    raise ValueError('目录索引达到50000项安全阈值，索引未完成；请拆分项目目录')
                if str(path) in seen:
                    continue
                seen.add(str(path))
                if not allowed(path):
                    continue
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode):
                    continue  # Never follow a symlink or open a special file.
                state = 'indexed' if path.suffix.lower() in text_types else 'unsupported'
                if info.st_size > READ_LIMIT and state=='indexed':
                    state = 'oversize'
                items[str(path)] = {'fingerprint':f'{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}',
                                    'state':state, 'size':info.st_size}
                if scope.get('document_text_enabled') and path.suffix.lower() in ('.pdf','.docx'):
                    from document_text import PARSER_VERSION
                    items[str(path)]['fingerprint'] += ':' + PARSER_VERSION
        except (OSError, ValueError) as exc:
            errors.append(str(folder)+'：'+str(exc))
    return items, errors


def sync(c, project, items, errors):
    old = {r['reference']:dict(r) for r in c.execute('SELECT * FROM source_index WHERE project=?', (project,))}
    for reference, item in items.items():
        prev = old.get(reference)
        if prev and prev['fingerprint']==item['fingerprint'] and prev['state']!='removed':
            continue
        c.execute('INSERT OR REPLACE INTO source_index(project,reference,fingerprint,state,size,version,offset,accepted) VALUES(?,?,?,?,?,?,0,0)',
                  (project, reference, item['fingerprint'], item['state'], item['size'], None))
    # An incomplete walk must never be interpreted as deletion.
    if not errors:
        for reference in old.keys()-items.keys():
            c.execute("UPDATE source_index SET state='removed' WHERE project=? AND reference=?", (project,reference))
    manifest = hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()
    c.execute('INSERT OR REPLACE INTO coverage VALUES(?,?)',
              (project, json.dumps({'inventory_complete':not errors, 'manifest_hash':manifest,
                                  'scan_limit':SCAN_LIMIT, 'errors':errors},ensure_ascii=False)))


def coverage(c, project):
    row = c.execute('SELECT body FROM coverage WHERE project=?', (project,)).fetchone()
    value = json.loads(row[0]) if row else {'inventory_complete':False, 'errors':[], 'scan_limit':SCAN_LIMIT}
    rows = [dict(r) for r in c.execute('SELECT state,size,offset,accepted FROM source_index WHERE project=?', (project,))]
    active = [r for r in rows if r['state']!='removed']
    value.update(indexed=len(active), supported=sum(r['state'] not in ('unsupported','oversize') for r in active),
                 processed=sum(r['state']=='read' for r in active),
                 partial=sum(r['state']=='read_partial' for r in active),
                 pending=sum(r['state'] in ('indexed','reading') for r in active),
                 blocked=sum(r['state'] in ('blocked','oversize') for r in active),
                 unsupported=sum(r['state']=='unsupported' for r in active),
                 removed=sum(r['state']=='removed' for r in rows),
                 accepted_chunks=sum(r['accepted'] for r in rows),
                 boundary='已索引不等于已理解；processed表示未发现提取缺口且文字批次处理完成。partial表示可提取文字已处理，但原文件仍有未解析内容，不计入processed；不是回包失败。pending才表示文字批次待处理。以上都不是科学核验。PDF/DOCX须另行授权；旧DOC、扫描文字、过大或无法读取的文件保留缺口。')
    return value


def batch(c, project, folders, secure_read, sensitive, allowed, total_limit, document_reader=None):
    rows = c.execute("SELECT * FROM source_index WHERE project=? AND state IN ('indexed','reading') ORDER BY reference", (project,)).fetchall()
    items, updates, size = [], [], 0
    for row in rows:
        if len(items)>=128 or size>=total_limit:
            break
        path = pathlib.Path(row['reference'])
        root = next((pathlib.Path(f) for f in folders if pathlib.Path(f) in path.parents), None)
        try:
            if root is None or not allowed(path):
                raise ValueError('目录授权已变化')
            raw = secure_read(path, root, READ_LIMIT)
            details = {}
            text_bytes = raw
            if path.suffix.lower() in ('.pdf','.docx'):
                if not document_reader:
                    raise ValueError('文档文字提取未授权')
                text_bytes, details = document_reader(raw,path.suffix.lower())
                details = dict(details, text_bytes=len(text_bytes))
            text = text_bytes.decode('utf-8')
            if '\x00' in text or sensitive.search(text):
                raise ValueError('非纯文本或疑似秘密')
            version = 'sha256:'+hashlib.sha256(raw).hexdigest()
            offset = row['offset'] if row['version']==version else 0
            part = text_bytes[offset:offset+total_limit-size]
            # Do not split a UTF-8 character at the batch boundary.
            content = part.decode('utf-8', errors='ignore')
            used = len(content.encode('utf-8'))
            if not used and text_bytes:
                break
            items.append({'id':'file:'+str(path), 'kind':'file', 'reference':str(path),
                          'version':version, 'content':content, 'state':'read', 'verification_status':'UNVERIFIED',
                          'chunk_start':offset, 'chunk_end':offset+used, 'file_bytes':len(raw),
                          'truncated':offset+used<len(text_bytes) or offset>0})
            if details:
                items[-1]['document_text']={k:v for k,v in details.items() if k!='units'}
                items[-1]['document_text']['locations']=[unit['label'] for unit in details.get('units',[])
                    if unit['start'] < offset+used and unit['end'] > offset]
                # Ledger keeps metadata only, never the extracted content.
            updates.append((version,offset,'reading',json.dumps({k:v for k,v in details.items() if k!='units'},ensure_ascii=False),project,str(path)))
            size += used
        except (OSError, ValueError, UnicodeError) as exc:
            reason=str(exc) if path.suffix.lower() in ('.pdf','.docx') and isinstance(exc,ValueError) else '读取受限、非纯文本或疑似秘密；未处理'
            updates.append((None,0,'blocked',json.dumps({'error':reason},ensure_ascii=False),project,str(path)))
            items.append({'id':'file:'+str(path), 'kind':'file', 'reference':str(path),
                          'state':'skipped_or_unreadable', 'verification_status':'UNVERIFIED'})
    return items, updates


def accept(c, project, items):
    advanced=0
    for item in items:
        if item.get('kind')!='file' or 'chunk_end' not in item:
            continue
        document=item.get('document_text',{})
        done=item['chunk_end']>=document.get('text_bytes',item['file_bytes'])
        state=('read_partial' if document and not document.get('complete') else 'read') if done else 'reading'
        result=c.execute("UPDATE source_index SET offset=?,state=?,accepted=accepted+1 WHERE project=? AND reference=? AND version=? AND offset=? AND state='reading'",
                  (item['chunk_end'], state,
                   project,item['reference'],item['version'],item['chunk_start']))
        advanced+=result.rowcount
    return advanced
