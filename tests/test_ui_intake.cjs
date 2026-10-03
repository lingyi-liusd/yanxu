const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(require('path').join(__dirname,'../index.html'),'utf8');
const helpers=html.slice(html.indexOf('function osDisclosure('),html.indexOf('function osRenderToday()'));
const helperCtx={esc:s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;')};
vm.createContext(helperCtx);vm.runInContext(helpers,helperCtx);
const markup=helperCtx.osSourceIntakeMarkup({items:[{id:'file:/a',name:'<script>资料.md',path:'/a/<script>',source_version:'sha256:abc'}]});
assert(markup.includes('&lt;script>资料.md'));assert(!markup.includes('<script>'));assert(!markup.includes('checked'));assert(!markup.includes('<details open'));
assert(markup.includes('仅登记位置与版本'));assert(markup.includes('尚未核验'));assert(markup.includes('sha256:abc'));
assert.equal(helperCtx.rdPathName('C:\\project\\note.md'),'note.md');
const fileHelpers=html.slice(html.indexOf('function fileName('),html.indexOf('function dateOnly('));
helperCtx.data={projects:[{id:'p',workspace:'/Users/Demo/Projects/sample'}]};vm.runInContext(fileHelpers,helperCtx);
assert.equal(helperCtx.fileCategory({project:'p',path:'/Users/Demo/Projects/sample/下一阶段计划.md'}),'文稿与文档');
assert.equal(helperCtx.fileCategory({project:'p',path:'/Users/Demo/Projects/sample/核查记录.md'}),'数据与记录');
assert.equal(helperCtx.fileCategory({project:'p',path:'/Users/Demo/Projects/sample/code/solver.py'}),'代码与配置');
assert.equal(helperCtx.fileCategory({project:'p',path:'/Users/Demo/Projects/sample/notes/meeting.md'}),'会议与笔记');
assert.equal(helperCtx.fileCategory({project:'other',path:'C:\\Users\\Codex\\计划.md'}),'文稿与文档');
assert.equal(helperCtx.fileName('C:\\Users\\Codex\\计划.md'),'计划.md');
helperCtx.pid='p';helperCtx.fileExpanded={};helperCtx.currentProject=()=>helperCtx.data.projects[0];
helperCtx.fileNode=f=>'<button>'+helperCtx.esc(f.path)+'</button>';helperCtx.fileRelationMarkup=()=>{throw Error('compact files must not infer relationships');};
vm.runInContext(html.split('\n').find(s=>s.startsWith('function fileGroups(')),helperCtx);
vm.runInContext(html.split('\n').find(s=>s.startsWith('function renderFileIndex(')),helperCtx);
const files=[{project:'p',path:'/Users/Demo/Projects/sample/计划.md'}];
const compact=helperCtx.renderFileIndex(files,files,helperCtx.fileGroups(files),true);
assert(compact.includes('文稿与文档'));assert(!compact.includes('0 个文件'));assert(!compact.includes('参考资料'));assert(!compact.includes('当前项目'));
const code=html.slice(html.indexOf('async function osSourceIntake()'),html.indexOf('async function osResumeBrief()'));
async function fixture(mode){
  const calls=[],toasts=[],boxes=[{checked:false,dataset:{intakeId:'file:/a'}},{checked:false,dataset:{intakeId:'file:/b'}}];
  const nodes={form:{innerHTML:'',querySelectorAll:()=>boxes},modal:{open:false,showModal(){this.open=true;},close(){this.open=false;}},intakeAll:{checked:false},intakeCancel:{},intakeConfirm:{disabled:true}};
  const ctx={aiProjectId:'p',currentRev:12,$:id=>nodes[id],loadState:async()=>{},osSourceIntakeMarkup:()=>markup,toast:s=>toasts.push(s),aiRefresh:async()=>calls.push('refresh'),osSourceSettings:()=>calls.push('settings'),
    api:async(path,body)=>{calls.push({path,body});if(!body)return {source_intake:{draft_hash:'hash',items:mode==='empty'?[]:[{id:'file:/a'},{id:'file:/b'}]}};
      if(mode==='failure')throw Error('草稿已过期');if(body.dry&&mode==='cancel')nodes.intakeCancel.onclick();if(body.dry&&mode==='switch')ctx.aiProjectId='other';return {added:2};}};
  vm.createContext(ctx);vm.runInContext(code,ctx);await ctx.osSourceIntake();
  if(mode==='empty')return {calls,nodes,toasts};
  assert(boxes.every(b=>!b.checked));assert(nodes.form.innerHTML.includes('暂不整理'));
  nodes.intakeAll.checked=true;nodes.intakeAll.onchange();assert(boxes.every(b=>b.checked));
  assert.equal(nodes.intakeConfirm.textContent,'确认登记 2 份资料');assert.equal(nodes.intakeConfirm.disabled,false);
  await nodes.intakeConfirm.onclick();return {calls,nodes,toasts};
}
(async()=>{
  let r=await fixture('ok');const writes=r.calls.filter(c=>c.body);assert.equal(writes.length,2);assert.equal(writes[0].body.dry,true);assert.equal(writes[1].body.dry,undefined);assert.equal(writes[1].body.ifRev,12);assert.equal(writes[1].body.draft_hash,'hash');assert.equal(writes[1].body.project_id,'p');assert.deepEqual(Array.from(writes[1].body.source_ids),['file:/a','file:/b']);assert(r.toasts.some(t=>t.includes('尚未核验')));
  for(const mode of ['cancel','switch','failure']){r=await fixture(mode);assert.equal(r.calls.filter(c=>c.body).length,1);}
  r=await fixture('failure');assert.equal(r.nodes.intakeConfirm.textContent,'重新查看资料');assert(!r.calls.includes('refresh'));
  r=await fixture('empty');assert(r.calls.includes('settings'));assert.equal(r.calls.filter(c=>c.body).length,0);
  console.log('Source intake UI PASS: unchecked metadata drafts, escaping, batch selection, dry-first version-bound confirmation, cancellation/project switch and no automatic retry');
})().catch(e=>{console.error(e);process.exitCode=1;});
