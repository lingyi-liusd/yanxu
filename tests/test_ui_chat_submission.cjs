const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const source=fs.readFileSync(path.join(__dirname,'../ecosystem.js'),'utf8');
const start=source.indexOf('    form.onsubmit=async e=>',source.indexOf('  function chatContent('));
const handler=source.slice(start,source.indexOf('\n    };',start)+7).replace('form.onsubmit=','handler=');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
function fixture(){
 const wait=deferred(),submit={disabled:false,isConnected:true},error={textContent:''},newError={textContent:''},calls=[],clears=[];
 let current=true;
 const form={isConnected:true,querySelector:s=>s==='[type=submit]'?submit:error};
 const ctx={form,submitting:false,sameConversation:()=>current,payload:()=> 'frozen',eco:{},origin:{project:'p1',id:'g1'},group:{id:'g1',object_rev:2},host:{querySelector:()=>({querySelector:()=>newError})},
  FormData:class{get(k){return {content:'sent text',history:'0'}[k];}getAll(){return [];}},
  YanxuChat:{capture(){},clear(...args){clears.push(args);}},mutate:async(...args)=>{calls.push(args);return wait.promise;},domain:{error:''},render(){ctx.renders++;},renders:0,chatRendered:{id:'g1'},update(){submit.disabled=false;}};
 vm.createContext(ctx);vm.runInContext(handler,ctx);
 return {ctx,wait,submit,error,newError,calls,clears,leave(){current=false;form.isConnected=false;}};
}
(async()=>{
 const f=fixture(),event={preventDefault(){}};
 const first=f.ctx.handler(event);f.submit.disabled=false;await f.ctx.handler(event);assert.equal(f.calls.length,1,'Separate in-flight lock survives readiness changes');f.wait.resolve({});await first;
 assert.deepEqual(f.clears,[['p1','g1','sent text']]);assert.equal(f.ctx.renders,1);
 for(const outcome of ['failure','success']){
  const f=fixture(),saving=f.ctx.handler(event);f.leave();
  if(outcome==='failure')f.wait.reject(Error('Original group failed'));else f.wait.resolve({});
  await saving;assert.equal(f.newError.textContent,'');assert.equal(f.ctx.domain.error,'');assert.equal(f.ctx.renders,0,'Old completion cannot redraw new conversation');
 }
 const g=fixture(),saving=g.ctx.handler(event);g.wait.reject(Error('Current failure'));await saving;assert.equal(g.error.textContent,'Current failure');assert.equal(g.submit.disabled,false);
 console.log('Chat submission PASS: single flight, original submitted text, stale success/failure isolation and current failure recovery');
})().catch(e=>{console.error(e);process.exit(1)});
