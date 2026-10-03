"""Human-bound local workspaces. Path policy, not an OS process sandbox."""
import contextlib
import json
import os
import pathlib
import sqlite3
import uuid


class Registry:
    def __init__(self, directory, snapshot):
        self.directory = pathlib.Path(directory).resolve()
        self.path = self.directory / 'workspaces.sqlite3'
        self.snapshot = snapshot
        with self.db() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY, name TEXT, root TEXT UNIQUE);
                CREATE TABLE IF NOT EXISTS bindings(project TEXT PRIMARY KEY, workspace_id TEXT,
                    relative_path TEXT, exclusions TEXT, revision INTEGER);
            ''')
            for column in ('root_identity','project_identity'):
                if column not in [r[1] for r in c.execute('PRAGMA table_info(bindings)')]:
                    c.execute('ALTER TABLE bindings ADD COLUMN '+column+' TEXT')
        os.chmod(self.path, 0o600)

    @contextlib.contextmanager
    def db(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def valid_root(self, root):
        path = pathlib.Path(root)
        protected = [pathlib.Path.home(), self.directory, pathlib.Path(__file__).parent.resolve(),
                     pathlib.Path(os.environ.get('CODEX_HOME', str(pathlib.Path.home()/'.codex'))).resolve()]
        if (not path.is_absolute() or not path.is_dir() or str(path.resolve()) != str(root)
                or any(path == p or path in p.parents for p in protected)
                or any(p in path.parents for p in protected[1:])):
            raise ValueError('请选择真实项目目录；不能使用整个用户目录、研序或Codex私有目录、符号链接')
        return path

    def status(self, project):
        raw = self.snapshot(project)['project']
        with self.db() as c:
            row = c.execute('SELECT b.*, w.name, w.root FROM bindings b JOIN workspaces w ON w.id=b.workspace_id WHERE project=?', (project,)).fetchone()
        if not row:
            return {'configured':False, 'revision':0, 'state':'needs_binding',
                    'suggested_path':raw.get('workspace') or raw.get('workspace_path') or '',
                    'path':None, 'boundary':'旧项目路径只是建议，不代表读取授权或目录隔离'}
        value = dict(row)
        value['exclusions'] = json.loads(value['exclusions'])
        value['path'] = str(pathlib.Path(value['root'])/value['relative_path'])
        value.update(configured=True, state='ready', access='read_only', isolation='path_policy',
                     boundary='项目目录不重叠；读取仍需独立授权。不是进程沙箱，也未授权Agent写本地文件。')
        try:
            self.valid_root(value['root'])
            p = pathlib.Path(value['path'])
            if not p.is_dir() or str(p.resolve()) != str(p):
                raise ValueError('项目目录缺失或被替换为符号链接')
            if value['root_identity']!=self.identity(value['root']) or value['project_identity']!=self.identity(p):
                raise ValueError('目录身份已变化，需要重新确认绑定，不能沿同名路径读取替换目录')
        except (OSError, ValueError) as exc:
            value.update(state='unavailable', error=str(exc))
        return value

    @staticmethod
    def identity(path):
        info=pathlib.Path(path).stat()
        return str(info.st_dev)+':'+str(info.st_ino)

    def configure(self, project, body):
        if not isinstance(body,dict):
            raise ValueError('工作区请求必须是对象')
        self.snapshot(project)
        if body.get('consent') != 'project-workspace-binding-v1':
            raise ValueError('须确认工作区和本项目目录；绑定不自动授权读取或发送正文')
        root = self.valid_root(body.get('root') or '')
        relative = pathlib.Path(body.get('relative_path') or '.')
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('项目目录必须是工作区内的相对路径')
        target = root/relative
        if not target.is_dir() or target.resolve() != target:
            raise ValueError('项目目录不存在或包含符号链接；不会自动创建或搬动文件')
        exclusions = body.get('exclusions', [])
        if (not isinstance(exclusions, list) or len(exclusions)>32 or any(not isinstance(x,str) or
                not x.strip() or pathlib.Path(x).is_absolute() or '..' in pathlib.Path(x).parts or x=='.' for x in exclusions)):
            raise ValueError('排除项须为项目内相对路径，每行一个，最多32项')
        exclusions = sorted(set(str(pathlib.Path(x)) for x in exclusions))
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT revision FROM bindings WHERE project=?', (project,)).fetchone()
            revision = row[0] if row else 0
            if body.get('if_revision') != revision:
                raise ValueError('工作区绑定已变化，请重新打开')
            others = c.execute('SELECT b.project,b.relative_path,w.root FROM bindings b JOIN workspaces w ON w.id=b.workspace_id WHERE b.project<>?', (project,)).fetchall()
            for other in others:
                peer = pathlib.Path(other['root'])/other['relative_path']
                if target == peer or target in peer.parents or peer in target.parents:
                    raise ValueError('项目目录与另一项目重叠，请选择独立子目录')
            if body.get('dry'):
                return {'dry':True, 'path':str(target), 'revision':revision+1}
            workspace = c.execute('SELECT id FROM workspaces WHERE root=?', (str(root),)).fetchone()
            wid = workspace[0] if workspace else 'ws-'+uuid.uuid4().hex
            if not workspace:
                c.execute('INSERT INTO workspaces VALUES(?,?,?)', (wid, str(body.get('name') or root.name)[:120], str(root)))
            c.execute('INSERT OR REPLACE INTO bindings VALUES(?,?,?,?,?,?,?)', (project, wid, str(relative), json.dumps(exclusions), revision+1,self.identity(root),self.identity(target)))
        return self.status(project)

    def allows(self, project, path, revision=None):
        value = self.status(project)
        if value['state']!='ready' or (revision is not None and value['revision']!=revision):
            return False
        root, path = pathlib.Path(value['path']), pathlib.Path(path)
        if not path.is_absolute() or not (path==root or root in path.parents) or path.resolve()!=path:
            return False
        rel = path.relative_to(root)
        return not any(rel==pathlib.Path(x) or pathlib.Path(x) in rel.parents for x in value['exclusions'])
