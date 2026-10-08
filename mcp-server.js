#!/usr/bin/env node
// 研序 MCP stdio server —— 零依赖，供 ZCode 等 MCP 客户端操作本机研序应用
const fs = require('fs'), path = require('path'), http = require('http'), os = require('os');
const DATA_DIR = process.env.RESEARCH_DESK_DATA_DIR || (process.platform === 'win32'
  ? path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local'), 'ResearchDesk')
  : process.platform === 'darwin' ? path.join(os.homedir(), 'Library', 'Application Support', 'ResearchDesk')
  : path.join(process.env.XDG_DATA_HOME || path.join(os.homedir(), '.local', 'share'), 'ResearchDesk'));
const AGENT_MODE = Boolean(process.env.RESEARCH_DESK_AGENT_TOKEN);
const TOKEN = process.env.RESEARCH_DESK_AGENT_TOKEN || fs.readFileSync(path.join(DATA_DIR, 'api-token'), 'utf8').trim();
const BASE = process.env.RESEARCH_DESK_BASE_URL || 'http://127.0.0.1:8765';
const timeoutValue = Number(process.env.RESEARCH_DESK_HTTP_TIMEOUT_MS || 15000);
const HTTP_TIMEOUT = Number.isFinite(timeoutValue) && timeoutValue > 0 ? timeoutValue : 15000;
const REVIEW_OUTPUT = {type:'object',additionalProperties:false,
  properties:Object.fromEntries(['recommendation','alternatives','tradeoffs','disagreements','unknowns','next_step','recheck_conditions'].map(k=>[k,{type:'string'}])),
  required:['recommendation','alternatives','tradeoffs','disagreements','unknowns','next_step','recheck_conditions','citations']};
REVIEW_OUTPUT.properties.citations={type:'array',maxItems:24,items:{type:'object',additionalProperties:false,
  properties:{claim:{type:'string'},material_id:{type:'string'},locator:{type:'string'},relation:{type:'string',enum:['source','inference','unknown']}},
  required:['claim','material_id','locator','relation']}};

function api(p, method, body) {
  return new Promise((res, rej) => {
    const payload = body === undefined ? null : JSON.stringify(body);
    const headers = { Authorization: 'Bearer ' + TOKEN, 'Content-Type': 'application/json' };
    if (payload !== null) headers['Content-Length'] = Buffer.byteLength(payload);
    const req = http.request(BASE + p, { method: method || 'GET', headers }, r => {
      r.on('aborted', () => rej(new Error('研序响应中断；写入可能已完成，请先读取记录再重试')));
      let b = ''; r.on('data', c => b += c);
      r.on('end', () => { const rev = Number(r.headers['x-rev'] || 0); try { res({ status: r.statusCode, json: JSON.parse(b), rev }); } catch (e) { res({ status: r.statusCode, json: { raw: b }, rev }); } });
    });
    req.setTimeout(HTTP_TIMEOUT, () => req.destroy(new Error('研序请求超时；写入可能已完成，请先读取记录再重试')));
    req.on('error', rej);
    if (payload !== null) req.write(payload);
    req.end();
  });
}
const slim = s => ({ projects: s.projects.map(p => ({ id: p.id, name: p.name, stages: p.stages })), tasks: s.tasks.map(t => ({ id: t.id, project: t.project, title: t.title, priority: t.priority, status: t.status, stage: t.stage, start: t.start, end: t.end, completed: t.completed, milestone: !!t.milestone, parent: t.parent || '', deps: t.deps || [] })), decisions: s.decisions.length });
const brief = s => {
  const t0 = new Date().toISOString().slice(0, 10);
  const mon = addD(t0, -((new Date(t0 + 'T00:00:00').getDay() + 6) % 7)), sun = addD(mon, 6);
  const pn = id => (s.projects.find(p => p.id === id) || {}).name || id;
  const pick = list => list.map(t => ({ id: t.id, project: pn(t.project), title: t.title, priority: t.priority, status: t.status, end: t.end }));
  const f = fn => s.tasks.filter(fn);
  return {
    本周截止: pick(f(t => t.end >= mon && t.end <= sun && t.status !== '已完成')),
    已逾期: pick(f(t => t.end && t.end < t0 && t.status !== '已完成')),
    进行中: s.tasks.filter(t => t.status === '进行中').length,
    本周已完成: f(t => t.completed >= mon && t.completed <= sun).length
  };
};
function addD(iso, n) { const d = new Date(iso + 'T00:00:00'); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); }

