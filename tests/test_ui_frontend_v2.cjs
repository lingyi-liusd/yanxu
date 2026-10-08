/* Renderer/structure contracts only: browser geometry remains a separate gate. */
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const root=path.join(__dirname,'..'),source=fs.readFileSync(path.join(root,'ecosystem.js'),'utf8'),css=fs.readFileSync(path.join(root,'ecosystem.css'),'utf8');
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ctx={document:{activeElement:null},esc,age:()=> '10/8 11:01',labels:{unread:'待复核'},button:(action,label,extra='')=>`<button data-eco="${action}" ${extra}>${label}</button>`,empty:(title,copy)=>`<div>${title}${copy}</div>`};vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(root,'chat_ui.js'),'utf8'),ctx);
vm.runInContext(source.slice(source.indexOf('  function radarReader('),source.indexOf('  function radarLayout(')),ctx);
const state={watches:[{id:'w',name:'合成来源'}]},alert={id:'a',title:'<变化>',status:'unread',watch_id:'w',created_at:'2026-10-08',note:'影响尚未核验',added:'<新增>',removed:'原文',url:'https://example.com',before_hash:'123',after_hash:'456',deliveries:[]};
const original=JSON.stringify(alert);let html=ctx.radarReader(state,alert);assert(html.includes('推送只创建待讨论项，不启动模型'));assert.equal((html.match(/class="eco-primary"/g)||[]).length,1);assert(html.includes('&lt;变化&gt;'));assert(html.includes('&lt;新增&gt;'));
alert.deliveries=[{id:'i/a',target:'project test',status:'unread'}];html=ctx.radarReader(state,alert);assert(html.includes('class="eco-button eco-primary radar-delivery-next"'));assert(html.includes('project=project%20test&inbox=1&item=i%2Fa'));assert(!html.includes('data-eco="push-alert" class="eco-primary"'));assert(html.indexOf('打开待讨论项')<html.indexOf('推送到其他位置'));assert(html.includes('确认问题、回复成员与发送范围后，才会启动模型'));
alert.deliveries=[];assert.equal(JSON.stringify(alert),original,'Rendering is read-only');
const group={id:'g',name:'合成群',members:[{id:'m',name:'合成成员',model:'model-x',engine:'codex'}],entries:[],timeline:[],used_calls:0};
const chatState={project_id:'p',groups:[group],connection:{connected:false}};
html=ctx.YanxuChat.render(chatState,group,'',esc,()=>'',ctx.button);
for(const term of ['chat-member-copy','未连接','model-x','chat-start-state','data-send-scope','data-send-consent','发送本条消息、选定历史与空间简介给所选成员','name="history"','name="reply"'])assert(html.includes(term),term);
assert(html.includes('最近 20 条历史'));assert(!html.includes('aria-label="管理群成员"'),'Header avoids duplicate add button; member strip retains member management');
const crowded={...group,pending_inbox:[1,2,3].map(i=>({id:String(i),title:'发现 '+i}))};html=ctx.YanxuChat.render({...chatState,groups:[crowded]},crowded,'',esc,()=>'',ctx.button);assert(html.includes('雷达送来 3 条待讨论发现'));assert.equal((html.match(/data-eco="discuss-inbox-group"/g)||[]).length,1);assert(html.includes('data-eco="group-inbox"'));
for(const selector of ['.chat-list-tools input','.chat-member-copy','.chat-scope-summary','.radar-next-action','.radar-secondary-actions','@media(min-width:851px) and (max-width:1120px)','@media(min-width:651px) and (max-width:850px)','prefers-reduced-motion:reduce'])assert(css.includes(selector),selector);
console.log('Frontend v2 PASS: compact member metadata, explicit send scope, one pending preview, delivered CTA hierarchy, encoded links, escaped read-only render, responsive and motion selectors; synthetic/static only.');
