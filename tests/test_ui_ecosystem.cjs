const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(require('path').join(__dirname,'../ecosystem.js'),'utf8');
new Function(source);
const calls=[],ctx={aiView:'discussion',aiProjectId:'p1',FormData:class{constructor(form){return form.entries}},
 document:{getElementById:()=>null,hidden:false},location:{search:'',assign:url=>calls.push({navigation:url})},URLSearchParams,setInterval:()=>0,data:{projects:[{id:'p1'}]},aiOpen(mode){ctx.aiView=mode;},
 aiRenderContent(){},aiRenderInspector(){},aiRefresh(){},render(){},loadState:async()=>{},api:async(p,b)=>{calls.push({p,b});return b?{rev:9,item:{id:'saved'}}:{project_id:'p1',rev:9};}};
vm.createContext(ctx);
for(const name of ['ecosystem_state.js','ecosystem_client.js'])vm.runInContext(fs.readFileSync(require('path').join(__dirname,'../'+name),'utf8'),ctx);vm.runInContext(source.replace('  navigation();\n  setInterval', '  this.fixture={eco,domain,mutate,refresh,roomMarkdown,radarFilteredAlerts};render=()=>{};\n  navigation();\n  setInterval'),ctx);
const {eco,domain,mutate,refresh}=ctx.fixture;
function reset(){calls.length=0;ctx.aiView='discussion';ctx.aiProjectId='p1';domain.value={project_id:'p1',rev:8};eco.pendingIntent=null;}
(async()=>{
 const radar={watches:[{id:'w1',name:'官方发布'},{id:'w2',name:'论文'}],alerts:[{id:'a1',watch_id:'w1',title:'旧版',status:'reviewed',deliveries:[],created_at:'2026-01-01',added:'内容'}, {id:'a2',watch_id:'w2',title:'新版',status:'unread',deliveries:[{}],created_at:'2026-01-02',added:'新技术'}]};
 const original=JSON.stringify(radar), filter=ctx.fixture.radarFilteredAlerts;
 assert.equal(filter(radar)[0].id,'a2');eco.radarStatus='unread';assert.equal(filter(radar).length,1);eco.radarStatus='pushed';assert.equal(filter(radar)[0].id,'a2');eco.radarSource='w1';assert.equal(filter(radar).length,0);eco.radarStatus='all';eco.radarQuery='官方';assert.equal(filter(radar)[0].id,'a1');eco.radarQuery='不存在';assert.equal(filter(radar).length,0);assert.equal(JSON.stringify(radar),original,'filters must not mutate records');eco.radarQuery='';eco.radarSource='';
 ctx.aiProjectId='ecosystem-personal-discussion';ctx.aiOpen('project');assert.equal(ctx.aiProjectId,'p1','Project mode must leave an app-owned personal space');
 ctx.aiProjectId='ecosystem-personal-discussion';ctx.aiOpen('discussion');assert.equal(ctx.aiProjectId,'ecosystem-personal-discussion','App navigation retains the selected space');assert(calls.some(c=>c.navigation==='/apps/discussion/?project=ecosystem-personal-discussion'),'Discussion must open its own app URL');
 const markdown=ctx.fixture.roomMarkdown({title:'fixture',question:'Q',context:{context_hash:'hash'},status:'failed',round:1,max_rounds:2,used_calls:3,max_calls:6,participants:[{name:'R',model:'M'}],failures:[{round:1,message:'未解决的失败'}],messages:[],adoptions:[{title:'人工采纳',rationale:'仍需核验',source_version:'source-v1'}]},'项目');
 assert(markdown.includes('3 / 6'));assert(markdown.includes('未解决的失败'));assert(markdown.includes('仍需核验'));assert(markdown.includes('source-v1'));
 reset();await mutate('room.create',{title:'fixture'});
 assert.equal(calls[0].b.dry,true);assert.equal(calls[1].b.ifRev,8);assert.equal(calls[1].b.project_id,'p1');
 for(const change of ['project','view','cancel','edit','replace']){
  reset();const form={entries:[['title','before']]},modal={open:true,querySelector:()=>form};
  eco.pendingIntent={project:'p1',view:'discussion',form,modal,payload:JSON.stringify(form.entries)};
  ctx.api=async(p,b)=>{calls.push({p,b});if(change==='project')ctx.aiProjectId='p2';if(change==='view')ctx.aiView='radar';if(change==='cancel')modal.open=false;if(change==='edit')form.entries=[['title','after']];if(change==='replace')modal.querySelector=()=>({});return {};};
  await assert.rejects(mutate('room.create',{title:'fixture'}));assert.equal(calls.length,1,change+' must discard dry preview');
 }
 reset();let validChat=true;eco.pendingIntent={chat:true,valid:()=>validChat};ctx.api=async(p,b)=>{calls.push({p,b});validChat=false;return {};};await assert.rejects(mutate('group.send',{id:'g',content:'fixture'}));assert.equal(calls.length,1,'changed chat composer must discard dry preview');
 reset();eco.pendingIntent={project:'p2',view:'discussion'};await assert.rejects(mutate('room.create'));assert.equal(calls.length,0);
 reset();ctx.api=async(p,b)=>{calls.push({p,b});ctx.aiProjectId='p2';return {project_id:'p1',rev:8};};await refresh();assert.equal(domain.value.rev,8);assert.equal(calls.length,1);assert(!calls[0].b,'Refresh is read-only');
 console.log('Ecosystem UI PASS: dry/apply same revision, project/view switch, cancelled/edited/replaced form, stale refresh; no model calls');
})().catch(e=>{console.error(e);process.exit(1)});
