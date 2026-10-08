import json, sqlite3, pathlib, secrets, os, webbrowser, threading, datetime, re, hashlib, tempfile, urllib.error, urllib.request, time
import agent_gateway
import project_backup
import agent_manager
import agent_connection
import workspace_registry
import folder_picker
import ecosystem
import ecosystem_contracts
ECOSYSTEM_BUILD_ID = ecosystem_contracts.build_id()
os.umask(0o077)
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
ROOT = pathlib.Path(__file__).resolve().parent
import platform_support
DEFAULT_DATA = platform_support.default_data()
DATA = pathlib.Path(os.environ.get('RESEARCH_DESK_DATA_DIR', str(DEFAULT_DATA))).expanduser().resolve()
DATA.mkdir(parents=True, exist_ok=True)
try:
    DATA.chmod(0o700)
except OSError:
    pass
DB = DATA / 'desk.sqlite3'
TOKEN_FILE = DATA / 'api-token'
if not TOKEN_FILE.exists():
    TOKEN_FILE.write_text(secrets.token_urlsafe(32))
try:
    TOKEN_FILE.chmod(0o600)
except OSError:
    pass
TOKEN = TOKEN_FILE.read_text().strip()
SCHEMA_VERSION = 1
FOCUS_FILE = DATA / 'daily-focus.json'
FOCUS_LOCK = threading.RLock()
FOCUS_SCHEMA_VERSION = 1
FOCUS_SCOPE = 'global'
FOCUS_TYPES = {'task', 'synthesized_action', 'review', 'unblock', 'wait'}
FOCUS_TRIGGERS = {'daily', 'task_changed', 'evidence_changed', 'manual_refresh'}
FOCUS_FEEDBACK = {'accepted', 'rejected', 'alternate'}
FOCUS_SYSTEM_PROMPT = '''You are the project focus planner of Research Desk, an AI-native project operating system.

Your role is not to choose the highest-priority task mechanically. Determine the single most valuable next focus for this long-running project, based only on the supplied project state. A focus may be an action, question, decision, review, or blocker; it need not be a task.

Consider the project's goal, current blockers, action dependencies, recent evidence, negative or inconclusive results, deadlines, downstream impact, uncertainty reduction, and whether a meaningful verifiable output can be produced now. A P0 task is a human prior, not an automatic override.

Do not invent experiments, evidence, results, deadlines, dependencies, or project facts. If the state is insufficient for a concrete action, return a review or unblock action. The action may reference an existing task or synthesize a new proposed action. Do not modify project state. Return exactly one primary focus as valid JSON only, with the requested schema.'''

def ui_language(value=None):
    if value is not None and value not in ('zh-CN','en'):
        raise ValueError('界面语言只支持中文或英语')
    with connect() as c:
        if value is not None:
            c.execute('INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)',('ui-language',value))
        row=c.execute('SELECT v FROM meta WHERE k=?',('ui-language',)).fetchone()
    return row[0] if row and row[0] in ('zh-CN','en') else None

def migrate_state(body, from_version):
    if not isinstance(body, dict):
        raise ValueError('数据库状态结构不正确')
    version = int(from_version or 0)
    if version < 1:
        body.setdefault('projects', [])
        body.setdefault('tasks', [])
        body.setdefault('files', [])
        body.setdefault('decisions', [])
        for t in body.get('tasks', []):
            if isinstance(t, dict):
                t.setdefault('status', '待开始')
                t.setdefault('priority', 'P2')
                t.setdefault('stage', '')
                t.setdefault('start', '')
                t.setdefault('end', '')
                t.setdefault('completed', '')
                t.setdefault('milestone', False)
                t.setdefault('parent', '')
                t.setdefault('deps', [])
                t.setdefault('note', '')
        for d in body.get('decisions', []):
            if isinstance(d, dict): d.setdefault('status', '待决')
        version = 1
    if version != SCHEMA_VERSION:
        raise ValueError('不支持的数据版本：%s' % version)
    return body, version

def connect():
    global _SCHEMA_READY
    c = sqlite3.connect(DB, timeout=15)
    if _SCHEMA_READY:
        return c
    with _INIT_LOCK:
        if _SCHEMA_READY:
            return c
        try:
            DB.chmod(0o600)
        except OSError:
            pass
        c.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, body TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)')
        for column, decl in [('time','TEXT'), ('actor','TEXT'), ('summary','TEXT'), ('gateway_body','TEXT')]:
            if column not in [row[1] for row in c.execute('PRAGMA table_info(history)')]:
                c.execute('ALTER TABLE history ADD COLUMN %s %s' % (column, decl))
        c.execute('INSERT OR IGNORE INTO state VALUES(1,?)', (json.dumps({'projects':[], 'tasks':[], 'files':[], 'decisions':[]}),))
        row = c.execute('SELECT body FROM state WHERE id=1').fetchone()
        body = json.loads(row[0])
        version_row = c.execute("SELECT v FROM meta WHERE k='schema_version'").fetchone()
        body, version = migrate_state(body, int(version_row[0]) if version_row else 0)
        if not version_row or int(version_row[0]) != version:
            c.execute('UPDATE state SET body=? WHERE id=1', (json.dumps(body, ensure_ascii=False),))
            c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('schema_version',?)", (str(version),))
        agent_gateway.schema(c)
        c.commit()
        _SCHEMA_READY = True
    return c
_INIT_LOCK = threading.Lock()
_SCHEMA_READY = False
SNAP_LOCK = threading.Lock()
def maybe_snapshot(state, c=None):
    day = datetime.date.today().isoformat()
    snapdir = DATA / 'snapshots'
    snapdir.mkdir(exist_ok=True)
    try:
        snapdir.chmod(0o700)
    except OSError:
        pass
    marker = snapdir / ('day-' + day)
    with SNAP_LOCK:
        if marker.exists():
            return
        snap = snapdir / ('auto-' + day + '.json')
        snap.write_text(json.dumps(project_backup.envelope(c) if c is not None else state, ensure_ascii=False), encoding='utf-8')
        marker.write_text('', encoding='utf-8')
        try:
            snap.chmod(0o600); marker.chmod(0o600)
        except OSError:
            pass
        snaps = sorted(snapdir.glob('auto-*.json'))
        for stale in snaps[:-14]:
            stale.unlink()
