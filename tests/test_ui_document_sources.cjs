const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
for(const match of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g))new vm.Script(match[1]);
const esc=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
const markup={esc};vm.createContext(markup);
vm.runInContext(html.slice(html.indexOf('function osSourceIndexItemMarkup('),html.indexOf('function osWorkspaceMarkup(')),markup);
let out=markup.osSourceIndexItemMarkup({reference:'/fake/<script>.docx',state:'read_partial',size:6000,offset:100,accepted:1,
 reading_details:{text_basis:'extracted_utf8',text_bytes:100,scope:'plain text only',gaps:['<script> unparsed image']}},'model_reply');
assert(out.includes('仍有内容缺口'));assert(out.includes('提取文字字节 100 / 100'));assert(out.includes('原文件 6000 字节'));
assert(out.includes('&lt;script>'));assert(!out.includes('<script>'));assert(!out.includes(' open'));
const code=html.slice(html.indexOf('async function osSourceSettings('),html.indexOf('function osManagerReview('));
async function form(mode,documents){
 const calls=[],nodes={form:{innerHTML:''},modal:{open:false,showModal(){this.open=true},close(){this.open=false}},sourceCancel:{},sourceSave:{},
 sourcePick:{},sourceRoot:{},sourcePreview:{},sourceLocal:{checked:true},sourceSend:{checked:false},sourceDocuments:{checked:documents},sourceFolders:{value:'/synthetic'},sourceThreads:{value:''}};
 const ctx={aiProjectId:'p',esc,$:id=>nodes[id],osDisclosure:()=>'',osManagerCadenceText:()=>'',osApplySetupReceipt:()=>{},aiRefresh:async()=>{},toast:()=>{},
 api:async(route,body)=>{calls.push({route,body});if(!body)return {workspace:{path:'/synthetic',revision:7},source_bridge:{revision:3}};
 if(body.dry&&mode==='cancel')nodes.modal.close();if(body.dry&&mode==='switch')ctx.aiProjectId='q';return {};}};
 vm.createContext(ctx);vm.runInContext(code,ctx);await ctx.osSourceSettings();
 assert(nodes.form.innerHTML.includes('id="sourceDocuments" type="checkbox">'));assert(!nodes.form.innerHTML.includes(' checked'));
 await nodes.sourceSave.onclick();const writes=calls.filter(c=>c.body);
 assert.equal(writes.length,mode==='ok'?2:1);assert.equal(writes[0].body.if_revision,3);assert.equal(writes[0].body.workspace_revision,7);
 assert.equal(writes[0].body.document_text_enabled,documents);assert.equal(writes[0].body.document_consent,documents?'selected-document-text-v1':'');
 assert.equal(writes[0].body.send_content,false);
}
(async()=>{for(const mode of ['ok','cancel','switch'])for(const documents of [false,true])await form(mode,documents);
 console.log('Document sources UI PASS: opt-in, separate consent, partial gaps, text/raw byte distinction, escaped disclosures, cancel/switch during dry run');
})().catch(e=>{console.error(e);process.exitCode=1});
