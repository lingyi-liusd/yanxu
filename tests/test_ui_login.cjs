const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
const nodes={},calls=[],timers=[];
for(const id of ['form','codexLoginOpen','codexLoginStatus','codexLoginClose'])nodes[id]={click(){this.clicked=true},removeAttribute(k){delete this[k]}};
nodes.modal={open:false,showModal(){this.open=true},close(){this.open=false}};
const ctx={URL,$:id=>nodes[id],setInterval:cb=>{timers.push(cb);return timers.length},clearInterval:()=>{},toast:()=>{},aiRefresh:async()=>{},api:async(p,b)=>{calls.push({p,b});return {auth_url:'https://auth.openai.com/authorize?state=synthetic',authenticated:false}}};
vm.createContext(ctx);vm.runInContext(html.slice(html.indexOf('async function osOpenCodexLogin('),html.indexOf('async function osControlPersistentConnection(')),ctx);
(async()=>{
 await ctx.osOpenCodexLogin({revision:4});assert(nodes.modal.open);assert(nodes.codexLoginOpen.clicked);assert(nodes.codexLoginOpen.href.startsWith('https://auth.openai.com/'));
 assert.equal(calls[0].p,'agent-connection/login');assert.equal(calls[0].b.if_revision,4);assert.equal(calls[0].b.consent,'codex-browser-login-v1');
 ctx.api=async()=>({authenticated:true});await timers[0]();assert(!nodes.modal.open);
 ctx.api=async()=>({auth_url:'https://evil.test/',authenticated:false});await assert.rejects(()=>ctx.osOpenCodexLogin({revision:4}),/安全/);
 assert(html.includes('登录并连接 Codex'));assert(html.includes("label:connection.state === 'waiting_login' ? '等待登录' : '需要登录'"));
 console.log('Login UI PASS: automatic browser entry, fallback link, verified status, explicit scope, hostile URL rejected');
})().catch(e=>{console.error(e);process.exit(1)});
