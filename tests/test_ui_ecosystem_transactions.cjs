const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const ctx={};vm.createContext(ctx);
for(const name of ['ecosystem_state.js','ecosystem_client.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../'+name),'utf8'),ctx);
function fixture(){
 const store=ctx.YanxuEcosystemState.create(),calls=[],warnings=[];
 let scope={project:'p1',view:'discussion',active:true},intent={valid:true};
 store.value={project_id:'p1',rev:8};
 const config={store,scope:()=>scope,captureIntent:()=>intent,intentValid:i=>i.valid,
  request:async(p,b)=>{calls.push({p,b});return b?(b.dry?{preview:true}:{rev:9,item:{id:'saved'}}):{project_id:'p1',rev:9};},
  afterWrite:async()=>{},onChange:()=>{},onRead:()=>{},onWriteWarning:m=>warnings.push(m)};
 return {store,calls,warnings,config,setScope:s=>scope=s,setIntent:i=>intent=i,client:()=>ctx.YanxuEcosystemClient.create(config)};
}
(async()=>{
 // Resolve a target project only inside the original write intent. A newer modal cannot authorize the old adoption.
 for(const change of ['cancel','replace','project','revision']){
  const f=fixture(),wait=deferred(),original=f.config.captureIntent(),client=f.client();
  const saving=client.mutate('room.adopt',async()=>{await wait.promise;return {id:'old-room',target_project_id:'p2'};});
  if(change==='cancel'||change==='replace')original.valid=false;
  if(change==='replace')f.setIntent({valid:true});
  if(change==='project')f.setScope({project:'p2',view:'discussion',active:true});
  if(change==='revision')f.store.value.rev=9;
  wait.resolve();await assert.rejects(saving);assert.equal(f.calls.length,0,change+' must reject before preview');
 }
 const f=fixture(),client=f.client();await client.mutate('room.adopt',async()=>({id:'old-room',target_project_id:'p2'}));
 assert.equal(f.calls[0].b.id,'old-room');assert.equal(f.calls[1].b.ifRev,8);assert.equal(f.calls.filter(c=>c.b&&!c.b.dry).length,1);
 // A readback failure cannot turn an acknowledged write into a failed submission or skip the domain read.
 for(const failure of ['host','domain','both']){
  const f=fixture();if(failure!=='domain')f.config.afterWrite=async()=>{throw Error('host unavailable');};
  if(failure!=='host'){const request=f.config.request;f.config.request=async(p,b)=>{if(!b){f.calls.push({p,b});throw Error('domain unavailable');}return request(p,b);};}
  const result=await f.client().mutate('room.create',{title:'synthetic'});
  assert.equal(result.id,'saved');assert.equal(f.calls.filter(c=>!c.b).length,1,'Domain read still runs');
  assert.equal(f.calls.filter(c=>c.b&&!c.b.dry).length,1,'No mutation retry');
  assert.equal(f.warnings.length,1);assert(f.warnings[0].includes('已保存'));assert(f.store.error.includes('已保存'));
 }
 // A late readback notice identifies the saved origin and leaves the new space's error alone.
 const moved=fixture();moved.config.afterWrite=async()=>{moved.setScope({project:'p2',view:'radar',active:true});throw Error('host unavailable');};
 moved.config.request=async(p,b)=>{moved.calls.push({p,b});return b?(b.dry?{preview:true}:{rev:9,item:{id:'saved'}}):{project_id:'p2',rev:10};};
 await moved.client().mutate('room.create',{title:'synthetic'});
 assert(moved.warnings[0].includes('原空间 p1'));assert.equal(moved.store.value.project_id,'p2');assert.equal(moved.store.error,'');
 console.log('Ecosystem transactions PASS: frozen async intent, cancelled/replaced/navigated/revised adoption, committed write survives readback failure; no retries or model calls');
})().catch(e=>{console.error(e);process.exit(1)});
