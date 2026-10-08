const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const dialogs=[],writes=[],nodes=Object.fromEntries(['resolution','question','keywords','interval'].map(name=>[name,{value:'',readOnly:true}]));
const ctx={aiView:'radar',aiProjectId:'p1',document:{getElementById:()=>null},location:{search:''},URLSearchParams,setInterval(){},data:{projects:[{id:'p1'}]},
  aiOpen(){},aiRenderContent(){},aiRenderInspector(){},aiRefresh(){},render(){},esc:s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;'),dialogs,writes,nodes};
vm.createContext(ctx);for(const name of ['ecosystem_state.js','ecosystem_client.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../'+name),'utf8'),ctx);
const source=fs.readFileSync(path.join(__dirname,'../ecosystem.js'),'utf8');
vm.runInContext(source.replace('  navigation();\n  setInterval',`  this.fixture={domain,resultWatchForm,resultObservationProposals,watchResultHistory,resultReferenceMarkup};dialog=(title,body,label,callback)=>{dialogs.push({title,body,label,callback});return {querySelector:selector=>nodes[selector.slice(6,-1)]};};mutate=async(op,values)=>{writes.push({op,values});return {};};render=()=>{};\n  navigation();\n  setInterval`),ctx);
const original={question:'Original question',keywords:['cost'],interval_minutes:60},proposed={...original,question:'Original question\nRegistered negative result'};
const candidate={id:'proposal',watch_id:'watch',watch_name:'<feed>',source:{result:{id:'r1',outcome:'failure',summary:'<negative result>',verification_status:'UNVERIFIED',source_ref:'synthetic://result',source_version:'v1'},task:{title:'Task'},action:{goal:'Check'},recheck_conditions:'Unknown'},source_hash:'source',basis_hash:'basis',target:{rule:original,object_rev:9,enabled:false},proposed,can_resolve:true,notice:'Review the result',boundary:'Suggestion only'};
const state={project_id:'p1',result_observation:{candidates:[candidate],total:1,shown:1,boundary:'Only existing scope'}};
(async()=>{
  const overview=ctx.fixture.resultObservationProposals(state);assert(overview.includes('&lt;negative result>'));assert(overview.includes('data-eco="result-watch"'));assert(!overview.includes('room.start'));
  ctx.fixture.resultWatchForm(candidate);const form=dialogs.at(-1);assert(form.body.includes('value="keep" selected'));assert(form.body.includes('type="checkbox" required'));assert(form.body.includes('readonly'));
  nodes.resolution.onchange({target:{value:'modify'}});assert.equal(nodes.question.value,proposed.question);assert.equal(nodes.interval.readOnly,false);
  const values=choice=>({get:name=>({resolution:choice,question:'Human edited question',keywords:'evidence, cost',interval:'120',reason:'Explicit scope and uncertainty'})[name]});
  await form.callback(values('modify'));const modified=writes.at(-1);assert.equal(modified.op,'watch.result.resolve');assert.equal(modified.values.expected_rev,9);assert.equal(modified.values.basis_hash,'basis');assert.equal(modified.values.consent,'result-observation-adjustment-v1');assert(!('enabled' in modified.values));assert(!('url' in modified.values));assert.equal(modified.values.rule.interval_minutes,120);
  nodes.resolution.onchange({target:{value:'keep'}});assert.equal(nodes.question.value,original.question);assert.equal(nodes.question.readOnly,true);
  await form.callback(values('keep'));assert.deepEqual(JSON.parse(JSON.stringify(writes.at(-1).values.rule)),original);
  assert(ctx.fixture.resultReferenceMarkup(candidate.source.result,state).includes('mode=observe&project=p1'));
  const receipt={resolution:'keep',reason:'<reason>',source:candidate.source,source_hash:'h',before:original,after:original};assert(ctx.fixture.watchResultHistory({result_adjustments:[receipt]}).includes('&lt;reason>'));
  assert(!writes.some(w=>/room.start|watch.check|watch.save/.test(w.op)),'Resolving suggestions cannot invoke model/fetch/general watch authorization');
  console.log('Result observation UI PASS: source escaping, explicit keep/modify, required consent/reason, source+target versions, authority fields excluded, history and project result link');
})().catch(e=>{console.error(e);process.exit(1)});
