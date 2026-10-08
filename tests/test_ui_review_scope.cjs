const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const source=fs.readFileSync(path.join(__dirname,'../ecosystem.js'),'utf8'),dialogs=[],writes=[];
const ctx={aiView:'discussion',aiProjectId:'p1',document:{getElementById:()=>null},location:{search:''},URLSearchParams,setInterval(){},
  data:{projects:[{id:'p1'}]},aiOpen(){},aiRenderContent(){},aiRenderInspector(){},aiRefresh(){},render(){},
  esc:s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;')};
vm.createContext(ctx);for(const name of ['ecosystem_state.js','ecosystem_client.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../'+name),'utf8'),ctx);
vm.runInContext(source.replace('  navigation();\n  setInterval',`  this.fixture={domain,newReview};dialog=(title,body,label,callback)=>{dialogs.push({title,body,label,callback});return {querySelector:()=>({})};};mutate=async(op,values)=>{writes.push({op,values});return {id:'synthetic-draft'};};render=()=>{};\n  navigation();\n  setInterval`),Object.assign(ctx,{dialogs,writes}));
ctx.fixture.domain.value={project_id:'p1',profiles:[],context:{decisions:[{id:'d1',title:'判断'}],tasks:[{id:'t1',title:'<untrusted>'}],results:[{id:'r1',summary:'未核验失败'}]}};
function values(selected){return {get:name=>({title:'合成草稿',question:'Q',material_title:'M',material:'selected material',review_of:'d1'})[name]||'',getAll:name=>selected[name]||[]};}
(async()=>{
  ctx.fixture.newReview();assert(dialogs[0].body.includes('&lt;untrusted>'));assert(!/name="context_[^"]+"[^>]+checked/.test(dialogs[0].body),'No records preselected');
  await dialogs[0].callback(values({}),undefined,()=>true);assert.equal(writes[0].op,'review.create');assert.deepEqual(JSON.parse(JSON.stringify(writes[0].values.context_selection)),{tasks:[],decisions:[],results:[]});assert.equal(writes[0].values.review_of,'d1');
  await dialogs[0].callback(values({context_tasks:['t1'],context_results:['r1']}),undefined,()=>true);assert.deepEqual(JSON.parse(JSON.stringify(writes[1].values.context_selection)),{tasks:['t1'],decisions:[],results:['r1']});
  console.log('Review scope UI PASS: unchecked records by default, explicit selected IDs wired to create, original decision retained, escaped record text; no model start');
})().catch(e=>{console.error(e);process.exit(1)});