EV_LOCK = threading.Lock()
EV_LISTENERS = set()
def notify(event=None):
    payload = event if isinstance(event, dict) else {'kind': 'state', 'research_changed': True}
    message = ('data: ' + json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n\n').encode()
    with EV_LOCK:
        listeners = list(EV_LISTENERS)
    for w in listeners:
        try:
            w.write(message); w.flush()
        except Exception:
            with EV_LOCK: EV_LISTENERS.discard(w)

def notify_named(name, payload):
    message = ('event: ' + name + '\ndata: ' + json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n\n').encode()
    with EV_LOCK:
        listeners = list(EV_LISTENERS)
    for w in listeners:
        try:
            w.write(message); w.flush()
        except Exception:
            with EV_LOCK: EV_LISTENERS.discard(w)
    # Older clients still depend on unnamed state notices.
    notify({'kind':'agent_event','collections':[], 'research_changed':False})

def local_today():
    return datetime.date.today().isoformat()

def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')

def _focus_default_store():
    return {'version': FOCUS_SCHEMA_VERSION, 'entries': [], 'feedback': []}

def _read_focus_store():
    if not FOCUS_FILE.exists():
        return _focus_default_store()
    try:
        raw = json.loads(FOCUS_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('当前重点缓存无法读取：%s' % exc)
    if not isinstance(raw, dict):
        raise ValueError('当前重点缓存结构不正确')
    raw.setdefault('version', FOCUS_SCHEMA_VERSION)
    raw.setdefault('entries', [])
    raw.setdefault('feedback', [])
    if not isinstance(raw['entries'], list) or not isinstance(raw['feedback'], list):
        raise ValueError('当前重点缓存结构不正确')
    return raw

def _write_focus_store(store):
    store = dict(store)
    store['version'] = FOCUS_SCHEMA_VERSION
    store['entries'] = list(store.get('entries', []))[-60:]
    store['feedback'] = list(store.get('feedback', []))[-120:]
    DATA.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix='.daily-focus-', dir=str(DATA))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(store, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, str(FOCUS_FILE))
    finally:
        if os.path.exists(temp_name):
            try:
                os.unlink(temp_name)
            except OSError:
                pass

def _history_rows(limit=60):
    with connect() as c:
        rows = c.execute('SELECT id,time,body,actor,summary,gateway_body FROM history ORDER BY id DESC LIMIT ?', (int(limit),)).fetchall()
    return [{'id': row[0], 'time': row[1], 'body': row[2], 'actor': row[3] or 'legacy', 'summary': row[4] or ''} for row in rows]

def _date_from_value(value):
    if not value:
        return ''
    if isinstance(value, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(float(value) / (1000 if value > 100000000000 else 1)).date().isoformat()
        except (ValueError, OSError, OverflowError):
            return ''
    raw = str(value)
    match = re.match(r'^(\d{4}-\d{2}-\d{2})', raw)
    if match:
        return match.group(1)
    try:
        return datetime.datetime.fromisoformat(raw.replace('Z', '+00:00')).date().isoformat()
    except ValueError:
        return ''

def _short_text(value, limit=360):
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    return text if len(text) <= limit else text[:limit] + '…'

def _priority_rank(value):
    return {'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3}.get(value, 2)

def _task_progress(task, children):
    value = task.get('progress')
    if isinstance(value, (int, float)):
        return max(0, min(100, round(float(value))))
    if children:
        return round(sum(1 for child in children if child.get('status') == '已完成') / len(children) * 100)
    return None

def _evidence_kind(task):
    raw = ' '.join(str(task.get(key, '') or '') for key in ('title', 'note', 'stage', 'noteType'))
    lower = raw.lower()
    if re.search(r'负结果|失败|不成立|不可行|无效|no-go|fail|negative', lower):
        return 'negative'
    if re.search(r'通过|成功|成立|有效|pass|positive|confirmed', lower):
        return 'positive'
    if re.search(r'无结论|不确定|未闭合|未闭|待验证|inconclusive|uncertain', lower):
        return 'inconclusive'
    if re.search(r'证据|结果|实验|仿真|finding|evidence|result|experiment|simulation|验证|核验', lower):
        return 'unknown'
    return ''

def build_project_context(state, history=None, scope=FOCUS_SCOPE, feedback=None, as_of=None):
    '''Build a bounded, deterministic project context for the focus engine.'''
    state = state or {}
    if scope == FOCUS_SCOPE and state.get('projects'):
        state = ecosystem.desk_state(state)
    as_of = as_of or local_today()
    projects = list(state.get('projects') or [])
    tasks = list(state.get('tasks') or [])
    decisions = list(state.get('decisions') or [])
    files = list(state.get('files') or [])
    project_ids = {p.get('id') for p in projects}
    if scope and scope != FOCUS_SCOPE:
        tasks = [t for t in tasks if t.get('project') == scope]
        decisions = [d for d in decisions if d.get('project') == scope]
        files = [f for f in files if f.get('project') == scope]
        projects = [p for p in projects if p.get('id') == scope]
    project_name = {p.get('id'): p.get('name', '') for p in projects}
    task_map = {t.get('id'): t for t in tasks if t.get('id')}
    children = {}
    dependents = {}
    for task in tasks:
        children.setdefault(task.get('parent'), []).append(task)
        for dep in task.get('deps') or []:
            dependents.setdefault(dep, []).append(task)
    today_date = datetime.date.fromisoformat(as_of)
    recent_cutoff = today_date - datetime.timedelta(days=7)

    def task_row(task):
        own_children = children.get(task.get('id'), [])
        unresolved = [dep for dep in task.get('deps') or [] if dep in task_map and task_map[dep].get('status') != '已完成']
        downstream = [item.get('id') for item in dependents.get(task.get('id'), []) if item.get('status') != '已完成']
        return {
            'id': task.get('id', ''), 'project_id': task.get('project', ''),
            'project': project_name.get(task.get('project'), task.get('project', '')),
            'title': _short_text(task.get('title'), 180), 'priority': task.get('priority', 'P2'),
            'status': task.get('status', '待开始'), 'stage': task.get('stage', ''), 'deadline': task.get('end', ''),
            'start': task.get('start', ''), 'completed': task.get('completed', ''),
            'progress': _task_progress(task, own_children), 'dependencies': list(task.get('deps') or []),
            'unresolved_dependency_ids': unresolved, 'downstream_task_ids': downstream,
            'downstream_count': len(downstream), 'parent': task.get('parent', ''),
            'updated_at': task.get('updated_at', ''), 'note': _short_text(task.get('note'), 360),
            'note_type': task.get('noteType', '')
        }

    rows = [task_row(task) for task in tasks]
    open_rows = [row for row in rows if row['status'] != '已完成']
    completed_rows = [row for row in rows if row['status'] == '已完成']
    overdue_rows = [row for row in open_rows if row['deadline'] and row['deadline'] < as_of]
    recently_completed = [row for row in completed_rows if _date_from_value(row['completed']) and _date_from_value(row['completed']) >= recent_cutoff.isoformat()]
    in_progress = [row for row in open_rows if row['status'] == '进行中']
    blocked = [row for row in open_rows if row['status'] == '受阻']
    todo = [row for row in open_rows if row['status'] == '待开始']
    blocking_tasks = [row for row in open_rows if row['status'] == '受阻' or row['downstream_count'] or row['unresolved_dependency_ids']]
    dependency_bottlenecks = [row for row in open_rows if row['unresolved_dependency_ids']]

    def row_sort(row):
        return (_priority_rank(row['priority']), row['deadline'] or '9999-99-99', -row['downstream_count'], row['title'])

    for group in (in_progress, blocked, todo, overdue_rows, recently_completed, blocking_tasks, dependency_bottlenecks):
        group.sort(key=row_sort)
    evidence = []
    for row in rows:
        kind = _evidence_kind(row)
        recent_marker = _date_from_value(row.get('completed')) or _date_from_value(row.get('start')) or _date_from_value(row.get('updated_at'))
        if kind and (not recent_marker or recent_marker >= recent_cutoff.isoformat()):
            evidence.append({'task_id': row['id'], 'project_id': row['project_id'], 'project': row['project'], 'title': row['title'], 'kind': kind, 'status': row['status'], 'note': row['note']})
    for file_item in files:
        modified = _date_from_value(file_item.get('modified') or file_item.get('mtime'))
        if modified and modified >= recent_cutoff.isoformat():
            evidence.append({'file_id': file_item.get('id', ''), 'project_id': file_item.get('project', ''), 'project': project_name.get(file_item.get('project'), file_item.get('project', '')), 'title': _short_text(file_item.get('path'), 180), 'kind': 'unknown', 'status': 'indexed', 'note': '最近更新的资料索引'})
    evidence = evidence[:20]
    recent_changes = []
    for item in (history or [])[:20]:
        if item.get('time'):
            recent_changes.append({'time': item.get('time'), 'actor': item.get('actor', 'legacy'), 'summary': _short_text(item.get('summary') or '状态发生变化', 240)})
    recent_changes.extend({'time': row.get('completed'), 'actor': 'state', 'summary': '完成任务：' + row['title']} for row in recently_completed[:12])
    recent_changes = recent_changes[:32]
    current_phases = []
    for project in projects:
        stages = project.get('stages') or []
        own = [row for row in rows if row['project_id'] == project.get('id')]
        phase = '未分阶段'
        if stages:
            for index, stage in enumerate(stages):
                stage_tasks = [row for row in own if row.get('stage') == stage or str(row.get('stage', '')).upper() == 'G' + str(index + 1)]
                if any(row['status'] != '已完成' for row in stage_tasks):
                    phase = stage
                    break
            else:
                phase = stages[-1] if own else stages[0]
        current_phases.append({'id': project.get('id', ''), 'name': project.get('name', ''), 'description': _short_text(project.get('description'), 420), 'goal': _short_text(project.get('goal'), 420), 'success_definition': _short_text(project.get('success_definition'), 420), 'current_state': _short_text(project.get('current_state'), 420), 'constraints': list(project.get('constraints') or []), 'type': project.get('type') or '', 'stages': list(stages), 'current_phase': phase})
    pending_decisions = [{'id': d.get('id', ''), 'project_id': d.get('project', ''), 'project': project_name.get(d.get('project'), d.get('project', '')), 'title': _short_text(d.get('title'), 180), 'question': _short_text(d.get('question'), 280), 'recommendation': _short_text(d.get('recommendation'), 280), 'status': d.get('status', '待决'), 'due': d.get('due', '')} for d in decisions if d.get('status') != '已决'][:20]
    feedback_rows = [item for item in (feedback or []) if item.get('date') == as_of and item.get('scope', FOCUS_SCOPE) == scope and item.get('action') in ('rejected', 'alternate')]
    return {
        'scope': scope, 'as_of': as_of, 'project_objectives': current_phases,
        'tasks': {'todo': todo[:40], 'in_progress': in_progress[:40], 'blocked': blocked[:40], 'completed': completed_rows[:40], 'recently_completed': recently_completed[:20], 'overdue': overdue_rows[:40]},
        'blocking_tasks': blocking_tasks[:30], 'dependency_bottlenecks': dependency_bottlenecks[:30],
        'recent_changes': recent_changes, 'recent_evidence': evidence,
        'pending_decisions': pending_decisions, 'user_rejected_focus': [{'focus_id': item.get('focus_id', ''), 'title': _short_text(item.get('title'), 180), 'action': item.get('action')} for item in feedback_rows],
        'open_task_count': len(open_rows), 'all_tasks_completed': bool(rows) and not open_rows
    }

# Existing integrations may still import the old function name.
build_research_context = build_project_context

def _context_hash(context):
    encoded = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()

class FocusProviderError(Exception):
    pass

class ResearchFocusProvider:
    name = 'unconfigured'

    @property
    def available(self):
        return False

    def generate(self, context, exclude_previous_focus=None):
        raise FocusProviderError('未配置 Project Focus AI provider')

class OpenAICompatibleFocusProvider(ResearchFocusProvider):
    name = 'openai-compatible'

    def __init__(self):
        self.url = os.environ.get('RESEARCH_FOCUS_API_URL', '').strip()
        self.key = os.environ.get('RESEARCH_FOCUS_API_KEY', '').strip()
        self.model = os.environ.get('RESEARCH_FOCUS_MODEL', '').strip()
        try:
            self.timeout = max(5, min(90, float(os.environ.get('RESEARCH_FOCUS_TIMEOUT', '25'))))
        except ValueError:
            self.timeout = 25

    @property
    def available(self):
        return bool(self.url and self.model)

    def generate(self, context, exclude_previous_focus=None):
        if not self.available:
            raise FocusProviderError('未配置 Project Focus API URL 或模型')
        user_payload = {'context': context, 'output_schema': {'focus_type': 'task|synthesized_action|review|unblock|wait (legacy compatibility)', 'task_id': 'existing task id or empty', 'entity_type': 'task|action|question|decision|review|blocker|wait', 'entity_id': 'existing task or decision id, or empty for a synthesized focus', 'project_id': 'existing project id or empty', 'title': 'string', 'reason': 'string', 'goal': 'string', 'expected_output': 'string', 'blocked_by': 'task ids or empty array', 'depends_on': 'task ids or empty array', 'confidence': 'number from 0 to 1', 'urgency': 'high|medium|low', 'impact': 'high|medium|low', 'uncertainty_reduction': 'high|medium|low', 'fallback_task_id': 'existing task id or empty', 'source_task_ids': 'existing task ids'}}
        if exclude_previous_focus:
            user_payload['previous_focus_to_avoid'] = {'focus_id': exclude_previous_focus.get('focus_id', ''), 'task_id': exclude_previous_focus.get('task_id', ''), 'title': exclude_previous_focus.get('title', '')}
        body = json.dumps({'model': self.model, 'temperature': 0.15, 'messages': [{'role': 'system', 'content': FOCUS_SYSTEM_PROMPT}, {'role': 'user', 'content': json.dumps(user_payload, ensure_ascii=False)}], 'response_format': {'type': 'json_object'}}, ensure_ascii=False).encode('utf-8')
        headers = {'Content-Type': 'application/json'}
        if self.key:
            headers['Authorization'] = 'Bearer ' + self.key
        request = urllib.request.Request(self.url, data=body, headers=headers, method='POST')
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode('utf-8')
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            raise FocusProviderError('Project Focus provider 请求失败：%s' % type(exc).__name__)
        try:
            envelope = json.loads(raw)
            content = envelope.get('choices', [{}])[0].get('message', {}).get('content') if isinstance(envelope, dict) else None
            if content is None and isinstance(envelope, dict):
                content = envelope.get('output_text') or envelope.get('content') or envelope
            if isinstance(content, str):
                content = re.sub(r'^\s*```(?:json)?\s*|\s*```\s*$', '', content.strip(), flags=re.I)
                content = json.loads(content)
            if not isinstance(content, dict):
                raise ValueError('provider output is not an object')
            return content
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise FocusProviderError('Project Focus provider 返回的 JSON 无效：%s' % type(exc).__name__)

def get_focus_provider():
    provider = OpenAICompatibleFocusProvider()
    return provider if provider.available else ResearchFocusProvider()

def _all_context_tasks(context):
    tasks = []
    for group in (context.get('tasks') or {}).values():
        if isinstance(group, list):
            tasks.extend(group)
    unique = {}
    for task in tasks:
        if task.get('id'):
            unique[task['id']] = task
    return unique

def _focus_id(focus, generated_at):
    raw = '|'.join([str(focus.get('date', '')), str(focus.get('status_snapshot_hash', '')), str(generated_at), str(focus.get('title', ''))])
    return 'focus-' + hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]

def _normalize_focus(raw, context, context_hash, trigger, source, generated_at, exclude_previous=None, provider_error=''):
    if not isinstance(raw, dict):
        raise FocusProviderError('focus 结果不是 JSON 对象')
    task_map = _all_context_tasks(context)
    project_ids = {item.get('id') for item in context.get('project_objectives', [])}
    focus_type = str(raw.get('focus_type') or '').strip()
    if focus_type not in FOCUS_TYPES:
        raise FocusProviderError('focus_type 不合法')
    task_id = str(raw.get('task_id') or '').strip()
    if task_id and task_id not in task_map:
        raise FocusProviderError('task_id 不在当前项目上下文中')
    if focus_type == 'task' and not task_id:
        raise FocusProviderError('task 类型必须绑定 task_id')
    project_id = str(raw.get('project_id') or '').strip()
    if project_id and project_id not in project_ids:
        project_id = task_map.get(task_id, {}).get('project_id', '')
    task = task_map.get(task_id, {})
    title = _short_text(raw.get('title') or task.get('title') or '复核当前项目状态', 220)
    reason = _short_text(raw.get('reason'), 720)
    goal = _short_text(raw.get('goal'), 500)
    expected_output = _short_text(raw.get('expected_output'), 500)
    if not reason or not goal or not expected_output:
        raise FocusProviderError('focus 缺少 reason、goal 或 expected_output')
    try:
        confidence = float(raw.get('confidence'))
    except (TypeError, ValueError):
        raise FocusProviderError('confidence 不合法')
    if confidence < 0 or confidence > 1:
        raise FocusProviderError('confidence 超出范围')
    urgency = str(raw.get('urgency') or 'medium')
    impact = str(raw.get('impact') or 'medium')
    uncertainty = str(raw.get('uncertainty_reduction') or 'medium')
    if urgency not in {'high', 'medium', 'low'} or impact not in {'high', 'medium', 'low'} or uncertainty not in {'high', 'medium', 'low'}:
        raise FocusProviderError('focus 等级字段不合法')
    valid_ids = set(task_map)
    raw_source_ids = raw.get('source_task_ids') or []
    if not isinstance(raw_source_ids, list):
        raise FocusProviderError('source_task_ids 不合法')
    if any(str(item) not in valid_ids for item in raw_source_ids):
        raise FocusProviderError('source_task_ids 含有不存在的任务')
    source_ids = list(dict.fromkeys(str(item) for item in raw_source_ids))[:20]
    if task_id and task_id not in source_ids:
        source_ids.insert(0, task_id)
    fallback_id = str(raw.get('fallback_task_id') or '').strip()
    if fallback_id not in valid_ids:
        fallback_id = ''
    def refs(value, field):
        if value is None:
            return []
        if not isinstance(value, list):
            raise FocusProviderError('%s 不合法' % field)
        if any(str(item) not in valid_ids for item in value):
            raise FocusProviderError('%s 含有不存在的任务' % field)
        return list(dict.fromkeys(str(item) for item in value))[:12]
    entity_type = str(raw.get('entity_type') or {'task':'task','synthesized_action':'action','review':'review','unblock':'blocker','wait':'wait'}.get(focus_type, 'review')).strip()
    if entity_type not in {'task','action','question','decision','review','blocker','wait'}:
        raise FocusProviderError('entity_type 不合法')
    entity_id = str(raw.get('entity_id') or (task_id if entity_type in {'task','blocker'} else '')).strip()
    if entity_type in {'task','blocker'} and entity_id and entity_id not in task_map:
        raise FocusProviderError('entity_id 不在当前项目上下文中')
    if entity_type == 'action' and entity_id and entity_id not in {str(item.get('id')) for item in context.get('recent_actions', [])}:
        raise FocusProviderError('action entity_id 不在当前项目上下文中')
    if entity_type == 'decision' and entity_id and entity_id not in {str(item.get('id')) for item in context.get('pending_decisions', [])}:
        raise FocusProviderError('decision entity_id 不在当前项目上下文中')
    focus = {
        'focus_id': '', 'date': context.get('as_of', local_today()), 'project_id': project_id or None,
        'generated_at': generated_at, 'trigger': trigger, 'focus_type': focus_type, 'task_id': task_id or None,
        'entity_type': entity_type, 'entity_id': entity_id or None,
        'title': title, 'reason': reason, 'goal': goal, 'expected_output': expected_output,
        'blocked_by': refs(raw.get('blocked_by'), 'blocked_by'), 'depends_on': refs(raw.get('depends_on'), 'depends_on'),
        'confidence': round(confidence, 3), 'urgency': urgency, 'impact': impact,
        'uncertainty_reduction': uncertainty, 'fallback_task_id': fallback_id or None,
        'source_task_ids': source_ids, 'status_snapshot_hash': context_hash,
        'provider': source, 'provider_error': provider_error or None
    }
    focus['focus_id'] = _focus_id(focus, generated_at)
    if exclude_previous:
        previous_id = str(exclude_previous.get('task_id') or '').strip()
        previous_title = _short_text(exclude_previous.get('title'), 220)
        if focus['focus_id'] == exclude_previous.get('focus_id') or (previous_id and task_id == previous_id) or (previous_title and title == previous_title):
            raise FocusProviderError('provider repeated the rejected focus')
    return focus

def _fallback_focus(context, context_hash, trigger, generated_at, exclude_previous=None):
    task_map = _all_context_tasks(context)
    excluded_id = (exclude_previous or {}).get('task_id')
    excluded_title = (exclude_previous or {}).get('title')
    def available(rows):
        return [row for row in rows if row.get('id') != excluded_id and row.get('title') != excluded_title]
    def evidence_focus_title(item):
        label = '不确定结果' if item.get('kind') == 'inconclusive' else '负结果'
        return '复核最近的' + label + '：' + item.get('title', '项目记录')
    blocking_decisions = [item for item in context.get('pending_decisions', []) if item.get('blocking') and item.get('title') != excluded_title]
    if blocking_decisions:
        item = blocking_decisions[0]
        raw = {'focus_type':'review', 'entity_type':'decision', 'entity_id':item.get('id'),
               'project_id':item.get('project_id',''), 'title':'等待关键决定：'+(item.get('question') or item.get('title') or '未命名决定'),
               'reason':'该决定被明确标记为阻塞；Agent 不应代替人选择方向或扩大范围。',
               'goal':'由人裁决，并记录选择、理由及对后续行动的影响。',
               'expected_output':'一条可追溯的人类决定。', 'confidence':0.82,
               'urgency':'high', 'impact':'high', 'uncertainty_reduction':'high', 'source_task_ids':[]}
        return _normalize_focus(raw, context, context_hash, trigger, 'fallback', generated_at, exclude_previous, 'AI provider unavailable; using rule-based fallback')
    negative = [item for item in context.get('recent_evidence', []) if item.get('kind') in ('negative', 'inconclusive') and item.get('task_id') != excluded_id and evidence_focus_title(item) != excluded_title]
    if negative:
        item = negative[0]
        raw = {'focus_type': 'review', 'task_id': '', 'project_id': item.get('project_id', ''), 'title': evidence_focus_title(item), 'reason': '最近记录包含负结果或不确定结果，继续沿用原方案可能放大错误投入；应先复核适用条件和下一步取舍。', 'goal': '判断当前方案是否仍值得继续，并明确停用、修订或补验证的路径。', 'expected_output': '形成一条带来源、版本和结果状态的复核记录。', 'confidence': 0.62, 'urgency': 'high', 'impact': 'high', 'uncertainty_reduction': 'high', 'source_task_ids': [item.get('task_id')] if item.get('task_id') else []}
        return _normalize_focus(raw, context, context_hash, trigger, 'fallback', generated_at, exclude_previous, 'AI provider unavailable; using rule-based fallback')
    active_actions = [item for item in context.get('recent_actions', []) if item.get('status') in ('claimed','running','result_reported') and item.get('goal') != excluded_title]
    if active_actions:
        item = active_actions[0]
        raw = {'focus_type':'synthesized_action', 'entity_type':'action', 'entity_id':item.get('id'),
               'project_id':item.get('project_id',''), 'title':item.get('goal') or '当前 Agent Action',
               'reason':'此 Action 已被 Agent 认领；先跟进其有界执行、来源和预期产物。'+(' 原因：'+item['why_now'] if item.get('why_now') else ''),
               'goal':item.get('goal') or '跟进当前 Action',
               'expected_output':item.get('expected_output') or '形成可追溯的阶段产物。',
               'confidence':0.72, 'urgency':'high', 'impact':'medium', 'uncertainty_reduction':'medium',
               'source_task_ids':[item['task_id']] if item.get('task_id') in task_map else []}
        return _normalize_focus(raw, context, context_hash, trigger, 'fallback', generated_at, exclude_previous, 'AI provider unavailable; using rule-based fallback')
    candidates = available(context.get('blocking_tasks', []))
    blocked = [row for row in candidates if row.get('status') == '受阻']
    if blocked:
        task = sorted(blocked, key=lambda row: (-row.get('downstream_count', 0), _priority_rank(row.get('priority')), row.get('deadline') or '9999', row.get('title', '')))[0]
        raw = {'focus_type': 'unblock', 'task_id': task.get('id'), 'project_id': task.get('project_id'), 'title': '解除阻塞：' + task.get('title', ''), 'reason': '该事项当前受阻' + ('，并影响 %s 个下游任务' % task.get('downstream_count') if task.get('downstream_count') else '') + '；先明确解除条件比继续堆叠后续工作更能推进主线。', 'goal': '明确阻塞原因、解除条件和最小可执行的下一步。', 'expected_output': '形成解除阻塞的依据、决定或可复现产物。', 'confidence': 0.68, 'urgency': 'high', 'impact': 'high' if task.get('downstream_count') else 'medium', 'uncertainty_reduction': 'high', 'fallback_task_id': task.get('id'), 'source_task_ids': [task.get('id')]}
        return _normalize_focus(raw, context, context_hash, trigger, 'fallback', generated_at, exclude_previous, 'AI provider unavailable; using rule-based fallback')
    due = available([row for row in (context.get('tasks', {}).get('overdue', []) + context.get('tasks', {}).get('todo', []) + context.get('tasks', {}).get('in_progress', [])) if row.get('deadline') == context.get('as_of') or (row.get('deadline') and row.get('deadline') < context.get('as_of'))])
    if due:
        task = sorted(due, key=lambda row: (0 if row.get('deadline') and row.get('deadline') < context.get('as_of') else 1, _priority_rank(row.get('priority')), -row.get('downstream_count', 0), row.get('title', '')))[0]
    else:
        active = available(context.get('tasks', {}).get('in_progress', []))
        task = sorted(active, key=lambda row: (-row.get('downstream_count', 0), _priority_rank(row.get('priority')), row.get('deadline') or '9999', row.get('title', '')))[0] if active else None
    if not task:
        todo = available(context.get('tasks', {}).get('todo', []))
        task = sorted(todo, key=lambda row: (_priority_rank(row.get('priority')), row.get('deadline') or '9999', row.get('title', '')))[0] if todo else None
    if not task:
        raw = {'focus_type': 'review', 'task_id': '', 'project_id': None, 'title': '复核下一阶段与开放问题', 'reason': '当前没有可继续推进的未完成事项，适合检查项目阶段、开放问题和下一轮可验证动作。', 'goal': '把已完成工作收敛成下一阶段的明确入口。', 'expected_output': '形成下一阶段计划、开放问题清单或项目状态复核记录。', 'confidence': 0.55, 'urgency': 'medium', 'impact': 'medium', 'uncertainty_reduction': 'high', 'source_task_ids': []}
    else:
        focus_type = 'wait' if task.get('status') == '受阻' else 'task'
        raw = {'focus_type': focus_type, 'task_id': task.get('id'), 'project_id': task.get('project_id'), 'title': task.get('title'), 'reason': '该动作当前最接近项目目标的可执行推进点；它的完成或复核会减少下一步的不确定性。', 'goal': '把当前动作推进到一个可以核验的状态。', 'expected_output': '一条可复核的记录、结果、决定或下一步入口。', 'confidence': 0.5, 'urgency': 'high' if task.get('priority') == 'P0' else 'medium', 'impact': 'high' if task.get('downstream_count', 0) else 'medium', 'uncertainty_reduction': 'medium', 'fallback_task_id': task.get('id'), 'source_task_ids': [task.get('id')]}
    return _normalize_focus(raw, context, context_hash, trigger, 'fallback', generated_at, exclude_previous, 'AI provider unavailable; using rule-based fallback')

def _find_cached_focus(store, scope, date, context_hash):
    for entry in reversed(store.get('entries', [])):
        if entry.get('scope', FOCUS_SCOPE) == scope and entry.get('date') == date and entry.get('context_hash') == context_hash and isinstance(entry.get('focus'), dict):
            return entry.get('focus')
    return None

def _focus_with_entity(focus):
    if not focus:
        return focus
    result = dict(focus)
    kind = result.get('focus_type') or 'review'
    result.setdefault('entity_type', {'task':'task','synthesized_action':'action','review':'review','unblock':'blocker','wait':'wait'}.get(kind,'review'))
    result.setdefault('entity_id', result.get('task_id') if result['entity_type'] in ('task','blocker') else None)
    return result

def _read_current_state_and_history():
    with connect() as c:
        state = json.loads(c.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
        rev = get_rev(c)
        history_rows = c.execute('SELECT id,time,body,actor,summary,gateway_body FROM history ORDER BY id DESC LIMIT 60').fetchall()
    history = [{'id': row[0], 'time': row[1], 'body': row[2], 'actor': row[3] or 'legacy', 'summary': row[4] or ''} for row in history_rows]
    return state, rev, history

def _attach_ledger_context(context, scope):
    """Feed sourced, append-only results into Planner without changing legacy state."""
    with connect() as c:
        evidence = c.execute("SELECT id,project_id,task_id,title,status,summary,source_ref,created_at FROM evidence WHERE (?='global' OR project_id=?) ORDER BY created_at DESC LIMIT 20",(scope,scope)).fetchall()
        decisions = c.execute("SELECT id,project_id,question,status,created_at,blocking FROM decision_requests WHERE (?='global' OR project_id=?) AND status='pending' ORDER BY created_at DESC LIMIT 12",(scope,scope)).fetchall()
        actions = c.execute("SELECT id,project_id,task_id,goal,why_now,expected_output,status,updated_at FROM actions WHERE (?='global' OR project_id=?) ORDER BY updated_at DESC LIMIT 20",(scope,scope)).fetchall()
        artifacts = c.execute("SELECT id,project_id,title,type,reference,created_at FROM artifacts WHERE (?='global' OR project_id=?) ORDER BY created_at DESC LIMIT 12",(scope,scope)).fetchall()
    ledger = [{'evidence_id':r[0], 'project_id':r[1], 'task_id':r[2], 'title':_short_text(r[3],180),
               'kind':{'FAIL':'negative','FAILURE':'negative','FAILED':'negative','PASS':'positive','SUCCESS':'positive','PASSED':'positive','INCONCLUSIVE':'inconclusive','PARTIAL':'inconclusive'}.get(r[4],'unknown'),
               'status':r[4],'note':_short_text(r[5],280),'source_ref':r[6],'created_at':r[7]} for r in evidence]
    context['recent_evidence'] = (ledger + context.get('recent_evidence', []))[:24]
    context['pending_decisions'] = ([{'id':r[0],'project_id':r[1],'title':_short_text(r[2],180),'question':_short_text(r[2],280),'status':r[3],'created_at':r[4],'blocking':bool(r[5])} for r in decisions] + context.get('pending_decisions', []))[:24]
    context['recent_actions'] = [{'id':r[0],'project_id':r[1],'task_id':r[2], 'goal':_short_text(r[3],180),
                                  'why_now':_short_text(r[4],240),'expected_output':_short_text(r[5],240),
                                  'status':r[6],'updated_at':r[7]} for r in actions]
    context['recent_artifacts'] = [{'id':r[0],'project_id':r[1],'title':_short_text(r[2],180),'type':r[3],'reference':r[4],'created_at':r[5]} for r in artifacts]
    return context

def _analysis_policy(scope):
    # Only a separately reviewed local file can authorize a configured provider.
    try:
        raw = json.loads((DATA / 'analysis-policy.json').read_text(encoding='utf-8'))
        policy = raw.get('projects', {}).get(scope, {})
    except (OSError, ValueError, AttributeError):
        return {}
    provider = get_focus_provider()
    if not isinstance(policy, dict) or scope == 'global' or policy.get('approved') is not True or not provider.available:
        return {}
    if policy.get('provider_url') != provider.url or policy.get('model') != provider.model:
        return {}
    fields = policy.get('context_fields')
    if not isinstance(fields, list) or not fields or not all(isinstance(field, str) and field in {'projects','tasks','blocked_tasks','recent_evidence','pending_decisions','recent_actions','recent_artifacts','as_of','scope'} for field in fields):
        return {}
    budget = policy.get('max_calls_per_day')
    if isinstance(budget, bool) or not isinstance(budget, int) or not 1 <= budget <= 100:
        return {}
    return policy

def _focus_status(scope=FOCUS_SCOPE):
    state, rev, history = _read_current_state_and_history()
    with FOCUS_LOCK:
        store = _read_focus_store()
        context = _attach_ledger_context(build_project_context(state, history, scope, store.get('feedback', [])), scope)
        context_hash = _context_hash(context)
        cached = _find_cached_focus(store, scope, context.get('as_of'), context_hash)
    provider = get_focus_provider()
    # A provider failure is a cached fallback, not a reason to retry on each render.
    # Manual refresh or a changed context can make another attempt.
    needs_generation = cached is None
    latest = next((item.get('focus') for item in reversed(store.get('entries', [])) if item.get('scope') == scope), None)
    selected = cached or latest
    stale = bool(selected and (needs_generation or selected.get('snapshot_rev', rev) != rev))
    return {'stale': stale, 'read_at': now_iso(), 'automatic_analysis': (_analysis_policy(scope).get('automatic_after_results') is True), 'model_allowed': bool(_analysis_policy(scope)), 'ok': True, 'previous_focus': _focus_with_entity(selected) if stale else None, 'focus': _focus_with_entity(selected) if not stale else None, 'needs_generation': needs_generation, 'cached': cached is not None, 'context_hash': context_hash, 'date': context.get('as_of'), 'scope': scope, 'provider_configured': provider.available, 'rev': rev}

def _generate_focus(body):
    body = body or {}
    trigger = str(body.get('trigger') or 'manual_refresh')
    if trigger not in FOCUS_TRIGGERS:
        trigger = 'manual_refresh'
    scope = str(body.get('scope') or FOCUS_SCOPE)
    force = bool(body.get('force')) or trigger == 'manual_refresh'
    exclude_id = str(body.get('exclude_previous_focus_id') or '').strip()
    state, rev, history = _read_current_state_and_history()
    with FOCUS_LOCK:
        store = _read_focus_store()
        context = _attach_ledger_context(build_project_context(state, history, scope, store.get('feedback', [])), scope)
        context_hash = _context_hash(context)
        cached = _find_cached_focus(store, scope, context.get('as_of'), context_hash)
        if cached and not force:
            return {'ok': True, 'focus': _focus_with_entity(cached), 'cached': True, 'needs_generation': False, 'context_hash': context_hash, 'date': context.get('as_of'), 'scope': scope, 'provider_configured': get_focus_provider().available, 'rev': rev}
        previous = None
        if exclude_id:
            for entry in reversed(store.get('entries', [])):
                focus = entry.get('focus') if isinstance(entry, dict) else None
                if isinstance(focus, dict) and focus.get('focus_id') == exclude_id:
                    previous = focus
                    break
        generated_at = now_iso()
        provider = get_focus_provider()
        source = 'fallback'
        provider_error = ''
        raw = None
        policy = _analysis_policy(scope)
        if body.get('use_provider') is True:
            if not policy:
                raise ValueError('模型分析未获项目、provider、数据范围与预算授权；不会发送项目数据')
            usage_key = scope + ':' + local_today()
            usage = store.setdefault('model_usage', {})
            if usage.get(usage_key, 0) >= policy['max_calls_per_day']:
                raise ValueError('今日模型分析预算已用尽')
            usage[usage_key] = usage.get(usage_key, 0) + 1
            _write_focus_store(store)
            try:
                raw = provider.generate({key:context[key] for key in policy['context_fields'] if key in context}, None)
                source = 'ai'
            except FocusProviderError as exc:
                provider_error = str(exc)
        if raw is None:
            focus = _fallback_focus(context, context_hash, trigger, generated_at, previous)
            if provider_error:
                focus['provider_error'] = provider_error
        else:
            try:
                focus = _normalize_focus(raw, context, context_hash, trigger, source, generated_at, previous)
            except FocusProviderError as exc:
                provider_error = str(exc)
                focus = _fallback_focus(context, context_hash, trigger, generated_at, previous)
                focus['provider_error'] = provider_error
        focus['snapshot_rev'] = rev
        focus['source_context_hash'] = context_hash
        entry = {'scope': scope, 'date': context.get('as_of'), 'context_hash': context_hash, 'generated_at': generated_at, 'focus': focus}
        store['entries'] = [item for item in store.get('entries', []) if not (item.get('scope', FOCUS_SCOPE) == scope and item.get('date') == context.get('as_of') and item.get('context_hash') == context_hash)]
        store['entries'].append(entry)
        _write_focus_store(store)
    latest_state, latest_rev, latest_history = _read_current_state_and_history()
    stale = latest_rev != rev
    return {'stale': stale, 'read_at': now_iso(), 'model_allowed': bool(_analysis_policy(scope)), 'automatic_analysis': (_analysis_policy(scope).get('automatic_after_results') is True), 'ok': True, 'focus': focus, 'cached': False, 'needs_generation': False, 'context_hash': context_hash, 'date': context.get('as_of'), 'scope': scope, 'provider_configured': provider.available, 'rev': rev}

def _emit_focus_changed(result, trigger):
    if not result.get('cached'):
        focus = result['focus']
        with connect() as c:
            ev = agent_gateway.event(c, result['scope'], 'system', 'focus.changed',
                'Planner 更新建议：' + str(focus.get('title') or '待复核'),
                'focus', str(focus.get('focus_id') or ''),
                after={'focus_type':focus.get('focus_type'), 'title':focus.get('title'), 'provider':focus.get('provider')},
                reason=trigger, importance='high')
        notify_named('focus.changed', ev)

def _refresh_focus_after_change(scope, trigger, result_committed=False):
    result = _generate_focus({'scope': scope, 'trigger': trigger, 'use_provider': (result_committed and _analysis_policy(scope).get('automatic_after_results') is True)})
    _emit_focus_changed(result, trigger)
    return result

def _accept_project_focus(body):
    scope = str(body.get('scope') or '')
    if not scope or scope == 'global':
        raise ValueError('采纳建议须明确项目')
    with FOCUS_LOCK:
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            status = _focus_status(scope)
            focus = status.get('focus') or {}
            if body.get('ifRev') is None or int(body['ifRev']) != get_rev(c):
                raise ValueError('版本冲突；请刷新后重新预览，未覆盖人工记录')
            if status.get('stale') or not focus or focus.get('focus_id') != body.get('focus_id') or focus.get('source_context_hash') != status['context_hash']:
                raise ValueError('建议已过期；请重新分析并预览')
            state = json.loads(c.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
            if not any(p['id'] == scope for p in state['projects']):
                raise ValueError('项目不存在')
            existing = next((t for t in state['tasks'] if t.get('id') == focus.get('task_id') and t.get('project') == scope), None)
            project_backup.history(c, 'human', '预览后采纳项目建议')
            tid = 'task-' + secrets.token_hex(10)
            task = {'id':tid, 'project':scope, 'title':focus['title'], 'status':'待开始', 'priority':'P1', 'stage':'', 'start':'', 'end':'', 'completed':'', 'milestone':False, 'parent':'', 'deps':list(focus.get('depends_on') or []), 'note':'建议理由：' + str(focus.get('reason') or '') + '\n预期产出：' + str(focus.get('expected_output') or ''), 'source_focus_id':focus['focus_id'], 'source_context_hash':status['context_hash'], 'source_task_ids':list(focus.get('source_task_ids') or []), 'suggestion_provider':focus.get('provider'), 'updated_at':now_iso()}
            if existing:
                existing.update({key:task[key] for key in ('source_focus_id','source_context_hash','source_task_ids','suggestion_provider','updated_at')})
                tid = existing['id']
                task = existing
            else:
                state['tasks'].append(task)
            validate(state)
            c.execute('UPDATE state SET body=? WHERE id=1', (json.dumps(state,ensure_ascii=False),))
            rev = bump_rev(c)
            event = agent_gateway.event(c,scope,'human','task.updated' if existing else 'task.created',task['title'],'task',tid,after=task,reason='预览后采纳；尚未发送给宿主')
            maybe_snapshot(state,c)
    notify_named(event['type'],event)
    notify({'kind':'state','collections':['tasks'],'research_changed':True})
    return {'ok':True, 'task_id':tid, 'execution':'not_sent', 'rev':rev}

def _record_focus_feedback(body):
    body = body or {}
    action = str(body.get('action') or '').strip()
    if action not in FOCUS_FEEDBACK:
        raise ValueError('当前重点反馈类型不正确')
    focus_id = str(body.get('focus_id') or '').strip()
    if not focus_id:
        raise ValueError('缺少 focus_id')
    record = {'date': str(body.get('date') or local_today()), 'scope': str(body.get('scope') or FOCUS_SCOPE), 'focus_id': focus_id, 'action': action, 'title': _short_text(body.get('title'), 220), 'time': now_iso()}
    with FOCUS_LOCK:
        store = _read_focus_store()
        store['feedback'] = [item for item in store.get('feedback', []) if not (item.get('date') == record['date'] and item.get('scope', FOCUS_SCOPE) == record['scope'] and item.get('focus_id') == focus_id and item.get('action') == action)]
        store['feedback'].append(record)
        _write_focus_store(store)
    return {'ok': True, 'feedback': record}
def get_rev(c):
    try:
        row = c.execute("SELECT v FROM meta WHERE k='rev'").fetchone()
        return int(row[0]) if row else 0
    except sqlite3.OperationalError:
        return 0
def bump_rev(c):
    r = get_rev(c) + 1
    c.execute("DELETE FROM meta WHERE k='rev'")
    c.execute("INSERT INTO meta(k,v) VALUES('rev',?)", (str(r),))
    return r
connect().close()
def validate(s):
    if not isinstance(s,dict): raise ValueError('备份结构不正确')
    s.setdefault('decisions', [])
    if set(s) != {'projects','tasks','files','decisions'}: raise ValueError('备份结构不正确')
    for key in s:
        if not isinstance(s[key],list): raise ValueError('数据必须为列表')
        ids = [x['id'] for x in s[key]]
        if len(ids)!=len(set(ids)): raise ValueError('存在重复编号')
    pids={p['id'] for p in s['projects']}
    for p in s['projects']:
        if not str(p.get('name','')).strip(): raise ValueError('项目名称不能为空')
        if p.get('app_owner') or p['id'] in ecosystem.APP_SPACES.values():
            if ecosystem.APP_SPACES.get(p.get('app_owner')) != p['id']:
                raise ValueError('App 个人空间身份不正确')
        for key in ('description','goal','success_definition','current_state','workspace','type'):
            if key in p and not isinstance(p[key],str): raise ValueError('项目 '+key+' 必须是文本')
        if 'constraints' in p and (not isinstance(p['constraints'],list) or any(not isinstance(item,str) for item in p['constraints'])):
            raise ValueError('项目 constraints 必须是文本列表')
    from datetime import date
    task_by_id={t['id']:t for t in s['tasks']}
    for t in s['tasks']:
        if t['project'] not in pids or not t.get('title','').strip(): raise ValueError('任务项目或标题不正确')
        if t['status'] not in ['待开始','进行中','受阻','已完成']: raise ValueError('任务状态不正确')
        if t.get('priority', 'P2') not in ['P0','P1','P2','P3']: raise ValueError('任务优先级不正确')
        for k in ['start','end','completed']:
            if t.get(k): date.fromisoformat(t[k])
        if t.get('start') and t.get('end') and t['start']>t['end']: raise ValueError('开始日期不能晚于截止日期')
        parent=t.get('parent','')
        if parent:
            if parent not in task_by_id or parent==t['id']: raise ValueError('父任务关系不正确')
            if task_by_id[parent].get('project')!=t['project']: raise ValueError('父任务必须属于同一项目')
        deps=t.get('deps',[])
        if not isinstance(deps,list): raise ValueError('任务依赖必须为列表')
        if len(deps)!=len(set(deps)): raise ValueError('任务依赖存在重复')
        for dep in deps:
            if dep not in task_by_id or dep==t['id']: raise ValueError('任务依赖不正确')
            if task_by_id[dep].get('project')!=t['project']: raise ValueError('前置依赖必须属于同一项目')
    def ensure_acyclic(label, edges):
        visiting=set(); visited=set()
        def visit(node):
            if node in visited: return
            if node in visiting: raise ValueError(label+'存在循环')
            visiting.add(node)
            for nxt in edges(node):
                if nxt: visit(nxt)
            visiting.remove(node); visited.add(node)
        for node in task_by_id: visit(node)
    ensure_acyclic('父任务关系', lambda node:[task_by_id[node].get('parent','')])
    ensure_acyclic('任务依赖', lambda node:list(task_by_id[node].get('deps',[])))
    for f in s['files']:
        if f['project'] not in pids: raise ValueError('资料没有关联项目')
    for d in s['decisions']:
        if d.get('project') not in pids or not str(d.get('title','')).strip(): raise ValueError('决策节点项目或标题不正确')
        if d.get('status') not in ['待决','讨论中','已决']: raise ValueError('决策节点状态不正确')
        if d.get('due'): date.fromisoformat(d['due'])
GATEWAY = agent_gateway.Gateway(connect, get_rev, bump_rev, validate, _focus_status, lambda c: maybe_snapshot(None,c))
def _manager_snapshot(project, connection=None):
    if connection is None:
        with connect() as c: return _manager_snapshot(project,c)
    if connection is not None:
        c = connection
        c.row_factory = sqlite3.Row
        state = json.loads(c.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
        item = next((p for p in state['projects'] if p['id'] == project), None)
        if not item: raise ValueError('项目不存在')
        context = {'project':item}
        for key in ('tasks','files','decisions'):
            context[key] = sorted([x for x in state[key] if x.get('project') == project], key=lambda x:x.get('id',''))
        context['files'] = [{k:v for k,v in item.items() if k in
                             ('id','project','path','name','title','type','size','mtime','updated_at','content_hash','hash')}
                            for item in context['files']]
        for key, table in (('actions','actions'),('results','action_results'),('artifacts','artifacts'),('evidence','evidence'),('proposals','proposals')):
            rows = c.execute('SELECT * FROM '+table+' WHERE project_id=? ORDER BY id', (project,)).fetchall()
            context[key] = [dict(row) for row in rows]
        for action in context['actions']:
            action['progress_reports_used'] = c.execute("SELECT COUNT(*) FROM project_events WHERE source_action=? AND type='agent.progress'", (action['id'],)).fetchone()[0]
            action['activity_reports'] = [dict(row) for row in c.execute(
                "SELECT type,summary,reason,timestamp FROM project_events WHERE project_id=? AND source_action=? AND type IN ('agent.start','agent.progress','agent.fail') ORDER BY seq DESC LIMIT 3",
                (project,action['id'])).fetchall()]
        # Agent Gateway DecisionRequests are separate from legacy decision notes.
        context['decisions'] += [dict(row) for row in c.execute('SELECT * FROM decision_requests WHERE project_id=? ORDER BY id',(project,)).fetchall()]
        context['result_reviews'] = [dict(row) for row in c.execute('SELECT * FROM result_reviews WHERE project_id=? ORDER BY created_at DESC,id DESC LIMIT 30',(project,)).fetchall()]
        return context
CONNECTION = agent_connection.Connection(DATA, notify_named)
MANAGER = agent_manager.Manager(DATA, _manager_snapshot, notify_named,
    runner=agent_connection.Runner(CONNECTION, agent_manager.codex_analyze))
WORKSPACES = workspace_registry.Registry(DATA, _manager_snapshot)
MANAGER.workspace = WORKSPACES
MANAGER.bridge.workspace = WORKSPACES
GATEWAY.workspace_status = WORKSPACES.status
def _source_intake(body):
    if not isinstance(body, dict):
        raise ValueError('资料确认请求必须是对象')
    project = str(body.get('project_id') or '')
    if body.get('confirm_indexing') is not True:
        raise ValueError('须确认只添加所选资料的索引')
    with connect() as c:
        c.execute('ATTACH DATABASE ? AS source_store', (str(MANAGER.bridge.path),))
        c.execute('BEGIN IMMEDIATE')
        rev = get_rev(c)
        if type(body.get('ifRev')) is not int or body['ifRev'] != rev:
            raise ValueError('项目记录已变化，请刷新后重新查看草稿')
        old = c.execute('SELECT body FROM state WHERE id=1').fetchone()[0]
        state = json.loads(old)
        if not any(p['id'] == project for p in state['projects']):
            raise ValueError('项目不存在')
        prepared = MANAGER.bridge.prepare_intake(c, project, body, state['files'])
        for item in prepared:
            item['id'] = 'file-' + secrets.token_hex(12)
        state['files'].extend(prepared)
        validate(state)
        if body.get('dry'):
            return {'dry': True, 'rev': rev, 'added': len(prepared)}, []
        summary = '确认登记所选来源资料索引（未核验）'
        c.execute('INSERT INTO history(body,time,actor,summary,gateway_body) VALUES(?,?,?,?,?)',
                  (old, datetime.datetime.now().isoformat(timespec='seconds'), 'human', summary,
                   json.dumps(project_backup.records(c), ensure_ascii=False)))
        c.execute('UPDATE state SET body=? WHERE id=1', (json.dumps(state, ensure_ascii=False),))
        new_rev = bump_rev(c)
        events = [agent_gateway.event(c, project, 'legacy-human', 'file.created', item['name'],
                  'file', item['id'], after=item, reason=summary) for item in prepared]
        maybe_snapshot(state, c)
    return {'rev': new_rev, 'added': len(prepared), 'files': prepared}, events

def _manager_context(project):
    try:
        status = MANAGER.status(project)
        latest = next((job for job in status['jobs'] if job['state']=='succeeded' and not job['stale']), None)
        return {'enabled':status['enabled'], 'mode':status['mode'], 'latest_analysis':latest,
                'continuity':status['continuity'],
                'resume_brief':status['resume_brief'],
                'ready_handoffs':[plan for plan in status['handoffs'] if plan['ready']],
                'recent_handoffs':status['handoffs'][:5],
                'authority':'管理建议未核验，不是科学证据或执行授权；领取 Action 仍须遵守原目标、预算及人审边界'}
    except ValueError as exc:
        return {'error':str(exc),'latest_analysis':None}
GATEWAY.manager_context = _manager_context
GATEWAY.manager = MANAGER
GATEWAY.manager_signature = lambda c,pid: MANAGER.source(pid,_manager_snapshot(pid,c))[1]

def _manager_execute(operation, project, record, report):
    """No bearer credential, tool runtime, or research Agent takeover."""
    aid = 'manager-agent-' + hashlib.sha256(project.encode()).hexdigest()[:16]
    with connect() as c:
        c.row_factory = sqlite3.Row
        c.execute('BEGIN IMMEDIATE')
        if operation!='claim':
            MANAGER.attach(c)
            saved=c.execute("SELECT * FROM manager_store.handoffs WHERE id=? AND project=? AND state='completed'",(record['handoff_id'],project)).fetchone()
            if saved and saved['action_id']==record['action_id'] and saved['agent_id']==aid:
                existing=c.execute('SELECT * FROM action_results WHERE id=? AND action_id=? AND project_id=?',
                                   (saved['result_id'],saved['action_id'],project)).fetchone()
                if existing:
                    # Local receipt reconciliation may repeat after commit; never create another Result.
                    return {'ok':True,'already_completed':True,'result_id':existing['id'],
                            'action_id':existing['action_id'],'outcome':existing['outcome']}
        project_backup.history(c,'agent','自动执行人批只读管理核查')
        agent = c.execute('SELECT * FROM agents WHERE id=?',(aid,)).fetchone()
        if not agent:
            c.execute('INSERT INTO agents VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                      (aid,project,'研序只读管理执行器','management_executor','EXECUTE',
                       hashlib.sha256(secrets.token_bytes(32)).hexdigest(),'[]','online',None,agent_gateway.stamp(),agent_gateway.stamp()))
            agent = c.execute('SELECT * FROM agents WHERE id=?',(aid,)).fetchone()
        if operation == 'claim':
            result, ev = MANAGER.claim(c,agent,record['id'],GATEWAY.manager_signature(c,project),GATEWAY)
        else:
            MANAGER.attach(c)
            execution=c.execute("SELECT * FROM manager_store.jobs WHERE project=? AND kind='execution' AND signature=?",
                                (project,'execution:'+str(record['handoff_id'])+':'+report['source_hash'])).fetchone()
            if execution and execution['review_context'] and report['state']=='succeeded':
                context=json.loads(execution['review_context'])
                policy=c.execute('SELECT * FROM manager_store.policies WHERE project=?',(project,)).fetchone()
                if not policy or not policy['enabled'] or policy['generation']!=execution['generation'] or not MANAGER.review_permission(c,execution,dict(context,source_hash=report['source_hash']),'manager_store.'):
                    report=dict(report,state='cancelled',analysis=None)
                elif GATEWAY.manager_signature(c,project)!=report['source_hash']:
                    report=dict(report,state='stale',analysis=None)
            # No scientific assessment is performed. Even a successful review is UNKNOWN.
            analysis = report['analysis'] if report['state']=='succeeded' else None
            summary = ('只读管理核查交付；科学结论未评估。\n' + agent_manager.encode(analysis)) if analysis else '只读核查已停止：'+report['state']+'；旧输出未采用，未核验。'
            result, ev = GATEWAY.result(c,agent,{'action_id':record['action_id'],'outcome':'unknown',
                'summary':summary,'source_ref':'research-desk:management-handoff/'+str(record['handoff_id']),
                'source_version':'sha256:'+report['source_hash'], 'provenance':'snapshot-only management review; not scientific evidence'})
            MANAGER.complete(c,agent,result)
            if execution and execution['review_context']:
                # Receipt and adopted/quarantined state commit together, even if notification fails.
                c.execute('UPDATE manager_store.jobs SET state=?,finished=? WHERE id=?',
                          (report['state'],time.time(),execution['id']))
                result['review_state']=report['state']
        bump_rev(c)
        maybe_snapshot(None,c)
    notify_named('manager.changed', {'project_id':project})
    notify({'kind':'state','research_changed':True})
    return result
MANAGER.executor = _manager_execute

def _manager_review(body):
    project = str(body.get('project_id',''))
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        revision = get_rev(c)
        if type(body.get('ifRev')) is not int or body['ifRev'] != revision:
            raise ValueError('项目版本已变化，请刷新后重新审阅')
        signature = GATEWAY.manager_signature(c,project)
        if not body.get('dry'):
            project_backup.history(c,'human','审阅自主管理行动草案')
        result = MANAGER.approve(c,project,body,signature)
        if result.get('already_approved'):
            c.rollback()
            return dict(result,rev=revision),None
        if body.get('dry'):
            c.rollback()
            return dict(result,dry=True,rev=revision),None
        ev = agent_gateway.event(c,project,'human','manager.'+result['state'],
                                 '自主管理行动草案：'+result['state'],'management_handoff',str(result['handoff_id']))
        result['rev'] = bump_rev(c)
        maybe_snapshot(None,c)
    return result,ev
ECOSYSTEM = ecosystem.Ecosystem(connect, GATEWAY, get_rev, bump_rev, notify_named, CONNECTION)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send(self,status,body,kind='application/json',extra=None):
        data = json.dumps(body,ensure_ascii=False).encode() if kind=='application/json' else body
        self.send_response(status); self.send_header('Content-Type',kind+'; charset=utf-8')
        self.send_header('Content-Length',str(len(data))); self.send_header('Cache-Control','no-store')
        for k,v in (extra or {}).items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(data)
    def local_request(self):
        try:
            host = urlparse('http://' + self.headers.get('Host', '') )
            valid = host.hostname in ('127.0.0.1', 'localhost') and (host.port or 80) == self.server.server_port
            valid = valid and not host.username and not host.password and host.path in ('', '/')
            origin = self.headers.get('Origin')
            if origin:
                source = urlparse(origin)
                valid = valid and source.scheme == 'http' and source.netloc == host.netloc and source.path in ('', '/')
            if not valid:
                self.send(403, {'error':'仅允许本机同源访问'})
            return valid
        except ValueError:
            self.send(403, {'error':'本机请求地址无效'})
            return False
    def do_GET(self):
        if not self.local_request(): return
        path=urlparse(self.path).path
        if path=='/healthz':
            return self.send(200, {'app':'research-desk', 'launch_id':os.environ.get('RESEARCH_DESK_LAUNCH_ID',''),
                                   'pid':os.getpid(), 'release':os.environ.get('RESEARCH_DESK_RELEASE','development'),
                                   'build_id':ECOSYSTEM_BUILD_ID, 'capabilities':ecosystem_contracts.capabilities()})
        if path=='/':
            return self.send(200,(ROOT/'index.html').read_bytes().replace(b'__TOKEN__',TOKEN.encode()).replace(b'__UI_LANGUAGE__',(ui_language() or '').encode()).replace(b'</body>',b'<script src="/local-presentation.js"></script></body>'),'text/html')
        if path in ('/apps/discussion/', '/apps/radar/'):
            app = path.split('/')[2]
            return self.send(200, (ROOT/'apps'/'shell.html').read_bytes().replace(b'__APP__', app.encode()).replace(b'__TOKEN__', TOKEN.encode()), 'text/html')
        if path in ('/apps/shell.js', '/apps/shell.css', '/apps/links.js'):
            return self.send(200, (ROOT/path[1:]).read_bytes(), 'text/javascript' if path.endswith('.js') else 'text/css')
        if path=='/local-presentation.js':
            local=DATA/'private-ui-overrides.json'
            functions=json.loads(local.read_text(encoding='utf-8')).get('functions',[]) if local.exists() else []
            return self.send(200,'\n'.join(functions).encode(),'text/javascript')
        if path in ('/ecosystem.js', '/ecosystem_state.js', '/ecosystem_client.js', '/ecosystem.css', '/review_ui.js', '/chat_ui.js'):
            return self.send(200, (ROOT / path[1:]).read_bytes(), 'text/javascript' if path.endswith('.js') else 'text/css')
        if path=='/assets/yanxu-logo.png':
            return self.send(200,(ROOT/'assets'/'yanxu-logo.png').read_bytes(),'image/png')
        if path=='/assets/fonts/ChillRoundGothic-Bold.woff':
            return self.send(200,(ROOT/'assets'/'fonts'/'ChillRoundGothic-Bold.woff').read_bytes(),'font/woff')
        if path=='/api/events':
            q = parse_qs(urlparse(self.path).query)
            if self.headers.get('Authorization')!='Bearer '+TOKEN and q.get('token',[''])[0]!=TOKEN:
                return self.send(401,{'error':'需要本机 API 令牌'})
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            with EV_LOCK: EV_LISTENERS.add(self.wfile)
            try:
                while True:
                    threading.Event().wait(15)
                    self.wfile.write(b': ping\n\n'); self.wfile.flush()
            except Exception:
                pass
            finally:
                with EV_LOCK: EV_LISTENERS.discard(self.wfile)
            return
        if path.startswith('/api/agent/'):
            try:
                agent = GATEWAY.authenticate(self._bearer())
                if path == '/api/agent/ecosystem':
                    return self.send(200, ECOSYSTEM.agent_get(agent))
                result, ev = GATEWAY.agent_get(agent,path,parse_qs(urlparse(self.path).query))
                if ev: notify_named(ev['type'],ev)
                return self.send(200,result)
            except agent_gateway.GatewayError as exc:
                return self.send(exc.status,{'error':str(exc)})
            except (ValueError,sqlite3.Error) as exc:
                return self.send(400,{'error':str(exc)})
        if self.headers.get('Authorization')!='Bearer '+TOKEN: return self.send(401,{'error':'需要本机 API 令牌'})
        if path == '/api/apps':
            try:
                result = ECOSYSTEM.apps(parse_qs(urlparse(self.path).query).get('app', [''])[0])
                return self.send(200, result, extra={'X-Rev': str(result['rev'])})
            except (ValueError, sqlite3.Error) as exc:
                return self.send(400, {'error': str(exc)})
        if path == '/api/ecosystem':
            try:
                project = parse_qs(urlparse(self.path).query).get('project_id', [''])[0]
                result = ECOSYSTEM.view(project)
                return self.send(200, result, extra={'X-Rev': str(result['rev'])})
            except (agent_gateway.GatewayError, ValueError, sqlite3.Error) as exc:
                return self.send(getattr(exc, 'status', 400), {'error': str(exc)})
        if path == '/api/ecosystem/brief':
            try:
                import review_service
                query = parse_qs(urlparse(self.path).query)
                project = query.get('project_id', [''])[0]
                with connect() as c:
                    c.execute('BEGIN')
                    GATEWAY.project(c, project)
                    room = ECOSYSTEM.item(c, project, query.get('room_id', [''])[0], 'room')
                    markdown = review_service.markdown(room)
                return self.send(200, {'markdown': markdown, 'filename': '研序评审-' + room['id'] + '.md',
                                       'sha256': hashlib.sha256(markdown.encode()).hexdigest(),
                                       'brief_revision': room['brief']['revision'], 'object_rev': room.get('object_rev', 0)})
            except (agent_gateway.GatewayError, ValueError, KeyError) as exc:
                return self.send(getattr(exc, 'status', 400), {'error': str(exc)})
        if path=='/api/ui/preferences':
            return self.send(200,{'language':ui_language()})
        if path=='/api/agent-connection':
            project = parse_qs(urlparse(self.path).query).get('project_id',[''])[0]
            return self.send(200, CONNECTION.status(project))
        if path=='/api/project/action-recovery':
            try:
                query=parse_qs(urlparse(self.path).query)
                with connect() as c:
                    c.execute('BEGIN')
                    result=GATEWAY.recovery_view(c,query.get('project_id',[''])[0],query.get('action_id',[''])[0])
                return self.send(200,result)
            except agent_gateway.GatewayError as exc:
                return self.send(exc.status,{'error':str(exc)})
            except (ValueError,sqlite3.Error) as exc:
                return self.send(400,{'error':str(exc)})
        if path=='/api/project/result-review':
            try:
                query=parse_qs(urlparse(self.path).query)
                with connect() as c:
                    c.execute('BEGIN')
                    pid=query.get('project_id',[''])[0]
                    GATEWAY.project(c,pid)
                    result=agent_gateway.result_review.target(c,pid,query.get('result_id',[''])[0])
                    result['rev']=get_rev(c)
                return self.send(200,result)
            except (agent_gateway.GatewayError,agent_gateway.result_review.ReviewError) as exc:
                return self.send(exc.status,{'error':str(exc)})
            except (ValueError,sqlite3.Error) as exc:
                return self.send(400,{'error':str(exc)})
        if path in ('/api/project/workspace','/api/project/source-index'):
            try:
                query=parse_qs(urlparse(self.path).query)
                project=query.get('project_id',[''])[0]
                MANAGER.snapshot(project)
                result=WORKSPACES.status(project) if path.endswith('/workspace') else MANAGER.bridge.index_page(project,query.get('offset',[0])[0],query.get('limit',[100])[0])
                return self.send(200,result)
            except (ValueError,sqlite3.Error) as exc:
                return self.send(400,{'error':str(exc)})
        if path=='/api/project/manager':
            try:
                project = parse_qs(urlparse(self.path).query).get('project_id',[''])[0]
                return self.send(200, MANAGER.status(project))
            except ValueError as exc: return self.send(400, {'error':str(exc)})
        if path in ('/api/agents','/api/research/today','/api/research/graph','/api/research/events','/api/research/evidence','/api/research/decisions','/api/project/today','/api/project/graph','/api/project/events','/api/project/evidence','/api/project/decisions','/api/project/artifacts','/api/project/results','/api/project/context'):
            try:
                result = GATEWAY.human_get(path,parse_qs(urlparse(self.path).query))
                if path=='/api/agents':
                    result['persistent'] = CONNECTION.status(parse_qs(urlparse(self.path).query).get('project_id',[''])[0])
                return self.send(200,result)
            except agent_gateway.GatewayError as exc:
                return self.send(exc.status,{'error':str(exc)})
            except (ValueError,sqlite3.Error) as exc:
                return self.send(400,{'error':str(exc)})
        if path=='/api/backup':
            with connect() as c: return self.send(200,project_backup.envelope(c),extra={'X-Rev':str(get_rev(c))})
        if path=='/api/state':
            q = parse_qs(urlparse(self.path).query)
            with connect() as c:
                s=json.loads(c.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
                rev=get_rev(c)
            s = ecosystem.desk_state(s)
            if q.get('slim'): s={k:v for k,v in s.items() if k!='files'}
            return self.send(200,s,extra={'X-Rev':str(rev)})
        if path in ('/api/research-focus','/api/project-focus'):
            q = parse_qs(urlparse(self.path).query)
            scope = str(q.get('scope', [FOCUS_SCOPE])[0] or FOCUS_SCOPE)
            try:
                return self.send(200, _focus_status(scope))
            except ValueError as exc:
                return self.send(500, {'error': str(exc)})
        if path=='/api/help':
            return self.send(200,{
                'name':'研序本机 API','base':'http://127.0.0.1:8765',
                'auth':'所有端点需 Authorization: Bearer <令牌>，令牌默认位于 ~/Library/Application Support/ResearchDesk/api-token（SSE 可用 ?token= 查询参数）',
                'endpoints':{
                    'GET /api/ecosystem?project_id=ID':'人类读取当前项目讨论、雷达、角色与共享上下文；不调用模型',
                    'POST /api/ecosystem':'{project_id,operation,ifRev,...}：生态操作；支持 dry:true；开始讨论与读取来源需分别显式确认',
                    'GET /api/agent/ecosystem':'项目 Agent 读取分配给自己的讨论请求与项目雷达变化',
                    'POST /api/agent/discussion/reply':'握手后用 {room_id,participant_id,run_id,output} 回复本轮；输出保持 UNVERIFIED',
                    'GET /api/backup':'完整、有版本的项目备份；不含 Agent 凭据和原始用户文件',
                    'POST /api/restore':'{backup:完整备份,ifRev:版本号}：原子恢复新旧记录；Agent 需重新连接',
                    'GET /api/state':'完整状态 {projects,tasks,files,decisions}；?slim=1 剔除 files 大数组；响应头 X-Rev 为状态版本号',
                    'POST /api/state':'整体写入（主要用于备份恢复）；推荐 body={state:{projects,tasks,files,decisions},ifRev:版本号}；兼容直接提交完整状态；ifRev 用于乐观锁校验',
                    'POST /api/action':'单条或批量操作。单条: {collection,item}；批量: {ops:[{collection,item}|{collection,op:"delete",id}...]}；可选 dry:true 只校验不落盘；可选 ifRev 乐观锁；可选 actor=human|agent|system 与 summary 记录操作来源和摘要。删除项目会级联删除其任务/资料/决策；删除任务会清理子任务与依赖引用',
                    'POST /api/undo':'{}：撤销最近一次保存',
                    'GET /api/history':'最近 60 次保存快照摘要 [{id,time,actor,summary,projects,tasks,files,decisions}]',
                    'POST /api/rollback':'{"id":历史id}：恢复到该时间点，当前状态先入历史',
                    'GET /api/snapshots':'每日自动快照列表；?name=auto-日期.json 读取内容',
                    'GET /api/events':'SSE 事件流：Agent、证据、决定和 focus.changed 为具名事件；保留旧版 unnamed state 通知兼容',
                    'GET /api/project-focus':'读取当前 Project Focus、context hash 与是否需要重新判断；不触发 AI；/api/research-focus 保留兼容',
                    'GET /api/project/manager?project_id=ID':'只读自主管理策略、来源hash、队列、草案和回执；刷新不调用模型',
                    'GET /api/project/workspace?project_id=ID':'人类读取工作区绑定和目录可用状态；Agent从get_context读取相同范围',
                    'POST /api/project/workspace':'仅人类绑定工作区：project_id/root/name/relative_path/exclusions/if_revision/consent=project-workspace-binding-v1，支持dry；不授权读取或写文件',
                    'GET /api/project/source-index?project_id=ID&offset=0&limit=100':'仅人类读取全部来源元数据分页；索引不代表内容已读或已验证',
                    'GET /api/project/action-recovery?project_id=ID&action_id=ID':'人类读取行动契约、已耗进度次数、登记产物和同项目已握手的接续 Agent；不终止进程',
                    'POST /api/project/action-recovery':'人工对账 mark_interrupted|continue|close_unknown|reconcile_completed；须ifRev/action_version/contract_hash/source_hash、逐项checked_records、external_work_stopped=true和consent=human-action-recovery-v1；支持dry。接续沿用原Action与已耗次数；已有Result只能对账，不重跑',
                    'GET /api/project/result-review?project_id=ID&result_id=ID':'人类读取复核对象hash、Result/Evidence原记录及人工复核收据；不读取来源文件',
                    'POST /api/project/result-review':'仅追加人工复核收据：须ifRev/target_hash/source_version、来源核对情况、判据、复核人、结论、限制和consent=human-result-review-v1；支持dry。不修改Result/Evidence原结论或核验等级，科学状态仍NOT_ASSESSED',
                    'POST /api/project/manager':'人类授权 enabled/max_calls_per_day；启用需 consent=codex-project-records-v1',
                    'POST /api/project/manager/schedule':'人类修改总结间隔和次数限制；summary_interval_minutes(1–1440)、max_calls_per_day=null不限次数、if_schedule_revision、schedule_consent=scheduled-codex-management-v1；支持dry，不重置用量/授权/原行动',
                    'POST /api/project/manager/handoff':'人审只读核查 approve|reject|create；须ifRev、source_hash与完整契约；支持dry。runtime启用时自动领取，使用共同每日预算',
                    'POST /api/project/manager/runtime':'另行授权登记文件元数据观察和只读执行器；enabled/consent=registered-file-metadata-and-review-v1；不扫描新目录或发送原文',
                    'POST /api/project/manager/sources':'人类独立授权所选folders/threads；if_revision/dry，读取consent=selected-local-sources-v1，正文发送另需content_consent=selected-source-text-to-codex-v1；PDF/DOCX另需document_text_enabled=true和document_consent=selected-document-text-v1；默认关闭，不含OCR',
                    'POST /api/project/manager/intake':'人审来源资料索引草稿；须ifRev/draft_hash/source_ids/confirm_indexing；支持dry。核对当前授权及文件版本，只添加未核验索引',
                    'POST /api/project/manager/extra-call':'仅今天为指定有效排队总结任务额外授权1次，job_id/source_hash/reason/consent=one-extra-call-today-v1；支持dry，不改常规预算',
                    'POST /api/agent/management/claim':'项目级EXECUTE令牌按handoff_id领取有效且人已批准的只读核查契约；原子锁、幂等回执',
                    'POST /api/research-focus':'生成或复用结构化 Daily Focus。body={trigger:daily|task_changed|evidence_changed|manual_refresh,force?,exclude_previous_focus_id?}',
                    'POST /api/research-focus/feedback':'记录用户反馈。body={focus_id,action:accepted|rejected|alternate,title?}',
                    'GET /api/agents?project_id=ID':'人类视图：Agent Registry、MCP最近通信与常驻管理通道状态',
                    'GET /api/agent-connection?project_id=ID':'人类只读视图：常驻连接策略、心跳及该项目会话；不调用模型',
                    'POST /api/agent-connection/model':'人类明确选择当前CLI接口model/list中的总结模型；model/if_revision/consent=codex-management-model-v1，先dry；只改研序管理模型，不写全局配置，不重跑旧任务',
                    'POST /api/agent-connection':'人类启用/暂停常驻管理通道；enabled/if_revision/dry，启用consent=codex-persistent-management-v1；不改变项目或资料授权/预算',
                    'POST /api/agent-connection/login':'人类点击后启动/复用当前实例的官方浏览器登录；if_revision及consent=codex-browser-login-v1；URL仅瞬时返回，不写入状态/日志，不修改项目授权',
                    'POST /api/agents/connect':'为指定 project_id 生成项目级 Agent token、MCP 配置与 contract；配置生成不表示已连接',
                    'GET /api/project/today|context|graph|evidence|results|artifacts|events|decisions':'通用项目视图；旧 /api/research/* 保留兼容',
                    'GET /api/agent/context|project|tasks|evidence|results|artifacts|decisions|events|actions':'项目级 Agent token；context 调用完成真实握手',
                    'POST /api/agent/activity|proposal|result|evidence|task|decision-request':'有边界 Action 生命周期与来源绑定写入；目标或科研证据覆盖进入人审',
                    'PATCH /api/agent/task/:id':'必须 ifRev、action_id、reason；只允许普通任务字段，冲突返回 409',
                    'POST /api/research/decisions/:id':'人类批准或拒绝待决请求并记录理由；不隐式修改研究目标',
                    'GET /api/help':'本说明'
                },
                'tasks 字段': 'id,project,title,priority(P0-P3),status(待开始/进行中/受阻/已完成),stage,start,end(YYYY-MM-DD),completed,milestone,note,parent(父任务id),deps(前置依赖id数组)',
                'rev 语义': '每次成功修改旧状态 rev+1；Agent task 写入必须携带 ifRev，过期返回 409；旧 /api/action 的过期写入返回 400'
            })
        if path=='/api/history':
            with connect() as c:
                rows = c.execute('SELECT id,time,body,actor,summary,gateway_body FROM history ORDER BY id DESC LIMIT 60').fetchall()
            out = []
            for i,tm,b,actor,summary,gateway in rows:
                d = json.loads(b)
                out.append({'id':i,'time':tm,'actor':actor or 'legacy','summary':summary or '', 'scope':'full' if gateway is not None else 'legacy_state', 'projects':len(d.get('projects',[])),'tasks':len(d.get('tasks',[])),'files':len(d.get('files',[])),'decisions':len(d.get('decisions',[]))})
            return self.send(200,out)
        if path=='/api/snapshots':
            q = parse_qs(urlparse(self.path).query)
            snapdir = DATA/'snapshots'
            if 'name' in q:
                name = q['name'][0]
                if not re.fullmatch(r'auto-[0-9-]+\.json', name): return self.send(400,{'error':'快照名称不正确'})
                f = snapdir/name
                if not f.exists(): return self.send(404,{'error':'快照不存在'})
                return self.send(200,json.loads(f.read_text(encoding='utf-8')))
            names = sorted((p.name for p in snapdir.glob('auto-*.json')), reverse=True) if snapdir.exists() else []
            return self.send(200,names)
        self.send(404,{'error':'不存在'})
    def _read_json_body(self):
        size=int(self.headers.get('Content-Length','0'))
        if size>20_000_000: raise ValueError('数据超过 20MB，请分批导入')
        body=json.loads(self.rfile.read(size))
        if not isinstance(body, dict): raise ValueError('请求体必须为 JSON 对象')
        return body
    def _bearer(self):
        value = self.headers.get('Authorization','')
        return value[7:] if value.startswith('Bearer ') else ''
    def do_POST(self):
        if not self.local_request(): return
        path=urlparse(self.path).path
        if path.startswith('/api/agent/'):
            try:
                agent=GATEWAY.authenticate(self._bearer())
                if path == '/api/agent/discussion/reply':
                    return self.send(200, ECOSYSTEM.agent_reply(agent, self._read_json_body()))
                result,ev=GATEWAY.agent_post(agent,path,self._read_json_body())
                if ev:
                    for item in (ev if isinstance(ev,list) else [ev]):
                        notify_named(item['type'],item)
                if path in ('/api/agent/result','/api/agent/evidence','/api/agent/artifact','/api/agent/task','/api/agent/decision-request'):
                    try:
                        trigger = 'evidence_changed' if path in ('/api/agent/result','/api/agent/evidence','/api/agent/artifact') else 'task_changed'
                        _refresh_focus_after_change(agent['project_id'], trigger, result_committed=(path == '/api/agent/result'))
                    except Exception as exc:
                        print('Planner refresh failed after committed Agent change: ' + str(exc), flush=True)
                return self.send(200,result)
            except agent_gateway.GatewayError as exc:
                return self.send(exc.status,{'error':str(exc)})
            except (ValueError,KeyError,TypeError,sqlite3.Error) as exc:
                return self.send(400,{'error':str(exc)})
        if self.headers.get('Authorization')!='Bearer '+TOKEN: return self.send(401,{'error':'需要本机 API 令牌'})
        if path == '/api/ecosystem':
            try:
                result = ECOSYSTEM.post(self._read_json_body())
                return self.send(200, result, extra={'X-Rev': str(result['rev'])})
            except (agent_gateway.GatewayError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
                return self.send(getattr(exc, 'status', 400), {'error': str(exc)})
        if path == '/api/apps':
            try:
                result = ECOSYSTEM.init_apps(self._read_json_body())
                return self.send(200, result, extra={'X-Rev': str(result['rev'])})
            except (ValueError, sqlite3.Error) as exc:
                return self.send(400, {'error': str(exc)})
        if path=='/api/project/folder-picker':
            # Human token plus the same-origin browser; no requested commands.
            if not self.headers.get('Origin'):
                return self.send(403,{'error':'请通过研序页面选择文件夹'})
            try:
                body=self._read_json_body()
                if set(body)!= {'project_id'} or not isinstance(body['project_id'],str):
                    raise ValueError('选择器只接受当前项目，不接受命令或路径')
                MANAGER.snapshot(body['project_id'])
                return self.send(200,folder_picker.choose())
            except (ValueError,TypeError,sqlite3.Error) as exc:
                return self.send(400,{'error':str(exc)})
        if path=='/api/ui/preferences':
            try:
                body=self._read_json_body()
                if set(body)!= {'language'} or not isinstance(body['language'],str):
                    raise ValueError('仅允许保存界面语言，不修改项目、授权或Codex配置')
                return self.send(200,{'language':ui_language(body['language'])})
            except (ValueError,TypeError,sqlite3.Error) as exc:
                return self.send(400,{'error':str(exc)})
        if path=='/api/agent-connection':
            try:
                return self.send(200, CONNECTION.configure(self._read_json_body()))
            except (ValueError,TypeError,sqlite3.Error) as exc:
                return self.send(400, {'error':str(exc)})
        if path=='/api/agent-connection/login':
            try:
                return self.send(200, CONNECTION.login(self._read_json_body()))
            except (ValueError,TypeError,sqlite3.Error,RuntimeError) as exc:
                return self.send(400, {'error':str(exc)})
        if path=='/api/agent-connection/model':
            try:
                return self.send(200, CONNECTION.choose_model(self._read_json_body()))
            except (ValueError,TypeError,sqlite3.Error,RuntimeError) as exc:
                return self.send(400, {'error':str(exc)})
        if path=='/api/project/action-recovery':
            try:
                result,ev=GATEWAY.human_recover(self._read_json_body())
                if ev:notify_named(ev['type'],ev)
                return self.send(200,result,extra={'X-Rev':str(result['rev'])})
            except agent_gateway.GatewayError as exc:
                return self.send(exc.status,{'error':str(exc)})
            except (ValueError,TypeError,sqlite3.Error) as exc:
                return self.send(400,{'error':str(exc)})
        if path=='/api/project/result-review':
            try:
                result,ev=GATEWAY.human_review(self._read_json_body())
                if ev:notify_named(ev['type'],ev)
                return self.send(200,result,extra={'X-Rev':str(result['rev'])})
            except (agent_gateway.GatewayError,agent_gateway.result_review.ReviewError) as exc:
                return self.send(exc.status,{'error':str(exc)})
            except (ValueError,TypeError,sqlite3.Error) as exc:
                return self.send(400,{'error':str(exc)})
        if path=='/api/project/manager/handoff':
            try:
                result,ev = _manager_review(self._read_json_body())
                if ev: notify_named('manager.changed',ev)
                return self.send(200,result,extra={'X-Rev':str(result['rev'])})
            except (ValueError,TypeError,sqlite3.Error) as exc: return self.send(400, {'error':str(exc)})
        if path=='/api/project/manager/sources':
            try:
                body = self._read_json_body()
                project = str(body.get('project_id',''))
                MANAGER.snapshot(project)  # validate project before persisting a private scope
                result = MANAGER.bridge.configure(project, body)
                if not body.get('dry'): notify_named('manager.changed', {'project_id':project})
                return self.send(200, result)
            except (ValueError,TypeError,sqlite3.Error) as exc: return self.send(400, {'error':str(exc)})
        if path=='/api/project/workspace':
            try:
                body=self._read_json_body()
                project=str(body.get('project_id',''))
                result=WORKSPACES.configure(project,body)
                if not body.get('dry'):
                    notify_named('manager.changed',{'project_id':project,'reason':'workspace.bound'})
                return self.send(200,result)
            except (ValueError,TypeError,sqlite3.Error) as exc:
                return self.send(400,{'error':str(exc)})
        if path=='/api/project/manager/intake':
            try:
                result, events = _source_intake(self._read_json_body())
                if events:
                    notify({'kind':'state', 'collections':['files'], 'project_changed':True})
                    for ev in events: notify_named(ev['type'], ev)
                    notify_named('manager.changed', {'project_id':str(events[0]['project_id'])})
                return self.send(200, result, extra={'X-Rev':str(result['rev'])})
            except (ValueError,TypeError,KeyError,sqlite3.Error) as exc: return self.send(400, {'error':str(exc)})
        if path=='/api/project/manager/schedule':
            try:
                body = self._read_json_body()
                return self.send(200, MANAGER.configure_schedule(str(body.get('project_id','')), body))
            except (ValueError,TypeError,sqlite3.Error) as exc: return self.send(400, {'error':str(exc)})
        if path=='/api/project/manager/extra-call':
            try:
                body = self._read_json_body()
                return self.send(200, MANAGER.grant_extra_call(str(body.get('project_id','')), body))
            except (ValueError,TypeError) as exc: return self.send(400, {'error':str(exc)})
        if path=='/api/project/manager/runtime':
            try:
                body = self._read_json_body()
                return self.send(200, MANAGER.configure_runtime(str(body.get('project_id','')), body))
            except (ValueError,TypeError) as exc: return self.send(400, {'error':str(exc)})
        if path=='/api/project/manager':
            try:
                body = self._read_json_body()
                return self.send(200, MANAGER.configure(str(body.get('project_id','')), body))
            except (ValueError,TypeError) as exc: return self.send(400, {'error':str(exc)})
        if path=='/api/agents/connect':
            try:
                base='http://127.0.0.1:'+str(self.server.server_port)
                return self.send(200,GATEWAY.connect_agent(self._read_json_body(),base,str(ROOT/'mcp-server.js')))
            except agent_gateway.GatewayError as exc:
                return self.send(exc.status,{'error':str(exc)})
        if path.startswith('/api/research/decisions/') or path.startswith('/api/project/decisions/'):
            try:
                result,ev=GATEWAY.human_resolve(path.rsplit('/',1)[-1],self._read_json_body())
                notify_named(ev['type'],ev)
                try:
                    _refresh_focus_after_change(ev['project_id'], 'task_changed')
                except Exception as exc:
                    print('Planner refresh failed after committed human decision: ' + str(exc), flush=True)
                return self.send(200,result)
            except agent_gateway.GatewayError as exc:
                return self.send(exc.status,{'error':str(exc)})
        if path == '/api/project-focus/accept':
            try:
                result = _accept_project_focus(self._read_json_body())
                return self.send(200, result, extra={'X-Rev':str(result['rev'])})
            except (ValueError, KeyError, TypeError) as exc:
                return self.send(400, {'error':str(exc)})
        if path in ('/api/research-focus', '/api/research-focus/feedback', '/api/project-focus', '/api/project-focus/feedback'):
            try:
                body = self._read_json_body()
                if path.endswith('/feedback'):
                    return self.send(200, _record_focus_feedback(body))
                result = _generate_focus(body)
                _emit_focus_changed(result, body.get('trigger') or 'manual_refresh')
                return self.send(200, result)
            except (ValueError, FocusProviderError) as exc:
                return self.send(400, {'error': str(exc)})
            except Exception:
                return self.send(500, {'error': '当前重点判断失败，页面可继续使用规则回退'})
        try:
            body=self._read_json_body()
            actor=str(body.get('actor') or 'human').strip().lower()
            if actor not in ['human','agent','system']: actor='human'
            summary=str(body.get('summary') or '').strip()[:240]
            changed_collections=set()
            legacy_events=[]
            with connect() as c:
                c.execute('BEGIN IMMEDIATE')
                old=c.execute('SELECT body FROM state WHERE id=1').fetchone()[0]
                s=json.loads(old)
                cur_rev=get_rev(c)
                old_gateway=project_backup.records(c)
                restore_gateway=None
                portable_restore=False
                if self.path in ('/api/state','/api/restore'):
                    changed_collections.update(['projects','tasks','files','decisions'])
                    req_rev=body.get('ifRev') if isinstance(body,dict) else None
                    if req_rev is not None and int(req_rev)!=cur_rev:
                        raise ValueError('状态已被修改（请求 rev %s，当前 %s），请重新 GET /api/state'% (req_rev,cur_rev))
                    if isinstance(body,dict) and isinstance(body.get('state'),dict):
                        s=body['state']
                    else:
                        s={k:v for k,v in body.items() if k not in ['ifRev','actor','summary']}
                    if self.path=='/api/restore':
                        if req_rev is None: raise ValueError('完整恢复必须提供 ifRev，请先刷新状态')
                        backup=body.get('backup',{})
                        if backup.get('format')!=project_backup.FORMAT or backup.get('version')!=project_backup.VERSION:
                            raise ValueError('不是支持的完整项目备份')
                        s=backup['state']
                        restore_gateway=backup.get('gateway')
                        portable_restore=True
                    if self.path == '/api/state':
                        s = ecosystem.preserve_app_state(s, json.loads(old))
                    s,_=migrate_state(s,0)
                elif self.path=='/api/undo':
                    changed_collections.update(['projects','tasks','files','decisions'])
                    row=c.execute('SELECT id,body,gateway_body FROM history ORDER BY id DESC LIMIT 1').fetchone()
                    if not row: raise ValueError('没有可撤销的修改')
                    if row[2] is None: raise ValueError('此旧历史仅包含任务状态；请从旧历史范围明确恢复，不支持完整撤销')
                    restore_gateway=json.loads(row[2])
                    c.execute('DELETE FROM history WHERE id=?',(row[0],)); s=json.loads(row[1]); s,_=migrate_state(s,0)
                elif self.path=='/api/action':
                    if body.get('ifRev') is not None and int(body['ifRev'])!=cur_rev:
                        raise ValueError('状态已被修改（请求 rev %s，当前 %s），请重新 GET /api/state'% (body['ifRev'],cur_rev))
                    ops=body['ops'] if isinstance(body.get('ops'),list) else [body]
                    for op in ops:
                        kind=op.get('collection')
                        if kind not in ['projects','tasks','files','decisions']: raise ValueError('集合不正确')
                        changed_collections.add(kind)
                        if op.get('op')=='delete':
                            rid=op.get('id')
                            if kind=='projects':
                                if not body.get('dry'): project_backup.delete_project(c,rid)
                                s['projects']=[x for x in s['projects'] if x['id']!=rid]
                                s['tasks']=[x for x in s['tasks'] if x['project']!=rid]
                                s['files']=[x for x in s['files'] if x['project']!=rid]
                                s['decisions']=[x for x in s['decisions'] if x['project']!=rid]
                            else:
                                s[kind]=[x for x in s[kind] if x['id']!=rid]
                                if kind=='tasks':
                                    for x in s['tasks']:
                                        if x.get('parent')==rid: x['parent']=''
                                        if x.get('deps'): x['deps']=[d for d in x['deps'] if d!=rid]
                        else:
                            item=op.get('item')
                            if not isinstance(item,dict): raise ValueError('缺少 item')
                            if kind == 'projects' and (item.get('app_owner') or item.get('id') in ecosystem.APP_SPACES.values()):
                                raise ValueError('App 个人空间元数据由对应 App 管理')
                            existing=next((x for x in s[kind] if x['id']==item.get('id')),None)
                            if existing is None:
                                item['id']=item.get('id') or secrets.token_hex(12)
                                if kind=='projects':
                                    for key in ('description','goal','success_definition','current_state','workspace','type'):
                                        item.setdefault(key,'')
                                    item.setdefault('constraints',[])
                                if kind=='tasks':
                                    item.setdefault('status','待开始'); item.setdefault('priority','P2')
                                    item.setdefault('milestone',False); item.setdefault('deps',[])
                                    item.setdefault('parent',''); item.setdefault('completed','')
                                if kind=='decisions': item.setdefault('status','待决')
                                s[kind].append(item)
                            else: existing.update(item)
                    if body.get('dry'):
                        validate(s)
                        return self.send(200,{'ok':True,'dry':True,'rev':cur_rev,'applied':len(ops)})
                elif self.path=='/api/rollback':
                    changed_collections.update(['projects','tasks','files','decisions'])
                    rid=int(body.get('id',0))
                    row=c.execute('SELECT body,gateway_body FROM history WHERE id=?',(rid,)).fetchone()
                    if not row: raise ValueError('历史记录不存在')
                    s=json.loads(row[0]); s,_=migrate_state(s,0)
                    if row[1] is not None: restore_gateway=json.loads(row[1])
                    elif not body.get('legacyStateOnly'): raise ValueError('旧历史仅包含任务状态，需明确 legacyStateOnly 范围')
                else: return self.send(404,{'error':'不存在'})
                validate(s)
                if restore_gateway is not None: project_backup.restore(c,s,restore_gateway,portable_restore)
                elif self.path in ('/api/state','/api/rollback'):
                    project_ids={p['id'] for p in s['projects']}
                    if any(row['project_id'] not in project_ids for table,rows in old_gateway.items() if table!='project_events' for row in rows):
                        raise ValueError('旧状态恢复将断开 Agent 项目记录；请使用完整项目备份')
                if self.path!='/api/undo': c.execute('INSERT INTO history(body,time,actor,summary,gateway_body) VALUES(?,?,?,?,?)',(old,datetime.datetime.now().isoformat(timespec='seconds'),actor,summary,json.dumps(old_gateway,ensure_ascii=False)))
                c.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(s,ensure_ascii=False),))
                new_rev=bump_rev(c)
                if self.path=='/api/action':
                    previous=json.loads(old)
                    for op in ops:
                        collection=op['collection']; rid=op.get('id') if op.get('op')=='delete' else (op.get('item') or {}).get('id')
                        before=next((x for x in previous[collection] if x.get('id')==rid),None)
                        after=next((x for x in s[collection] if x.get('id')==rid),None)
                        project_id=rid if collection=='projects' else ((after or before or {}).get('project') or 'global')
                        entity=collection[:-1]
                        kind=entity+'.deleted' if op.get('op')=='delete' else entity+'.created' if before is None else entity+'.completed' if collection=='tasks' and (after or {}).get('status')=='已完成' and (before or {}).get('status')!='已完成' else entity+'.updated'
                        title=(after or before or {}).get('title') or (after or before or {}).get('name') or kind
                        legacy_events.append(agent_gateway.event(c,project_id,'legacy-'+actor,kind,str(title),entity,rid or '',before=before,after=after,reason=summary,importance='high' if kind.endswith(('deleted','completed')) else 'normal'))
                else:
                    legacy_events.append(agent_gateway.event(c,'global','legacy-'+actor,'state.replaced',summary or '整体状态发生变化','state','1',
                        before={key:len(json.loads(old).get(key,[])) for key in ('projects','tasks','files','decisions')},
                        after={key:len(s.get(key,[])) for key in ('projects','tasks','files','decisions')},reason=summary,importance='high'))
                if self.path in ('/api/restore','/api/undo','/api/rollback','/api/state'):
                    MANAGER.invalidate_pending(c)
                maybe_snapshot(s,c)
            if self.path in ('/api/restore','/api/undo','/api/rollback'):
                with FOCUS_LOCK:
                    FOCUS_FILE.unlink(missing_ok=True)
            changed = bool(changed_collections.intersection({'projects', 'tasks', 'files', 'decisions'}))
            notify({'kind': 'state', 'collections': sorted(changed_collections), 'project_changed': changed, 'research_changed': changed})
            for ev in legacy_events: notify_named(ev['type'],ev)
            self.send(200,ecosystem.desk_state(s),extra={'X-Rev':str(new_rev)})
        except (ValueError,KeyError,TypeError) as e: self.send(400,{'error':str(e)})
        except Exception: self.send(500,{'error':'保存失败，请检查磁盘空间和服务日志'})
    def do_PATCH(self):
        if not self.local_request(): return
        path=urlparse(self.path).path
        if not path.startswith('/api/agent/task/'):
            return self.send(404,{'error':'不存在'})
        try:
            agent=GATEWAY.authenticate(self._bearer())
            result,ev=GATEWAY.patch_task(agent,path.rsplit('/',1)[-1],self._read_json_body())
            notify_named(ev['type'],ev)
            try:
                _refresh_focus_after_change(agent['project_id'], 'task_changed')
            except Exception as exc:
                print('Planner refresh failed after committed Agent task patch: ' + str(exc), flush=True)
            return self.send(200,result,extra={'X-Rev':str(result['rev'])})
        except agent_gateway.GatewayError as exc:
            return self.send(exc.status,{'error':str(exc)})
        except (ValueError,KeyError,TypeError,sqlite3.Error) as exc:
            return self.send(400,{'error':str(exc)})
if __name__=='__main__':
    port=int(os.environ.get('PORT','8765'))
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print('研序项目工作空间：http://127.0.0.1:'+str(port),flush=True)
    if os.environ.get('OPEN_BROWSER')=='1': threading.Timer(.5,lambda:webbrowser.open('http://127.0.0.1:'+str(port))).start()
    CONNECTION.start()
    MANAGER.start()
    ECOSYSTEM.start()
    def stop_server(*args):
        MANAGER.stop.set()
        ECOSYSTEM.stop.set()
        CONNECTION.close()
        threading.Thread(target=server.shutdown, daemon=True).start()
    import signal
    signal.signal(signal.SIGTERM, stop_server)
    signal.signal(signal.SIGINT, stop_server)
    try:
        server.serve_forever()
    finally:
        MANAGER.stop.set()
        ECOSYSTEM.stop.set()
        CONNECTION.close()
        server.server_close()
