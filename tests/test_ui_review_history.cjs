const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const dialogs=[],writes=[],reads=[];
const ctx={aiView:'discussion',aiProjectId:'p1',document:{getElementById:()=>null},location:{search:''},URLSearchParams,setInterval(){},
  api:async(path)=>{reads.push(path);return {project_version:'fresh-target',context:{context_hash:'legacy-wide'}};},
  data:{projects:[{id:'p1',name:'个人空间'},{id:'p2',name:'正式项目'}]},aiOpen(){},aiRenderContent(){},aiRenderInspector(){},aiRefresh(){},render(){},
  esc:s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;'),dialogs,writes,reads};
vm.createContext(ctx);for(const name of ['ecosystem_state.js','ecosystem_client.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../'+name),'utf8'),ctx);
const source=fs.readFileSync(path.join(__dirname,'../ecosystem.js'),'utf8');
vm.runInContext(source.replace('  navigation();\n  setInterval',`  this.fixture={domain,historicalReview,adopt,preview};dialog=(title,body,label,callback)=>{dialogs.push({title,body,label,callback});return {querySelector:()=>({})};};mutate=async(op,values)=>{writes.push({op,values});return {id:'new-history'};};render=()=>{};\n  navigation();\n  setInterval`),ctx);
const room={id:'old',object_rev:7,title:'<original>',question:'Q',context:{context_hash:'h',tasks:[{id:'t0',title:'Old task'}],decisions:[],results:[]},materials:[{id:'M1',title:'<material>',content:'old'}],used_calls:1,max_calls:1,participants:[],messages:[]};
ctx.fixture.domain.value={project_id:'p1',project_version:'current-project',profiles:[],context:{project:{app_owner:'discussion'},tasks:[],decisions:[],results:[]}};
(async()=>{
  ctx.fixture.historicalReview(room);const form=dialogs.at(-1);
  assert(form.body.includes('&lt;material>'));assert(form.body.includes('required maxlength="2000"'));
  assert(!/name="history_[^"]+"[^>]+checked/.test(form.body),'History must not be preselected');
  const values={get:name=>({title:'H',question:'Q',reason:'Explicit old scope',constraints:''})[name]||'',getAll:name=>name==='history_materials'?['M1']:[]};
  await form.callback(values);
  const write=writes.at(-1);assert.equal(write.op,'review.create');assert(!('materials' in write.values));
  assert.deepEqual(JSON.parse(JSON.stringify(write.values.history_source)),{room_id:'old',expected_rev:7,context_hash:'h',reason:'Explicit old scope',selection:{materials:['M1'],tasks:[],decisions:[],results:[]}});
  assert.deepEqual(JSON.parse(JSON.stringify(write.values.context_selection)),{tasks:[],decisions:[],results:[]});assert.equal(write.values.max_calls,1);
  room.history_source=write.values.history_source;ctx.fixture.preview(room);assert(dialogs.at(-1).body.includes('Explicit old scope'));
  ctx.fixture.adopt(room,'room');await dialogs.at(-1).callback({get:name=>({destination:'p2',target:'task',title:'T',rationale:'R'})[name]});
  assert.deepEqual(reads,['ecosystem?project_id=p2']);assert.equal(writes.at(-1).values.target_project_version,'fresh-target');assert(!('target_context_hash' in writes.at(-1).values));
  assert(!writes.some(w=>w.op==='room.start'),'No model start during historical draft creation');
  console.log('History UI PASS: explicit unchecked selection/reason, preserved source version, new draft budget, human preview and fresh target object version');
})().catch(e=>{console.error(e);process.exit(1)});
