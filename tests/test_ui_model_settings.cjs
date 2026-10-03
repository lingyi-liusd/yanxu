const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
const esc=s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
const nodes={},calls=[],messages=[];
let setting={revision:8,enabled:true,connected:true,authenticated:true,last_heartbeat:'now',model_selection:{effective_model:'old-model',ready:false,error:'需要选择',models:[{model:'new-model',is_default:true},{model:'other-model'}]}};
const ctx={esc,encodeURIComponent,osDisclosure:()=>'',osApplySetupReceipt:()=>{},aiConnectionBusy:false,aiProjectId:'p1',aiAgentsUnavailable:false,$:id=>nodes[id],toast:x=>messages.push(x),aiRefresh:async()=>{},api:async(p,b)=>{calls.push({p,b});return b?{}:setting;}};
vm.createContext(ctx);
vm.runInContext(html.slice(html.indexOf('function osPersistentConnectionState('),html.indexOf('function osAgentConnectionTree()')),ctx);
vm.runInContext(html.slice(html.indexOf('async function osModelSettings()'),html.indexOf('function aiEventArrived(')),ctx);
function reset(){calls.length=0;ctx.aiProjectId='p1';for(const id of ['form','managementModel','managementModelConsent','managementModelSave','managementModelCancel','managementChosen','managementRecommended'])nodes[id]={value:'',checked:false,disabled:false};nodes.modal={open:false,showModal(){this.open=true},close(){this.open=false}};}
function select(){nodes.managementModel.value='new-model';nodes.managementModelConsent.checked=true;nodes.managementModelConsent.onchange();}
(async()=>{
 assert.equal(ctx.osPersistentConnectionState(setting).state,'partial');
 assert.equal(ctx.osPersistentConnectionState({...setting,model_selection:undefined}).state,'success');
 assert.equal(ctx.osPersistentConnectionState({...setting,connected:false}).state,'failure');
 reset();await ctx.osModelSettings();assert.equal(calls.length,1);assert(nodes.managementModelSave.disabled);assert(nodes.form.innerHTML.includes('value="">请选择模型'));assert(!nodes.form.innerHTML.includes(' selected'));assert(nodes.form.innerHTML.includes('全部可用模型'));assert(nodes.form.innerHTML.includes('value="other-model"'));assert(!nodes.form.innerHTML.includes('<summary>其他模型</summary>'));
 nodes.managementModel.value='new-model';nodes.managementModel.onchange();assert(nodes.managementModelSave.disabled,'Selection alone is not consent');
 select();assert(!nodes.managementModelSave.disabled);await nodes.managementModelSave.onclick();
 assert.equal(calls.length,3);assert.equal(calls[1].p,'agent-connection/model');assert.equal(calls[1].b.dry,true);assert.equal(calls[2].b.model,'new-model');assert.equal(calls[2].b.if_revision,8);assert.equal(calls[2].b.consent,'codex-management-model-v1');assert(!nodes.modal.open);
 reset();await ctx.osModelSettings();select();nodes.managementModelCancel.onclick();await nodes.managementModelSave.onclick();assert.equal(calls.length,1);
 reset();await ctx.osModelSettings();select();ctx.aiProjectId='p2';await nodes.managementModelSave.onclick();assert.equal(calls.length,1);
 reset();await ctx.osModelSettings();select();let release;ctx.api=(p,b)=>{calls.push({p,b});return new Promise(r=>release=r)};const save=nodes.managementModelSave.onclick();await Promise.resolve();ctx.aiProjectId='p2';release({});await save;assert.equal(calls.length,2,'A stale dry preview cannot apply');
 ctx.api=async(p,b)=>{calls.push({p,b});if(b)throw Error('stale revision');return setting};reset();await ctx.osModelSettings();select();await nodes.managementModelSave.onclick();assert(nodes.modal.open);assert(!nodes.managementModelSave.disabled);assert.equal(calls.length,2,'Failure does not retry');
 setting={...setting,connected:false};reset();await ctx.osModelSettings();assert(!nodes.modal.open);assert.equal(calls.length,1);
 assert(html.includes('osConnectionModelMarkup(connection)'));assert(html.includes('模型设置待确认'));assert(html.includes('data-ai-action="persistent-model"'));
 console.log('Model UI PASS: connected/usable split, advertised choices, explicit consent, versioned dry/apply, stale/cancel/failure no retry or permission expansion');
})().catch(e=>{console.error(e);process.exit(1)});
