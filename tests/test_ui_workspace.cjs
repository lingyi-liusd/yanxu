const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(require('path').join(__dirname,'../index.html'),'utf8');
for(const match of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g))new vm.Script(match[1]);
const code=html.slice(html.indexOf('function osWorkspaceMarkup('),html.indexOf('async function osSourceSettings('));
const escape=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
const ctx={esc:escape};vm.createContext(ctx);vm.runInContext(code,ctx);
let out=ctx.osWorkspaceMarkup({workspace:{state:'needs_binding',suggested_path:'/old'}});
assert(out.includes('尚未绑定'));assert(out.includes('绑定不自动读取'));assert(out.includes('/old'));
out=ctx.osWorkspaceMarkup({workspace:{state:'ready',name:'<script>',path:'/safe'},source_bridge:{enabled:true,send_content:true,coverage:{indexed:140,processed:128,pending:12,inventory_complete:true}}});
assert(out.includes('&lt;script>'));assert(out.includes('value="128"'));assert(out.includes('待处理 12'));assert(out.includes('已处理不等于'));
out=ctx.osWorkspaceMarkup({source_bridge:{enabled:true,workspace_blocked:true,coverage:{indexed:140,processed:0,pending:140}}});assert(out.includes('旧正文已隔离'));
assert(html.includes('workspace_revision:workspace.revision'));assert(html.includes('data-ai-action="workspace-settings"'));
async function formTest(mode){
const calls=[],toasts=[],nodes={form:{},modal:{open:false,showModal(){this.open=true},close(){this.open=false}},workspacePick:{},workspacePreview:{},workspaceCancel:{},workspaceSave:{},workspaceConfirmScope:{checked:false},'field-workspaceRoot':{value:'/isolated'},'field-workspaceRelative':{value:'.'},'field-workspaceName':{value:'test'},'field-workspaceExclusions':{value:'tmp\n'}};
const test={aiProjectId:'p',esc:escape,$:id=>nodes[id],field:()=>'',osApplySetupReceipt:()=>{},toast:s=>toasts.push(s),aiRefresh:async()=>{},api:async(path,body)=>{calls.push({path,body});if(!body)return{revision:2,state:'needs_binding'};if(body.dry&&mode==='cancel')nodes.modal.close();if(body.dry&&mode==='switch')test.aiProjectId='other';return{revision:3};}};
vm.createContext(test);vm.runInContext(code,test);await test.osWorkspaceSettings();
await nodes.workspaceSave.onclick();assert.equal(calls.length,1);nodes.workspaceConfirmScope.checked=true;await nodes.workspaceSave.onclick();
const writes=calls.filter(c=>c.body);assert.equal(writes[0].body.dry,true);assert.equal(writes[0].body.if_revision,2);
assert.equal(writes.length,mode==='ok'?2:1);assert(writes.every(c=>c.path==='project/workspace'));
}
(async()=>{for(const mode of ['ok','cancel','switch'])await formTest(mode);console.log('Workspace UI PASS: separate unchecked consent, dry/revision binding, escaping, partial coverage and project-switch safety');})().catch(e=>{console.error(e);process.exitCode=1});