const TASK_FIELDS = 'project(必填,项目id),title(必填),priority(P0-P3,默认P2),status(待开始/进行中/受阻/已完成),stage,start,end(YYYY-MM-DD),completed,milestone(bool),note,parent(父任务id),deps(依赖id数组)';
const PROJECT_FIELDS = 'id(更新时提供),name(必填),description,goal,success_definition,current_state,constraints(文本数组),workspace,type,stages(阶段名称数组)';
const DECISION_FIELDS = 'id(更新时提供),project(必填),title(必填),question,recommendation,status(待决/讨论中/已决),owner,due,outcome';
const LEGACY_TOOLS = [
  { name: 'research_state', description: '读取研序完整状态（项目/任务/决策；不含资料索引大数组）', inputSchema: { type: 'object', properties: {}, additionalProperties: false } },
  { name: 'research_project_upsert', description: '兼容工具：创建或更新项目。' + PROJECT_FIELDS, inputSchema: { type: 'object', properties: { id: { type: 'string' }, name: { type: 'string' }, description: { type: 'string' }, goal: { type: 'string' }, success_definition: { type: 'string' }, current_state: { type: 'string' }, constraints: { type: 'array', items: { type: 'string' } }, workspace: { type: 'string' }, type: { type: 'string' }, stages: { type: 'array', items: { type: 'string' } } }, required: ['name'] } },
  { name: 'research_project_delete', description: '删除项目并级联清理任务/资料/决策。高风险操作，必须显式 confirm=true。', inputSchema: { type: 'object', properties: { id: { type: 'string' }, confirm: { type: 'boolean' } }, required: ['id','confirm'] } },
  { name: 'research_task_find', description: '按关键字/状态/项目过滤任务', inputSchema: { type: 'object', properties: { q: { type: 'string', description: '标题/备注/阶段模糊匹配' }, status: { type: 'string' }, project: { type: 'string', description: '项目 id 或名称片段' } }, required: [] } },
  { name: 'research_task_upsert', description: '创建或更新任务。' + TASK_FIELDS, inputSchema: { type: 'object', properties: { id: { type: 'string' }, project: { type: 'string' }, title: { type: 'string' }, priority: { type: 'string' }, status: { type: 'string' }, stage: { type: 'string' }, start: { type: 'string' }, end: { type: 'string' }, note: { type: 'string' }, milestone: { type: 'boolean' }, parent: { type: 'string' }, deps: { type: 'array', items: { type: 'string' } } }, required: ['project', 'title'] } },
  { name: 'research_task_delete', description: '删除任务（自动清理子任务与依赖引用）', inputSchema: { type: 'object', properties: { id: { type: 'string' } }, required: ['id'] } },
  { name: 'research_decision_upsert', description: '创建或更新决策节点。' + DECISION_FIELDS, inputSchema: { type: 'object', properties: { id: { type: 'string' }, project: { type: 'string' }, title: { type: 'string' }, question: { type: 'string' }, recommendation: { type: 'string' }, status: { type: 'string' }, owner: { type: 'string' }, due: { type: 'string' }, outcome: { type: 'string' } }, required: ['project','title'] } },
  { name: 'research_decision_delete', description: '删除决策节点', inputSchema: { type: 'object', properties: { id: { type: 'string' } }, required: ['id'] } },
  { name: 'research_batch', description: '批量操作，ops 数组每项 {collection,item} 或 {collection,op:"delete",id}；collection ∈ projects/tasks/decisions/files', inputSchema: { type: 'object', properties: { ops: { type: 'array', items: { type: 'object' } } }, required: ['ops'] } },
  { name: 'research_week_brief', description: '跨项目聚合：本周截止/已逾期/进行中/本周已完成', inputSchema: { type: 'object', properties: {}, additionalProperties: false } },
  { name: 'research_agent_brief', description: 'Agent 接管项目时的压缩上下文：项目、重点任务、待决事项和最近 Agent 变更。', inputSchema: { type: 'object', properties: {}, additionalProperties: false } },
  { name: 'research_history', description: '最近 60 次保存快照摘要', inputSchema: { type: 'object', properties: {}, additionalProperties: false } },
  { name: 'research_rollback', description: '恢复到指定历史时间点（高风险；当前状态先入历史；必须 confirm=true）', inputSchema: { type: 'object', properties: { id: { type: 'number' }, confirm: { type: 'boolean' } }, required: ['id','confirm'] } }
];
const AGENT_TOOLS = [
  { name:'research.get_project_context', description:'连接握手并读取压缩项目上下文；开始工作前必须调用', inputSchema:{type:'object',properties:{}} },
  { name:'research.get_current_focus', description:'读取当前 Planner 建议；建议不是执行授权', inputSchema:{type:'object',properties:{}} },
  { name:'research.get_tasks', description:'读取当前项目任务', inputSchema:{type:'object',properties:{}} },
  { name:'research.get_task', description:'按 ID 读取任务', inputSchema:{type:'object',properties:{id:{type:'string'}},required:['id']} },
  { name:'research.get_recent_events', description:'读取最近结构化项目事件', inputSchema:{type:'object',properties:{}} },
  { name:'research.get_evidence', description:'读取保留负结果的证据账本', inputSchema:{type:'object',properties:{}} },
  { name:'research.get_decisions', description:'读取决策请求与旧决策记录', inputSchema:{type:'object',properties:{}} },
  { name:'research.get_open_questions', description:'读取未决问题', inputSchema:{type:'object',properties:{}} },
  { name:'research.get_blockers', description:'读取阻塞任务', inputSchema:{type:'object',properties:{}} },
  { name:'research.get_actions', description:'读取 Action 与执行状态', inputSchema:{type:'object',properties:{}} },
  { name:'research.claim_action', description:'兼容工具：认领现有任务为有边界 Action', inputSchema:{type:'object',properties:{task_id:{type:'string'},reason:{type:'string'},expected_output:{type:'string'},goal:{type:'string'},success_condition:{type:'string'},failure_condition:{type:'string'},budget:{type:'object'},stop_condition:{type:'string'}},required:['task_id','reason','expected_output']} },
  { name:'research.report_activity', description:'报告 Action start/progress/fail 或 heartbeat；不得包含内部思维链', inputSchema:{type:'object',properties:{action_id:{type:'string'},phase:{type:'string'},summary:{type:'string'},reason:{type:'string'}},required:['action_id','phase','summary']} },
  { name:'research.record_result', description:'兼容工具：记录来源与版本绑定的结果；自动登记未核验依据并完成 Action', inputSchema:{type:'object',properties:{action_id:{type:'string'},outcome:{type:'string'},summary:{type:'string'},source_ref:{type:'string'},source_version:{type:'string'},evidence_title:{type:'string'},artifact_path:{type:'string'},provenance:{type:'string'}},required:['action_id','outcome','summary','source_ref','source_version']} },
  { name:'research.add_evidence', description:'从明确 Action 补充未独立核验证据；不覆盖或删除旧证据', inputSchema:{type:'object',properties:{action_id:{type:'string'},task_id:{type:'string'},title:{type:'string'},summary:{type:'string'},status:{type:'string'},source_ref:{type:'string'},source_version:{type:'string'},artifact_path:{type:'string'},provenance:{type:'string'}},required:['action_id','title','summary','status','source_ref','source_version']} },
  { name:'research.propose_task', description:'兼容工具：提出任务或方向提案，不直接执行', inputSchema:{type:'object',properties:{title:{type:'string'},body:{type:'string'},kind:{type:'string'},action_id:{type:'string'}},required:['title','body']} },
  { name:'research.create_task', description:'从明确 Action 创建普通任务，保留旧任务视图兼容', inputSchema:{type:'object',properties:{title:{type:'string'},priority:{type:'string'},stage:{type:'string'},deps:{type:'array',items:{type:'string'}},ifRev:{type:'number'},reason:{type:'string'},action_id:{type:'string'}},required:['title','ifRev','action_id']} },
  { name:'research.update_task', description:'兼容工具：从明确 Action 按 rev 更新允许的任务字段；冲突返回错误，保护人写笔记和已记录结论', inputSchema:{type:'object',properties:{id:{type:'string'},ifRev:{type:'number'},changes:{type:'object'},reason:{type:'string'},action_id:{type:'string'}},required:['id','ifRev','changes','reason','action_id']} },
  { name:'research.request_human_decision', description:'提出需人类裁决的问题与备选项', inputSchema:{type:'object',properties:{question:{type:'string'},context:{type:'string'},options:{type:'array',items:{type:'string'}},impact:{type:'string'},blocking:{type:'boolean'},action_id:{type:'string'}},required:['question','context','options']} },
  { name:'research.finish_action', description:'兼容性确认：result 已自动结束 Action；重复 finish 幂等', inputSchema:{type:'object',properties:{action_id:{type:'string'},summary:{type:'string'}},required:['action_id','summary']} }
];
const PROJECT_TOOLS = [
  {name:'project.get_discussion_requests',description:'读取本 Agent 被分配的讨论请求与冻结上下文；仅提出建议，不构成执行项目任务的授权。先 project.get_context 握手。',inputSchema:{type:'object',properties:{}}},
  {name:'project.reply_discussion',description:'回复人启动的当前讨论轮次，保存 UNVERIFIED 建议；不能代其他 Agent 回复或采纳为决策。',inputSchema:{type:'object',properties:{room_id:{type:'string'},participant_id:{type:'string'},run_id:{type:'string'},output:{type:'object',properties:{position:{type:'string'},evidence:{type:'string'},objections:{type:'string'},next_step:{type:'string'}},required:['position','evidence','objections','next_step'],additionalProperties:false}},required:['room_id','participant_id','run_id','output'],additionalProperties:false}},
  {name:'project.get_radar_alerts',description:'读取当前项目的来源变化记录；文字变化不证明项目结论失效，保留来源前后版本及待复核状态。',inputSchema:{type:'object',properties:{}}},
  {name:'project.reply_review',description:'提交获准的方案评审简报；只引用请求中的材料 ID 与实际行号。来源定位不等于事实核验，不自动采纳或执行。',inputSchema:{type:'object',additionalProperties:false,properties:{room_id:{type:'string'},participant_id:{type:'string'},run_id:{type:'string'},output:REVIEW_OUTPUT},required:['room_id','participant_id','run_id','output']}},
  {name:'project.get_context',description:'连接握手，读取包含目标、状态、重点、行动、成果、依据、结果、决定与权限的 Project Context',inputSchema:{type:'object',properties:{}}},
  {name:'project.claim_management_action',description:'按ID原子领取人已批准且来源有效的只读核查行动；契约不可改写。先读取 get_context.management.ready_handoffs。返回已有同Agent领取结果可安全重试。不是实验授权。',inputSchema:{type:'object',properties:{handoff_id:{type:'integer'}},required:['handoff_id']}},
  {name:'project.get_state',description:'读取当前项目记录状态与阻塞计数',inputSchema:{type:'object',properties:{}}},
  {name:'project.get_focus',description:'读取当前重点；建议不是执行授权',inputSchema:{type:'object',properties:{}}},
  {name:'project.get_actions',description:'读取 Agent Action',inputSchema:{type:'object',properties:{}}},
  {name:'project.get_artifacts',description:'读取显式成果与旧文件索引，二者分别标注',inputSchema:{type:'object',properties:{}}},
  {name:'project.get_evidence',description:'读取可追溯依据，保留负结果与核验等级',inputSchema:{type:'object',properties:{}}},
  {name:'project.get_results',description:'读取原始结果状态与统一状态映射',inputSchema:{type:'object',properties:{}}},
  {name:'project.get_decisions',description:'读取待决定请求与旧决策',inputSchema:{type:'object',properties:{}}},
  {name:'project.get_events',description:'读取项目事件时间线',inputSchema:{type:'object',properties:{}}},
  {name:'project.claim_action',description:'严格认领：先get_context握手，必须当前source_hash、完整原契约/判据/预算/停止条件及本项目已存在依赖；全文不截断。recorded只核对依赖存在，all_completed才要求全完成。不是扩大执行授权。',inputSchema:{type:'object',properties:{context_hash:{type:'string'},task_id:{type:'string'},title:{type:'string'},goal:{type:'string'},reason:{type:'string',maxLength:4000},expected_output:{type:'string',maxLength:4000},success_condition:{type:'string',maxLength:4000},failure_condition:{type:'string',maxLength:4000},dependencies:{type:'array',items:{type:'string'}},dependency_policy:{type:'string',enum:['recorded','all_completed']},budget:{type:'object'},stop_condition:{type:'string',maxLength:4000}},required:['context_hash','reason','expected_output','success_condition','failure_condition','budget','stop_condition']}},
  {name:'project.report_activity',description:'报告 Action start/progress/fail/heartbeat，不提交内部思维链',inputSchema:{type:'object',properties:{action_id:{type:'string'},phase:{type:'string'},summary:{type:'string'},reason:{type:'string'}},required:['action_id','phase','summary']}},
  {name:'project.record_result',description:'记录 success/failure/partial/inconclusive/unknown 或兼容 PASS/FAIL；必须绑定来源和版本',inputSchema:{type:'object',properties:{action_id:{type:'string'},outcome:{type:'string'},summary:{type:'string'},source_ref:{type:'string'},source_version:{type:'string'},evidence_title:{type:'string'},provenance:{type:'string'}},required:['action_id','outcome','summary','source_ref','source_version']}},
  {name:'project.add_artifact',description:'从明确 Action 登记成果引用，不复制原文件',inputSchema:{type:'object',properties:{action_id:{type:'string'},type:{type:'string'},title:{type:'string'},reference:{type:'string'},source_version:{type:'string'},summary:{type:'string'}},required:['action_id','type','title','reference','source_version']}},
  {name:'project.propose_action',description:'提出新行动，等待审阅；不直接创建或执行',inputSchema:{type:'object',properties:{title:{type:'string'},body:{type:'string'},action_id:{type:'string'}},required:['title','body']}},
  {name:'project.request_decision',description:'提出需要人裁决的范围、方向或约束问题',inputSchema:{type:'object',properties:{question:{type:'string'},context:{type:'string'},options:{type:'array',items:{type:'string'}},impact:{type:'string'},blocking:{type:'boolean'},action_id:{type:'string'}},required:['question','context','options']}}
];
const TOOLS = AGENT_MODE ? [...PROJECT_TOOLS,...AGENT_TOOLS] : LEGACY_TOOLS;
async function agentApi(p, method, body) {
  const r = await api('/api/agent/' + p, method, body);
  if (r.status !== 200) throw new Error(r.json.error || 'Agent Gateway 请求失败 (' + r.status + ')');
  return r.json;
}
async function callAgent(name, a) {
  const get = p => agentApi(p, 'GET');
  if (name === 'project.get_discussion_requests') { const value=await get('ecosystem');return {requests:value.requests,warnings:value.warnings}; }
  if (name === 'project.reply_discussion') return agentApi('discussion/reply','POST',a);
  if (name === 'project.reply_review') return agentApi('discussion/reply','POST',a);
  if (name === 'project.get_radar_alerts') return {alerts:(await get('ecosystem')).alerts};
  if (name === 'project.get_context') return get('context');
  if (name === 'project.claim_management_action') return agentApi('management/claim','POST',a);
  if (name === 'project.get_state') { const c = await get('context'); return {project:c.project,current_state:c.current_state,current_focus:c.current_focus,active_actions:c.actions.filter(x => ['claimed','running','result_reported'].includes(x.status)),blockers:c.blockers,recent_results:c.results,pending_decisions:c.decisions,rev:c.rev}; }
  if (name === 'project.get_focus') return (await get('context')).current_focus;
  if (name === 'project.get_actions') return get('actions');
  if (name === 'project.get_artifacts') return get('artifacts');
  if (name === 'project.get_evidence') return get('evidence');
  if (name === 'project.get_results') return get('results');
  if (name === 'project.get_decisions') return get('decisions');
  if (name === 'project.get_events') return get('events');
  if (name === 'project.claim_action') return agentApi('activity','POST',{...a,phase:'claim',contract_mode:'strict_v2'});
  if (name === 'project.report_activity') return agentApi('activity','POST',a);
  if (name === 'project.record_result') return agentApi('result','POST',a);
  if (name === 'project.add_artifact') return agentApi('artifact','POST',a);
  if (name === 'project.propose_action') return agentApi('proposal','POST',{...a,kind:'action'});
  if (name === 'project.request_decision') return agentApi('decision-request','POST',a);
  if (name === 'research.get_project_context') return get('context');
  if (name === 'research.get_current_focus') return (await get('context')).current_focus;
  if (name === 'research.get_tasks') return get('tasks');
  if (name === 'research.get_task') { const rows = (await get('tasks')).tasks; return rows.find(t => t.id === a.id) || null; }
  if (name === 'research.get_recent_events') return get('events');
  if (name === 'research.get_evidence') return get('evidence');
  if (name === 'research.get_decisions') return get('decisions');
  if (name === 'research.get_open_questions') return (await get('context')).open_questions;
  if (name === 'research.get_blockers') return (await get('context')).blockers;
  if (name === 'research.get_actions') return get('actions');
  if (name === 'research.claim_action') return agentApi('activity','POST',{...a,phase:'claim'});
  if (name === 'research.report_activity') return agentApi('activity','POST',a);
  if (name === 'research.record_result') return agentApi('result','POST',a);
  if (name === 'research.add_evidence') return agentApi('evidence','POST',a);
  if (name === 'research.propose_task') return agentApi('proposal','POST',a);
  if (name === 'research.create_task') return agentApi('task','POST',a);
  if (name === 'research.update_task') {
    const r = await api('/api/agent/task/' + encodeURIComponent(a.id),'PATCH',a);
    if (r.status !== 200) throw new Error(r.json.error || '任务更新失败 (' + r.status + ')');
    return r.json;
  }
  if (name === 'research.request_human_decision') return agentApi('decision-request','POST',a);
  if (name === 'research.finish_action') return agentApi('activity','POST',{...a,phase:'finish'});
  throw new Error('未知 Agent 工具: ' + name);
}
async function safeAction(ops, summary) {
  const state = await api('/api/state?slim=1');
  if (state.status !== 200) throw new Error(state.json.error || '读取状态失败');
  const rev = state.rev;
  const dry = await api('/api/action', 'POST', { ops, ifRev: rev, dry: true, actor: 'agent', summary });
  if (dry.status !== 200) throw new Error(dry.json.error || '预检失败');
  const applied = await api('/api/action', 'POST', { ops, ifRev: rev, actor: 'agent', summary });
  if (applied.status !== 200) throw new Error(applied.json.error || '写入失败');
  return applied.json;
}
async function call(name, a) {
  a = a || {};
  if (AGENT_MODE) return callAgent(name, a);
  if (name === 'research_state') { const { json } = await api('/api/state?slim=1'); return slim(json); }
  if (name === 'research_project_upsert') {
    const item = Object.fromEntries(['id','name','description','goal','success_definition','current_state','constraints','workspace','type','stages'].filter(k => Object.prototype.hasOwnProperty.call(a,k)).map(k => [k,a[k]]));
    if (!item.id) delete item.id;
    const json = await safeAction([{ collection: 'projects', item }], (a.id ? '更新项目：' : '创建项目：') + item.name);
    const p = (json.projects || []).find(x => x.id === item.id || x.name === item.name) || {};
    return { ok: true, id: p.id || item.id, name: item.name };
  }
  if (name === 'research_project_delete') {
    if (a.confirm !== true) throw new Error('删除项目需要 confirm=true');
    const { json: state } = await api('/api/state?slim=1');
    const p = (state.projects || []).find(x => x.id === a.id);
    await safeAction([{ collection: 'projects', op: 'delete', id: a.id }], '删除项目：' + (p ? p.name : a.id));
    return { ok: true, id: a.id };
  }
  if (name === 'research_task_find') {
    const { json } = await api('/api/state?slim=1'); const q = (a.q || '').toLowerCase();
    return slim(json).tasks.filter(t => (!q || (t.title || '').toLowerCase().includes(q) || String(t.stage || '').toLowerCase().includes(q))
      && (!a.status || t.status === a.status)
      && (!a.project || t.project.includes(a.project) || (slim(json).projects.find(p => p.id === t.project) || { name: '' }).name.includes(a.project)));
  }
  if (name === 'research_task_upsert') {
    const item = { priority: 'P2', status: '待开始', ...a };
    const json = await safeAction([{ collection: 'tasks', item }], (a.id ? '更新任务：' : '创建任务：') + item.title);
    const nt = (json.tasks || []).find(t => (item.id && t.id === item.id) || (t.title === item.title && t.project === item.project)) || {};
    return { ok: true, id: nt.id || item.id, title: item.title };
  }
  if (name === 'research_task_delete') { await safeAction([{ collection: 'tasks', op: 'delete', id: a.id }], '删除任务：' + a.id); return { ok: true }; }
  if (name === 'research_decision_upsert') { const item = { status: '待决', ...a }; const json = await safeAction([{ collection: 'decisions', item }], (a.id ? '更新决策：' : '创建决策：') + item.title); const d = (json.decisions || []).find(x => (item.id && x.id === item.id) || (x.title === item.title && x.project === item.project)) || {}; return { ok: true, id: d.id || item.id, title: item.title }; }
  if (name === 'research_decision_delete') { await safeAction([{ collection: 'decisions', op: 'delete', id: a.id }], '删除决策：' + a.id); return { ok: true }; }
  if (name === 'research_batch') { if (a.ops.some(op => op && op.collection === 'projects' && op.op === 'delete')) throw new Error('项目删除必须使用 research_project_delete 并显式 confirm=true'); const json = await safeAction(a.ops, '批量更新 ' + a.ops.length + ' 项'); return { ok: true, projects: json.projects.length, tasks: json.tasks.length }; }
  if (name === 'research_week_brief') { const { json } = await api('/api/state?slim=1'); return brief(json); }
  if (name === 'research_agent_brief') {
    const { json: s } = await api('/api/state?slim=1');
    const { json: h } = await api('/api/history');
    const today = new Date().toISOString().slice(0, 10), pn = id => (s.projects.find(p => p.id === id) || {}).name || id;
    const active = s.tasks.filter(t => t.status !== '已完成' && (t.status === '进行中' || t.priority === 'P0')).sort((a,b) => (a.priority === 'P0' ? -1 : 0) - (b.priority === 'P0' ? -1 : 0)).slice(0, 12).map(t => ({ id:t.id, project:pn(t.project), title:t.title, priority:t.priority, status:t.status, end:t.end || '' }));
    const overdue = s.tasks.filter(t => t.end && t.end < today && t.status !== '已完成').slice(0, 12).map(t => ({ id:t.id, project:pn(t.project), title:t.title, end:t.end }));
    const pendingDecisions = (s.decisions || []).filter(d => d.status !== '已决').slice(0, 12).map(d => ({ id:d.id, project:pn(d.project), title:d.title, status:d.status, due:d.due || '' }));
    return { projects:s.projects.map(p => ({id:p.id,name:p.name,goal:p.goal || '',stages:p.stages || []})), active, overdue, pendingDecisions, recentAgentChanges:(h || []).filter(x => x.actor === 'agent').slice(0, 8) };
  }
  if (name === 'research_history') { const { json } = await api('/api/history'); return json; }
  if (name === 'research_rollback') { if (a.confirm !== true) throw new Error('回滚需要 confirm=true'); const { status, json } = await api('/api/rollback', 'POST', { id: a.id, actor:'agent', summary:'Agent 回滚历史状态：' + a.id }); if (status !== 200) throw new Error(json.error || '回滚失败'); return { ok: true, projects: json.projects.length, tasks: json.tasks.length }; }
  throw new Error('未知工具: ' + name);
}
let buf = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', d => { buf += d; let i; while ((i = buf.indexOf('\n')) >= 0) { const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1); if (line) handle(line); } });
function handle(line) {
  let msg; try { msg = JSON.parse(line); } catch (e) { return; }
  if (msg.method === 'initialize') return send({ id: msg.id, result: { protocolVersion: '2024-11-05', capabilities: { tools: {} }, serverInfo: { name: 'research-desk', version: '3.0.0' }, instructions: AGENT_MODE ? 'Before work call project.get_context. Inspect failed or partial results, constraints, blockers and human decisions. Claim one bounded Action; report progress; register sourced artifacts and results. A result is UNVERIFIED until independently checked. Never overwrite prior evidence, human notes or the project goal. Request human decisions for direction and constraints.' : 'Legacy compatibility tools; prefer project-scoped Agent Gateway connection for new work.' } });
  if (msg.method === 'notifications/initialized' || String(msg.method).startsWith('notifications/')) return;
  if (msg.method === 'tools/list') return send({ id: msg.id, result: { tools: TOOLS } });
  if (msg.method === 'tools/call') {
    call(msg.params.name, msg.params.arguments)
      .then(out => send({ id: msg.id, result: { content: [{ type: 'text', text: JSON.stringify(out, null, 1) }] } }))
      .catch(e => send({ id: msg.id, result: { content: [{ type: 'text', text: 'ERROR: ' + e.message }], isError: true } }));
    return;
  }
  if (msg.id != null) send({ id: msg.id, error: { code: -32601, message: 'method not found: ' + msg.method } });
}
function send(o) { try { process.stdout.write(JSON.stringify({ jsonrpc: '2.0', ...o }) + '\n'); } catch (e) {} }
process.on('error', () => process.exit(0));
