/* Standalone app shell. The shared discussion/radar components never load Yanxu's UI. */
let aiView=APP,aiProjectId='',aiInspectorOpen=innerWidth>=1080,data={projects:[]};
const $=id=>document.getElementById(id);
function appApplyTheme(theme){document.documentElement.dataset.theme=theme==='dark'?'dark':'light';}
try{appApplyTheme(localStorage.getItem('rd-theme'));}catch(_){appApplyTheme('light');}
window.addEventListener('storage',event=>{if(event.key==='rd-theme')appApplyTheme(event.newValue);});
function appToggleTheme(){
 const next=document.documentElement.dataset.theme==='dark'?'light':'dark';appApplyTheme(next);
 try{localStorage.setItem('rd-theme',next);}catch(_){}
 const button=document.querySelector('[data-theme-toggle]');if(button)button.textContent=next==='dark'?'使用浅色外观':'使用深色外观';
}
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path,body){
 const response=await fetch('/api/'+path,{method:body?'POST':'GET',headers:{Authorization:'Bearer '+APP_TOKEN,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});
 const value=await response.json();if(!response.ok)throw Error(value.error||'读取失败');return value;
}
async function loadState(){const current=await api('apps?app='+APP);data.projects=current.spaces;return current;}
function aiProjectPicker(){return '<select aria-label="记录空间">'+data.projects.map(p=>'<option value="'+esc(p.id)+'" '+(p.id===aiProjectId?'selected':'')+'>'+esc(p.personal?'个人空间':p.name+' · 续芽项目')+'</option>').join('')+'</select>';}
function render(){document.body.dataset.inspector=aiInspectorOpen?'open':'closed';aiRenderContent();aiRenderInspector();if(innerWidth<1080&&aiInspectorOpen){const close=document.createElement('button');close.className='eco-button';close.type='button';close.textContent='关闭详情';close.onclick=()=>{aiInspectorOpen=false;render();};$('inspector').prepend(close);}}
let aiRenderContent=()=>{},aiRenderInspector=()=>{},aiRefresh=()=>{};
function aiOpen(mode){if(mode!==APP){window.open('/apps/'+mode+'/?project='+encodeURIComponent(aiProjectId),'_blank','noopener');return;}aiView=mode;render();aiRefresh();}
async function aiSelectProject(id){
 aiProjectId=id;try{localStorage.setItem('yanxu-app-space-'+APP,id);}catch(_){}
 const q=new URLSearchParams(location.search);q.set('project',id);q.delete('item');history.replaceState(null,'','?'+q);render();await aiRefresh();
}
let lastViewportNarrow=innerWidth<1080;
window.addEventListener('resize',()=>{const narrow=innerWidth<1080;if(narrow&&!lastViewportNarrow){aiInspectorOpen=false;render();}lastViewportNarrow=narrow;});
let previousUnread=new Set(),badgeInitialized=false;
function appUpdateBadge(inbox){
 if(APP!=='discussion')return;
 const unread=inbox.filter(i=>i.status==='unread'),ids=new Set(unread.map(i=>i.id));$('inboxBadge').textContent=unread.length||'';
 if(unread.some(i=>!previousUnread.has(i.id))||(!badgeInitialized&&unread.length)){
  const notice=$('appReminder');notice.hidden=false;notice.innerHTML='雷达送来了 '+unread.length+' 条待讨论项。确认后才会启动模型。<button type="button" data-read>查看收件箱</button><button type="button" data-hide>收起</button>';
  notice.querySelector('[data-read]').onclick=()=>{appOpenInbox();notice.hidden=true;};notice.querySelector('[data-hide]').onclick=()=>notice.hidden=true;
 }
 if(!unread.length)$('appReminder').hidden=true;
 previousUnread=ids;badgeInitialized=true;
}
function appSetSection(inbox){$('appInbox').classList.toggle('selected',inbox);$('appHome').classList.toggle('selected',!inbox);}
function settingsDialog(title,content){
 let d=$('appSettingsDialog');if(!d){d=document.createElement('dialog');d.id='appSettingsDialog';d.className='eco-dialog';document.body.append(d);}
 d.innerHTML='<h2>'+title+'</h2>'+content+'<p class="eco-form-error" role="alert"></p><div class="eco-actions"><button type="button" data-close>关闭</button></div>';d.querySelector('[data-close]').onclick=()=>d.close();if(!d.open)d.showModal();return d;
}
async function appSettings(){
 const status=await api('agent-connection?project_id='+encodeURIComponent(aiProjectId)),space=aiProjectId;
 const d=settingsDialog('连接与设置','<h3>外观</h3><button class="eco-button" type="button" data-theme-toggle>'+(document.documentElement.dataset.theme==='dark'?'使用浅色外观':'使用深色外观')+'</button><ol class="eco-setup-steps"><li>连接本机 Codex，并完成账号登录。</li><li>在聊天信息中管理模型与助手，选择接口提供的模型。</li><li>把配置好的成员加入群聊，再选择谁来回复。</li></ol><p class="eco-muted">当前空间：'+esc(data.projects.find(p=>p.id===space)?.name)+ '。角色由讨论室配置；雷达推送和收件箱不调用模型。</p><h3>共享 Codex 连接</h3><p>'+esc(status.connected?(status.authenticated?'已连接并登录':'已连接，尚未登录'):'未连接')+'</p><button class="eco-button" type="button" data-connection>'+(status.enabled?'暂停连接':'连接 Codex')+'</button><button class="eco-button" type="button" data-login>浏览器登录</button><details><summary>外部助手（高级接入）</summary><p class="eco-muted">支持能使用 MCP 的外部 Agent。配置使用本空间提出建议的权限，生成后需在客户端注册并完成握手。</p><label class="eco-field">连接名称<input name="agentName" maxlength="80" placeholder="例如：外部核查者"></label><button class="eco-button" type="button" data-agent>生成空间连接</button></details>');
 d.querySelector('[data-theme-toggle]').onclick=appToggleTheme;
 const report=e=>{d.querySelector('[role=alert]').textContent=e.message;};
 d.querySelector('[data-connection]').onclick=()=>{
  const enabled=!status.enabled;
  const confirm=settingsDialog(enabled?'启用共享连接':'暂停共享连接','<p class="eco-muted">'+(enabled?'启动本机 Codex 通道。每轮发送内容仍需单独确认；连接、心跳不调用模型。':'暂停后不会启动新的 Codex 讨论调用。')+'</p><label class="eco-check"><input type="checkbox" required data-confirm>我确认此连接设置</label><button class="eco-button" type="button" data-apply>确认</button>');
  confirm.querySelector('[data-apply]').onclick=async()=>{try{if(!confirm.querySelector('[data-confirm]').checked)throw Error('请先确认设置');const body={enabled,if_revision:status.revision,consent:'codex-persistent-management-v1'};await api('agent-connection',{...body,dry:true});if(!confirm.open||!confirm.querySelector('[data-confirm]')?.checked||space!==aiProjectId)throw Error('空间或窗口已变化，请重新查看');await api('agent-connection',body);await appSettings();}catch(e){confirm.querySelector('[role=alert]').textContent=e.message;}};
 };
 d.querySelector('[data-login]').onclick=()=>{
  const confirm=settingsDialog('登录 Codex','<p class="eco-muted">为本机共享连接登录账号。会打开登录页面，登录本身不启动讨论。</p><button class="eco-button" type="button" data-start>打开登录页面</button>');
  confirm.querySelector('[data-start]').onclick=async()=>{try{const value=await api('agent-connection/login',{if_revision:status.revision,consent:'codex-browser-login-v1'});if(value.auth_url)window.open(value.auth_url,'_blank','noopener');else confirm.querySelector('[role=alert]').textContent=value.error||'登录流程已启动，请查看状态';}catch(e){confirm.querySelector('[role=alert]').textContent=e.message;}};
 };
 d.querySelector('[data-agent]').onclick=async()=>{
  try{
   const name=d.querySelector('[name=agentName]').value.trim();if(!name)throw Error('请填写连接名称');if(space!==aiProjectId)throw Error('空间已变化，请重新打开设置');
   const value=await api('agents/connect',{project_id:space,name,type:'external',permission:'PROPOSE',contract_mode:'strict_v2'});
   const output=settingsDialog('保存外部连接','<p class="eco-muted">包含私有令牌，只显示在本机。请保存到对应客户端；配置生成不表示已经连接。首次调用 project.get_context，然后领取讨论请求。</p><label class="eco-field">MCP 配置<textarea readonly></textarea></label>');output.querySelector('textarea').value=JSON.stringify(value.mcp_config,null,2);await aiRefresh();
  }catch(e){report(e);}
 };
}
async function bootApp(){
 document.title=APP==='discussion'?'聊天室':'雷达';$('appBrand').textContent=APP==='discussion'?'◌ 聊天室':'◎ 雷达';$('appHome').textContent=APP==='discussion'?'群聊':'关注与变化';$('appInbox').hidden=APP!=='discussion';
 document.querySelector('.app-sidebar>.app-caption').textContent=APP==='discussion'?'群聊与多模型讨论':'关注来源与变化';
 if(!document.querySelector('.eco-peer-nav')){const nav=document.createElement('nav');nav.className='radar-peer-nav eco-peer-nav';nav.setAttribute('aria-label','续芽应用');nav.innerHTML=[['research','▦','工作台','/'],['discussion','◌','聊天室','/apps/discussion/'],['radar','◎','雷达','/apps/radar/']].map(([id,glyph,label,url])=>'<a href="'+url+'" '+(APP===id?'aria-current="page"':'')+'><span aria-hidden="true">'+glyph+'</span>'+label+'</a>').join('');document.querySelector('.app-brand').after(nav);}
 $('appHome').onclick=()=>appOpenHome();$('appInbox').onclick=()=>appOpenInbox();$('appSettings').onclick=()=>appSettings().catch(e=>settingsDialog('连接与设置', '<p>'+esc(e.message)+'</p>'));
 try{
  let current=await loadState();
  if(!current.initialized){const body={ifRev:current.rev};await api('apps',{...body,dry:true});await api('apps',body);current=await loadState();}
  const query=new URLSearchParams(location.search);let saved;try{saved=localStorage.getItem('yanxu-app-space-'+APP);}catch(_){}
  aiProjectId=[query.get('project'),saved,current.personal_id].find(id=>data.projects.some(p=>p.id===id));
  render();await aiRefresh();if(query.get('inbox')==='1')appOpenInbox(query.get('item'));else if(query.get('item'))appOpenItem(query.get('item'));
 }catch(e){$('content').innerHTML='<p class="app-error">'+esc(e.message)+'</p><button type="button" onclick="location.reload()">重新读取</button>';}
}
