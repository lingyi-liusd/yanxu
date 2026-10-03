const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
const iso=d=>[d.getFullYear(),String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0')].join('-');
const ctx={weekStart:s=>{const d=new Date(s+'T00:00:00');d.setDate(d.getDate()-(d.getDay()+6)%7);return iso(d)},addDays:(s,n)=>{const d=new Date(s+'T00:00:00');d.setDate(d.getDate()+n);return iso(d)}};
vm.createContext(ctx);vm.runInContext(html.slice(html.indexOf('function rdCalendarDates('),html.indexOf('function weekTasks()')),ctx);
for(const anchor of ['2024-02-15','2026-02-15','2026-10-02','2026-12-31']){
 const days=ctx.rdCalendarDates(anchor,'month');assert.equal(days.length%7,0);assert.equal(new Date(days[0]+'T00:00:00').getDay(),1);assert(days.includes(anchor.slice(0,7)+'-01'));assert.equal(new Set(days).size,days.length);
 assert.equal(ctx.rdCalendarDates(anchor,'week').length,7);
}
assert(ctx.rdCalendarDates('2024-02-15','month').includes('2024-02-29'));
const tasks=[{id:'a',start:'2026-10-02',end:'2026-10-02'},{id:'b'},{id:'note',start:'2026-10-02',noteType:'note'}], before=JSON.stringify(tasks);
assert.equal(ctx.rdCalendarMarks(tasks,'2026-10-02').length,1);assert.equal(ctx.rdCalendarMarks(tasks,'2026-10-02')[0].label,'开始 / 截止');assert.equal(JSON.stringify(tasks),before);
vm.runInContext(html.slice(html.indexOf('function rdTimelineData('),html.indexOf('function rdTimelineNode(')),ctx);
const agents=[{id:'a',name:'Codex',project_id:'p'},{id:'b',name:'Codex',project_id:'p'},{id:'idle',name:'新模型',project_id:'p'},{id:'foreign',project_id:'q'}];
const events=[{id:'1',seq:1,actor:'a',source_action:'x',project_id:'p',summary:'DeepSeek 文字不是身份'},{id:'2',seq:2,actor:'b',source_action:'x',project_id:'p'},{id:'3',seq:3,actor:'a',source_action:'x',project_id:'p'},{id:'4',seq:4,actor:'system',project_id:'p'},{id:'5',seq:5,actor:'foreign',project_id:'q'}];
const graph=ctx.rdTimelineData(events,agents,'p');assert.equal(graph.events.length,4);assert.equal(graph.groups.length,3);assert.equal(graph.groups[0].events.length,2);assert(graph.lanes.some(a=>a.id==='idle'));assert(!graph.lanes.some(a=>a.name==='DeepSeek'));assert(!graph.lanes.some(a=>a.id==='foreign'));assert.equal(new Set(graph.groups.flatMap(g=>g.events.map(e=>e.id))).size,4);
assert(html.includes('loaded.agents=rows[1]'));assert(html.includes('data-cal-mode'));assert(html.includes('data-timeline-mode'));assert(html.includes('if(!aiView) { try { await loadState(); render(); }'));
console.log('Calendar/timeline PASS: leap/year/month/week boundaries; no invented dates; immutable tasks; real project-scoped Agent lanes; idle new Agent visible; action grouping retains originals; read-only live refresh');
async function refresh(view,name){
 let callback;const counts={state:0,render:0,refresh:0,focus:0};
 const c={aiView:view,aiRefreshTimer:0,clearTimeout:()=>{},setTimeout:fn=>{callback=fn;return 1},loadState:async()=>counts.state++,render:()=>counts.render++,aiRefresh:()=>counts.refresh++,loadDailyFocus:async()=>counts.focus++};
 vm.createContext(c);vm.runInContext(html.slice(html.indexOf('function aiEventArrived('),html.indexOf('if (window.rdEventStream) [')),c);c.aiEventArrived(name);await callback();return counts;
}
(async()=>{
 assert.deepEqual(await refresh('events','agent.connected'),{state:0,render:0,refresh:1,focus:0});
 assert.deepEqual(await refresh('','task.updated'),{state:1,render:1,refresh:0,focus:0});
 console.log('Live hooks PASS: Agent handshake refreshes timeline; calendar task events reload state without summary/model invocation');
})().catch(e=>{console.error(e);process.exitCode=1;});
