const fs=require('fs'), vm=require('vm'), assert=require('assert');
const html=fs.readFileSync(require('path').join(__dirname,'../index.html'),'utf8');
const ctx={priorityOf:t=>t.priority||'P2',priorityRank:t=>Number((t.priority||'P2').slice(1)),localISO:d=>[d.getFullYear(),String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0')].join('-')};
vm.createContext(ctx);vm.runInContext(html.slice(html.indexOf('function rdPlanBuckets('),html.indexOf('async function rdReadPlan(')),ctx);
const tasks=[{id:'done',project:'p',status:'已完成'}, {id:'active',project:'p',status:'进行中'}, {id:'future',project:'p',status:'待开始',start:'2026-10-08'}, {id:'blocked',project:'p',status:'进行中',deps:['missing']}, {id:'cross',project:'p',status:'待开始',deps:['other']}, {id:'other',project:'q',status:'已完成'}, {id:'ready',project:'p',status:'待开始',deps:['done']}, {id:'invalid',project:'p',status:'待开始',start:'2026-02-31'}, {id:'paused',project:'p',status:'待开始',priority:'P3'}, {id:'unknown',project:'p',status:'UNKNOWN'}, {id:'note',project:'p',status:'进行中',noteType:'note'}];
const before=JSON.stringify(tasks),g=ctx.rdPlanBuckets(tasks,'2026-10-02');
assert.deepEqual(Array.from(g.active,r=>r.task.id),['active']);assert.deepEqual(Array.from(g.ready,r=>r.task.id),['ready']);assert.deepEqual(Array.from(g.dated,r=>r.task.id),['future']);
for(const id of ['blocked','cross','invalid','paused','unknown'])assert(g.waiting.some(r=>r.task.id===id));
assert.equal(Object.values(g).flat().length,10);assert.equal(JSON.stringify(tasks),before);
ctx.esc=s=>String(s||'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');ctx.rdBriefText=s=>s;ctx.aiTime=s=>s||'';ctx.osTreeGroup=(title,rows,open,count)=>'<details'+(open?' open':'')+'><summary>'+ctx.esc(title)+' '+count+'</summary>'+rows+'</details>';ctx.osTreeRow=(kind,id,title,meta)=>'<button data-id="'+ctx.esc(id)+'">'+ctx.esc(title)+' '+ctx.esc(meta)+'</button>';
vm.runInContext(html.slice(html.indexOf('function rdArtifactCategory('),html.indexOf('function osRenderArtifacts(')),ctx);
const rows=[{id:'a',type:'document',title:'210 资产盘点与分析'},{id:'b',type:'document',title:'交接与预算'},{id:'c',type:'code',title:'源码'},{id:'d',type:'document',title:'失败验证 <script>',source_version:'v1'}];
const old=JSON.stringify(rows),tree=ctx.rdArtifactTree(rows,'');assert(!tree.includes('<details open'));assert.equal((tree.match(/data-id=/g)||[]).length,4);assert(tree.includes('&lt;script>'));assert(tree.includes('交接与导航'));assert(tree.includes('实验与验证'));
const search=ctx.rdArtifactTree(rows,'v1');assert(search.includes('rd-result-forks'));assert(search.includes('匹配成果'));assert(search.includes('data-id="d"'));assert(!search.includes('data-id="a"'));assert.equal(JSON.stringify(rows),old);
assert(tree.includes('rd-result-root'));assert.equal((tree.match(/<section class="rd-result-branch"/g)||[]).length,4);assert(!tree.includes('<details class="rd-result-branch"'));
const dense=Array.from({length:100},(_,i)=>({id:'record-'+i,type:'analysis',title:'分析 '+i}));
const denseTree=ctx.rdArtifactTree(dense,'');assert.equal((denseTree.match(/data-id=/g)||[]).length,100);assert(denseTree.includes('还有 97 项成果'));assert(!denseTree.includes('<details open'));assert(denseTree.includes('100 项'));assert(ctx.rdArtifactTree(dense,'not-found').includes('没有匹配的成果'));
assert(!html.slice(html.indexOf('function weekTasks()'),html.indexOf('function overviewDateLabel(')).includes('rd-week-attention'));
console.log('Planning/library PASS: exclusive buckets, no fake dates, blocked/missing/cross-project dependencies, unknown/paused/invalid dates, notes excluded, collapsed categories, escaped searchable sources, immutable records');
async function readFixture(change) {
  let resolve, renders=0;const calls=[];
  const c={rdPlanProject:'p',rdPlanReadSequence:0,rdPlanManager:null,rdPlanManagerRevision:-1,currentRev:5,homeView:'week',aiView:'',weekTasks:()=>renders++,api:route=>{calls.push(route);return new Promise(r=>resolve=r);}};
  vm.createContext(c);vm.runInContext(html.slice(html.indexOf('async function rdReadPlan('),html.indexOf('function rdPlanTree(')),c);
  const pending=c.rdReadPlan();if(change==='project')c.rdPlanProject='q';if(change==='revision')c.currentRev=6;if(change==='view')c.aiView='today';
  resolve({project_id:'p',enabled:true});await pending;
  assert.deepEqual(calls,['project/manager?project_id=p']);assert.equal(renders,change?0:1);assert.equal(Boolean(c.rdPlanManager),!change);
}
(async()=>{await readFixture('');await readFixture('project');await readFixture('revision');await readFixture('view');console.log('Planning Agent read PASS: GET only, no model call, stale revision/project/view response rejected');})().catch(e=>{console.error(e);process.exitCode=1;});
