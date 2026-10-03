"""Metadata-only file-index drafts; neither facts, evidence nor execution approval."""
import hashlib
import json
import pathlib


def build(project, files, scope):
    registered = {f.get('path') for f in files if f.get('project') == project}
    observed = [{k: row.get(k) for k in ('id', 'kind', 'reference', 'version', 'state')}
                for row in scope.get('observed', [])] if scope.get('enabled') else []
    observed.sort(key=lambda row: str(row.get('id') or ''))
    snapshot = {'project_id': project, 'revision': scope.get('revision', 0),
                'enabled': bool(scope.get('enabled')), 'observed': observed,
                'registered_paths': sorted(str(p) for p in registered if p)}
    signature = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    items, seen = [], set()
    for row in observed:
        path, version = row.get('reference'), row.get('version') or ''
        if (row.get('kind') != 'file' or row.get('state') != 'read' or not path
                or path in registered or path in seen
                or len(version) != 71 or not version.startswith('sha256:')
                or any(c not in '0123456789abcdef' for c in version[7:])):
            continue
        seen.add(path)
        items.append({'id': row['id'], 'name': pathlib.Path(path).name, 'path': path,
                      'source_version': version, 'verification_status': 'UNVERIFIED'})
    return {'project_id': project, 'draft_hash': signature,
            'source_revision': scope.get('revision', 0), 'mode': 'local-metadata', 'items': items,
            'boundary': '只根据已授权读取的文件位置生成登记草稿；确认后只添加资料索引，不复制正文、不建立结论或证据、不启动行动。'}
