const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
for (const script of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)) new vm.Script(script[1]);
const source = (from, to) => { const a = html.indexOf(from), b = html.indexOf(to, a); assert(a >= 0 && b > a, from); return html.slice(a, b); };
const clone = value => JSON.parse(JSON.stringify(value));
const decode = value => value.replace(/&(amp|lt|gt|quot|#39);/g, (_, key) => ({amp:'&',lt:'<',gt:'>',quot:'"','#39':"'"}[key]));

// Only DOM and network boundaries are emulated. All rendering, escaping,
// payload validation, context guards, API, refresh and dialog helpers are real.
class Element {
  constructor(tag, attrs = {}) { this.tagName = tag; this.attrs = attrs; this.children = []; this.listeners = {}; this.checked = 'checked' in attrs; this.disabled = 'disabled' in attrs; this.value = attrs.value || ''; this.open = false; this.parentElement = null; }
  get id() { return this.attrs.id; }
  get dataset() { return Object.fromEntries(Object.entries(this.attrs).filter(([k]) => k.startsWith('data-')).map(([k,v]) => [k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase()),v])); }
  set className(value) { this.attrs.class = value; }
  get className() { return this.attrs.class || ''; }
  get firstElementChild() { return this.children.find(c => c instanceof Element) || null; }
  get textContent() { return this.children.map(c => c instanceof Element ? c.textContent : c).join(''); }
  set textContent(value) { this.children = [String(value)]; }
  get innerHTML() { return this._html || ''; }
  set innerHTML(value) {
    this._html = String(value); this.children = [];
    const stack = [this];
    for (const token of this._html.match(/<!--[\s\S]*?-->|<[^>]+>|[^<]+/g) || []) {
      if (token.startsWith('<!--')) continue;
      if (token.startsWith('</')) { if (stack.length > 1) stack.pop(); continue; }
      if (!token.startsWith('<')) { stack.at(-1).children.push(decode(token)); continue; }
      const match = token.match(/^<([\w-]+)([\s\S]*?)\/?\s*>$/);
      if (!match) throw Error('Invalid fixture HTML: ' + token);
      const attrs = {};
      for (const a of match[2].matchAll(/([\w-]+)(?:="([^"]*)"|='([^']*)')?/g)) attrs[a[1]] = decode(a[2] ?? a[3] ?? '');
      const node = new Element(match[1].toLowerCase(), attrs), parent = stack.at(-1);
      node.parentElement = parent; parent.children.push(node);
      if (!['input','br','hr','img','meta','link'].includes(node.tagName)) stack.push(node);
    }
    for (const select of this.querySelectorAll('select')) {
      const options = select.querySelectorAll('option'); select.value = (options.find(o => 'selected' in o.attrs) || options[0] || {}).value || '';
    }
    for (const textarea of this.querySelectorAll('textarea')) textarea.value = textarea.textContent;
  }
  matches(selector) {
    return selector.split(',').some(s => {
      s = s.trim();
      if (s.includes(' ')) { const parts = s.split(/\s+/), last = parts.pop(); return this.matches(last) && !!this.parentElement?.closest(parts.join(' ')); }
      const attr = s.match(/\[([\w-]+)(?:="([^"]*)")?\]/);
      if (attr && (!(attr[1] in this.attrs) || (attr[2] != null && this.attrs[attr[1]] !== attr[2]))) return false;
      s = s.replace(/\[[^\]]+\]/g, '');
      const id = s.match(/#([\w-]+)/); if (id && this.id !== id[1]) return false;
      for (const c of s.matchAll(/\.([\w-]+)/g)) if (!this.className.split(/\s+/).includes(c[1])) return false;
      const tag = s.match(/^[\w-]+/); return !tag || this.tagName === tag[0];
    });
  }
  querySelectorAll(selector) { const out = []; const visit = node => { for (const child of node.children) if (child instanceof Element) { if (child.matches(selector)) out.push(child); visit(child); } }; visit(this); return out; }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) || null; }
  addEventListener(name, listener) { (this.listeners[name] ||= []).push(listener); }
  removeEventListener(name, listener) { this.listeners[name] = (this.listeners[name] || []).filter(x => x !== listener); }
  dispatch(name, event = {}) { for (const listener of [...(this.listeners[name] || [])]) listener(event); }
  showModal() { this.open = true; }
  close() { this.open = false; this.dispatch('close'); }
  cancel() { this.dispatch('cancel'); this.close(); }
  insertAdjacentHTML(position, value) { assert.equal(position, 'beforeend'); const fragment = new Element('fragment'); fragment.innerHTML = value; this._html = (this._html || '') + value; for (const child of fragment.children) { if (child instanceof Element) child.parentElement = this; this.children.push(child); } }
  prepend(node) { node.parentElement = this; this.children.unshift(node); }
  remove() { this.parentElement.children = this.parentElement.children.filter(c => c !== this); }
  setAttribute(key,value) { this.attrs[key] = value; }
}
const sha = 'sha256:' + 'a'.repeat(64), attack = '<img src=x onerror="boom">';
function recovery(overrides = {}) {
  return Object.assign({action:{id:'a',project_id:'p',agent_id:'old',status:'running',version:7,goal:'original ' + attack,expected_output:'deliver',success_condition:'success',failure_condition:'failure',stop_condition:'stop',budget:'{"max_progress_reports":6}',approved_contract:{goal:'original',stop_condition:'stop',budget:{max_progress_reports:6}},authority_note:'authority ' + attack,contract_hash:'contract-hash'},results:[],artifacts:[{id:'artifact-1',title:'output ' + attack,verification_status:'UNVERIFIED'}],used_progress_reports:3,max_progress_reports:6,eligible_agents:[{id:'ready',name:'Ready',status:'offline',handshake_at:'2026-10-03'}, {id:'no-handshake',name:'Pending',status:'online',handshake_at:null}, {id:'foreign',project_id:'q',handshake_at:'now'}],receipts:[],source_hash:'source-hash',rev:12},overrides);
}
function review(overrides = {}) {
  return Object.assign({result:{id:'r',project_id:'p',action_id:'a',summary:'original failed ' + attack,outcome:'FAILED',verification_status:'UNVERIFIED',source_ref:'fixture://source',source_version:sha},evidence:null,evidence_candidates:[],evidence_id:null,evidence_association:'missing',association_note:'0项匹配，无法唯一关联Evidence',target_hash:'target-hash',source_ref:'fixture://source',source_version:sha,reviews:[{id:'old-review',notes:'negative ' + attack}],scientific_status:'NOT_ASSESSED',rev:12},overrides);
}
function fixture(kind, snapshot, transport = async () => null, locale = 'zh-CN') {
  const document = new Element('document'); document.innerHTML = '<div id="content"></div><div id="inspector"></div><div id="toolbar"></div><dialog id="modal"><form id="form"></form></dialog>';
  document.documentElement = {lang:locale}; document.getElementById = id => document.querySelector('#' + id); document.createElement = tag => new Element(tag);
  const calls = [], toasts = [], eventHooks = {}, timers = [];
  const ctx = {document,window:{innerWidth:1440,rdEventStream:{addEventListener:(name,fn)=>{eventHooks[name]=fn;}}},TOKEN:'synthetic-fixture-only',data:{projects:[{id:'p',name:'Fixture',goal:'goal'}],tasks:[],files:[],decisions:[]},aiProjectId:'p',aiView:'today',aiSelection:{kind,id:kind==='action'?'a':'r'},aiRefreshSequence:0,currentRev:0,aiFocusStatus:null,aiReadAt:'',aiAnalysisBusy:false,aiManagerStatus:null,aiProject:{actions:[],results:[]},aiToday:null,aiActions:null,aiResults:null,aiAgents:null,aiEvidence:null,aiArtifacts:null,aiEvents:null,aiGraph:null,aiAgentsUnavailable:false,aiInspectorOpen:false,aiRefreshTimer:0,pid:'p',toast:text=>toasts.push(text),setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout:()=>{},navigator:{clipboard:{writeText:async()=>{}}}};
  ctx.fetch = async (url, options = {}) => {
    const body = options.body === undefined ? undefined : JSON.parse(options.body), call = {url,body,method:options.method || 'GET'}; calls.push(call);
    let response = await transport(call,ctx,document);
    if (response == null) {
      if (url.startsWith('/api/project/action-recovery?') || url.startsWith('/api/project/result-review?')) response = snapshot;
      else if (body) response = {rev:body.dry ? body.ifRev : body.ifRev+1,receipt:{scientific_status:'NOT_ASSESSED'},verification_status:'UNVERIFIED'};
      else if (url === '/api/state') response = ctx.data;
      else if (url.startsWith('/api/project/context?')) response = {project:ctx.data.projects[0],actions:kind==='action'?[snapshot.action]:[],results:kind==='result'?[snapshot.result]:[]};
      else if (url.startsWith('/api/project/today?')) response = {project:ctx.data.projects[0]};
      else response = {};
    }
    return {ok:!response.error,json:async()=>clone(response),headers:{get:()=>response.rev == null ? null : String(response.rev)}};
  };
  vm.createContext(ctx);
  for (const prefix of ['const $ =','const esc =','function normalize(','async function api(','async function loadState(']) vm.runInContext(html.split('\n').find(line=>line.startsWith(prefix)),ctx);
  vm.runInContext(source('function aiRenderContent()', 'function osUpdateAgentConnections()'),ctx);
  vm.runInContext(source('const rdEnglish = {','(function rdLanguageController()'),ctx);
  vm.runInContext(source('function aiEventArrived(name)', '[["todayNav"'),ctx);
  vm.runInContext(source('$("inspector").addEventListener("click"', '$("content").addEventListener("click", function (event) {\n  const workspace'),ctx);
  const get = id => document.getElementById(id), host = () => get('closureBody');
  const writes = () => calls.filter(c=>c.body !== undefined);
  const input = (id,value) => { const node = get(id); assert(node,id); if (typeof value === 'boolean') node.checked = value; else node.value = value; (node.onchange || node.oninput)?.call(node); };
  const open = () => kind === 'action' ? ctx.osActionRecovery('a') : ctx.osResultReview('r');
  return {ctx,document,calls,toasts,eventHooks,timers,get,host,writes,input,open};
}
function fillRecovery(f, operation = 'mark_interrupted') {
  for (const box of f.host().querySelectorAll('[data-recovery-record]')) { box.checked = true; box.onchange(); }
  if (f.get('recoveryNoOutput')) f.input('recoveryNoOutput',true);
  f.input('recoveryOperation',operation); if (operation === 'continue') f.input('recoveryAgent','ready');
  f.input('recoverySummary','human checked original records'); f.input('recoveryStopped',true);
}
function fillReview(f, assessment = 'matched', version = sha) {
  f.input('reviewCheckedVersion',version); f.input('reviewAssessment',assessment); f.input('reviewKind','source'); f.input('reviewCriteria','compare declared content versions'); f.input('reviewReviewer','human'); f.input('reviewConclusion','accepted'); f.input('reviewNotes','Only a declaration; negative result retained.'); f.input('reviewConfirm',true);
}
async function save(f) { const button=f.get('closureSave'); assert(!button.disabled,'valid input should enable confirmation'); await button.onclick(); }
const tick = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  let checks = 0;
  for (const operation of ['mark_interrupted','continue','close_unknown','reconcile_completed']) {
    const snapshot = recovery(operation === 'reconcile_completed' ? {results:[{id:'old-result',summary:'negative result',outcome:'FAILED',verification_status:'UNVERIFIED'}]} : {}), before = JSON.stringify(snapshot);
    const f = fixture('action',snapshot); await f.open();
    assert.equal(f.writes().length,0); assert(f.host().querySelectorAll('input[type="checkbox"]').every(n=>!n.checked)); assert(f.get('closureSave').disabled);
    const markup=f.host().innerHTML; for (const text of ['不能终止外部进程','原行动契约','contract-hash','authority','已用进度报告次数','>3<','报告次数上限','>6<','UNKNOWN','failed']) assert(markup.includes(text),text);
    assert(!markup.includes(attack)); assert(markup.includes('&lt;img')); assert.equal(f.get('recoveryAgent').querySelectorAll('option').length,2);
    fillRecovery(f,operation); await save(f);
    const [dry,apply]=f.writes(); assert.equal(f.writes().length,2); assert.equal(dry.body.dry,true); assert.equal(apply.body.dry,false);
    assert.deepEqual({...dry.body,dry:false},apply.body); assert.equal(apply.body.ifRev,12); assert.equal(apply.body.action_version,7); assert.equal(apply.body.contract_hash,'contract-hash'); assert.equal(apply.body.source_hash,'source-hash'); assert.equal(apply.body.external_work_stopped,true); assert.equal(apply.body.consent,'human-action-recovery-v1'); assert.equal(apply.body.operation,operation); assert.deepEqual(apply.body.checked_records,snapshot.results.concat(snapshot.artifacts).map(r=>r.id));
    assert.equal(operation==='continue'?apply.body.to_agent_id:undefined,operation==='continue'?'ready':undefined); assert.equal(JSON.stringify(snapshot),before);
    assert(!f.document.querySelectorAll('script').length); assert(!f.get('content').innerHTML.includes('状态暂不可读取')); assert(f.calls.some(c=>c.url==='/api/state'),'successful commit must refresh the existing view'); checks++;
  }
  {
    const f=fixture('action',recovery({artifacts:[]})); await f.open(); fillRecovery(f,'close_unknown'); f.input('recoveryNoOutput',false); assert(f.get('closureSave').disabled); await f.get('closureSave').onclick(); assert.equal(f.writes().length,0); f.input('recoveryNoOutput',true); await save(f); assert.equal(f.writes()[1].body.checked_no_registered_output,true); assert.deepEqual(f.writes()[1].body.checked_records,[]); checks++;
  }
  for (const invalid of ['unchecked-record','missing-terms','unhandshaken','foreign-agent','has-result','finished','manager-action']) {
    const snapshot=recovery(); if(invalid==='missing-terms')snapshot.action.stop_condition=''; if(invalid==='has-result')snapshot.results=[{id:'r'}]; if(invalid==='finished')snapshot.action.status='finished'; if(invalid==='manager-action')snapshot.action.agent_id='manager-agent-test';
    const f=fixture('action',snapshot); await f.open(); fillRecovery(f,'continue');
    if(invalid==='unchecked-record'){f.host().querySelectorAll('[data-recovery-record]')[0].checked=false;f.input('recoverySummary','reason');}
    if(invalid==='unhandshaken')f.input('recoveryAgent','no-handshake'); if(invalid==='foreign-agent')f.input('recoveryAgent','foreign');
    assert(f.get('closureSave').disabled,invalid); await f.get('closureSave').onclick(); assert.equal(f.writes().length,0); checks++;
  }
  for (const kind of ['action','result']) for (const mode of ['cancel','escape','switch-project','switch-view','switch-selection','replace-form','close-reopen','conflict','preview-rev','apply-conflict']) {
    const snapshot=kind==='action'?recovery():review();
    const f=fixture(kind,snapshot,async(call,ctx,doc)=>{
      if(!call.body)return null;
      if(call.body.dry){
        if(mode==='cancel')doc.getElementById('closureCancel').onclick(); if(mode==='escape')doc.getElementById('modal').cancel();
        if(mode==='switch-project')ctx.aiProjectId='q'; if(mode==='switch-view')ctx.aiView='evidence'; if(mode==='switch-selection')ctx.aiSelection={kind:kind,id:'other'};
        if(mode==='replace-form')doc.getElementById('form').innerHTML='<div id="closureBody"></div><button id="closureSave"></button>';
        if(mode==='close-reopen'){doc.getElementById('modal').close();doc.getElementById('modal').showModal();}
        if(mode==='conflict')return {error:'409 version conflict'}; if(mode==='preview-rev')return {rev:13};
      } else if(mode==='apply-conflict')return {error:'409 apply conflict'};
      return null;
    });
    await f.open(); kind==='action'?fillRecovery(f):fillReview(f); await save(f);
    assert.equal(f.writes().length,mode==='apply-conflict'?2:1,kind+' '+mode); assert(!f.calls.some(c=>c.url==='/api/state'),'no stale success refresh');
    if(['conflict','preview-rev','apply-conflict'].includes(mode)){assert(f.get('closureSave').disabled);assert.equal(f.get('closureSave').onclick,null,'conflicts must require a fresh read, not retry');assert(f.host().innerHTML.includes('重新读取'));} checks++;
  }
  for(const kind of ['action','result'])for(const mode of ['cancel','switch-project','switch-view','switch-selection','replace-form','superseded']){
    let release;const f=fixture(kind,kind==='action'?recovery():review(),async call=>call.url.includes(kind==='action'?'action-recovery?':'result-review?')?await new Promise(resolve=>{release=resolve;}):null);
    const pending=f.open();await tick(); if(mode==='cancel')f.get('modal').cancel();if(mode==='switch-project')f.ctx.aiProjectId='q';if(mode==='switch-view')f.ctx.aiView='';if(mode==='switch-selection')f.ctx.aiSelection={kind,id:'other'};if(mode==='replace-form')f.get('form').innerHTML='<p>other dialog</p>';if(mode==='superseded')f.ctx.osClosureStart(kind,kind==='action'?'a':'r','new dialog');
    release(kind==='action'?recovery():review());await pending;assert.equal(f.writes().length,0);assert(!f.get('recoveryOperation')&&!f.get('reviewAssessment'),'late GET must not install stale controls');checks++;
  }
  for (const assessment of ['matched','missing','mismatch','unavailable','symbolic']) {
    const version=assessment==='symbolic'?'v1':sha, snapshot=review({source_version:version}), before=JSON.stringify(snapshot), f=fixture('result',snapshot); await f.open();
    assert(!f.get('reviewConfirm').checked);assert.equal(f.get('reviewCheckedVersion').value,'');assert(f.get('closureSave').disabled);assert.equal(f.writes().length,0);
    for(const text of ['FAILED','UNVERIFIED','NOT_ASSESSED','人工来源声明','不证明实际字节一致','target-hash','negative'])assert(f.host().innerHTML.includes(text),text);
    assert(!f.host().innerHTML.includes(attack)); fillReview(f,assessment,assessment==='matched'?sha:assessment==='symbolic'?'v1':''); await save(f);
    const [dry,apply]=f.writes();assert.equal(dry.body.dry,true);assert.equal(apply.body.dry,false);assert.deepEqual({...dry.body,dry:false},apply.body);assert.equal(apply.body.ifRev,12);assert.equal(apply.body.source_assessment,assessment);assert.equal(apply.body.target_hash,'target-hash');assert.equal(apply.body.consent,'human-result-review-v1');assert(!('verification_status' in apply.body));assert(!('scientific_status' in apply.body));assert.equal(JSON.stringify(snapshot),before);checks++;
  }
  for(const [registered,checked] of [[sha,'sha256:'+'b'.repeat(64)],['v1','v1'],['sha256:abc','sha256:abc'],['',''],[sha,sha.toUpperCase()]]){
    const f=fixture('result',review({source_version:registered}));await f.open();fillReview(f,'matched',checked);assert(f.get('closureSave').disabled);await f.get('closureSave').onclick();assert.equal(f.writes().length,0);checks++;
  }
  for(const conclusion of ['rejected','needs_more']){const f=fixture('result',review());await f.open();fillReview(f);f.input('reviewConclusion',conclusion);await save(f);assert.equal(f.writes()[1].body.conclusion,conclusion);checks++;}
  for(const kind of ['software','scientific']){const f=fixture('result',review());await f.open();fillReview(f);f.input('reviewKind',kind);await save(f);assert.equal(f.writes()[1].body.review_kind,kind);assert(!('scientific_status' in f.writes()[1].body));checks++;}
  {
    const evidence=[{id:'e1',project_id:'p',title:'first'},{id:'e2',project_id:'p',title:'second '+attack}], snapshot=review({evidence_candidates:evidence,evidence_association:'ambiguous'}), f=fixture('result',snapshot);await f.open();fillReview(f);f.input('reviewEvidence','e2');await tick();
    assert(!f.get('reviewConfirm').checked,'target change clears consent');assert.equal(f.get('reviewCheckedVersion').value,'');assert.equal(f.get('reviewEvidence').value,'e2');assert(f.host().innerHTML.includes('&lt;img'));
    fillReview(f);await save(f);assert.equal(f.writes()[1].body.evidence_id,'e2');assert.equal(f.writes()[1].body.target_hash,'target-hash');assert.equal(f.calls.filter(c=>c.url.includes('result-review?')).length,2);checks++;
  }
  {
    const f=fixture('result',review());await f.open();f.input('reviewEvidence','not-a-candidate');await tick();assert(f.get('closureSave').disabled);assert.equal(f.writes().length,0);checks++;
  }
  for(const kind of ['action','result']){
    const f=fixture(kind,kind==='action'?recovery():review());f.ctx.aiProject=kind==='action'?{actions:[recovery().action]}:{results:[review().result]};f.ctx.aiRenderInspector();const out=f.get('inspector').innerHTML;
    assert(out.includes(kind==='action'?'data-ai-action="action-recovery"':'data-ai-action="result-review"'));assert(!out.includes('<details open'));assert(!out.includes(attack));if(kind==='action'){assert(out.includes('授权说明'));assert(out.includes('契约 hash'));}
    const button=f.get('inspector').querySelector('[data-ai-action="'+(kind==='action'?'action-recovery':'result-review')+'"]');assert(button);f.get('inspector').dispatch('click',{target:button});await tick();assert(f.get(kind==='action'?'recoveryOperation':'reviewAssessment'),'real inspector click must open usable controls');assert.equal(f.writes().length,0);f.get('modal').close();
    for(const event of ['action.reconciled','result.reviewed'])assert.equal(typeof f.eventHooks[event],'function');f.eventHooks[kind==='action'?'action.reconciled':'result.reviewed']();await f.timers.at(-1)();await tick();assert(f.calls.some(c=>c.url==='/api/state'));assert.equal(f.writes().length,0);checks++;
  }
  {
    const f=fixture('result',review(),undefined,'en');await f.open();assert(f.host().innerHTML.includes('human source declaration'));assert(f.host().innerHTML.includes('FAILED'));assert(f.host().innerHTML.includes('UNVERIFIED'));
    for(const text of ['核对这项行动 →','授权说明','已用进度报告次数','标记中断','以未知关闭交付','人工复核与收据','相同 SHA-256 内容版本（人工声明）','符号版本（不是内容 hash）','科学复核','我已核对并停止原外部执行；此确认不会终止任何进程。'])assert.notEqual(f.ctx.rdTranslateUI(text,'en'),text,text);
    assert.equal(f.ctx.rdTranslateUI('FAILED','en'),'FAILED');assert.equal(f.ctx.rdTranslateUI('UNVERIFIED','en'),'UNVERIFIED');checks++;
  }
  {
    const f=fixture('action',recovery(),async(call,ctx)=>{if(call.url==='/api/agents/connect'){ctx.aiProjectId='q';return{codex_config_toml:'synthetic',codex_command:'synthetic',agent_instruction:'synthetic'};}return null;});await f.ctx.aiConnectCodex();assert.equal(f.writes()[0].body.contract_mode,'strict_v2');assert(!f.get('modal').open);assert(!f.get('aiConfig'));checks++;
  }
  assert(html.includes('.rd-closure-label'));assert(html.includes("option.rd-closure-label"));assert(html.includes('[data-preserve-original]'));
  console.log(`Closure UI PASS: ${checks} VM scenarios using real helpers/API/refresh; dry-first same-revision payloads, unchecked consent, full records, inherited contract/budget, no retry, stale dialog guards, SHA-256 human declarations, Evidence selection, immutable FAILED/UNVERIFIED, bilingual labels and SSE. No production access or real browser/model/file validation.`);
})().catch(error=>{console.error(error);process.exitCode=1;});
