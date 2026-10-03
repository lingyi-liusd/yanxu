const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
for(const m of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g))new vm.Script(m[1]);
const esc=s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
const nodes={},calls=[];
const setting={revision:8,enabled:true,connected:true,authenticated:true,model_selection:{ready:false,models:[{model:'recommended',is_default:true},{model:'other'}]}};
const manager={workspace:{path:'/synthetic',revision:4},source_bridge:{revision:2,folders:['/synthetic'],enabled:false}};
const ctx={aiProjectId:'p',aiConnectionBusy:false,esc,field:()=>'',osDisclosure:()=>'',osManagerCadenceText:()=>'',toast:()=>{},aiRefresh:async()=>{},$:id=>nodes[id],api:async(p,b)=>{calls.push({p,b});return p.startsWith('agent-connection?')?setting:manager;}};
vm.createContext(ctx);
vm.runInContext(html.slice(html.indexOf('function osSetupMarkup('),html.indexOf('aiRenderToday = osRenderToday;')),ctx);
vm.runInContext(html.slice(html.indexOf('async function osPickFolder('),html.indexOf('async function osSourceIndex(')),ctx);
vm.runInContext(html.slice(html.indexOf('async function osSourceSettings('),html.indexOf('function osManagerReview(')),ctx);
vm.runInContext(html.slice(html.indexOf('async function osModelSettings('),html.indexOf('function aiEventArrived(')),ctx);
function reset(){calls.length=0;ctx.aiProjectId='p';ctx.aiConnectionBusy=false;for(const id of ['form','managementModel','managementModelConsent','managementModelSave','managementModelCancel','managementChosen','managementRecommended','sourcePick','sourceRoot','sourcePreview','sourceSave','sourceCancel','sourceLocal','sourceSend','sourceDocuments','sourceFolders','sourceThreads'])nodes[id]={value:'',checked:false,disabled:false};nodes.sourceFolders.value='/synthetic';nodes.modal={open:false,showModal(){this.open=true},close(){this.open=false}};}
const ordinary=ctx.api;
(async()=>{
 const markup=ctx.osSetupMarkup(setting,manager);assert(markup.includes('data-ai-action="source-scope"'));assert(markup.includes('data-ai-action="persistent-model"'));assert(!markup.includes('已授权'));assert(html.includes('AI 设置 · Agents'));
 reset();await ctx.osModelSettings();assert.equal(nodes.managementModel.value,'');assert(nodes.managementModelSave.disabled);nodes.managementRecommended.onclick();assert.equal(nodes.managementModel.value,'recommended');assert(!nodes.managementModelConsent.checked);assert(nodes.managementModelSave.disabled);assert.equal(calls.length,1,'Choosing a recommendation is not a save or model call');
 nodes.managementModelConsent.checked=true;nodes.managementModelConsent.onchange();nodes.managementModel.value='other';nodes.managementModel.onchange();assert(!nodes.managementModelConsent.checked);
 // A consent change during the dry-run must not commit an old model selection.
 nodes.managementModelConsent.checked=true;nodes.managementModelConsent.onchange();ctx.api=async(p,b)=>{calls.push({p,b});if(b?.dry)nodes.managementModelConsent.checked=false;return {};};await nodes.managementModelSave.onclick();assert.equal(calls.length,2);
 ctx.api=ordinary;reset();await ctx.osSourceSettings();assert(!nodes.form.innerHTML.includes(' checked'));assert(nodes.form.innerHTML.includes('高级设置 · 路径与对话'));nodes.sourceLocal.checked=nodes.sourceSend.checked=nodes.sourceDocuments.checked=true;
 ctx.api=async(p,b)=>{calls.push({p,b});return {path:'/synthetic/child',cancelled:false};};await nodes.sourcePick.onclick();assert.equal(nodes.sourceFolders.value,'/synthetic/child','A child selection replaces the broad default, not retains it');assert(!nodes.sourceLocal.checked && !nodes.sourceSend.checked && !nodes.sourceDocuments.checked);assert(calls.every(x=>!x.p.includes('sources')||!x.b));
 nodes.sourceLocal.checked=true;const before=nodes.sourceFolders.value;ctx.api=async()=>({cancelled:true});await nodes.sourcePick.onclick();assert.equal(nodes.sourceFolders.value,before);assert(nodes.sourceLocal.checked,'Cancel leaves the draft unchanged');
 // Late folder responses cannot edit another project or replacement dialog.
 let release;ctx.api=()=>new Promise(r=>release=r);const picker=nodes.sourcePick.onclick();ctx.aiProjectId='other';release({path:'/wrong'});await picker;assert.equal(nodes.sourceFolders.value,before);
 ctx.api=ordinary;reset();await ctx.osSourceSettings();nodes.sourceLocal.checked=true;ctx.api=async(p,b)=>{calls.push({p,b});if(b?.dry){nodes.sourceSave={};}return {};};await nodes.sourceSave.onclick();assert.equal(calls.filter(x=>x.b).length,1,'A replaced dialog cannot apply its old preview');
 ctx.api=ordinary;reset();await ctx.osSourceSettings();nodes.sourceLocal.checked=true;ctx.api=async(p,b)=>{calls.push({p,b});if(b?.dry){nodes.sourceFolders.value='/changed';nodes.sourceFolders.oninput();}return {};};await nodes.sourceSave.onclick();assert.equal(calls.filter(x=>x.b).length,1,'Editing scope invalidates the pending consent');
 console.log('Setup UX PASS: prominent entry, live recommendation without auto-selection, separate unchecked grants, narrower folders, cancel/switch/replaced-dialog/edit-during-preview guards');
})().catch(e=>{console.error(e);process.exitCode=1});
