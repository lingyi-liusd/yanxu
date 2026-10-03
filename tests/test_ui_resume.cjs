const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(require('path').join(__dirname,'../index.html'),'utf8');
const code=html.slice(html.indexOf('async function osResumeBrief()'),html.indexOf('async function osSourceSettings()'));
async function fixture(second, switchProject=false, navigate=false, switchView=false){
  const target={dataset:{resumeView:'evidence',resumeKind:'result',resumeId:'r1'}},calls=[];
  const nodes={form:{querySelectorAll:selector=>navigate&&selector==='[data-resume-view]'?[target]:[]},modal:{showModal(){},close(){calls.push('close');}},resumeClose:{},resumeCopy:{},resumeText:{value:'old text',parentElement:{},select(){}}};
  const copied=[],toasts=[];let reads=0;
  const ctx={aiProjectId:'p',aiView:'today', $:id=>nodes[id],osResumeBriefMarkup:()=>'',toast:s=>toasts.push(s),
    navigator:{clipboard:{writeText:async s=>copied.push(s)}},aiOpen:async v=>{calls.push(v);ctx.aiView=switchView?'project':v;},osSelect:(k,id)=>calls.push(k+':'+id),
    api:async()=>{reads++; if(reads===2 && switchProject)ctx.aiProjectId='another';
      return reads===1?{source_hash:'current',resume_brief:{handoff:{management_budget:{used_today:1}}}}:second;}};
  vm.createContext(ctx);vm.runInContext(code,ctx);await ctx.osResumeBrief();await nodes.resumeCopy.onclick();
  if(navigate)await target.onclick();
  return {copied,toasts,reads,calls};
}
(async()=>{
  let r=await fixture({source_hash:'changed',resume_brief:{handoff:{}}});
  assert.equal(r.copied.length,0);assert(r.toasts.some(s=>s.includes('记录已变化')));
  r=await fixture({source_hash:'current',resume_brief:{handoff:{management_budget:{used_today:2}}}});
  assert.equal(r.copied.length,1);assert(r.copied[0].includes('"used_today": 2'));assert(r.toasts.some(s=>s.includes('尚未发送或启动行动')));assert.equal(r.reads,2);
  r=await fixture({source_hash:'current',resume_brief:{handoff:{}}},true);assert.equal(r.copied.length,0);
  r=await fixture({source_hash:'current',resume_brief:{handoff:{}}},false,true);assert.deepEqual(r.calls,['close','evidence','result:r1']);
  r=await fixture({source_hash:'current',resume_brief:{handoff:{}}},false,true,true);assert.deepEqual(r.calls,['close','evidence']);
  console.log('Resume copy PASS: stale/project-switch rejection, fresh budget readback, no external message or action');
  const clickCode=html.slice(html.indexOf('$("content").addEventListener("click", async function (event)'),html.indexOf('$("toolbar").addEventListener("click", function (event)'));
  let handler, calls=[],toasts=[],hasToday=true;const button={dataset:{resumeProject:'p',resumeView:'evidence',resumeKind:'result',resumeId:'r1'}};
  const ctx={aiView:'today',aiProjectId:'p',$:()=>({addEventListener:(type,fn)=>handler=fn,querySelector:()=>hasToday?{}:null}),toast:s=>toasts.push(s),aiRefresh:async()=>calls.push('refresh'),osSelect:(kind,id)=>calls.push(kind+':'+id)};
  vm.createContext(ctx);vm.runInContext(clickCode,ctx);const event={target:{closest:selector=>selector==='[data-resume-view]'?button:null}};
  await handler(event);assert.deepEqual(calls,['refresh','result:r1']);assert.equal(ctx.aiView,'today');calls=[];ctx.aiProjectId='other';await handler(event);assert.equal(calls.length,0);assert(toasts.some(s=>s.includes('项目已切换')));
  ctx.aiProjectId='p';ctx.aiRefresh=async()=>{ctx.aiProjectId='other';};await handler(event);assert.equal(calls.length,0);
  ctx.aiProjectId='p';ctx.aiRefresh=async()=>{ctx.aiView='project';};await handler(event);assert.equal(calls.length,0);
  ctx.aiRefresh=async()=>{throw Error('offline');};await handler(event);assert(toasts.some(s=>s.includes('offline')));
  ctx.aiView='today';ctx.aiRefresh=async()=>{hasToday=false;};await handler(event);assert.equal(calls.length,0);
  hasToday=true;ctx.aiRefresh=async()=>false;await handler(event);assert.equal(calls.length,0);assert(toasts.some(s=>s.includes('未能读取最新记录')));
  button.dataset.resumeHash='old';ctx.aiManagerStatus={project_id:'p',source_hash:'new'};ctx.aiRefresh=async()=>true;
  await handler(event);assert.equal(calls.length,0);assert(toasts.some(s=>s.includes('项目已有新进展')));
  ctx.aiManagerStatus={project_id:'other',source_hash:'old'};await handler(event);assert.equal(calls.length,0);
  ctx.aiManagerStatus={project_id:'p',source_hash:'old'};await handler(event);assert.deepEqual(calls,['result:r1']);
  console.log('Today primary navigation PASS: awaited record read in place, stale project/view guard and readable error, no write or action');
})().catch(e=>{console.error(e);process.exitCode=1;});
