const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(require('path').join(__dirname,'../ecosystem.js'),'utf8');
const calls=[],dialogs=[],buttons=[],closeHandlers=[],notices=[],copied=[];
const feedback={textContent:''};
const tokenInput={type:'password',value:'fixture-not-a-real-token',selected:0,select(){this.selected++;}};
const actions={prepend(...nodes){buttons.push(...nodes);}},modal={open:true,form:null,querySelector(selector){return selector==='form'?this.form:selector==='[name=project_token]'?tokenInput:selector==='.eco-form-error'?feedback:actions;},addEventListener(name,callback,options){assert.equal(name,'close');assert(options.once);closeHandlers.push(callback);}};
const ctx={aiView:'discussion',aiProjectId:'p1',FormData:class{constructor(form){return form.entries;}},
  document:{getElementById(id){return id==='ecoDialog'?modal:null;},createElement(){return {};},hidden:false},
  location:{search:''},URLSearchParams,setInterval(){return 0;},data:{projects:[{id:'p1'}]},esc:String,$:()=>modal,
  aiOpen(){},aiRenderContent(){},aiRenderInspector(){},aiRefresh(){},render(){},toast(message){notices.push(message);},
  navigator:{clipboard:{async writeText(value){copied.push(value);}}}};
vm.createContext(ctx);
for(const name of ['ecosystem_state.js','ecosystem_client.js'])vm.runInContext(fs.readFileSync(require('path').join(__dirname,'../'+name),'utf8'),ctx);
vm.runInContext(source.replace('  navigation();\n  setInterval',
  `  this.fixture={eco,domain,externalAgentForm};dialog=(title,body,label,callback)=>{dialogs.push({title,body,label,callback});if(title==='外部连接已登记')modal.form={entries:[]};return modal;};refresh=async()=>{};render=()=>{};\n  navigation();\n  setInterval`),Object.assign(ctx,{dialogs,modal}));
const {eco,domain,externalAgentForm}=ctx.fixture;
function reset(){calls.length=0;dialogs.length=0;buttons.length=0;closeHandlers.length=0;notices.length=0;copied.length=0;tokenInput.type='password';tokenInput.value='fixture-not-a-real-token';tokenInput.selected=0;ctx.aiProjectId='p1';ctx.aiView='discussion';modal.open=true;
  modal.form={entries:[['name','Test client'],['permission','PROPOSE']]};
  domain.value={project_id:'p1',rev:8,context:{project:{name:'Test project'}}};
  ctx.api=async(path,body)=>{calls.push({path,body});return body.dry?{preview:true}:{permission:'PROPOSE',token:'fixture-not-a-real-token'};};}
(async()=>{
  reset();externalAgentForm();const first=dialogs[0];
  assert(first.body.includes('PROPOSE')&&first.body.includes('READ'));assert(!first.body.includes('EXECUTE'));
  await first.callback(new Map(modal.form.entries),modal.form);
  assert.equal(calls.length,2);assert(calls[0].body.dry);assert.equal(calls[1].body.ifRev,8);
  assert.equal(calls[1].body.project_id,'p1');assert.equal(calls[1].body.permission,'PROPOSE');
  assert.equal(dialogs[1].title,'外部连接已登记');assert(dialogs[1].body.includes('type="password" readonly'));
  const copy=buttons.find(b=>b.textContent==='复制项目令牌'),reveal=buttons.find(b=>b.textContent==='显示项目令牌');
  assert(copy&&reveal);assert.equal(tokenInput.type,'password');
  await copy.onclick();assert.deepEqual(copied,['fixture-not-a-real-token']);assert.equal(tokenInput.type,'password');
  ctx.navigator.clipboard=undefined;await copy.onclick();assert(notices.at(-1).includes('手动复制'));assert(feedback.textContent.includes('手动复制'),'Failure is visible inside top-layer dialog');assert.equal(tokenInput.type,'password','Copy failure must not reveal by itself');
  reveal.onclick();assert.equal(tokenInput.type,'text');assert.equal(reveal.textContent,'隐藏项目令牌');assert.equal(tokenInput.selected,1);
  reveal.onclick();assert.equal(tokenInput.type,'password');
  ctx.aiProjectId='p2';await copy.onclick();reveal.onclick();assert.equal(copied.length,1);assert.equal(tokenInput.type,'password','Wrong project cannot reveal old token');
  ctx.aiProjectId='p1';modal.open=false;reveal.onclick();assert.equal(tokenInput.type,'password');
  for(const close of closeHandlers)close();assert.equal(tokenInput.value,'');assert.equal(tokenInput.type,'password');
  ctx.navigator.clipboard={async writeText(value){copied.push(value);}};
  for(const change of ['project','view','cancel','edit','replace']){
    reset();externalAgentForm();const callback=dialogs[0].callback,form=modal.form;
    ctx.api=async(path,body)=>{calls.push({path,body});
      if(change==='project')ctx.aiProjectId='p2';if(change==='view')ctx.aiView='radar';
      if(change==='cancel')modal.open=false;if(change==='edit')form.entries[0][1]='changed';
      if(change==='replace')modal.form={entries:form.entries};return {preview:true};};
    await assert.rejects(callback(new Map(form.entries),form));assert.equal(calls.length,1,change);
    assert.equal(dialogs.length,1,'No token receipt after stale preview');
  }
  reset();externalAgentForm();const callback=dialogs[0].callback,form=modal.form;
  ctx.api=async(path,body)=>{calls.push({path,body});if(!body.dry)ctx.aiProjectId='p2';return {permission:'PROPOSE',token:'fixture-not-a-real-token'};};
  await callback(new Map(form.entries),form);assert.equal(calls.length,2);assert.equal(dialogs.length,1,'Late receipt must not show original project token in another project');
  console.log('External registration UI PASS: limited permission, dry/revisioned apply, stale form/project rejection, masked token, explicit reveal/manual-copy fallback, close clears token, no model calls');
})().catch(error=>{console.error(error);process.exit(1)});
