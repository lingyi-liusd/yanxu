const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(require('path').join(__dirname,'../index.html'),'utf8');
const calls=[],renders=[];
const ctx={aiProjectId:'p1',aiView:'project',aiRefreshSequence:0,aiProject:null,$:()=>null,data:{projects:[{id:'p1'},{id:'p2'}]},loadState:async()=>{},api:async(path,body)=>{calls.push({path,body});return path.startsWith('project-focus')?{focus:null}:{project:{id:ctx.aiProjectId}};},aiRenderContent:()=>renders.push(ctx.aiProject.project.id),aiRenderInspector:()=>{},osMountStatus:()=>{},osUpdateSetupIndicators:()=>{},Date,encodeURIComponent};
vm.createContext(ctx);
vm.runInContext(html.slice(html.indexOf('const aiReadingState ='),html.indexOf('function aiTime(')),ctx);
vm.runInContext(html.slice(html.indexOf('async function aiRefresh()'),html.indexOf('function osUpdateAgentConnections(')),ctx);
(async()=>{
 await ctx.aiRefresh();assert.equal(renders.at(-1),'p1');assert(calls.every(x=>x.body===undefined),'Refresh must never POST analysis');
 let resolveOld;ctx.api=async(path)=>path.startsWith('project-focus')?{focus:null}:new Promise(resolve=>{resolveOld=resolve;});
 const old=ctx.aiRefresh();await new Promise(resolve=>setImmediate(resolve));
 ctx.aiProjectId='p2';ctx.api=async(path)=>path.startsWith('project-focus')?{focus:null}:{project:{id:'p2'}};
 await ctx.aiRefresh();resolveOld({project:{id:'p1'}});await old;
 assert.equal(ctx.aiProject.project.id,'p2');assert.equal(renders.at(-1),'p2');
 let resolveView;ctx.api=async(path)=>path.startsWith('project-focus')?{focus:null}:new Promise(resolve=>{resolveView=resolve;});
 const oldView=ctx.aiRefresh();await new Promise(resolve=>setImmediate(resolve));
 const count=renders.length;ctx.aiView='today';resolveView({project:{id:'p2'}});await oldView;
 assert.equal(renders.length,count,'A response for the old view must not redraw the new view');
 // An initial empty selection must wait for state, never ask the server for its implicit personal space.
 const headers=[],errors=[];ctx.esc=String;ctx.render=()=>headers.push(ctx.aiProjectId);ctx.aiResetProjectCache=()=>{ctx.aiToday=null;ctx.aiProject=null;};
 ctx.$=id=>id==='content'?{set innerHTML(value){errors.push(value);}}:null;
 ctx.aiRenderContent=()=>renders.push(ctx.aiToday?.project?.id);ctx.aiProjectId='';ctx.data.projects=[];
 ctx.loadState=async()=>{ctx.data.projects=[{id:'formal'}];};calls.length=0;
 ctx.api=async(path,body)=>{calls.push({path,body});return path.startsWith('project-focus')?{focus:null}:{project:{id:path.includes('project_id=formal')?'formal':'personal'}};};
 await ctx.aiRefresh();assert.equal(ctx.aiProjectId,'formal');assert.equal(ctx.aiToday.project.id,'formal');assert.equal(headers.at(-1),'formal');
 assert(calls.every(x=>!x.path.includes('project_id=')||x.path.endsWith('project_id=formal')));
 // No formal project: retain the start screen and do not query a hidden personal space.
 ctx.aiProjectId='';ctx.data.projects=[];ctx.loadState=async()=>{};calls.length=0;
 await ctx.aiRefresh();assert.equal(calls.length,0);assert.equal(ctx.aiToday,null);
 // A removed/hidden selection resolves from current state and clears its cached content.
 ctx.aiProjectId='personal';ctx.data.projects=[{id:'formal'}];await ctx.aiRefresh();assert.equal(ctx.aiProjectId,'formal');assert.equal(ctx.aiToday.project.id,'formal');
 // Selection/view changes during state read abandon the old request before any scoped API.
 let stateReady;ctx.loadState=()=>new Promise(resolve=>{stateReady=resolve;});calls.length=0;
 const loading=ctx.aiRefresh();ctx.aiProjectId='p2';stateReady();await loading;assert.equal(calls.length,0);assert.equal(ctx.aiProjectId,'p2');
 ctx.loadState=async()=>{};ctx.aiProjectId='formal';ctx.api=async path=>path.startsWith('project-focus')?{focus:null}:{project:{id:'personal'}};
 const saved=ctx.aiToday;await ctx.aiRefresh();assert.equal(ctx.aiToday,saved);assert(errors.at(-1).includes('返回的项目与当前选择不符'));
 assert(html.includes('!p.id || p.id !== aiProjectId'),'Today refuses a mismatched cached project while loading');
 assert(html.includes('aiEventArrived("state")'));assert(html.includes('if (aiView) aiRefresh()'));
 console.log('UI refresh PASS: initial/hidden/deleted scope, no implicit personal query, state-read races and wrong-project responses rejected, read-only/stale view guards');
})().catch(e=>{console.error(e);process.exit(1)});
