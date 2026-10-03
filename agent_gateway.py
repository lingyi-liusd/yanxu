import project_backup
"""Additive project state engine and project-scoped Agent Gateway.

The legacy JSON state stays intact. Evidence and outputs are append-only;
an action's delivery status is never treated as result verification.
"""
import datetime
import hashlib
import json
import secrets
import sqlite3
import shlex
import shutil
import os
import action_contracts
import result_review

RESULT_STATUS = {
    'PASS':'success', 'PASSED':'success', 'SUCCESS':'success',
    'FAIL':'failure', 'FAILED':'failure', 'FAILURE':'failure',
    'PARTIAL':'partial', 'INCONCLUSIVE':'inconclusive', 'UNKNOWN':'unknown',
}
ARTIFACT_TYPES = {'file','code','document','image','report','dataset','presentation','design','build','pr','analysis','other'}


class GatewayError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def stamp():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def decoded(value, default=None):
    return json.loads(value) if value else default


def schema(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS agents (
      id TEXT PRIMARY KEY, project_id TEXT NOT NULL, name TEXT NOT NULL,
      type TEXT NOT NULL, permission TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
      capabilities TEXT NOT NULL, status TEXT NOT NULL, current_action TEXT,
      created_at TEXT NOT NULL, last_seen TEXT);
    CREATE TABLE IF NOT EXISTS project_events (
      seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
      timestamp TEXT NOT NULL, project_id TEXT NOT NULL, actor TEXT NOT NULL,
      type TEXT NOT NULL, entity_type TEXT, entity_id TEXT, summary TEXT NOT NULL,
      before_json TEXT, after_json TEXT, payload_json TEXT, reason TEXT,
      source_action TEXT, importance TEXT NOT NULL DEFAULT 'normal');
    CREATE INDEX IF NOT EXISTS idx_events_project ON project_events(project_id,seq DESC);
    CREATE TABLE IF NOT EXISTS evidence (
      id TEXT PRIMARY KEY, project_id TEXT NOT NULL, action_id TEXT, task_id TEXT,
      status TEXT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL,
      source_ref TEXT NOT NULL, source_version TEXT, artifact_path TEXT,
      provenance TEXT, actor TEXT NOT NULL, created_at TEXT NOT NULL,
      supersedes_id TEXT, invalidated_at TEXT);
    CREATE INDEX IF NOT EXISTS idx_evidence_project ON evidence(project_id,created_at DESC);
    CREATE TABLE IF NOT EXISTS actions (
      id TEXT PRIMARY KEY, project_id TEXT NOT NULL, task_id TEXT,
      goal TEXT NOT NULL, why_now TEXT NOT NULL, expected_output TEXT NOT NULL,
      success_condition TEXT, failure_condition TEXT, dependencies TEXT,
      agent_id TEXT, status TEXT NOT NULL, budget TEXT, stop_condition TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
    CREATE INDEX IF NOT EXISTS idx_actions_project ON actions(project_id,updated_at DESC);
    CREATE TABLE IF NOT EXISTS action_results (
      id TEXT PRIMARY KEY, action_id TEXT NOT NULL, project_id TEXT NOT NULL,
      outcome TEXT NOT NULL, summary TEXT NOT NULL, source_ref TEXT NOT NULL,
      actor TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS artifacts (
      id TEXT PRIMARY KEY, project_id TEXT NOT NULL, action_id TEXT NOT NULL,
      type TEXT NOT NULL, title TEXT NOT NULL, reference TEXT NOT NULL,
      source_version TEXT NOT NULL, summary TEXT, agent_id TEXT NOT NULL,
      created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_artifacts_project ON artifacts(project_id,created_at DESC);
    CREATE TABLE IF NOT EXISTS proposals (
      id TEXT PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL,
      title TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL,
      actor TEXT NOT NULL, action_id TEXT, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS decision_requests (
      id TEXT PRIMARY KEY, project_id TEXT NOT NULL, question TEXT NOT NULL,
      context TEXT NOT NULL, options_json TEXT NOT NULL, impact TEXT,
      blocking INTEGER NOT NULL, status TEXT NOT NULL, action_id TEXT,
      actor TEXT NOT NULL, created_at TEXT NOT NULL, resolved_at TEXT,
      resolution TEXT);
    CREATE TABLE IF NOT EXISTS action_contracts (
      id TEXT PRIMARY KEY, project_id TEXT NOT NULL, action_id TEXT NOT NULL UNIQUE,
      contract_json TEXT NOT NULL, contract_hash TEXT NOT NULL, authority_note TEXT NOT NULL,
      contract_mode TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS agent_protocols (
      agent_id TEXT PRIMARY KEY, contract_mode TEXT NOT NULL, handshake_at TEXT);
    CREATE TABLE IF NOT EXISTS action_recoveries (
      id TEXT PRIMARY KEY, project_id TEXT NOT NULL, action_id TEXT NOT NULL,
      operation TEXT NOT NULL, from_agent TEXT, to_agent TEXT, action_version INTEGER NOT NULL,
      contract_hash TEXT NOT NULL, context_hash TEXT NOT NULL, checked_records TEXT NOT NULL,
      summary TEXT NOT NULL, created_at TEXT NOT NULL);
    ''')
    for table in ('evidence','action_results'):
        columns = {row[1] for row in c.execute('PRAGMA table_info('+table+')')}
        if 'verification_status' not in columns:
            c.execute("ALTER TABLE "+table+" ADD COLUMN verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED'")
        if table == 'action_results' and 'source_version' not in columns:
            c.execute("ALTER TABLE action_results ADD COLUMN source_version TEXT NOT NULL DEFAULT ''")
    result_review.schema(c)
    c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('agent_schema_version','5')")


def row_dict(cursor, row):
    return dict(zip((x[0] for x in cursor.description), row)) if row else None


def one(c, query, args=()):
    cur = c.execute(query, args)
    return row_dict(cur, cur.fetchone())


def all_rows(c, query, args=()):
    cur = c.execute(query, args)
    return [row_dict(cur, row) for row in cur.fetchall()]


def event(c, project_id, actor, kind, summary, entity_type='', entity_id='', before=None, after=None, payload=None, reason='', action_id='', importance='normal'):
    eid = 'ev-' + secrets.token_hex(12)
    ts = stamp()
    c.execute('''INSERT INTO project_events
      (id,timestamp,project_id,actor,type,entity_type,entity_id,summary,before_json,after_json,payload_json,reason,source_action,importance)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
      (eid,ts,project_id,actor,kind,entity_type,entity_id,summary,
       encoded(before) if before is not None else None,
       encoded(after) if after is not None else None,
       encoded(payload) if payload is not None else None,reason,action_id,importance))
    return {'id':eid,'timestamp':ts,'project_id':project_id,'actor':actor,'type':kind,
            'entity_type':entity_type,'entity_id':entity_id,'summary':summary,
            'before':before,'after':after,'payload':payload,'reason':reason,
            'source_action':action_id,'importance':importance}


class Gateway:
    error_class = GatewayError
    def __init__(self, connect, get_rev, bump_rev, validate, focus_status, snapshot=None):
        self.connect = connect
        self.get_rev = get_rev
        self.bump_rev = bump_rev
        self.validate = validate
        self.focus_status = focus_status
        self.snapshot = snapshot or (lambda c: None)

    def state(self, c):
        return decoded(c.execute('SELECT body FROM state WHERE id=1').fetchone()[0])

    def project(self, c, project_id):
        p = next((p for p in self.state(c)['projects'] if p['id'] == project_id), None)
        if not p:
            raise GatewayError('项目不存在', 404)
        return p

    def authenticate(self, token):
        if not token:
            raise GatewayError('缺少 Agent token', 401)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as c:
            agent = one(c, 'SELECT id,project_id,name,type,permission,capabilities,status,current_action,created_at,last_seen FROM agents WHERE token_hash=?', (digest,))
        if not agent:
            raise GatewayError('Agent token 无效', 401)
        return agent

    def require(self, agent, permission):
        rank = {'READ':0,'PROPOSE':1,'EXECUTE':2}
        if rank.get(agent['permission'], -1) < rank[permission]:
            raise GatewayError('Agent 权限不足；请向人类提出请求', 403)

    def human_get(self, path, query):
        if path.startswith('/api/project/') and path not in ('/api/project/context','/api/project/results','/api/project/artifacts'):
            path = '/api/research/' + path[len('/api/project/'):]
        with self.connect() as c:
            if path == '/api/agents':
                agents = all_rows(c, 'SELECT id,project_id,name,type,permission,capabilities,status,current_action,created_at,last_seen FROM agents ORDER BY created_at DESC')
                for a in agents:
                    a['capabilities'] = decoded(a['capabilities'], [])
                    a['connected'] = self.is_live(a)
                return {'agents':agents}
            if path == '/api/research/today':
                return self.today(c, query.get('project_id',[''])[0])
            if path == '/api/project/context':
                state = self.state(c)
                pid = query.get('project_id',[''])[0] or (state['projects'][0]['id'] if state['projects'] else '')
                if not pid: return {'project':None}
                return self.context(c, self.project(c,pid), state, None)
            if path == '/api/project/results':
                project_id = query.get('project_id',[''])[0]
                if project_id: self.project(c,project_id)
                rows = all_rows(c,"SELECT * FROM action_results WHERE (?='' OR project_id=?) ORDER BY created_at DESC LIMIT 100",(project_id,project_id))
                return {'results':[dict(row, normalized_status=RESULT_STATUS.get(row['outcome'],'unknown')) for row in rows]}
            if path == '/api/project/artifacts':
                project_id = query.get('project_id',[''])[0]
                if project_id: self.project(c,project_id)
                return {'artifacts':all_rows(c,"SELECT * FROM artifacts WHERE (?='' OR project_id=?) ORDER BY created_at DESC LIMIT 100",(project_id,project_id)),
                        'indexed_files':[f for f in self.state(c)['files'] if not project_id or f['project']==project_id]}
            if path == '/api/research/graph':
                return self.graph(c, query.get('project_id',[''])[0])
            if path == '/api/research/events':
                project_id = query.get('project_id',[''])[0]
                if project_id: self.project(c, project_id)
                limit = min(100, max(1, int(query.get('limit',['30'])[0])))
                rows = all_rows(c, "SELECT * FROM project_events WHERE (?='' OR project_id=?) ORDER BY seq DESC LIMIT ?", (project_id,project_id,limit))
                return {'events':[self.public_event(row) for row in rows]}
            if path == '/api/research/evidence':
                project_id = query.get('project_id',[''])[0]
                if project_id: self.project(c, project_id)
                return {'evidence':all_rows(c,"SELECT * FROM evidence WHERE (?='' OR project_id=?) ORDER BY created_at DESC LIMIT 100",(project_id,project_id))}
            if path == '/api/research/decisions':
                project_id = query.get('project_id',[''])[0]
                if project_id: self.project(c, project_id)
                rows = all_rows(c,"SELECT * FROM decision_requests WHERE (?='' OR project_id=?) ORDER BY created_at DESC LIMIT 100",(project_id,project_id))
                return {'decisions':[self.public_decision(r) for r in rows]}
        raise GatewayError('不存在', 404)

    def is_live(self, a):
        if not a['last_seen']:
            return False
        try:
            last = datetime.datetime.fromisoformat(a['last_seen'])
            if last.tzinfo is None:
                last = last.astimezone()
            return (datetime.datetime.now().astimezone() - last).total_seconds() < 120
        except ValueError:
            return False

    def public_event(self, e):
        for field, target in (('before_json','before'),('after_json','after'),('payload_json','payload')):
            e[target] = decoded(e.pop(field), None)
        return e

    def public_decision(self, d):
        d['options'] = decoded(d.pop('options_json'), [])
        d['blocking'] = bool(d['blocking'])
        return d

    def connect_agent(self, body, base, mcp_path):
        project_id = str(body.get('project_id') or '')
        name = str(body.get('name') or 'Codex').strip()[:80]
        kind = str(body.get('type') or 'coding_agent').strip()[:80]
        permission = str(body.get('permission') or 'EXECUTE').upper()
        if permission not in ('READ','PROPOSE','EXECUTE'):
            raise GatewayError('权限必须是 READ / PROPOSE / EXECUTE')
        token = secrets.token_urlsafe(32)
        aid = 'agent-' + secrets.token_hex(8)
        with self.connect() as c:
            self.project(c, project_id)
            mode=body.get('contract_mode','legacy')
            if mode not in ('legacy','strict_v2'):
                raise GatewayError('contract_mode 须为 legacy 或 strict_v2')
            c.execute('''INSERT INTO agents VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                      (aid,project_id,name,kind,permission,hashlib.sha256(token.encode()).hexdigest(),
                       encoded(['code','terminal','file'] if name.lower() == 'codex' else []),
                       'configured',None,stamp(),None))
            c.execute('INSERT INTO agent_protocols VALUES(?,?,NULL)',(aid,mode))
        node_command = os.environ.get('RESEARCH_DESK_NODE_BIN') or shutil.which('node') or 'node'
        server_name = 'research-desk-' + aid[6:]
        config = {'mcpServers': {server_name: {'command':node_command,'args':[mcp_path],
                  'env':{'RESEARCH_DESK_BASE_URL':base,'RESEARCH_DESK_AGENT_TOKEN':token,
                         'RESEARCH_DESK_PROJECT_ID':project_id}}}}
        codex_toml = ('[mcp_servers.'+server_name+']\n'
                      'command = '+json.dumps(node_command)+'\n'
                      'args = ['+json.dumps(mcp_path)+']\n'
                      'required = false\n\n'
                      '[mcp_servers.'+server_name+'.env]\n'
                      'RESEARCH_DESK_BASE_URL = '+json.dumps(base)+'\n'
                      'RESEARCH_DESK_AGENT_TOKEN = '+json.dumps(token)+'\n'
                      'RESEARCH_DESK_PROJECT_ID = '+json.dumps(project_id)+'\n')
        codex_command = ('codex mcp add '+shlex.quote(server_name)
                         +' --env '+shlex.quote('RESEARCH_DESK_BASE_URL='+base)
                         +' --env '+shlex.quote('RESEARCH_DESK_AGENT_TOKEN='+token)
                         +' --env '+shlex.quote('RESEARCH_DESK_PROJECT_ID='+project_id)
                         +' -- '+shlex.quote(node_command)+' '+shlex.quote(mcp_path))
        if os.name == 'nt':
            def ps_quote(value):
                return "'" + str(value).replace("'", "''") + "'"
            executable = os.environ.get('RESEARCH_DESK_CODEX_BIN') or 'codex'
            arguments = [executable, 'mcp', 'add', server_name, '--env', 'RESEARCH_DESK_BASE_URL='+base,
                         '--env', 'RESEARCH_DESK_AGENT_TOKEN='+token, '--env', 'RESEARCH_DESK_PROJECT_ID='+project_id,
                         '--', node_command, mcp_path]
            codex_command = '& ' + ' '.join(ps_quote(a) for a in arguments)
            if os.environ.get('RESEARCH_DESK_CODEX_BIN') and os.environ.get('CODEX_HOME'):
                codex_command = '$env:CODEX_HOME = ' + ps_quote(os.environ['CODEX_HOME']) + '; ' + codex_command
        elif os.environ.get('RESEARCH_DESK_CODEX_BIN'):
            codex_command = shlex.quote(os.environ['RESEARCH_DESK_CODEX_BIN']) + codex_command[len('codex'):]
            if os.environ.get('CODEX_HOME'):
                codex_command = 'CODEX_HOME=' + shlex.quote(os.environ['CODEX_HOME']) + ' ' + codex_command
        contract = ('# Research Desk Project Agent Contract\n\nProject: '+project_id+'\n'
                    'Before work call project.get_context; read negative results, constraints, blockers and pending decisions. '
                    'Claim one bounded Action, report progress, register sourced artifacts and results. '
                    'Do not overwrite human notes, prior evidence or the project goal. '
                    'Request a human decision for direction, scope, constraints or destructive changes. '
                    'Action completion is not independent result verification.\n')
        return {'agent_id':aid,'project_id':project_id,'endpoint':base+'/api/agent/context',
                'contract_mode':mode,
                'permission':permission,'token':token,'mcp_config':config,'codex_config_toml':codex_toml,
                'codex_command':codex_command,'agent_instruction':contract,
                'workspace':{'path':body.get('workspace_path') or None,'status':'not_configured' if not body.get('workspace_path') else 'provided'},
                'connected':False,'note':'配置已生成，尚未连接。推荐使用官方注册命令；不要重复追加配置段，不修改features、模型或登录设置。连接不强制阻塞Codex启动，工具审批沿用宿主设置。'}

    def agent_get(self, agent, path, query):
        self.require(agent, 'READ')
        with self.connect() as c:
            p = self.project(c, agent['project_id'])
            state = self.state(c)
            if path == '/api/agent/context':
                # This is the actual connection handshake, not config generation.
                if agent['status'] == 'configured':
                    with c:
                        c.execute('UPDATE agents SET status=?,last_seen=? WHERE id=?',('online',stamp(),agent['id']))
                        ev = event(c,p['id'],agent['id'],'agent.connected',agent['name']+' 已握手','agent',agent['id'],importance='high')
                else:
                    c.execute('UPDATE agents SET last_seen=? WHERE id=?',(stamp(),agent['id']))
                    ev = None
                c.execute('INSERT INTO agent_protocols(agent_id,contract_mode,handshake_at) VALUES(?,?,?) ON CONFLICT(agent_id) DO UPDATE SET handshake_at=excluded.handshake_at',
                          (agent['id'],'legacy',stamp()))
                response = self.context(c,p,state,agent)
            else:
                c.execute('UPDATE agents SET last_seen=? WHERE id=?',(stamp(),agent['id']))
                ev = None
                if path == '/api/agent/project': response = {'project':p}
                elif path == '/api/agent/tasks': response = {'tasks':[t for t in state['tasks'] if t['project']==p['id']]}
                elif path == '/api/agent/evidence': response = {'evidence':all_rows(c,'SELECT * FROM evidence WHERE project_id=? ORDER BY created_at DESC LIMIT 100',(p['id'],))}
                elif path == '/api/agent/decisions': response = {'decisions':[self.public_decision(r) for r in all_rows(c,'SELECT * FROM decision_requests WHERE project_id=? ORDER BY created_at DESC LIMIT 100',(p['id'],))], 'legacy_decisions':[d for d in state['decisions'] if d['project']==p['id']]}
                elif path == '/api/agent/events': response = {'events':[self.public_event(r) for r in all_rows(c,'SELECT * FROM project_events WHERE project_id=? ORDER BY seq DESC LIMIT 30',(p['id'],))]}
                elif path == '/api/agent/actions': response = {'actions':[self.public_action(c,a) for a in all_rows(c,'SELECT * FROM actions WHERE project_id=? ORDER BY updated_at DESC LIMIT 40',(p['id'],))]}
                elif path == '/api/agent/artifacts': response = {'artifacts':all_rows(c,'SELECT * FROM artifacts WHERE project_id=? ORDER BY created_at DESC LIMIT 100',(p['id'],)), 'indexed_files':[f for f in state['files'] if f['project']==p['id']]}
                elif path == '/api/agent/results': response = {'results':[dict(row,normalized_status=RESULT_STATUS.get(row['outcome'],'unknown')) for row in all_rows(c,'SELECT * FROM action_results WHERE project_id=? ORDER BY created_at DESC LIMIT 100',(p['id'],))]}
                else: raise GatewayError('不存在',404)
        return response, ev

    def context(self, c, p, state, agent):
        pid = p['id']
        tasks = [t for t in state['tasks'] if t['project']==pid]
        active = [t for t in tasks if t.get('status')!='已完成']
        blocked = [t for t in active if t.get('status')=='受阻']
        evidence = all_rows(c,'SELECT id,title,status,summary,source_ref,created_at FROM evidence WHERE project_id=? ORDER BY created_at DESC LIMIT 12',(pid,))
        actions = [self.public_action(c,a) for a in all_rows(c,'SELECT * FROM actions WHERE project_id=? ORDER BY updated_at DESC LIMIT 8',(pid,))]
        decisions = [dict(self.public_decision(r), source='request') for r in all_rows(c,"SELECT * FROM decision_requests WHERE project_id=? AND status='pending' ORDER BY created_at DESC LIMIT 8",(pid,))]
        legacy_decisions = [dict(d, source='legacy') for d in state['decisions'] if d['project']==pid]
        events = [self.public_event(r) for r in all_rows(c,'SELECT * FROM project_events WHERE project_id=? ORDER BY seq DESC LIMIT 10',(pid,))]
        results = [dict(r,normalized_status=RESULT_STATUS.get(r['outcome'],'unknown')) for r in all_rows(c,'SELECT * FROM action_results WHERE project_id=? ORDER BY created_at DESC LIMIT 12',(pid,))]
        artifacts = all_rows(c,'SELECT * FROM artifacts WHERE project_id=? ORDER BY created_at DESC LIMIT 30',(pid,))
        agents = all_rows(c,'SELECT id,name,type,permission,status,current_action,last_seen FROM agents WHERE project_id=? ORDER BY created_at DESC',(pid,))
        proposals = all_rows(c,"SELECT * FROM proposals WHERE project_id=? AND status='pending' ORDER BY created_at DESC LIMIT 20",(pid,))
        for proposal in proposals:
            origin = one(c,"SELECT payload_json FROM project_events WHERE entity_id=? AND type='proposal.created' ORDER BY seq DESC LIMIT 1",(proposal['id'],))
            snapshot = decoded(origin['payload_json'],{}).get('snapshot_rev') if origin else None
            proposal['snapshot_rev'] = snapshot
            proposal['stale'] = snapshot != self.get_rev(c)
        goal = p.get('goal') or ''
        constraints = p.get('constraints') or p.get('frozen_constraints') or []
        active_action = next((a for a in actions if a['status'] in ('claimed','running','result_reported')),None)
        focus = self.focus_status(pid).get('focus')
        return {'project':{'id':pid,'name':p['name'],'description':p.get('description') or '',
                           'type':p.get('type') or '', 'workspace':p.get('workspace') or p.get('workspace_path') or ''},
                'goal':{'statement':goal,'success_definition':p.get('success_definition') or ''},
                'current_state':{'recorded':p.get('current_state') or '',
                                 'active_action':active_action['id'] if active_action else None,
                                 'blocked_count':len(blocked)},
                'objective':goal,'proposals':proposals,
                'current_phase':next((t.get('stage') for t in active if t.get('status')=='进行中' and t.get('stage')), ''),
                'current_focus':focus,
                'management':self.manager_context(pid) if hasattr(self,'manager_context') else None,
                'constraints':constraints,
                'critical_constraints':constraints,'open_questions':[d['question'] for d in decisions] + [d.get('question') or d.get('title','') for d in legacy_decisions if d.get('status')!='已决'],
                'questions':[{'id':d['id'],'title':d['question'],'source':'decision_request'} for d in decisions] + [{'id':d['id'],'title':d.get('question') or d.get('title',''),'source':'legacy_decision'} for d in legacy_decisions if d.get('status')!='已决'],
                'blockers':[{'id':t['id'],'title':t['title']} for t in blocked[:8]],
                'recent_results':evidence,'recent_negative_results':[e for e in evidence if e['status'] in ('FAIL','FAILED','FAILURE','INCONCLUSIVE','PARTIAL')],
                'active_tasks':[{'id':t['id'],'title':t['title'],'status':t.get('status'),'priority':t.get('priority'),'deps':t.get('deps',[])} for t in active[:20]],
                'decisions':decisions+legacy_decisions,'recent_decisions':decisions+legacy_decisions[:8],
                'legacy_decisions':legacy_decisions,'recent_events':events,'events':events,
                'actions':actions,'artifacts':artifacts,'indexed_files':[f for f in state['files'] if f['project']==pid][:50],
                'evidence':evidence,'results':results,'agents':agents,
                'result_reviews':all_rows(c,'SELECT * FROM result_reviews WHERE project_id=? ORDER BY created_at DESC LIMIT 30',(pid,)),
                'workspace':self.workspace_status(pid) if hasattr(self,'workspace_status') else {'path':p.get('workspace') or p.get('workspace_path'),'configured':bool(p.get('workspace') or p.get('workspace_path'))},
                'permissions':{'level':agent['permission'] if agent else 'HUMAN',
                               'human_gate':['project goal','constraints','result or evidence replacement','destructive changes','direction closure']},
                'agent_permissions':{'level':agent['permission'] if agent else 'HUMAN','human_gate':['project goal','frozen constraints','result overwrite','evidence delete','direction closure']},
                'claim_contract':{'mode':'strict_v2 for new project MCP; legacy HTTP remains compatible',
                                  'requires':['get_context handshake','current context_hash','complete conditions','known project dependencies']},
                'rev':self.get_rev(c)}

    def public_action(self,c,action):
        stored=one(c,'SELECT * FROM action_contracts WHERE action_id=?',(action['id'],))
        if stored:
            action.update(contract_hash=stored['contract_hash'],approved_contract=decoded(stored['contract_json']),
                          authority_note=stored['authority_note'],contract_mode=stored['contract_mode'])
        else:
            action.update(contract_hash=action_contracts.digest(self.legacy_contract(action)),
                          approved_contract=None,contract_mode='legacy',authority_note='旧行动原契约保留，不自动补写条件')
        action['used_progress_reports']=c.execute("SELECT count(*) FROM project_events WHERE project_id=? AND source_action=? AND type='agent.progress'",(action['project_id'],action['id'])).fetchone()[0]
        return action

    @staticmethod
    def legacy_contract(action):
        return {'goal':action['goal'],'reason':action['why_now'],'expected_output':action['expected_output'],
                'success_condition':action['success_condition'],'failure_condition':action['failure_condition'],
                'stop_condition':action['stop_condition'],'dependencies':decoded(action['dependencies'],[]),
                'budget':decoded(action['budget'],{})}

    def agent_post(self, agent, path, body):
        pid = agent['project_id']
        if path in ('/api/agent/proposal','/api/agent/decision-request'): self.require(agent,'PROPOSE')
        else: self.require(agent,'EXECUTE')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            self.project(c,pid)
            previous_rev=self.get_rev(c)
            project_backup.history(c,agent['id'],'Agent 操作：'+path.rsplit('/',1)[-1])
            if path == '/api/agent/activity': result, ev = self.activity(c,agent,body)
            elif path == '/api/agent/proposal': result, ev = self.proposal(c,agent,body)
            elif path == '/api/agent/result': result, ev = self.result(c,agent,body)
            elif path == '/api/agent/evidence': result, ev = self.add_evidence(c,agent,body)
            elif path == '/api/agent/artifact': result, ev = self.add_artifact(c,agent,body)
            elif path == '/api/agent/task': result, ev = self.task(c,agent,body)
            elif path == '/api/agent/decision-request': result, ev = self.decision_request(c,agent,body)
            elif path == '/api/agent/management/claim' and hasattr(self,'manager'):
                result, ev = self.manager.claim(c,agent,body.get('handoff_id'),self.manager_signature(c,pid),self)
                if result.get('already_claimed'):
                    c.rollback()
                    return result,None
            else: raise GatewayError('不存在',404)
            if path == '/api/agent/result' and hasattr(self,'manager'):
                self.manager.complete(c,agent,result)
            c.execute('UPDATE agents SET last_seen=? WHERE id=?',(stamp(),agent['id']))
            if self.get_rev(c)==previous_rev: self.bump_rev(c)
            self.snapshot(c)
        return result, ev

    def action_for(self, c, agent, action_id):
        action = one(c,'SELECT * FROM actions WHERE id=? AND project_id=?',(action_id,agent['project_id']))
        if not action: raise GatewayError('Action 不存在',404)
        if action['agent_id'] and action['agent_id'] != agent['id']:
            raise GatewayError('Action 已由其他 Agent 认领',409)
        return action

    def activity(self,c,agent,b,approved_contract=None):
        phase = str(b.get('phase') or '').lower()
        if phase not in ('claim','start','progress','finish','fail','heartbeat'):
            raise GatewayError('phase 必须是 claim/start/progress/finish/fail/heartbeat')
        aid = str(b.get('action_id') or '')
        if phase == 'claim' and not aid:
            protocol=one(c,'SELECT * FROM agent_protocols WHERE agent_id=?',(agent['id'],))
            strict=bool(approved_contract is not None or b.get('contract_mode')=='strict_v2'
                        or protocol and protocol['contract_mode']=='strict_v2')
            if strict and approved_contract is None and (not protocol or not protocol['handshake_at']):
                raise GatewayError('请先调用 project.get_context 核对目标、版本和原契约',409)
            context_hash = b.get('context_hash')
            if strict and approved_contract is None and not context_hash:
                raise GatewayError('严格认领需要当前 context_hash',409)
            if context_hash is not None:
                if not isinstance(context_hash,str) or not hasattr(self,'manager_signature') or context_hash != self.manager_signature(c,agent['project_id']):
                    raise GatewayError('接续版本已变化；请重新调用 project.get_context 后再认领',409)
            if one(c,"SELECT id FROM actions WHERE agent_id=? AND status IN ('claimed','running','result_reported')",(agent['id'],)):
                raise GatewayError('Agent 已有未结束的 Action；请先报告结果并停止',409)
            task_id = str(b.get('task_id') or '')
            state = self.state(c)
            task = next((t for t in state['tasks'] if t['id']==task_id and t['project']==agent['project_id']),None)
            if task_id and not task: raise GatewayError('task_id 不属于本项目',404)
            if not task and not str(b.get('goal') or b.get('title') or '').strip():
                raise GatewayError('独立 Action 需要 goal 或 title')
            if task and one(c,"SELECT id FROM actions WHERE task_id=? AND status IN ('running','claimed','result_reported')",(task_id,)):
                raise GatewayError('该任务已有进行中的 Action',409)
            aid = 'act-' + secrets.token_hex(10)
            ts = stamp()
            budget=b.get('budget') or {'max_progress_reports':20}
            if not isinstance(budget,dict) or not 1 <= int(budget.get('max_progress_reports',20)) <= 100:
                raise GatewayError('Action 进度预算必须在 1–100 次之间')
            dependencies = b.get('dependencies') if b.get('dependencies') is not None else (task.get('deps') or [] if task else [])
            if not isinstance(dependencies,list) or any(not isinstance(dep,str) for dep in dependencies):
                raise GatewayError('Action dependencies 必须是文本列表')
            title = str(b.get('goal') or b.get('title') or (task or {}).get('title') or '')
            if not title.strip() or len(title)>400:
                raise GatewayError('行动目标须为非空文本，最多400字；不会截断')
            if strict:
                contract=approved_contract or {k:b.get(k) for k in action_contracts.TEXT_FIELDS if k!='goal'}
                if approved_contract is None:
                    contract.update(goal=title,scope='project_action',budget=b.get('budget'),dependencies=dependencies,
                                    dependency_policy=b.get('dependency_policy','recorded'))
                try:
                    contract=action_contracts.validate(contract,management=approved_contract is not None)
                except ValueError as exc:
                    raise GatewayError(str(exc))
                known={t['id']:t for t in state['tasks'] if t['project']==agent['project_id']}
                if any(d not in known for d in dependencies):
                    raise GatewayError('依赖缺失或不属于本项目；先核对，不会猜测',409)
                if contract.get('dependency_policy')=='all_completed' and any(known[d].get('status')!='已完成' for d in dependencies):
                    raise GatewayError('契约要求依赖全部完成，目前尚未满足',409)
                title=contract['goal']
            else:
                contract=None
            # Exact work identity only; no model/fuzzy guess that two experiments are equivalent.
            normalize = lambda text: ' '.join(str(text or '').split())
            expected = self.required(b,'expected_output')
            for other in all_rows(c,"SELECT id,goal,expected_output,dependencies FROM actions WHERE project_id=? AND status IN ('claimed','running','result_reported')", (agent['project_id'],)):
                if (len(title) < 400 and len(str(other['goal'])) < 400 and
                    normalize(other['goal']) == normalize(title) and
                    normalize(other['expected_output']) == normalize(expected) and
                    sorted(decoded(other['dependencies'],[])) == sorted(dependencies)):
                    raise GatewayError('相同目标、产出和依赖已有未结束行动 '+other['id']+'；请查看原行动，不要重复认领',409)
            c.execute('''INSERT INTO actions (id,project_id,task_id,goal,why_now,expected_output,success_condition,failure_condition,dependencies,agent_id,status,budget,stop_condition,created_at,updated_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                      (aid,agent['project_id'],task_id or None,title,
                       contract['reason'] if contract else self.required(b,'reason'),contract['expected_output'] if contract else self.required(b,'expected_output'),str(b.get('success_condition') or ''),
                       str(b.get('failure_condition') or ''),encoded(dependencies),agent['id'],'claimed',
                       encoded(budget),str(b.get('stop_condition') or '完成本 Action 后停止并重新规划'),ts,ts))
            if contract is not None:
                note='人审只读核查：不得实验、改文件、改目标或替代证据。' if approved_contract is not None else '执行范围来自原项目授权；新行动不扩权。'
                c.execute('INSERT INTO action_contracts VALUES(?,?,?,?,?,?,?,?)',
                          ('contract-'+secrets.token_hex(10),agent['project_id'],aid,encoded(contract),action_contracts.digest(contract),note,'strict_v2',ts))
            c.execute('UPDATE agents SET current_action=?,status=? WHERE id=?',(aid,'online',agent['id']))
            ev=event(c,agent['project_id'],agent['id'],'agent.claimed',agent['name']+' 认领：'+title,'action',aid,
                     after={'status':'claimed','task_id':task_id or None},reason=str(b.get('reason') or ''),action_id=aid,importance='high')
            return {'ok':True,'action_id':aid,'status':'claimed','contract_hash':action_contracts.digest(contract) if contract is not None else None},ev
        action = self.action_for(c,agent,aid)
        if phase in ('start','progress') and action['status'] not in ('claimed','running'):
            raise GatewayError('Action 当前不可继续',409)
        if phase == 'finish' and action['status'] == 'finished':
            return {'ok':True,'action_id':aid,'status':'finished','already_finished':True},None
        if phase == 'finish' and action['status'] != 'result_reported':
            raise GatewayError('完成前必须记录 result；交付完成不等于结果已核验',409)
        if phase == 'heartbeat':
            return {'ok':True,'action_id':aid,'status':action['status']},None
        if phase == 'fail' and action['status'] in ('finished','failed'):
            raise GatewayError('Action 已结束',409)
        if phase == 'fail' and action['status'] not in ('claimed','running','result_reported'):
            raise GatewayError('行动已中断，须先由人核对现场',409)
        if phase == 'progress':
            count=c.execute("SELECT COUNT(*) FROM project_events WHERE source_action=? AND type='agent.progress'",(aid,)).fetchone()[0]
            max_reports=int((decoded(action['budget'],{}) or {}).get('max_progress_reports',20))
            if count >= max_reports: raise GatewayError('Action 进度预算已用尽；请报告结果或请求人类决定',409)
        status={'start':'running','progress':'running','finish':'finished','fail':'failed'}[phase]
        c.execute('UPDATE actions SET status=?,updated_at=?,version=version+1 WHERE id=?',(status,stamp(),aid))
        c.execute('UPDATE agents SET current_action=? WHERE id=?',(None if phase in ('finish','fail') else aid,agent['id']))
        summary=self.required(b,'summary')
        ev=event(c,agent['project_id'],agent['id'],'agent.'+phase,summary,'action',aid,
                 before={'status':action['status']},after={'status':status},reason=str(b.get('reason') or ''),
                 action_id=aid,importance='high' if phase in ('finish','fail') else 'normal')
        return {'ok':True,'action_id':aid,'status':status},ev

    def required(self,b,key):
        value=str(b.get(key) or '').strip()
        if not value: raise GatewayError('缺少 '+key)
        if len(value)>4000: raise GatewayError(key+' 最多4000字；不会静默截断')
        return value

    def proposal(self,c,agent,b):
        title=self.required(b,'title')
        kind=str(b.get('kind') or 'task')
        if kind not in ('task','action','direction_change','goal_change','constraint_change','evidence_review','note'):
            raise GatewayError('proposal.kind 不支持')
        pr='prop-'+secrets.token_hex(10)
        c.execute('INSERT INTO proposals VALUES(?,?,?,?,?,?,?,?,?)',(pr,agent['project_id'],kind,title,self.required(b,'body'),'pending',agent['id'],str(b.get('action_id') or ''),stamp()))
        ev=event(c,agent['project_id'],agent['id'],'proposal.created',title,'proposal',pr,payload={'kind':kind,'snapshot_rev':self.get_rev(c)+1},importance='high' if kind!='task' else 'normal')
        return {'ok':True,'proposal_id':pr,'status':'pending'},ev

    def result(self,c,agent,b):
        aid=self.required(b,'action_id')
        action=self.action_for(c,agent,aid)
        if action['status'] not in ('claimed','running'):
            raise GatewayError('Action 不可记录结果',409)
        outcome=str(b.get('outcome') or '').upper()
        if outcome not in RESULT_STATUS:
            raise GatewayError('结果必须为 success / failure / partial / inconclusive / unknown，或兼容的 PASS / FAIL')
        source=self.required(b,'source_ref')
        source_version=self.required(b,'source_version')
        rid='res-'+secrets.token_hex(10)
        summary=self.required(b,'summary')
        c.execute('''INSERT INTO action_results
          (id,action_id,project_id,outcome,summary,source_ref,actor,created_at,source_version)
          VALUES(?,?,?,?,?,?,?,?,?)''',(rid,aid,agent['project_id'],outcome,summary,source,agent['id'],stamp(),source_version))
        eid='evidence-'+secrets.token_hex(10)
        evidence_title=str(b.get('evidence_title') or action['goal']).strip()[:200]
        c.execute('''INSERT INTO evidence
          (id,project_id,action_id,task_id,status,title,summary,source_ref,source_version,artifact_path,provenance,actor,created_at,supersedes_id,invalidated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
          (eid,agent['project_id'],aid,action['task_id'],outcome,evidence_title,summary,source,source_version,
           str(b.get('artifact_path') or ''),str(b.get('provenance') or ''),agent['id'],stamp(),None,None))
        c.execute('UPDATE actions SET status=?,updated_at=?,version=version+1 WHERE id=?',('finished',stamp(),aid))
        c.execute('UPDATE agents SET current_action=NULL WHERE id=?',(agent['id'],))
        events=[
            event(c,agent['project_id'],agent['id'],'result.'+outcome.lower(),summary,'result',rid,
                  after={'outcome':outcome,'source_ref':source,'source_version':source_version,'verification_status':'UNVERIFIED'},action_id=aid,importance='high'),
            event(c,agent['project_id'],agent['id'],'evidence.added',evidence_title,'evidence',eid,
                  after={'status':outcome,'source_ref':source,'source_version':source_version,'verification_status':'UNVERIFIED'},action_id=aid,importance='high'),
            event(c,agent['project_id'],agent['id'],'agent.finish','Action 交付完成：'+action['goal'],'action',aid,
                  before={'status':action['status']},after={'status':'finished'},reason='result '+rid+' 已自动登记依据；结果未独立核验',action_id=aid,importance='high')]
        return {'ok':True,'result_id':rid,'evidence_id':eid,'outcome':outcome,'action_id':aid,
                'delivery_status':'finished','result_status':RESULT_STATUS[outcome],
                'scientific_status':outcome,'normalized_status':RESULT_STATUS[outcome],
                'verification_status':'UNVERIFIED'},events

    def add_evidence(self,c,agent,b):
        status=str(b.get('status') or '').upper()
        if status not in set(RESULT_STATUS) | {'ONGOING','NOT_RUN'}:
            raise GatewayError('证据状态不正确')
        if b.get('supersedes_id') or b.get('invalidated_at'):
            raise GatewayError('替代或失效依据需人审；原依据不可覆盖',403)
        aid=self.required(b,'action_id')
        action=self.action_for(c,agent,aid)
        if action['status'] not in ('claimed','running','result_reported','finished'):
            raise GatewayError('Evidence 必须来自明确 Action',409)
        title=self.required(b,'title'); source=self.required(b,'source_ref')
        source_version=self.required(b,'source_version')
        eid='evidence-'+secrets.token_hex(10)
        row=(eid,agent['project_id'],aid,str(b.get('task_id') or ''),status,title,self.required(b,'summary'),
             source,source_version,str(b.get('artifact_path') or ''),
             str(b.get('provenance') or ''),agent['id'],stamp(),None,None)
        c.execute('''INSERT INTO evidence
          (id,project_id,action_id,task_id,status,title,summary,source_ref,source_version,artifact_path,provenance,actor,created_at,supersedes_id,invalidated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',row)
        ev=event(c,agent['project_id'],agent['id'],'evidence.added',title,'evidence',eid,
                 after={'status':status,'source_ref':source,'source_version':row[8]},action_id=aid,importance='high')
        return {'ok':True,'evidence_id':eid,'status':status,'verification_status':'UNVERIFIED'},ev

    def add_artifact(self,c,agent,b):
        aid=self.required(b,'action_id')
        action=self.action_for(c,agent,aid)
        if action['status'] not in ('claimed','running','result_reported','finished'):
            raise GatewayError('Artifact 必须来自明确 Action',409)
        kind=str(b.get('type') or 'other').lower()
        if kind not in ARTIFACT_TYPES:
            raise GatewayError('Artifact type 不支持')
        title=self.required(b,'title')
        reference=self.required(b,'reference')
        source_version=self.required(b,'source_version')
        artifact_id='artifact-'+secrets.token_hex(10)
        c.execute('''INSERT INTO artifacts
          (id,project_id,action_id,type,title,reference,source_version,summary,agent_id,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?)''',
          (artifact_id,agent['project_id'],aid,kind,title,reference,source_version,
           str(b.get('summary') or '')[:2000],agent['id'],stamp()))
        ev=event(c,agent['project_id'],agent['id'],'artifact.added',title,'artifact',artifact_id,
                 after={'type':kind,'reference':reference,'source_version':source_version},action_id=aid,importance='high')
        return {'ok':True,'artifact_id':artifact_id,'type':kind,'action_id':aid},ev

    def task(self,c,agent,b):
        if b.get('ifRev') is None: raise GatewayError('创建任务必须提供 ifRev')
        action_id=self.required(b,'action_id')
        action=self.action_for(c,agent,action_id)
        if action['status'] not in ('claimed','running'):
            raise GatewayError('创建任务必须来自正在执行的 Action',409)
        state=self.state(c)
        title=self.required(b,'title')
        tid='task-'+secrets.token_hex(10)
        t={'id':tid,'project':agent['project_id'],'title':title,'status':'待开始','priority':str(b.get('priority') or 'P2'),
           'stage':str(b.get('stage') or ''),'start':'','end':'','completed':'','milestone':False,
           'note':'','parent':'','deps':list(b.get('deps') or []),'updated_at':stamp()}
        state['tasks'].append(t)
        self.validate(state)
        rev=self.get_rev(c)
        if b.get('ifRev') is not None and int(b['ifRev'])!=rev:
            event(c,agent['project_id'],agent['id'],'task.conflict','Agent 创建任务版本冲突','task',tid,payload={'requested_rev':b['ifRev'],'current_rev':rev})
            raise GatewayError('状态版本冲突，请重新读取',409)
        old=c.execute('SELECT body FROM state WHERE id=1').fetchone()[0]
        c.execute('UPDATE state SET body=? WHERE id=1',(encoded(state),))
        new_rev=self.bump_rev(c)
        ev=event(c,agent['project_id'],agent['id'],'task.created',title,'task',tid,after=t,reason=str(b.get('reason') or ''),action_id=str(b.get('action_id') or ''))
        return {'ok':True,'task':t,'rev':new_rev},ev

    def patch_task(self,agent,tid,b):
        self.require(agent,'EXECUTE')
        if b.get('ifRev') is None: raise GatewayError('PATCH 任务必须提供 ifRev',400)
        action_id=self.required(b,'action_id')
        allowed={'title','status','priority','stage','start','end','completed','deps','parent'}
        changes=b.get('changes')
        if not isinstance(changes,dict) or not changes: raise GatewayError('缺少 changes')
        if set(changes)-allowed:
            raise GatewayError('受保护字段需走 Proposal + 人审；Agent 不可覆盖人写笔记或已记录结论',403)
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            project_backup.history(c,agent['id'],'Agent 更新任务')
            action=self.action_for(c,agent,action_id)
            if action['status'] not in ('claimed','running'):
                raise GatewayError('任务更新必须来自正在执行的 Action',409)
            rev=self.get_rev(c)
            if int(b['ifRev'])!=rev:
                # Conflict is returned, never silently overwrite. A retry can be audited after reread.
                raise GatewayError('状态版本冲突，请重新读取',409)
            state=self.state(c)
            task=next((t for t in state['tasks'] if t['id']==tid and t['project']==agent['project_id']),None)
            if not task: raise GatewayError('任务不存在',404)
            before=dict(task)
            task.update(changes)
            task['updated_at']=stamp()
            self.validate(state)
            old=c.execute('SELECT body FROM state WHERE id=1').fetchone()[0]
            c.execute('UPDATE state SET body=? WHERE id=1',(encoded(state),))
            new_rev=self.bump_rev(c)
            kind='task.completed' if changes.get('status')=='已完成' else 'task.blocked' if changes.get('status')=='受阻' else 'task.updated'
            ev=event(c,agent['project_id'],agent['id'],kind,task['title'],'task',tid,before=before,after=task,
                     reason=self.required(b,'reason'),action_id=action_id,importance='high' if kind!='task.updated' else 'normal')
            self.snapshot(c)
        return {'ok':True,'task':task,'rev':new_rev},ev

    def decision_request(self,c,agent,b):
        did='decision-'+secrets.token_hex(10)
        question=self.required(b,'question')
        options=b.get('options') or []
        if not isinstance(options,list) or len(options)<2:
            raise GatewayError('需要至少两个选项')
        c.execute('INSERT INTO decision_requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (did,agent['project_id'],question,self.required(b,'context'),encoded(options),str(b.get('impact') or ''),
                   int(bool(b.get('blocking'))),'pending',str(b.get('action_id') or ''),agent['id'],stamp(),None,None))
        ev=event(c,agent['project_id'],agent['id'],'decision.requested',question,'decision',did,
                 payload={'options':options,'blocking':bool(b.get('blocking'))},action_id=str(b.get('action_id') or ''),importance='high')
        return {'ok':True,'decision_id':did,'status':'pending'},ev

    def human_resolve(self,did,b):
        resolution=self.required(b,'resolution')
        if str(b.get('status')) not in ('approved','rejected'):
            raise GatewayError('人类决定必须 approved 或 rejected')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=one(c,'SELECT * FROM decision_requests WHERE id=?',(did,))
            if not old: raise GatewayError('决定请求不存在',404)
            if old['status']!='pending': raise GatewayError('该请求已处理',409)
            project_backup.history(c,'human','处理项目决定')
            self.bump_rev(c)
            c.execute('UPDATE decision_requests SET status=?,resolved_at=?,resolution=? WHERE id=?',
                      (b['status'],stamp(),resolution,did))
            ev=event(c,old['project_id'],'human','decision.'+b['status'],old['question'],'decision',did,
                     before={'status':'pending'},after={'status':b['status'],'resolution':resolution},importance='high')
            self.snapshot(c)
        return {'ok':True,'decision_id':did,'status':b['status']},ev

    def recovery_view(self,c,pid,aid):
        self.project(c,pid)
        action=one(c,'SELECT * FROM actions WHERE id=? AND project_id=?',(aid,pid))
        if not action: raise GatewayError('行动不属于当前项目',404)
        action=self.public_action(c,action)
        results=all_rows(c,'SELECT * FROM action_results WHERE action_id=? AND project_id=?',(aid,pid))
        artifacts=all_rows(c,'SELECT * FROM artifacts WHERE action_id=? AND project_id=?',(aid,pid))
        reports=action['used_progress_reports']
        maximum=decoded(action['budget'],{}).get('max_progress_reports',20)
        agents=all_rows(c,"SELECT a.id,a.name,a.status,p.handshake_at FROM agents a LEFT JOIN agent_protocols p ON p.agent_id=a.id WHERE a.project_id=? AND a.permission='EXECUTE' AND (a.current_action IS NULL OR a.current_action=?)",(pid,aid))
        return {'action':action,'results':results,'artifacts':artifacts,'used_progress_reports':reports,
                'max_progress_reports':maximum,'eligible_agents':agents,
                'receipts':all_rows(c,'SELECT * FROM action_recoveries WHERE action_id=? ORDER BY created_at DESC',(aid,)),
                'source_hash':self.manager_signature(c,pid) if hasattr(self,'manager_signature') else '',
                'rev':self.get_rev(c),'authority':'只能核对登记状态；不启动工具或模型，不证明外部任务已停止或完成'}

    def human_review(self,b):
        pid=str(b.get('project_id') or '')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            self.project(c,pid)
            rev=self.get_rev(c)
            if type(b.get('ifRev')) is not int or b['ifRev']!=rev:
                raise GatewayError('记录已变化，请重新打开复核页面',409)
            receipt=result_review.prepare(c,pid,b)
            if b.get('dry'):
                result_review.save(c,receipt)
                c.rollback()
                return {'dry':True,'rev':rev,'receipt':receipt},None
            project_backup.history(c,'human','追加结果人工复核收据')
            result_review.save(c,receipt)
            ev=event(c,pid,'human','result.reviewed','人工复核：'+receipt['conclusion'],'result',receipt['result_id'],
                     payload={k:receipt[k] for k in ('id','target_hash','source_assessment','review_kind','criteria','reviewer','conclusion','notes','scientific_status')},
                     reason='只追加所查版本与人工结论；原结果、负记录和UNVERIFIED不变',importance='high')
            rev=self.bump_rev(c);self.snapshot(c)
        return {'rev':rev,'receipt':receipt,'verification_status':'UNVERIFIED','scientific_status':'NOT_ASSESSED'},ev

    def human_recover(self,b):
        pid=str(b.get('project_id') or '');aid=str(b.get('action_id') or '')
        operation=b.get('operation')
        if operation not in ('mark_interrupted','continue','close_unknown','reconcile_completed'):
            raise GatewayError('不支持的对账操作')
        if b.get('consent')!='human-action-recovery-v1' or b.get('external_work_stopped') is not True:
            raise GatewayError('须确认已核对并停止原外部执行；研序不会代为终止宿主进程')
        summary=self.required(b,'summary')
        checked=b.get('checked_records')
        if not isinstance(checked,list) or len(checked)>100 or any(not isinstance(x,str) for x in checked):
            raise GatewayError('核对记录须为所查看的成果/结果ID列表')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            view=self.recovery_view(c,pid,aid);action=view['action']
            if (type(b.get('ifRev')) is not int or b['ifRev']!=view['rev']
                    or type(b.get('action_version')) is not int or b['action_version']!=action['version']
                    or b.get('contract_hash')!=action['contract_hash'] or b.get('source_hash')!=view['source_hash']):
                raise GatewayError('行动、契约或来源已变化，请重新核对',409)
            available={r['id'] for r in view['results']+view['artifacts']}
            if len(set(checked))!=len(checked) or any(x not in available for x in checked):
                raise GatewayError('核对项缺失或不属于原行动',409)
            if available-set(checked):
                raise GatewayError('须核对原行动全部已登记成果和结果；不能跳过已有交付',409)
            if not available and b.get('checked_no_registered_output') is not True:
                raise GatewayError('尚无登记产物，须明确记录外部执行仍未知')
            if action['status'] not in ('claimed','running','result_reported','interrupted'):
                raise GatewayError('行动已结束，不可重放或重新接管',409)
            if str(action['agent_id'] or '').startswith('manager-agent-'):
                raise GatewayError('管理执行器仍走原中断回执，不经外部Agent接管',409)
            if view['results'] and operation!='reconcile_completed':
                raise GatewayError('已有结果；只能核对原交付完成，不得重跑',409)
            if operation=='reconcile_completed' and not view['results']:
                raise GatewayError('尚未登记结果，不能声明原交付已完成',409)
            target=None
            if operation=='continue':
                target=one(c,'SELECT a.*,p.handshake_at FROM agents a LEFT JOIN agent_protocols p ON p.agent_id=a.id WHERE a.id=? AND a.project_id=?',(b.get('to_agent_id'),pid))
                if not target or target['permission']!='EXECUTE' or not target['handshake_at']:
                    raise GatewayError('接续Agent须属于当前项目、可执行并已读取get_context',409)
                if one(c,"SELECT id FROM actions WHERE agent_id=? AND id<>? AND status IN ('claimed','running','result_reported')",(target['id'],aid)):
                    raise GatewayError('接续Agent已有活跃行动',409)
                # No claim or new budget: the same action and original progress
                # events are retained. Legacy missing terms are never invented.
                if not action['success_condition'] or not action['failure_condition'] or not action['stop_condition']:
                    raise GatewayError('旧契约缺判据，不能补写后冒充原授权；请先保留未知交接',409)
            new_status={'mark_interrupted':'interrupted','continue':'claimed','close_unknown':'interrupted','reconcile_completed':'finished'}[operation]
            rid='recovery-'+secrets.token_hex(10)
            receipt={'id':rid,'project_id':pid,'action_id':aid,'operation':operation,'from_agent':action['agent_id'],
                     'to_agent':target['id'] if target else None,'action_version':action['version'],
                     'contract_hash':action['contract_hash'],'context_hash':view['source_hash'],
                     'checked_records':checked,'summary':summary,'scientific_status':'UNKNOWN','status':new_status}
            if b.get('dry'):return dict(receipt,dry=True,rev=view['rev']),None
            project_backup.history(c,'human','核对中断行动：'+operation)
            c.execute('INSERT INTO action_recoveries VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                      (rid,pid,aid,operation,action['agent_id'],target['id'] if target else None,action['version'],
                       action['contract_hash'],view['source_hash'],encoded(checked),summary,stamp()))
            c.execute('UPDATE agents SET current_action=NULL WHERE id=? AND current_action=?',(action['agent_id'],aid))
            c.execute('UPDATE actions SET status=?,agent_id=?,version=version+1,updated_at=? WHERE id=?',
                      (new_status,target['id'] if target else action['agent_id'],stamp(),aid))
            if target:c.execute('UPDATE agents SET current_action=? WHERE id=?',(aid,target['id']))
            # close_unknown closes delivery without creating an invented result.
            if operation=='close_unknown':c.execute("UPDATE actions SET status='failed' WHERE id=?",(aid,));receipt['status']='failed'
            ev=event(c,pid,'human','action.reconciled',summary,'action',aid,
                     before={'status':action['status'],'agent_id':action['agent_id']},
                     after={'status':receipt['status'],'agent_id':target['id'] if target else action['agent_id']},
                     payload=receipt,reason='人工对账；无工具执行、无模型调用，不重置预算或科学核验',action_id=aid,importance='high')
            receipt['rev']=self.bump_rev(c);self.snapshot(c)
        return receipt,ev

    def today(self,c,pid):
        state=self.state(c)
        if not pid and state['projects']: pid=state['projects'][0]['id']
        p=next((x for x in state['projects'] if x['id']==pid),None)
        if not p: return {'project':None,'pulse':'Waiting','sentence':'尚未选择项目。','events':[],'action':None,'decision':None}
        actions=all_rows(c,'SELECT * FROM actions WHERE project_id=? ORDER BY updated_at DESC LIMIT 12',(pid,))
        current=next((a for a in actions if a['status'] in ('claimed','running','result_reported')),None)
        last_progress=one(c,"SELECT summary,timestamp FROM project_events WHERE source_action=? AND type='agent.progress' ORDER BY seq DESC LIMIT 1",(current['id'],)) if current else None
        current_agent=one(c,'SELECT last_seen FROM agents WHERE id=?',(current['agent_id'],)) if current else None
        connected=bool(current_agent and self.is_live(current_agent))
        decisions=[dict(self.public_decision(x), source='request') for x in all_rows(c,"SELECT * FROM decision_requests WHERE project_id=? AND status='pending' ORDER BY created_at DESC LIMIT 8",(pid,))]
        decisions.extend(dict(d,source='legacy',question=d.get('question') or d.get('title') or '',
                              context=d.get('recommendation') or '',blocking=True)
                         for d in state['decisions'] if d['project']==pid and d.get('status')!='已决')
        evidence=all_rows(c,'SELECT id,title,status,summary,source_ref,created_at FROM evidence WHERE project_id=? ORDER BY created_at DESC LIMIT 5',(pid,))
        events=[self.public_event(x) for x in all_rows(c,'SELECT * FROM project_events WHERE project_id=? AND importance=? ORDER BY seq DESC LIMIT 8',(pid,'high'))]
        tasks=[t for t in state['tasks'] if t['project']==pid]
        blocked=next((t for t in sorted(tasks,key=lambda item:({'P0':0,'P1':1,'P2':2,'P3':3}.get(item.get('priority'),2),item.get('title',''))) if t.get('status')=='受阻'),None)
        focus=self.focus_status(pid).get('focus')
        if not focus:
            global_focus=self.focus_status('global').get('focus')
            if global_focus and global_focus.get('project_id')==pid:
                focus=global_focus
        pulse='Needs Decision' if any(d['blocking'] for d in decisions) else 'Waiting' if current and not connected else 'Advancing' if current and current['status'] in ('claimed','running') else 'Reviewing' if current and current['status']=='result_reported' else 'Blocked' if blocked else 'Waiting'
        sentence=(current['goal']+'；Agent 最近未通信，Action 保留原状态，等待重连或人工处理。') if current and not connected else (current['goal']+'；当前由 Agent 执行，结果仍需依据来源和版本核验。') if current else ('存在待处理的人类决定；受影响的方向须在裁决后推进。' if decisions else ('当前存在受阻事项；当前建议：'+focus['title']+'。尚未有 Agent 认领。') if blocked and focus else '没有正在执行的 Agent Action；请查看现有行动和依据，确定下一步。')
        critical=decisions[0]['question'] if decisions else (current['goal'] if current else (focus['title'] if focus else blocked['title'] if blocked else '当前最关键的开放问题尚未明确记录'))
        next_step='处理待决定事项，并明确受影响行动的下一步。' if decisions else (current['expected_output'] if current else (focus['expected_output'] if focus else '查看当前重点，并将其转成有边界的 Action。'))
        narrative=''.join([('最近记录：'+events[0]['summary']+'。') if events else '尚无结构化项目事件。',
                           ('当前：'+current['goal']+'。') if current else '当前没有运行中的 Agent Action。',
                           ('待决定：'+decisions[0]['question']+'。') if decisions else ''])
        why=current['why_now'] if current else (focus.get('reason','') if focus else '此问题阻塞当前行动。' if blocked else '依据当前显式记录；不自动推断未核验结论。')
        return {'project':{'id':pid,'name':p['name'],'description':p.get('description') or '',
                           'goal':p.get('goal') or '', 'current_state':p.get('current_state') or ''},
                'pulse':pulse,'sentence':sentence,
                'where_are_we':((p.get('current_state') or '').rstrip('。；; ')+'；'+sentence) if p.get('current_state') else sentence,
                'what_is_happening':(current['goal'] if current and connected else 'Agent 最近未通信；Action 等待重连或人工处理。' if current else '当前没有运行中的 Agent Action。'),
                'what_changed':events[0]['summary'] if events else '尚无结构化重要事件。',
                'what_next':next_step,
                'what_needs_me':decisions[0]['question'] if decisions else '当前没有待处理的人类决定。',
                'critical_question':critical,'why':why,
                'next_step':next_step,'action':current,'action_agent_connected':connected,'last_progress':last_progress,'decision':decisions[0] if decisions else None,
                'decisions':decisions,'recent_evidence':evidence,'events':events,'narrative':narrative,
                'focus':focus}

    def graph(self,c,pid):
        state=self.state(c)
        if not pid and state['projects']: pid=state['projects'][0]['id']
        p=next((x for x in state['projects'] if x['id']==pid),None)
        if not p: return {'nodes':[],'edges':[]}
        nodes=[{'id':'goal:'+pid,'type':'Goal','label':p.get('goal') or p['name']}]
        edges=[]
        tasks=[t for t in state['tasks'] if t['project']==pid][:60]
        for t in tasks:
            nodes.append({'id':'task:'+t['id'],'type':'Task','label':t['title'],'status':t.get('status')})
            edges.append({'from':'goal:'+pid,'to':'task:'+t['id'],'type':'derived_from'})
            for dep in t.get('deps') or []: edges.append({'from':'task:'+dep,'to':'task:'+t['id'],'type':'depends_on'})
        for a in all_rows(c,'SELECT id,task_id,goal,status FROM actions WHERE project_id=? ORDER BY updated_at DESC LIMIT 30',(pid,)):
            nodes.append({'id':'action:'+a['id'],'type':'Action','label':a['goal'],'status':a['status']})
            if a['task_id']: edges.append({'from':'task:'+a['task_id'],'to':'action:'+a['id'],'type':'derived_from'})
        for e in all_rows(c,'SELECT id,action_id,title,status FROM evidence WHERE project_id=? ORDER BY created_at DESC LIMIT 30',(pid,)):
            nodes.append({'id':'evidence:'+e['id'],'type':'Evidence','label':e['title'],'status':e['status']})
            if e['action_id']: edges.append({'from':'action:'+e['action_id'],'to':'evidence:'+e['id'],'type':'supports' if RESULT_STATUS.get(e['status'])=='success' else 'contradicts' if RESULT_STATUS.get(e['status'])=='failure' else 'derived_from'})
        for a in all_rows(c,'SELECT id,action_id,title,type FROM artifacts WHERE project_id=? ORDER BY created_at DESC LIMIT 30',(pid,)):
            nodes.append({'id':'artifact:'+a['id'],'type':'Artifact','label':a['title'],'status':a['type']})
            edges.append({'from':'action:'+a['action_id'],'to':'artifact:'+a['id'],'type':'produced'})
        for d in all_rows(c,'SELECT id,action_id,question,status FROM decision_requests WHERE project_id=? ORDER BY created_at DESC LIMIT 20',(pid,)):
            nodes.append({'id':'decision:'+d['id'],'type':'Decision','label':d['question'],'status':d['status']})
            if d['action_id']: edges.append({'from':'action:'+d['action_id'],'to':'decision:'+d['id'],'type':'blocks' if d['status']=='pending' else 'derived_from'})
        return {'nodes':nodes,'edges':edges,'scope':'recorded_relationships_only'}
