const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
const context={data:{projects:[{id:'p',stages:['执行','复核']}],tasks:[{id:'t',project:'p',stage:'执行',status:'已完成'}]},aiProjectId:'p',aiProject:{actions:[{id:'a',project_id:'p',task_id:'t',status:'finished'},{id:'b',project_id:'p',status:'failed'},{id:'foreign',project_id:'q',status:'running'}]}};
vm.createContext(context);
function run(from,to){const start=html.indexOf(from),end=html.indexOf(to,start);assert(start>=0&&end>start);vm.runInContext(html.slice(start,end),context);}
run('function stageIndexFor(', 'function phaseTimelineStates(');
run('function phaseTimelineStates(', '\nfunction ');
run('function osProjectStages()', 'function osTaskMarks(');
const before=JSON.stringify(context);const stages=context.osProjectStages();
assert.equal(stages[0].actions.length,1);assert.equal(stages[1].actions.length,0);assert.equal(stages[2].actions[0].id,'b');assert.equal(JSON.stringify(context),before);
run('function rdDeliveryState(', 'function rdDeliveryMarkup(');
const c={project:{id:'p'},actions:context.aiProject.actions,results:[{project_id:'p',verification_status:'UNVERIFIED',outcome:'SUCCESS'},{project_id:'q',verification_status:'VERIFIED'}]};
const snapshot=JSON.stringify(c),state=context.rdDeliveryState(c);assert.equal(state.active,0);assert.equal(state.done,1);assert.equal(state.failed,1);assert.equal(state.unverified,1);assert.equal(JSON.stringify(c),snapshot);
run('function rdProjectChangeExplanation(', 'function rdProjectChangeMarkup(');
const changes=context.rdProjectChangeExplanation({project:{id:'p'},actions:[{id:'a',project_id:'p'}],results:[{action_id:'a',project_id:'p',verification_status:'UNVERIFIED'}],events:[{project_id:'p',type:'agent.connected',timestamp:'3'},{project_id:'p',type:'agent.finish',entity_type:'action',entity_id:'a',source_action:'a',timestamp:'2',before:{status:'running'},after:{status:'finished'}},{project_id:'p',type:'result.success',source_action:'a',timestamp:'1'}]});
assert.equal(changes.rows.length,1);assert(changes.rows[0].reason.includes('仍未独立核验'));assert(!changes.rows[0].reason.includes('result res-'));
run('const rdEnglish = {','(function rdLanguageController()');
assert.equal(context.rdTranslateUI('项目状态','en'),'Project status');assert.equal(context.rdTranslateUI('项目状态','zh-CN'),'项目状态');assert.equal(context.rdTranslateUI('2 / 3 完成','en'),'2 / 3 completed');assert.equal(context.rdTranslateUI('陌生科研原文','en'),'陌生科研原文');assert.equal(context.rdTranslateUI('UNVERIFIED','en'),'UNVERIFIED');
assert.equal(context.rdTranslateUI('分批回包 3 / 5 · 总摘要尚未完成','en'),'Batch responses 3 / 5 · Final summary is not complete');
assert(context.rdTranslateUI('登记记录将分 5 批处理，再合并为一份总结。每批及汇总均计入模型用量，全部完成前不生成行动建议。','en').includes('No action suggestion'));
assert(context.rdIsOriginalHeader({closest:()=>({})},''));assert(!context.rdIsOriginalHeader({closest:()=>({})},'project'));
context.osNodeAttrs=()=>'';context.esc=String;context.osTaskMarks=()=>'';context.osDisclosure=()=>'';
run('function osJourney()', 'function rdDeliveryState(');const journey=context.osJourney();assert(journey.includes('1 / 1 完成'));assert(!journey.includes('2 / 2 完成'),'Task and its bound action must not be counted twice');
assert(html.includes("localStorage.setItem('yanxu-ui-language',locale)"));assert(html.includes('protectedSelector'));assert(html.includes('input,textarea,pre,code,option,#projects,.rd-brand'));assert(html.includes('id="rd-interface-language"'));
for(const s of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi))new Function(s[1]);
console.log('PASS: project isolation, immutable delivery counts, explicit stages, unbound actions, meaningful change grouping, unverified completion, bilingual catalog, script compilation. DOM locale persistence requires live browser check.');

(async()=>{
 const calls=[],clicks={};const button={setAttribute(){},addEventListener(k,f){clicks[k]=f;}};
 const document={documentElement:{},querySelectorAll:()=>[],getElementById:()=>button,createElement:()=>button,
   querySelector:()=>({prepend(){}}),body:{}};
 const runtime={document,localStorage:{getItem:()=>null,setItem(){}},MutationObserver:class{observe(){}},
   rdTranslateUI:context.rdTranslateUI,Promise,WeakMap,api:async(path,body)=>{calls.push({path,body});},toast:()=>assert.fail('Unexpected save failure')};
 vm.createContext(runtime);
 const controller=html.slice(html.indexOf('(function rdLanguageController(){'),html.indexOf('</script>',html.indexOf('(function rdLanguageController(){'))).replace('__UI_LANGUAGE__','en');
 vm.runInContext(controller,runtime);
 assert.equal(document.documentElement.lang,'en','Server preference must survive empty native localStorage');
 clicks.click();await new Promise(resolve=>setImmediate(resolve));
 assert.equal(document.documentElement.lang,'zh-CN');
 assert.deepEqual(calls,[{path:'ui/preferences',body:{language:'zh-CN'}}]);
 console.log('PASS: native restart locale initialization and language-only persistence.');
})().catch(e=>{console.error(e);process.exit(1)});
