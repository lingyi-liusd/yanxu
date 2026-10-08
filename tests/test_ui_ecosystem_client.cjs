const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const ctx={};vm.createContext(ctx);
for(const name of ['ecosystem_state.js','ecosystem_client.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../'+name),'utf8'),ctx);
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};};
function fixture(){
  const store=ctx.YanxuEcosystemState.create(),calls=[],reads=[],changes=[];
  let scope={project:'p1',view:'discussion',active:true},handler=()=>{throw Error('Unexpected transport call');};
  const client=ctx.YanxuEcosystemClient.create({store,scope:()=>scope,request:(p,b)=>{calls.push({p,b});return handler(p,b);},
    captureIntent:()=>null,intentValid:()=>true,afterWrite:async()=>{},onRead:r=>reads.push(r),onChange:()=>changes.push(store.value)});
  return {store,client,calls,reads,changes,setScope:s=>scope=s,setHandler:h=>handler=h};
}
(async()=>{
  // Two project reads may overlap; a previous request/finally cannot replace or unlock the newer one.
  const f=fixture(),old=deferred(),fresh=deferred();f.setHandler(p=>p.endsWith('p1')?old.promise:fresh.promise);
  const oldRead=f.client.refresh();await f.client.refresh();assert.equal(f.calls.length,1,'Same scope coalesces polling');
  f.setScope({project:'p2',view:'radar',active:true});const newRead=f.client.refresh();assert.equal(f.calls.length,2,'New project can read without waiting');
  old.reject(Error('Old project failed'));await oldRead;assert.equal(f.store.error,'');await f.client.refresh();assert.equal(f.calls.length,2,'Old finally must not clear new busy state');
  fresh.resolve({project_id:'p2',rev:9,rooms:[]});await newRead;assert.equal(f.store.value.project_id,'p2');assert.equal(f.changes.length,1);

  // Leaving the view invalidates both success and failure; returning identical data preserves the object identity used by a dry write.
  const g=fixture(),late=deferred();g.setHandler(()=>late.promise);const request=g.client.refresh();g.setScope({project:'p1',view:'project',active:false});late.resolve({project_id:'p1',rev:8});await request;assert.equal(g.store.value,null);assert.equal(g.reads.length,0);
  g.setScope({project:'p1',view:'discussion',active:true});const snapshot={project_id:'p1',rev:9,rooms:[]};g.store.value=snapshot;
  g.setHandler(async()=>({...snapshot,rooms:[]}));await g.client.refresh();assert.strictEqual(g.store.value,snapshot);assert.equal(g.changes.length,0);
  g.setHandler(async()=>({project_id:'p1',rev:8,rooms:[]}));await g.client.refresh();assert.strictEqual(g.store.value,snapshot);assert.equal(g.reads.length,1,'Regressed read must not update a badge');
  g.setHandler(async()=>({project_id:'p2',rev:10}));await g.client.refresh();assert(g.store.error.includes('不符'));assert.strictEqual(g.store.value,snapshot);
  g.setHandler(async()=>snapshot);await g.client.refresh();assert.equal(g.store.error,'');assert.equal(g.changes.length,2,'Error recovery must rerender even for the same record');

  // A record change during dry requires fresh human intent; never silently commit against it.
  for(const replace of [false,true]){
    const w=fixture();w.store.value={project_id:'p1',rev:8};w.setHandler(async()=>{if(replace)w.store.value={project_id:'p1',rev:8};else w.store.value.rev=9;return {preview:true};});
    await assert.rejects(w.client.mutate('room.create',{title:'Selected'}));assert.equal(w.calls.length,1);
  }

  // A committed write starts a fresh read even if a poll was pending; its old response cannot overwrite the new record.
  const w=fixture(),poll=deferred();w.store.value={project_id:'p1',rev:8};let gets=0;
  w.setHandler(async(p,b)=>b?(b.dry?{preview:true}:{rev:9,item:{id:'saved'}}):(++gets===1?poll.promise:{project_id:'p1',rev:9,rooms:[{id:'saved'}]}));
  const pending=w.client.refresh();assert.equal((await w.client.mutate('room.create',{title:'Selected'})).id,'saved');
  assert.equal(gets,2);poll.resolve({project_id:'p1',rev:8,rooms:[]});await pending;assert.equal(w.store.value.rooms[0].id,'saved');
  assert.equal(w.calls.filter(c=>c.b&&!c.b.dry).length,1);assert.equal(w.calls.find(c=>c.b&&!c.b.dry).b.ifRev,8);

  // Apps first-use creation also obeys the current opening intent; no dry/apply after navigation.
  const a=fixture();a.setHandler(async()=>({initialized:false,rev:8}));await assert.rejects(a.client.spaces('radar',()=>false));assert.equal(a.calls.length,1);
  console.log('Ecosystem client PASS: scope overlap/order, stale errors, same-record identity, no revision regression, write preview invalidation, commit refresh, no hidden calls');
})().catch(e=>{console.error(e);process.exit(1)});
