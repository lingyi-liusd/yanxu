/* Additive companion surfaces; same project identity, local API and Apple-style panes. */
(() => {
  'use strict';
  const domain = YanxuEcosystemState.create();
  const eco = {projectState:null,spaces:[],selection:null,comparison:false,filter:'',tab:'groups',groupDetails:false,radarTab:'discoveries',radarStatus:'all',radarSource:'',radarQuery:'',radarReaderOpen:false,openSequence:0};
  const labels = {draft:'待开始',running:'讨论中',round_complete:'本轮完成',completed:'轮次已完成',stopped:'已停止',failed:'本轮失败',interrupted:'上次讨论中断',unread:'待复核',reviewed:'已查看',dismissed:'已忽略',seen:'已查看',discussed:'已建立讨论'};
  const fields = {position:'观点',evidence:'依据与待核实项',objections:'分歧与反例',next_step:'建议的下一步'};
  const active = () => ['discussion','radar'].includes(aiView);
  const safeState = () => domain.current(aiProjectId);
  const button = (action,label,extra='') => '<button class="eco-button '+(extra.includes('class="eco-primary"')?'eco-primary':'')+'" type="button" data-eco="'+action+'" '+extra.replace('class="eco-primary"','')+'>'+label+'</button>';
  const empty = (title,copy,actions='') => '<div class="eco-empty"><h3>'+title+'</h3><p>'+copy+'</p><div class="eco-actions">'+actions+'</div></div>';
  const age = value => value ? new Date(value).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '尚未检查';
  const selected = kind => (safeState()?.[kind==='inbox'?'inbox':kind+'s'] || []).find(i => i.id === eco.selection);

  const client = YanxuEcosystemClient.create({
    store:domain, scope:()=>({project:aiProjectId,view:aiView,active:active()}),
    request:(path,body)=>api(path,body), captureIntent:()=>eco.pendingIntent,
    intentValid:intent=>!intent||(intent.chat?intent.valid():(intent.project===aiProjectId&&intent.view===aiView&&intent.modal.open&&intent.modal.querySelector('form')===intent.form&&JSON.stringify([...new FormData(intent.form)])===intent.payload)),
    afterWrite:()=>loadState(), onChange:()=>render(),
    onRead:result=>{if(typeof appUpdateBadge==='function')appUpdateBadge(result.inbox||[]);}
  });
  async function refresh() { return client.refresh(); }
  async function mutate(operation,values={}) { return client.mutate(operation,values); }

  function navigation() {
    // App switching belongs to the peer-app launcher, not Yanxu's module navigation.
  }

  async function open(mode,id=null,initial=false) {
    const sequence=++eco.openSequence,project=aiProjectId,view=aiView;
    const current=()=>sequence===eco.openSequence&&project===aiProjectId&&view===aiView;
    eco.selection=id; eco.filter=''; eco.comparison=false;eco.radarSource='';eco.radarQuery='';eco.radarStatus='all';
    if(typeof STANDALONE_APP==='undefined'){
      const spaces=await client.spaces(mode,current);
      if(!current())return;
      eco.spaces=spaces.spaces;
      const requested=initial?new URLSearchParams(location.search).get('project'):null;if(requested&&eco.spaces.some(p=>p.id===requested))aiProjectId=requested;else if(!eco.spaces.some(p=>p.id===aiProjectId))aiProjectId=spaces.personal_id;
    }
    return aiOpen(mode);
  }

  function roomMessage(message) {
    const content = message.kind==='human' ? '<p>'+esc(message.content)+'</p>' : Object.entries(fields).map(([key,label])=>'<h4>'+label+'</h4><p>'+esc(message.output[key] || '未提供')+'</p>').join('');
    return '<article class="eco-message"><header><strong>'+esc(message.author)+'</strong><small>'+esc('第 '+message.round+' 轮 · '+(message.model || (message.kind==='human'?'人工记录':'外部 Agent 回复')))+'</small></header>'+content+'<h4>'+esc(message.kind==='human'?'人工补充':'AI 建议 · 未独立核验')+'</h4></article>';
  }

  function adoptedLink(room) {
    const receipt=(room.adoptions||[])[0]; if(!receipt) return '';
    const url='/?project='+encodeURIComponent(receipt.target_project_id||room.project_id)+'&'+(receipt.target==='task'?'task':'decision')+'='+encodeURIComponent(receipt.id);
    return '<a class="eco-button eco-primary" href="'+url+'">查看项目'+(receipt.target==='task'?'任务':'决策')+' →</a>';
  }
  function roomNext(room, project) {
    if(room.adopted_id) return '<section class="eco-next-step"><strong>已采纳：'+esc(room.adoptions?.[0]?.title||'项目记录')+'</strong><div class="eco-actions">'+adoptedLink(room)+'</div></section>';
    return '<section class="eco-next-step"><strong>把讨论变成下一步</strong><p>由你确认采纳理由，再保存为项目任务或决策。</p>'+button('adopt-room',project.app_owner?'保存下一步 / 送到续芽':'采纳为任务或决策',room.active||room.context_stale||(room.mode==='review'&&!room.brief)?'disabled':'class="eco-primary"')+'</section>';
  }
  function inboxNext(incoming) {
    return '<div class="eco-actions eco-next-step">'+(incoming.room_id?button(incoming.group_id?'open-inbox-group':'open-inbox-room','打开已创建的讨论','class="eco-primary"'):button(incoming.group_id?'discuss-inbox-group':'discuss-inbox','确认讨论设置','class="eco-primary" data-id="'+esc(incoming.id)+'"'))+(incoming.group_id&&!incoming.room_id?button('open-inbox-group','打开接收群聊'):'')+'</div>';
  }
  function content() {
    const state=safeState(), host=$('content');
    host.classList.toggle('chat-host',aiView==='discussion'&&eco.tab==='groups');
    if (!aiProjectId) { host.innerHTML=empty('先选择一个项目','讨论和雷达都围绕现有项目展开。可以从左侧建立或选择项目。'); return; }
    if (!state) { host.innerHTML=empty(domain.error?'暂时无法读取':'正在读取项目',esc(domain.error || '读取项目上下文与生态记录。'),button('refresh','重新读取')); return; }
    let html='';
    if(aiView==='discussion'&&eco.tab==='groups'){chatContent(state,host);return;}
    if (aiView==='discussion') {
      const room=selected('room'),incoming=selected('inbox');
      if(eco.tab==='inbox'){
        html=inboxContent(state,incoming);
      }else if (room) {
        const messages=eco.comparison?room.messages.filter(m=>m.kind==='agent'&&m.round===room.round):room.messages;
        html=button('back','‹ 全部评审')+'<div class="eco-heading"><div><h2>'+esc(room.title)+'</h2><p>'+esc(labels[room.status]||room.status)+' · 第 '+room.round+' / '+room.max_rounds+' 轮</p></div><div class="eco-actions">'+(room.mode==='review'?(room.brief?button('edit-brief','编辑简报',room.adopted_id?'disabled':''):''):button('compare',eco.comparison?'按时间阅读':'比较本轮观点'))+button('history-review','使用历史快照',room.active?'disabled':'')+button('export-room',room.mode==='review'?'导出简报':'导出记录',room.mode==='review'&&!room.brief?'disabled':'')+'</div></div><p class="eco-question">'+esc(room.question)+'</p>';
        if (room.context_stale) html+='<p class="eco-notice">本次评审依赖的记录已有变化。这份记录保留原上下文；继续执行或采纳前，请重新核对并建立新评审。</p>';
        if (room.failures.length) html+='<p class="eco-notice">'+room.failures.map(f=>esc(f.message)).join('<br>')+'</p>';
        html+=room.mode==='review'?YanxuReview.render(room):'<div class="'+(eco.comparison?'eco-comparison':'')+'">'+(messages.length?messages.map(roomMessage).join(''):empty('从同一个问题开始','首轮各角色独立提出观点；下一轮可以读取此前发言。结果由你判断和采纳。'))+'</div>';
        html+=roomNext(room,state.context.project);
        if (!room.active) html+='<div class="eco-actions" style="margin-top:20px">'+button('message','补充想法')+'</div>';
      } else {
        html='<div class="eco-heading"><div><h2>评审</h2><p>给出问题、材料和约束，形成可检查、可修订的判断简报。</p></div><div class="eco-actions">'+button('new-review','评审一个方案','class="eco-primary"')+button('new-room','高级讨论')+button('profiles','执行器设置')+'</div></div><input class="eco-search" id="ecoSearch" type="search" placeholder="搜索评审" aria-label="搜索评审" value="'+esc(eco.filter)+'">';
        const rooms=state.rooms.filter(r=>r.mode!=='group'&&(r.title+' '+r.question).includes(eco.filter));
        html+='<div class="eco-list">'+(rooms.length?rooms.map(r=>'<button class="eco-row" type="button" data-eco="select-room" data-id="'+esc(r.id)+'"><span><strong>'+esc(r.title)+'</strong><small>'+esc(r.participants.map(p=>p.name).join(' · ')+' / '+(labels[r.status]||r.status))+'</small></span><time>'+age(r.updated_at)+'</time></button>').join(''):empty('从你要决定的问题开始','选取材料，保留约束。不创建项目，也能完成一次评审。',button('new-review','评审一个方案')))+'</div>';
      }
    } else { html=radarLayout(state); }
    if(domain.error)html='<p class="eco-notice" role="alert">'+esc(domain.error)+'</p>'+html;
    host.innerHTML=html; bind(host);if(typeof YanxuReview!=='undefined')YanxuReview.bind(host);
    const radarSearch=$('radarSearch');if(radarSearch)radarSearch.oninput=e=>{eco.radarQuery=e.target.value;const caret=e.target.selectionStart;content();const next=$('radarSearch');next.focus();try{next.setSelectionRange(caret,caret);}catch(_){}};for(const [id,key] of [['radarStatus','radarStatus'],['radarSource','radarSource']]){const control=$(id);if(control)control.onchange=e=>{eco[key]=e.target.value;content();};}
    const search=$('ecoSearch'); if(search)search.oninput=e=>{eco.filter=e.target.value;content();const next=$('ecoSearch');next.focus();next.setSelectionRange(eco.filter.length,eco.filter.length);};
  }

  function inspector() {
    const state=safeState(), host=$('inspector');
    if(!state){host.innerHTML='';return;}
    const room=selected('room'),alert=selected('alert'),incoming=selected('inbox'), project=state.context.project;
    if(aiView==='discussion'&&eco.tab==='groups'){host.innerHTML=YanxuChat.inspector(selected('group'),esc,button);bind(host);return;}
    if(eco.tab==='inbox'){host.innerHTML=inboxInspector(state,incoming);bind(host);return;}
    if(aiView==='radar'&&!alert){
      const sources=(state.observations||[]).flatMap(o=>o.sources);
      host.innerHTML='<div class="radar-overview"><span class="radar-overline">SOURCE HEALTH</span><h2>来源状态</h2><p>最近一次检查的覆盖情况</p>'+sources.map(source=>'<div class="radar-health"><i class="'+esc(source.status)+'"></i><span><strong>'+esc(source.name)+'</strong><small>'+esc(({covered:'已成功覆盖',failed:'检查失败',stale:'材料已过期',not_checked:'待首次检查'})[source.status]||'待检查')+'</small></span></div>').join('')+'<section class="radar-next"><h3>发现 → 群聊 → 判断</h3><p>变化推送后成为待讨论项。由你确认问题与成员，再开始模型讨论。</p><a href="/apps/discussion/">打开聊天室 ↗</a></section><details><summary>查看覆盖详情</summary>'+observationCoverage(state)+'</details></div>';return;
    }
    let html='<div class="eco-inspector"><small class="eco-muted">'+esc(project.name)+'</small><h2>'+ (room?'讨论上下文':alert?'变化详情':'项目上下文')+'</h2><p>'+esc(project.goal||'项目尚未填写目标')+'</p>';
    if(room){
      html+='<section><h3>本轮角色</h3>'+room.participants.map(p=>'<div class="eco-role"><strong>'+esc(p.name)+'</strong><small>'+esc(p.model||'外部 Agent')+'</small></div>').join('')+'<dl><dt>轮次</dt><dd>'+room.round+' / '+room.max_rounds+'</dd><dt>已用配额</dt><dd>'+room.used_calls+' / '+room.max_calls+'</dd></dl>';
      if(['draft','round_complete'].includes(room.status)&&!room.context_stale)html+='<div class="eco-actions">'+(room.mode==='review'&&!room.participants.length?button('choose-executor','选择执行器'):button('start-room',room.round?'开始下一轮':'预览并开始'))+'</div>';
      if(room.active)html+='<p class="eco-muted">执行中，外部 Agent 可通过项目连接领取当前讨论请求。</p><div class="eco-actions">'+button('stop-room','停止本轮')+'</div>';
      if(room.source_change)html+='<section><h3>触发本次讨论的来源</h3><p>'+esc(room.source_change.title)+'</p><div class="eco-actions">'+button('open-source-alert','在雷达查看来源')+'</div></section>';
      if(room.execution_receipts?.length)html+='<details><summary>执行记录与配额对账</summary>'+room.execution_receipts.map(receipt=>'<p>'+esc(({reserved:'等待发送',dispatch_authorized:'已授权发送，尚未确认收到',dispatched:'已启动',reply_accepted:'已接收回复',failed_or_unknown:'失败或接收状态未知',interrupted_unknown:'重启后待对账',stop_requested_unknown:'已要求停止，消耗待对账'})[receipt.state]||receipt.state)+'<br><small>'+esc(receipt.detail)+'</small></p>').join('')+'</details>';html+='</section><section><h3>采纳与下一步</h3>'+(room.adopted_id?'<p>已采纳为项目'+(room.adoptions[0].target==='task'?'任务':'决策')+'：'+esc(room.adoptions[0].title)+'</p>'+adoptedLink(room):'<p>保留各角色的分歧，由你填写采纳理由并加入项目。</p><div class="eco-actions">'+button('adopt-room',project.app_owner?'保存下一步 / 送到续芽':'采纳为任务或决策',room.active||room.context_stale||(room.mode==='review'&&!room.brief)?'disabled':'')+'</div>')+'</section>';
    }else if(alert){
      html+='<section><h3>来源与版本</h3><p><a href="'+esc(alert.url)+'" target="_blank" rel="noopener noreferrer">打开原来源</a></p><dl><dt>前版本</dt><dd>'+esc(alert.before_hash.slice(0,12))+'</dd><dt>后版本</dt><dd>'+esc(alert.after_hash.slice(0,12))+'</dd><dt>关联决策</dt><dd>'+esc(alert.decision_ids.map(id=>state.context.decisions.find(d=>d.id===id)?.title||id).join('、')||'尚未指定')+'</dd></dl></section><section><h3>复核</h3><div class="eco-actions">'+button('review-alert','标记已查看')+button('dismiss-alert','忽略此变化')+'</div><p>'+esc(alert.review_note||'文字发生变化，尚未核验其对项目的影响。')+'</p><div class="eco-actions">'+button('push-alert','推送到收件箱或群聊')+button('adopt-alert',alert.adopted_id?'已加入项目':'建立复核任务',alert.adopted_id?'disabled':'')+'</div>'+ (alert.deliveries||[]).map(i=>'<p><a href="/apps/discussion/?project='+encodeURIComponent(i.target)+'&inbox=1&item='+encodeURIComponent(i.id)+'" target="_blank" rel="noopener">查看已送达记录 · '+esc(labels[i.status]||i.status)+'</a></p>').join('')+'</section>';
    }else{
      html+='<section><h3>共享记录</h3><p>默认保存到当前个人空间；选择关联续芽项目后，才带入该项目的记录。采纳由你确认。</p><div class="eco-actions">'+button('context','查看上下文')+button('copy-context','复制接续简报')+'</div></section>';
      if(aiView==='discussion')html+='<section><h3>角色</h3>'+state.profiles.map(p=>'<div class="eco-role"><strong>'+esc(p.name)+'</strong><small>'+esc(p.model||'外部 Agent')+'</small></div>').join('')+'<div class="eco-actions">'+button('profiles','管理角色')+'</div></section>';
      else html+='<section><h3>检查节奏</h3><p>可以手动检查，也可以按来源设置自动检查。自动检查仅在本机核心运行时生效；关闭页面不清空收件箱。</p></section>';
    }
    if(project.app_owner&&(state.context.tasks.length||state.context.decisions.length))html+='<section><h3>个人下一步与决策</h3>'+[...state.context.tasks,...state.context.decisions].map(i=>'<p>'+esc(i.title)+'<br><small>'+esc(i.note||'')+'</small></p>').join('')+'</section>';
    html+='<section><h3>记录范围</h3><p class="eco-muted">'+esc(state.context.boundary)+'</p></section></div>';
    host.innerHTML=html;bind(host);
  }


  let chatRendered=null;
  function chatContent(state,host){
    if(chatRendered)YanxuChat.capture(host,chatRendered.project,chatRendered.id);
    const group=selected('group');
    host.innerHTML=(domain.error?'<p class="eco-notice" role="alert">'+esc(domain.error)+'</p>':'')+YanxuChat.render(state,group,eco.filter,esc,age,button);
    if(group){
      const latest=[...(group.entries||[])].reverse().map(e=>(state.rooms||[]).find(r=>r.id===e.room_id)).find(r=>r&&!r.active&&r.messages?.some(m=>m.kind==='agent'));
      if(latest){const feed=host.querySelector('.chat-feed');feed.insertAdjacentHTML('beforeend','<div class="chat-system eco-next-step">'+(latest.adopted_id?adoptedLink(latest):button('open-group-review','整理本轮观点并保存下一步','data-id="'+esc(latest.id)+'"'))+'</div>');}
    }
    chatRendered=group?{project:aiProjectId,id:group.id}:null;
    bind(host);YanxuChat.restore(host,aiProjectId,group);
    const search=host.querySelector('#chatSearch');search.oninput=()=>{eco.filter=search.value;content();const next=host.querySelector('#chatSearch');next.focus();};
    const form=host.querySelector('#chatComposer');if(!form)return;
    const origin={project:aiProjectId,id:group.id,view:aiView};
    const payload=()=>JSON.stringify([...new FormData(form)]);
    const update=()=>{
      const ids=[...form.querySelectorAll('[name=reply]:checked')].map(n=>n.value), members=group.members.filter(m=>ids.includes(m.id)), names=members.map(m=>m.name);
      const blocked=members.filter(m=>YanxuChat.memberStatus(state,m).blocked);
      form.querySelector('[data-reply-target]').textContent=ids.length===group.members.length&&ids.length?'＠ 全体成员':ids.length?'＠ '+names.join('、'):'仅记录';
      const submit=form.querySelector('[type=submit]'); submit.disabled=!!group.active_room_id || !!blocked.length;
      submit.textContent=ids.length?'发送':'保存文字';submit.title=blocked.length?'先连接或取消选择暂不可用的成员':ids.length?'发送给 '+names.join('、'):'只保存文字';
      const hint=form.querySelector('[data-connection-hint]');
      hint.innerHTML=blocked.length?'<span>'+blocked.map(m=>esc(m.name+'：'+YanxuChat.memberStatus(state,m).label)).join('；')+'</span>'+button('connection-settings','连接与设置')+'<small>也可以在 ＠ 中取消选择这些成员，或仅保存文字。</small>':ids.length?'<small>发送后选定成员各回复一次；外部助手的实际响应以收到回复为准。</small>':'<small>本条仅保存文字，不调用模型。</small>';
      bind(hint);
    };update();form.querySelector('.chat-send-options').ontoggle=()=>YanxuChat.capture(host,origin.project,origin.id);form.oninput=()=>YanxuChat.capture(host,origin.project,origin.id);form.onchange=()=>{update();YanxuChat.capture(host,origin.project,origin.id);};
    form.querySelector('textarea').onkeydown=e=>{if(YanxuChat.shouldSend(e)){e.preventDefault();if(!form.querySelector('[type=submit]').disabled)form.requestSubmit();}};
    form.onsubmit=async e=>{e.preventDefault();const submit=form.querySelector('[type=submit]');if(submit.disabled)return;submit.disabled=true;const frozen=payload();const intent={chat:true,valid:()=>aiProjectId===origin.project&&aiView===origin.view&&eco.tab==='groups'&&eco.selection===origin.id&&form.isConnected&&payload()===frozen};eco.pendingIntent=intent;
      const fd=new FormData(form);YanxuChat.capture(host,origin.project,origin.id);try{await mutate('group.send',{id:group.id,expected_rev:group.object_rev,content:fd.get('content'),reply_profile_ids:fd.getAll('reply'),history_count:Number(fd.get('history')),consent:'group-chat-message-v1'});YanxuChat.clear(origin.project,origin.id);chatRendered=null;render();}
      catch(error){const target=form.isConnected?form:host.querySelector('#chatComposer');if(target)target.querySelector('.eco-form-error').textContent=error.message;else{domain.error=error.message;render();}}
      finally{if(eco.pendingIntent===intent)eco.pendingIntent=null;if(submit.isConnected)update();}
    };
  }
  function groupForm(existing){
    const state=safeState(),members=existing?.members||[];
    dialog(existing?'群聊设置':'创建群聊',input('name','群聊名称',existing?.name||'新群聊','required maxlength="80"')+'<p class="eco-muted">选择已配置的模型或 Agent，最多 6 位。可以先建群，再邀请成员。</p><div class="chat-member-choices">'+state.profiles.map(p=>'<label><input type="checkbox" name="member" value="'+esc(p.id)+'" '+(members.some(m=>m.id===p.id)?'checked':'')+'><span><strong>'+esc(p.name)+'</strong><small>'+esc(p.model||'外部 Agent')+'</small></span></label>').join('')+'</div>'+(!state.profiles.length?'<p>暂无模型配置。建群后在详情中点击“配置模型 / Agent”。</p>':''),'保存',async form=>{const item=await mutate(existing?'group.update':'group.create',{id:existing?.id,name:form.get('name'),profile_ids:form.getAll('member'),...(existing?{expected_rev:existing.object_rev}:{})});eco.tab='groups';eco.selection=item.id;render();});
  }

  async function pushChoices(state){
    const options=[],personal='ecosystem-personal-discussion';
    const routes=state.context.project.app_owner?[['personal',personal,'个人']]:[['project',state.project_id,'此项目'],['personal',personal,'个人']];
    for(const [mode,id,label] of routes){
      const destination=id===state.project_id?state:await client.readProject(id);
      options.push([JSON.stringify([mode,'']),label+'讨论收件箱']);
      for(const group of destination.groups||[])options.push([JSON.stringify([mode,group.id]),label+'群聊 · '+group.name]);
    }
    return options;
  }
  function incomingReplyReadiness(state,group,ids){
    const members=group.members.filter(m=>ids.includes(m.id));
    if(!members.length||members.length!==ids.length)return {allowed:false,message:'请至少选择一位有效的回复成员。'};
    const blocked=members.filter(m=>YanxuChat.memberStatus(state,m).blocked);
    return blocked.length?{allowed:false,message:blocked.map(m=>m.name+'：'+YanxuChat.memberStatus(state,m).label).join('；')+'。请先在连接与设置中处理，或取消选择这些成员。'}:{allowed:true,message:'确认后选定成员各回复一次；实际响应以收到回复为准。'};
  }
  async function discussIncoming(incoming){
    const state=safeState(),group=state.groups.find(g=>g.id===incoming?.group_id);
    if(!group||incoming.room_id||!['unread','seen'].includes(incoming.status))throw Error('此发现已处理或目标群不可用，请重新查看');
    const source=incoming.source_change;
    const modal=dialog('讨论雷达发现', '<p>送到群聊：'+esc(group.name)+'</p><h3>'+esc(source.title)+'</h3><details><summary>查看来源变化</summary><h4>新增或修改</h4><pre>'+esc(source.added||'无')+'</pre><h4>移除或修改前</h4><pre>'+esc(source.removed||'无')+'</pre></details>'+(source.diff_truncated?'<p>摘录已截断，请先核对原来源。</p>':'')+area('content','讨论的问题',source.brief?.question||'这次变化对我们有什么影响？','required maxlength="4000"')+'<fieldset><legend>回复成员</legend>'+group.members.map(m=>'<label class="eco-check"><input name="reply" type="checkbox" value="'+esc(m.id)+'" checked>'+esc(m.name)+'</label>').join('')+'</fieldset>'+select('history','带入群聊历史',[['0','不带入'],['5','最近5条'],['10','最近10条'],['20','最近20条']],'5')+'<label class="eco-check"><input type="checkbox" name="confirm" required>确认发送来源变化、上述问题、选定群历史与空间简介；每位选定成员回复一次</label>','确认并开始',async form=>{const ids=form.getAll('reply');const readiness=incomingReplyReadiness(state,group,ids);if(!readiness.allowed)throw Error(readiness.message);await mutate('group.send',{id:group.id,expected_rev:group.object_rev,inbox_id:incoming.id,inbox_expected_rev:incoming.object_rev,source_version:incoming.source_version,content:form.get('content'),reply_profile_ids:ids,history_count:Number(form.get('history')),consent:form.get('confirm')==='on'?'group-chat-message-v1':''});eco.tab='groups';eco.selection=group.id;render();});
    const hint=document.createElement('p');hint.className='eco-reply-readiness';hint.setAttribute('role','status');modal.querySelector('fieldset').after(hint);
    const update=()=>{const ids=[...modal.querySelectorAll('[name=reply]:checked')].map(n=>n.value),readiness=incomingReplyReadiness(state,group,ids);hint.textContent=readiness.message;modal.querySelector('[type=submit]').disabled=!readiness.allowed;};
    modal.querySelectorAll('[name=reply]').forEach(n=>n.addEventListener('change',update));update();
  }
  function radarReader(state,alert){
    if(!alert)return button('radar-close-reader','‹ 返回发现','data-radar-back')+empty('暂无可阅读的发现','请选择其他来源或调整筛选。首次检查建立基线，检查失败或尚未检查时无法判断是否有变化。');
        let html='<div class="eco-heading"><div><h2>'+esc(alert.title)+'</h2><p>'+age(alert.created_at)+' · '+esc(labels[alert.status])+'</p></div></div><p class="eco-question">'+esc(alert.note)+'</p><div class="eco-diff"><section><h3>新增或修改后的文字</h3><pre>'+esc(alert.added||'没有新增文字')+'</pre></section><section><h3>移除或修改前的文字</h3><pre>'+esc(alert.removed||'没有移除文字')+'</pre></section></div>';
        html+='<div class="eco-actions eco-next-step">'+button('push-alert','推送到收件箱或群聊','class="eco-primary"')+button('adopt-alert',alert.adopted_id?'已加入项目':'建立复核任务',alert.adopted_id?'disabled':'')+'</div>';
        const pending=(alert.deliveries||[]).filter(i=>i.status==='unread'||i.status==='seen').at(-1);
        if(pending)html+='<a class="radar-delivery-next" href="/apps/discussion/?project='+encodeURIComponent(pending.target)+'&inbox=1&item='+encodeURIComponent(pending.id)+'">打开待讨论项 →<small>确认后才会启动模型</small></a>';
        if(alert.structured_changes)html+='<section><h3>条目变化</h3>'+[['added','新增'],['updated','更新'],['removed','移除']].map(([key,label])=>'<h4>'+label+' · '+alert.structured_changes[key].length+'</h4>'+alert.structured_changes[key].map(entry=>'<p><strong>'+esc(entry.title||entry.id)+'</strong><br>'+esc(entry.summary)+'<br><small>'+esc(entry.date)+' · '+esc(entry.url)+'</small></p>').join('')).join('')+'<small>'+esc(alert.structured_changes.coverage)+'</small></section>';
        if(alert.brief)html+='<section class="review-brief"><h3>'+esc(alert.brief.question)+'</h3><p>'+esc(alert.brief.relevance)+'</p><p class="eco-muted">'+esc(alert.brief.basis)+'</p>'+alert.brief.affected_decisions.map(d=>'<p><strong>待复核：'+esc(d.title)+'</strong><br>'+esc(d.reason)+'</p>').join('')+'<p>'+esc(alert.brief.next_step)+'</p><small>'+esc(alert.brief.coverage)+'</small></section>';
        if(alert.diff_truncated) html+='<p class="eco-notice">当前差异摘录超过展示上限，部分内容未显示。来源版本哈希与差异摘录已保存。</p>';
    return '<div class="radar-reader-top">'+button('radar-close-reader','‹ 返回发现','data-radar-back')+'<small>'+esc(state.watches.find(w=>w.id===alert.watch_id)?.name||'来源已移除')+'</small></div>'+html+'<details class="radar-source-details"><summary>来源信息与送达记录</summary><p><a href="'+esc(alert.url)+'" target="_blank" rel="noopener noreferrer">打开原来源 ↗</a></p>'+ (alert.deliveries||[]).map(i=>'<p><a href="/apps/discussion/?project='+encodeURIComponent(i.target)+'&inbox=1&item='+encodeURIComponent(i.id)+'">查看已送达记录 →</a></p>').join('')+'<small>来源版本：'+esc(alert.before_hash.slice(0,12))+' → '+esc(alert.after_hash.slice(0,12))+'</small></details><div class="radar-reader-garden" aria-hidden="true"></div>';
  }
  function radarLayout(state){
    const sources=(state.observations||[]).flatMap(o=>o.sources),alerts=radarFilteredAlerts(state);
    if(!alerts.some(a=>a.id===eco.selection))eco.selection=alerts[0]?.id||null;
    const current=alerts.find(a=>a.id===eco.selection);
    const statusNames={covered:'已成功覆盖',failed:'检查失败',stale:'材料已过期',not_checked:'待首次检查'};
    const sourceRow=(id,name,copy,status,count)=>'<button class="radar-source-choice '+(eco.radarSource===id?'selected':'')+'" type="button" data-eco="radar-source-select" data-id="'+esc(id)+'"><i class="radar-source-glyph" aria-hidden="true">'+(id?'◈':'◎')+'</i><span><strong>'+esc(name)+'</strong><small>'+esc(copy)+'</small></span><em class="radar-health-dot '+esc(status||'not_checked')+'" aria-label="'+esc(statusNames[status]||'汇总')+'"></em><b>'+count+'</b></button>';
    const sidebar='<aside class="radar-source-pane"><details class="radar-source-disclosure" '+(innerWidth>=760?'open':'')+'><summary>我的来源 <span>'+state.watches.length+'</span></summary><div class="radar-source-menu">'+sourceRow('','全部来源','查看已保存的发现','',state.alerts.length)+state.watches.map(w=>{const health=sources.find(i=>i.id===w.id);return sourceRow(w.id,w.name,statusNames[health?.status]||'待首次检查',health?.status,state.alerts.filter(a=>a.watch_id===w.id&&a.status==='unread').length);}).join('')+'</div><div class="radar-source-tools">'+button('new-watch','＋ 添加来源')+button('radar-tab','管理来源','data-tab="sources"')+'</div></details><div class="radar-sidebar-garden" aria-hidden="true"></div><p class="radar-garden-caption">在信息的花园里<br>发现值得继续的想法 🌱</p></aside>';
    const list='<section class="radar-discovery-pane"><header><h2>最新发现</h2><small>'+alerts.length+' 条</small></header><label class="radar-search">⌕ <input type="search" id="radarSearch" aria-label="搜索发现" placeholder="在发现中搜索…" value="'+esc(eco.radarQuery)+'"></label><div class="radar-controls"><select id="radarStatus" aria-label="发现状态">'+options([['all','全部'],['unread','待查看'],['pushed','已推送']],eco.radarStatus)+'</select>'+button('radar-tab','阅读发现','data-tab="discoveries"')+'</div><div class="radar-discovery-list">'+(alerts.length?alerts.map(a=>'<button class="radar-discovery '+(a.id===eco.selection?'selected':'')+'" type="button" data-eco="select-alert" data-id="'+esc(a.id)+'"><small>'+esc(state.watches.find(w=>w.id===a.watch_id)?.name||'已移除的来源')+'<time>'+age(a.created_at)+'</time></small><strong>'+esc(a.brief?.question||a.title)+'</strong><p>'+esc((a.added||a.removed||a.note||'查看变化').replace(/\s+/g,' ').slice(0,110))+'</p><span>'+esc(labels[a.status]||a.status)+(a.deliveries?.length?' · 已推送':'')+'</span></button>').join(''):empty('还没有匹配的发现',state.alerts.length?'试试其他来源或搜索词。':'来源可能尚未完成检查；没有发现不代表没有变化。'))+'</div></section>';
    return '<div class="radar-reader-layout '+(eco.radarReaderOpen?'reader-open':'')+'">'+sidebar+list+'<section class="radar-reading-pane" aria-label="变化阅读">'+(eco.radarTab==='sources'?button('radar-close-reader','‹ 返回发现','data-radar-back')+radarHome(state):radarReader(state,current))+'</section></div>';
  }
  function radarFilteredAlerts(state){
    const query=eco.radarQuery.trim().toLocaleLowerCase();
    return state.alerts.filter(a=>(!eco.radarSource||a.watch_id===eco.radarSource)&&(eco.radarStatus==='all'||(eco.radarStatus==='unread'?a.status==='unread':a.deliveries?.length>0))&&(!query||[a.title,a.brief?.question,a.added,a.removed,state.watches.find(w=>w.id===a.watch_id)?.name].join(' ').toLocaleLowerCase().includes(query))).slice().sort((a,b)=>new Date(b.created_at)-new Date(a.created_at));
  }
  function radarHome(state){
    const sources=(state.observations||[]).flatMap(o=>o.sources),unread=state.alerts.filter(a=>a.status==='unread').length,covered=sources.filter(s=>s.status==='covered').length;
    const tab=(id,label)=>'<button type="button" data-eco="radar-tab" data-tab="'+id+'" class="'+(eco.radarTab===id?'selected':'')+'" aria-pressed="'+(eco.radarTab===id)+'">'+label+'</button>';
    let html='<div class="radar-workspace"><header class="radar-heading"><div><small>YOUR SIGNAL DESK</small><h2>让重要变化浮出水面</h2><p>关注来源，读懂变化，把值得讨论的发现送到群聊。</p></div>'+button('new-watch','＋ 添加来源','class="eco-primary"')+'</header><div class="radar-metrics"><div><span>关注来源</span><strong>'+state.watches.length+'</strong></div><div><span>待查看发现</span><strong>'+unread+'</strong></div><div><span>有效覆盖</span><strong>'+covered+'<small> / '+sources.length+'</small></strong></div></div><div class="radar-tabs">'+tab('discoveries','最新发现')+tab('sources','关注来源')+'</div><div class="radar-controls">';
    if(eco.radarTab==='discoveries')html+='<label class="radar-search">⌕ <input type="search" id="radarSearch" aria-label="搜索发现" placeholder="搜索标题、来源或变化内容" value="'+esc(eco.radarQuery)+'"></label><select id="radarStatus" aria-label="发现状态">'+options([['all','全部状态'],['unread','待查看'],['pushed','已推送']],eco.radarStatus)+'</select>';
    html+='<select id="radarSource" aria-label="关注来源筛选">'+options([['','全部来源'],...state.watches.map(w=>[w.id,w.name])],eco.radarSource)+'</select></div>';
    if(eco.radarTab==='discoveries'){
      const alerts=radarFilteredAlerts(state);
      html+='<div class="radar-feed-label"><h3>变化动态</h3><span>'+alerts.length+' 条发现 · 最近优先</span></div><div class="radar-feed">'+(alerts.length?alerts.map(a=>{
        const watch=state.watches.find(w=>w.id===a.watch_id),name=watch?.name||'已移除的来源',pushed=a.deliveries?.length||0;
        const excerpt=(a.added||a.removed||a.note||'打开查看来源变化').replace(/\s+/g,' ').slice(0,220);
        return '<button type="button" class="radar-card" data-eco="select-alert" data-id="'+esc(a.id)+'"><div class="radar-card-meta"><span class="radar-source-icon">'+esc(name.slice(0,1))+'</span><span>'+esc(name)+'</span><time>'+age(a.created_at)+'</time></div><h3>'+esc(a.brief?.question||a.title)+'</h3><p>'+esc(excerpt)+'</p><footer><span class="radar-pill '+(a.status==='unread'?'pending':'')+'">'+esc(labels[a.status]||a.status)+'</span><span class="radar-pill">'+(pushed?'已推送 '+pushed+' 处':'尚未推送')+'</span><span class="radar-read">查看变化 ↗</span></footer></button>';
      }).join(''):empty(state.alerts.length?'没有匹配的发现':'等待新的发现',state.alerts.length?'试试其他来源、状态或搜索词。':'添加来源并完成首次检查后，后续变化会出现在这里。没有发现不代表全部来源已覆盖。'))+'</div>';
    }else{
      html+='<div class="radar-feed-label"><h3>我的关注</h3>'+button('import-pack','导入来源包')+'</div><div class="radar-sources eco-list">';
    html+=state.watches.filter(w=>!eco.radarSource||w.id===eco.radarSource).map(w=>{const coverage=sources.find(s=>s.id===w.id);return '<div class="radar-source"><div class="eco-row"><span><strong>'+esc(w.name)+'</strong><small>'+esc(w.question||w.url)+'</small><small>'+esc(({covered:'已成功覆盖',failed:'检查失败',stale:'材料已过期',not_checked:'待首次检查'})[coverage?.status]||'待检查')+' · '+(w.enabled?'每 '+w.interval_minutes+' 分钟检查':'自动检查暂停')+(w.auto_push?' · 自动推送开启':'')+'</small></span><div class="eco-actions">'+button('check-watch','检查一次','data-id="'+esc(w.id)+'"')+button('edit-watch','设置','data-id="'+esc(w.id)+'"')+'</div></div>'+(w.delivery_error?'<p class="eco-notice">本次发现已保存，推送失败。可打开该变化重新选择推送目标。</p>':'')+'<details><summary>检查详情</summary><p>'+esc(coverage?.message||'尚无检查结果')+'</p><p>最近检查：'+age(w.last_checked)+'</p><p>最近成功：'+age(w.snapshot?.captured_at)+'</p>'+ (w.delivery_error?'<p>'+esc(w.delivery_error)+'</p>':'')+'</details>'+watchResultHistory(w)+'</div>';}).join('')||empty(state.watches.length?'没有匹配的来源':'添加关注来源',state.watches.length?'请选择其他来源。':'支持公开网页、RSS/XML与JSON。');

      html+='</div><details class="radar-coverage"><summary>主题覆盖与检查范围</summary>'+observationCoverage(state)+'</details>';
    }
    return html+resultObservationProposals(state)+'</div>';
  }

  function observationCoverage(state){
    return (state.observations||[]).map(group=>'<section class="observation-coverage"><h3>'+esc(group.question)+'</h3><p>'+esc(group.summary)+' · 覆盖 '+group.covered+' / '+group.total+'</p>'+group.sources.map(source=>'<p><strong>'+esc(source.name)+'</strong> · '+esc(source.message)+'<br><small>最近成功读取：'+age(source.last_success)+' · '+(source.automatic?(source.due?'等待自动检查':'自动检查开启'):'自动检查暂停')+'</small></p>').join('')+'<small class="eco-muted">'+esc(group.boundary)+'</small></section>').join('');
  }

  function inboxContent(state,incoming){
    if(incoming){
      const a=incoming.source_change;
      return button('back','‹ 收件箱')+'<div class="eco-heading"><div><h2>'+esc(a.title)+'</h2><p>来自雷达 · '+age(incoming.created_at)+' · '+esc(incoming.status==='unread'?'待讨论':labels[incoming.status])+'</p></div></div><p class="eco-question">'+esc(a.note)+'</p><div class="eco-diff"><section><h3>新增或修改后的文字</h3><pre>'+esc(a.added||'没有新增文字')+'</pre></section><section><h3>移除或修改前的文字</h3><pre>'+esc(a.removed||'没有移除文字')+'</pre></section></div>'+(a.diff_truncated?'<p class="eco-notice">差异摘录已截断，需打开来源核查完整内容。</p>':'')+inboxNext(incoming)+'<p class="eco-notice">推送保存来源版本和差异。模型由你确认后启动；变化对判断的影响仍需核验。</p>';
    }
    return '<div class="eco-heading"><div><h2>收件箱</h2><p>雷达发现自动送达。选择值得讨论的变化，确认后再开始。</p></div><span class="badge">'+state.unread_count+' 条未读</span></div><div class="eco-list">'+((state.inbox||[]).length?state.inbox.map(i=>'<button class="eco-row '+(i.status==='unread'?'unread':'')+'" type="button" data-eco="select-inbox" data-id="'+esc(i.id)+'"><span><strong>'+esc(i.source_change.title)+'</strong><small>'+esc(i.status==='unread'?'待讨论':labels[i.status])+' · 来自雷达</small></span><time>'+age(i.created_at)+'</time></button>').join(''):empty('这里等待新的发现','在雷达中添加来源并启用推送。首次读取建立基线，后续匹配关键词的变化才送达。'))+'</div>';
  }
  function inboxInspector(state,incoming){
    if(!incoming)return '<div class="eco-inspector"><h2>待讨论项</h2><p>雷达与讨论室可以分别打开。已送达的变化保留在本机，关闭 App 或重启后仍可查看。</p><section><h3>处理方式</h3><p>打开变化 → 确认角色与问题 → 预览并启动讨论。收到推送不消耗模型配额。</p></section></div>';
    const a=incoming.source_change;
    return '<div class="eco-inspector"><h2>来源与下一步</h2><p><a href="'+esc(a.url)+'" target="_blank" rel="noopener noreferrer">打开原来源 ↗</a></p><dl><dt>前版本</dt><dd>'+esc(a.before_hash.slice(0,12))+'</dd><dt>后版本</dt><dd>'+esc(a.after_hash.slice(0,12))+'</dd><dt>送达版本</dt><dd>'+esc(incoming.source_version.slice(0,12))+'</dd></dl><section><h3>讨论</h3><p>'+(incoming.room_id?'已创建讨论，保留原始推送。':'先选择角色和问题，再预览本轮发送内容。')+'</p><div class="eco-actions">'+(incoming.room_id?button(incoming.group_id?'open-inbox-group':'open-inbox-room','打开已创建的讨论'):button(incoming.group_id?'discuss-inbox-group':'discuss-inbox','确认讨论设置','class="eco-primary" data-id="'+esc(incoming.id)+'"')+button('mark-inbox','标记已查看')+button('dismiss-inbox','忽略此变化'))+'</div></section>'+(!incoming.origin_available?'<p class="eco-notice">原雷达记录已移除，保留送达时的来源快照。</p>':'')+'</div>';
  }

  function dialog(title,body,submitLabel,callback){
    const origin={project:aiProjectId,view:aiView};
    let modal=$('ecoDialog');if(!modal){modal=document.createElement('dialog');modal.id='ecoDialog';modal.className='eco-dialog';document.body.append(modal);}
    modal.innerHTML='<h2>'+title+'</h2><form>'+body+'<div class="eco-form-error" role="alert"></div><div class="eco-actions">'+(submitLabel?'<button class="eco-button eco-primary" type="submit">'+submitLabel+'</button>':'')+'<button class="eco-button" type="button" data-cancel>关闭</button></div></form>';
    modal.querySelector('[data-cancel]').onclick=()=>modal.close();
    modal.querySelector('form').onsubmit=async e=>{e.preventDefault();const submit=e.submitter;submit.disabled=true;const error=modal.querySelector('.eco-form-error');error.textContent='';const intent={...origin,modal,form:e.target,payload:JSON.stringify([...new FormData(e.target)])};eco.pendingIntent=intent;try{await callback(new FormData(e.target),e.target);if(modal.querySelector('form')===intent.form)modal.close();}catch(err){error.textContent=err.message;}finally{if(eco.pendingIntent===intent)eco.pendingIntent=null;submit.disabled=false;}};
    if(!modal.open)modal.showModal();return modal;
  }
  const input=(name,label,value='',extra='')=>'<label class="eco-field">'+label+'<input name="'+name+'" value="'+esc(value)+'" '+extra+'></label>';
  const area=(name,label,value='',extra='')=>'<label class="eco-field">'+label+'<textarea name="'+name+'" '+extra+'>'+esc(value)+'</textarea></label>';
  const options=(list,value)=>list.map(([id,label])=>'<option value="'+esc(id)+'" '+(id===value?'selected':'')+'>'+esc(label)+'</option>').join('');
  const select=(name,label,list,value)=>'<label class="eco-field">'+label+'<select name="'+name+'">'+options(list,value)+'</select></label>';

  function profileForm(existing){
    const state=safeState(),p=existing||{},models=state.connection?.model_selection.models||[];
    const roles=[['方案提出者','提出可执行的方案，说明适用条件、代价和待验证假设。'],['依据核查者','逐项检查依据与来源，区分已知事实、推测和未知，不把引用当成验证。'],['反例审查者','寻找反例、遗漏和失败条件，说明何时应停止或调整方向。']];
    const modal=dialog(p.id?'编辑角色':'添加角色',input('name','角色名称',p.name||roles[0][0],'required maxlength="80"')+select('engine','执行方式',[['codex','共享 Codex 连接'],['external','本空间已登记的外部 Agent']],p.engine||'codex')+select('model','Codex 模型',models.map(m=>[m.model,m.display_name||m.model]),p.model||models[0]?.model)+select('agent_id','外部 Agent',state.agents.filter(a=>a.permission!=='READ').map(a=>[a.id,a.name]),p.agent_id)+area('instructions','角色职责',p.instructions||roles[0][1],'required maxlength="2000"')+'<p class="eco-muted">使用 Codex 前请在“连接与设置”中连接。外部角色使用当前空间连接。</p>','保存角色',async form=>{await mutate('profile.save',{id:p.id,name:form.get('name'),engine:form.get('engine'),model:form.get('model')||'',agent_id:form.get('agent_id')||'',instructions:form.get('instructions')});});
    const engine=modal.querySelector('[name=engine]');const update=()=>{modal.querySelector('[name=model]').parentElement.hidden=engine.value!=='codex';modal.querySelector('[name=agent_id]').parentElement.hidden=engine.value!=='external';};engine.onchange=update;update();
  }
  function profiles(){
    const state=safeState();const modal=dialog('讨论角色',state.profiles.length?'<div class="eco-list">'+state.profiles.map(p=>'<button class="eco-row" type="button" data-edit-profile="'+esc(p.id)+'"><span><strong>'+esc(p.name)+'</strong><small>'+esc(p.model||state.agents.find(a=>a.id===p.agent_id)?.name||'外部 Agent')+'</small></span><span>编辑</span></button>').join('')+'</div>':'<p class="eco-muted">可以分别配置方案提出者、依据核查者和反例审查者，也可以根据你的项目设定角色。</p>',null,null);
    const add=document.createElement('button');add.className='eco-button';add.type='button';add.textContent='添加角色';add.onclick=()=>profileForm();modal.querySelector('.eco-actions').prepend(add);
    const connect=document.createElement('button');connect.className='eco-button';connect.type='button';connect.textContent='登记外部 Agent';connect.onclick=externalAgentForm;modal.querySelector('.eco-actions').prepend(connect);
    modal.querySelectorAll('[data-edit-profile]').forEach(b=>b.onclick=()=>profileForm(state.profiles.find(p=>p.id===b.dataset.editProfile)));
  }
  function externalAgentForm(){
    const state=safeState();
    if(!state)return;
    dialog('登记外部 Agent',input('name','连接名称','外部评审客户端','required maxlength="80"')+
      select('permission','项目权限',[['PROPOSE','读取当前项目并回复评审建议'],['READ','只读取当前项目']], 'PROPOSE')+
      '<p class="eco-muted">范围：'+esc(state.context.project.name)+'。只创建这个项目的连接；不启动模型、不绑定目录、不授予文件读取或项目执行权。登记后可在角色中选择该连接。</p>',
      '登记并取得项目令牌',async (values,form)=>{
        const project=state.project_id,view=aiView,payload=JSON.stringify([...new FormData(form)]),modal=$('ecoDialog');
        const current=()=>aiProjectId===project&&aiView===view&&modal.open&&modal.querySelector('form')===form&&JSON.stringify([...new FormData(form)])===payload;
        const body={project_id:project,name:values.get('name'),type:'external_review_client',permission:values.get('permission'),contract_mode:'strict_v2',ifRev:state.rev};
        const result=await client.registerAgent(body,current);
        if(!current()){toast('连接已登记；令牌未展示，请回到原项目检查。');return;}
        await refresh();
        if(!current())return;
        const receipt=dialog('外部连接已登记', '<p>'+esc(result.permission)+' · '+esc(state.context.project.name)+'；尚未握手，不代表在线。</p>'+
          input('project_token','项目令牌（仅本次显示）',result.token,'type="password" readonly autocomplete="off"')+
          '<p class="eco-muted">供你选定的客户端使用。关闭后不再次显示，不写入全局配置。Python 接入示例只在你指定回复文件时提交建议。</p>',null,null);
        const tokenInput=receipt.querySelector('[name=project_token]'),tokenForm=receipt.querySelector('form');
        const showingReceipt=()=>aiProjectId===project&&aiView===view&&receipt.open&&receipt.querySelector('form')===tokenForm;
        const reveal=document.createElement('button');reveal.type='button';reveal.className='eco-button';reveal.textContent='显示项目令牌';
        reveal.onclick=()=>{if(!showingReceipt())return;tokenInput.type=tokenInput.type==='password'?'text':'password';reveal.textContent=tokenInput.type==='password'?'显示项目令牌':'隐藏项目令牌';if(tokenInput.type==='text')tokenInput.select();};
        const copy=document.createElement('button');copy.type='button';copy.className='eco-button';copy.textContent='复制项目令牌';
        copy.onclick=async()=>{if(!showingReceipt())return;const feedback=receipt.querySelector('.eco-form-error');feedback.textContent='';try{await navigator.clipboard.writeText(tokenInput.value);if(showingReceipt()){copy.textContent='项目令牌已复制';toast('项目令牌已复制');}}catch(error){if(showingReceipt()){feedback.textContent='复制不可用，请点击“显示项目令牌”，选中文字手动复制';toast(feedback.textContent);}}};
        receipt.addEventListener('close',()=>{tokenInput.value='';tokenInput.type='password';},{once:true});
        receipt.querySelector('.eco-actions').prepend(copy,reveal);
      });
  }
  function reviewRecordFields(state){
    return '<details><summary>选取项目记录（可选）</summary><p class="eco-muted">项目信息随本次评审保存；下面的记录默认不选，不会发送。复核已有判断时自动包含该判断。每类最多选取 20 条；结果列表只列最近 20 条。</p>'+[['tasks','任务'],['decisions','判断'],['results','结果']].map(([key,label])=>'<fieldset><legend>'+label+'</legend>'+(state.context[key]||[]).map(record=>'<label class="eco-check"><input type="checkbox" name="context_'+key+'" value="'+esc(record.id)+'">'+esc(record.title||record.summary||record.id)+'</label>').join('')+'</fieldset>').join('')+'</details>';
  }
  function newReview(alert=null,incoming=null){
    const state=safeState();
    const material=alert?'新增或修改：\n'+(alert.added||'无')+'\n移除：\n'+(alert.removed||'无'):'';
    const form=dialog('评审一个方案',input('title','评审标题',alert?'评估：'+alert.title:'','required maxlength="200"')+area('question','现在要决定什么？',alert?.brief?.question||'','required maxlength="4000"')+area('constraints','有哪些不能违反的条件？','','maxlength="4000"')+input('material_title','材料标题',alert?alert.title:'','required maxlength="200"')+input('reference','材料来源或说明',alert?.url||'','maxlength="2000"')+area('material','本次选取的材料正文或摘录',material,'required maxlength="16000"')+'<label class="eco-field">或选择一份文本材料<input type="file" name="material_file" accept=".txt,.md,text/plain,text/markdown"></label><details><summary>执行设置 · 一次评审</summary>'+select('profile','执行器',[['','稍后选择'],...state.profiles.map(p=>[p.id,p.name+' · '+(p.model||'外部 Agent')])],'')+'<p class="eco-muted">基线使用一个执行器、一轮、一次配额。角色和模型在执行器设置中配置；保存不会调用模型。</p></details>'+(!state.profiles.length?'<p class="eco-notice">可先保存问题和材料，开始前再选择执行器。</p>':'')+select('review_of','复核已有判断（可选）',[['','一次新评审'],...state.context.decisions.map(d=>[d.id,d.title||d.question])],'')+reviewRecordFields(state)+'<p class="eco-muted">材料将在本机保存为本次快照，模型发送仍需预览确认。这里只保存选取的材料，不读取其他文件。</p>','保存评审草稿',async values=>{
      const room=await mutate('review.create',{title:values.get('title'),question:values.get('question'),constraints:values.get('constraints'),materials:[{title:values.get('material_title'),content:values.get('material'),reference:values.get('reference')}],profile_ids:values.get('profile')?[values.get('profile')]:[],max_rounds:1,max_calls:1,inbox_id:incoming?.id||'',alert_id:incoming?'':alert?.id||'',review_of:values.get('review_of')||'',context_selection:Object.fromEntries(['tasks','decisions','results'].map(key=>[key,values.getAll('context_'+key)]))});
      eco.selection=room.id;eco.tab='rooms';aiView='discussion';if(typeof appSetSection==='function')appSetSection(false);render();
    });
    form.querySelector('[name=material_file]').onchange=async event=>{
      const file=event.target.files[0];if(!file)return;
      try{if(file.size>64000)throw Error('材料较大，请选取相关摘录');const content=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());if(content.length>16000)throw Error('材料超过 16000 字，请明确选取摘录');if(!form.open)return;form.querySelector('[name=material]').value=content;form.querySelector('[name=material_title]').value=file.name;form.querySelector('[name=reference]').value='用户选取文本文件：'+file.name;}catch(error){form.querySelector('.eco-form-error').textContent=error.message;}
    };
  }
  function editBrief(room){
    const modal=dialog('编辑评审简报',YanxuReview.editor(room,area),'保存修订',async form=>{
      const content=YanxuReview.editedContent(form);
      await mutate('review.brief.save',{id:room.id,expected_rev:room.object_rev||0,brief_revision:room.brief.revision,content,reason:form.get('reason')});
    });
    YanxuReview.bindEditor(modal,room,area);
  }
  function historicalReview(room){
    const state=safeState(),keys=['materials','tasks','decisions','results'];
    const choices=keys.map(key=>'<fieldset><legend>'+({materials:'历史材料',tasks:'历史任务',decisions:'历史判断',results:'历史结果'}[key])+'</legend>'+(key==='materials'?(room.materials||[]):(room.context[key]||[])).map(row=>'<label class="eco-check"><input type="checkbox" name="history_'+key+'" value="'+esc(row.id)+'">'+esc(row.title||row.summary||row.id)+'</label>').join('')+'</fieldset>').join('');
    dialog('使用历史快照建立评审',input('title','评审标题',('复核：'+room.title).slice(0,200),'required maxlength="200"')+area('question','现在要决定什么？',room.question,'required maxlength="4000"')+area('constraints','本次约束',room.constraints||'','maxlength="4000"')+area('reason','为什么仍要使用这些历史快照？','','required maxlength="2000"')+'<p class="eco-muted">请选择 1–12 份原评审保存的快照，默认不选。历史记录成为固定材料，不代表当前状态。原评审已耗 '+room.used_calls+' / '+room.max_calls+'，本次另存草稿，不重置原消耗。</p>'+choices+select('profile','本次执行器',[['','稍后选择'],...state.profiles.map(p=>[p.id,p.name+' · '+(p.model||'外部 Agent')])],'')+select('review_of','复核当前判断（可选）',[['','不绑定当前判断'],...state.context.decisions.map(d=>[d.id,d.title||d.question])],'')+reviewRecordFields(state)+'<p class="eco-muted">保存当前项目信息与选定当前记录；预览确认后才能运行一次评审。</p>','保存历史材料评审',async values=>{
      const created=await mutate('review.create',{title:values.get('title'),question:values.get('question'),constraints:values.get('constraints'),profile_ids:values.get('profile')?[values.get('profile')]:[],max_rounds:1,max_calls:1,review_of:values.get('review_of')||'',context_selection:Object.fromEntries(['tasks','decisions','results'].map(key=>[key,values.getAll('context_'+key)])),history_source:{room_id:room.id,expected_rev:room.object_rev||0,context_hash:room.context.context_hash,reason:values.get('reason'),selection:Object.fromEntries(keys.map(key=>[key,values.getAll('history_'+key)]))}});
      eco.selection=created.id;eco.tab='rooms';aiView='discussion';if(typeof appSetSection==='function')appSetSection(false);render();
    });
  }
  function newRoom(alert,incoming){
    const state=safeState();if(!state.profiles.length){profiles();return;}
    const modal=dialog('新建讨论',input('title','讨论主题',alert?'复核：'+alert.title:'','required maxlength="200"')+area('question','这次需要解决什么问题？',alert?'这处来源变化可能影响项目中的哪些判断？请说明依据与仍需核实的内容。':'','required maxlength="4000"')+'<fieldset class="eco-checks"><legend>参与角色</legend>'+state.profiles.map((p,i)=>'<label class="eco-check"><input type="checkbox" name="profile" value="'+esc(p.id)+'" '+(i<3?'checked':'')+'>'+esc(p.name)+'</label>').join('')+'</fieldset><div class="eco-field-pair">'+input('rounds','最多轮次',2,'type="number" min="1" max="3" required')+input('calls','调用 / 回复配额',Math.min(3,state.profiles.length)*2,'type="number" min="1" max="18" required')+'</div><p class="eco-muted">创建后可以先查看项目上下文，确认后再开始。每轮完成后由你决定是否继续。</p>','创建讨论',async form=>{const room=await mutate('room.create',{title:form.get('title'),question:form.get('question'),profile_ids:form.getAll('profile'),max_rounds:Number(form.get('rounds')),max_calls:Number(form.get('calls')),alert_id:incoming?'':alert?.id||'',inbox_id:incoming?.id||''});eco.selection=room.id;eco.tab='rooms';aiView='discussion';if(typeof appSetSection==='function')appSetSection(false);render();});
    modal.querySelectorAll('[name=profile],[name=rounds]').forEach(node=>node.addEventListener('change',()=>{modal.querySelector('[name=calls]').value=modal.querySelectorAll('[name=profile]:checked').length*Number(modal.querySelector('[name=rounds]').value);}));
  }
  function importSourcePack(){
    let selectedPack=null;
    const modal=dialog('导入来源包','<label class="eco-field">选择来源包文件<input type="file" name="pack_file" accept=".json,application/json" required></label><input type="hidden" name="pack_version" value=""><div data-pack-preview></div><p class="eco-muted">只登记列出的公开来源。自动读取和推送均暂停，首次读取另行确认。</p>','登记这些来源',async()=>{if(!selectedPack)throw Error('请先选择并检查一个来源包');await mutate('source.pack.import',{pack:selectedPack});});
    const picker=modal.querySelector('[name=pack_file]');picker.onchange=async()=>{
      selectedPack=null;modal.querySelector('[name=pack_version]').value='';const file=picker.files[0];if(!file)return;
      try{if(file.size>20000)throw Error('来源包超过 20KB');const bytes=await file.arrayBuffer(),pack=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));if(!Array.isArray(pack.sources)||!pack.sources.length)throw Error('来源包没有可选择的来源');if(!modal.open||picker.files[0]!==file)return;
        modal.querySelector('[data-pack-preview]').innerHTML='<h3>'+esc(pack.name)+'</h3><p>'+esc(pack.question)+'</p>'+pack.sources.map(s=>'<p><strong>'+esc(s.name)+'</strong><br>'+esc(s.url)+'</p>').join('');
        const digest=await crypto.subtle.digest('SHA-256',bytes);if(!modal.open||picker.files[0]!==file)return;modal.querySelector('[name=pack_version]').value=Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('');selectedPack=pack;
      }catch(error){modal.querySelector('.eco-form-error').textContent=error.message;}
    };
  }
  async function watchForm(existing){
    const state=safeState(),w=existing||{},initialView=aiView,choices=await pushChoices(state);if(safeState()!==state||aiView!==initialView)throw Error('空间或记录已变化，请重新打开来源设置');
    dialog(w.id?'来源设置':'添加来源',area('question','希望持续回答的问题',w.question||'','required maxlength="1000"')+input('name','来源名称',w.name||'','required maxlength="100"')+input('url','公开来源地址',w.url||'','type="url" required '+(w.id?'readonly':''))+input('keywords','关键词（逗号分隔，留空追踪全部文字变化）',(w.keywords||[]).join(', '))+'<fieldset class="eco-checks"><legend>关联项目决策（可选）</legend>'+state.context.decisions.map(d=>'<label class="eco-check"><input type="checkbox" name="decision" value="'+esc(d.id)+'" '+(w.decision_ids?.includes(d.id)?'checked':'')+'>'+esc(d.title||d.question||d.id)+'</label>').join('')+'</fieldset>'+input('interval','自动检查间隔（分钟）',w.interval_minutes||60,'type="number" min="15" max="1440" required')+'<label class="eco-check"><input type="checkbox" name="enabled" '+(w.enabled?'checked':'')+'>启用自动检查；本机核心运行时按上述频率读取该公开来源</label>'+
      '<label class="eco-check"><input type="checkbox" name="auto_push" '+(w.auto_push?'checked':'')+'>新变化自动推送到讨论室，确认后再启动模型</label>'+select('push_route','送到哪里',choices,JSON.stringify([w.push_target||(state.context.project.app_owner?'personal':'project'),w.push_group_id||'']))+'<p class="eco-muted">保存来源版本与差异摘录；首次检查建立基线，不推送。</p>','保存来源',async form=>{await mutate('watch.save',{id:w.id,expected_rev:w.id?w.object_rev:undefined,question:form.get('question'),name:form.get('name'),url:form.get('url'),keywords:String(form.get('keywords')).split(/[,，]/).map(v=>v.trim()).filter(Boolean),decision_ids:form.getAll('decision'),interval_minutes:Number(form.get('interval')),enabled:form.get('enabled')==='on',auto_push:form.get('auto_push')==='on',push_target:JSON.parse(form.get('push_route'))[0],push_group_id:JSON.parse(form.get('push_route'))[1],consent:'radar-public-source-v1'});});
  }
  function resultObservationProposals(state){
    const group=state.result_observation;if(!group?.total)return '';
    return '<section class="observation-coverage" id="result-observation"><h3>根据结果复核观察规则 · '+group.total+'</h3><p class="eco-muted">'+esc(group.boundary)+'</p>'+(group.shown<group.total?'<p>当前显示前 '+group.shown+' 项，共 '+group.total+' 项；处理后刷新查看后续候选。</p>':'')+group.candidates.map(p=>'<article><h4>'+esc(p.watch_name)+'</h4><p>结果：'+esc(resultOutcomeLabel(p.source.result.outcome))+' · '+esc(p.source.result.verification_status)+'<br>'+esc(p.source.result.summary)+'</p><p>'+esc(p.notice)+'</p>'+button('result-watch','查看并处理建议','data-id="'+esc(p.id)+'" '+(p.can_resolve?'':'disabled'))+(!p.can_resolve?'<p>此来源已达到 50 条处理记录上限，历史保留。</p>':'')+'</article>').join('')+'</section>';
  }
  function resultOutcomeLabel(value){
    const labels={PASS:'成功',PASSED:'成功',SUCCESS:'成功',FAIL:'失败',FAILED:'失败',FAILURE:'失败',PARTIAL:'部分',INCONCLUSIVE:'未定',UNKNOWN:'未知'};
    return (labels[String(value).toUpperCase()]||'未识别状态')+'（原值 '+value+'）';
  }
  function watchResultHistory(watch){
    const receipts=watch.result_adjustments||[];if(!receipts.length)return '';
    return '<details><summary>结果驱动的观察处理记录 · '+receipts.length+'</summary>'+receipts.map(r=>'<section><h4>'+esc(r.resolution==='keep'?'维持原规则':'修改观察规则')+'</h4><p>'+esc(r.reason)+'</p><p>原结果：'+esc(resultOutcomeLabel(r.source.result.outcome))+' · '+esc(r.source.result.verification_status)+'<br>'+esc(r.source.result.summary)+'</p><p>之前：'+esc(r.before.question)+'<br>之后：'+esc(r.after.question)+'</p><small>'+esc('关键词 '+r.before.keywords.join('、')+' → '+r.after.keywords.join('、')+'；间隔 '+r.before.interval_minutes+' → '+r.after.interval_minutes+' 分钟')+'</small><details><summary>查看版本依据</summary><p>'+esc(r.source.result.source_ref)+' · '+esc(r.source.result.source_version)+'</p><p>来源版本：'+esc(r.source_hash)+'</p><p>结果记录：'+esc(r.source.result.id)+'</p></details><p>原结果和判断保留；处理不改变核验等级。</p></section>').join('')+'</details>';
  }
  function resultWatchForm(candidate){
    if(!candidate)throw Error('此观察建议已变化，请重新读取');
    const original=candidate.target.rule,proposed=candidate.proposed,source=candidate.source;
    const modal=dialog('依据结果处理观察规则','<p><strong>'+esc(candidate.watch_name)+'</strong></p><p>原结果：'+esc(resultOutcomeLabel(source.result.outcome))+' · '+esc(source.result.verification_status)+'<br>'+esc(source.result.summary)+'</p><p>复核条件：'+esc(source.recheck_conditions||'未补充')+'</p><p>'+esc(candidate.notice)+'</p><details><summary>查看结果、采纳与版本依据</summary><p>任务：'+esc(source.task.title)+'<br>行动：'+esc(source.action.goal)+'</p><p>'+esc(source.result.source_ref)+' · '+esc(source.result.source_version)+'</p><p>来源版本：'+esc(candidate.source_hash)+'</p><p>'+esc(candidate.boundary)+'</p></details>'+select('resolution','如何处理',[['keep','维持原规则'],['modify','修改规则']],'keep')+area('question','关注问题',original.question,'maxlength="1000" readonly')+input('keywords','关键词（逗号分隔）',original.keywords.join(', '),'readonly')+input('interval','检查间隔（分钟）',original.interval_minutes,'type="number" min="15" max="1440" required readonly')+area('reason','处理理由与仍需核实的内容','','required maxlength="2000"')+'<p class="eco-muted">来源地址、关联判断、启用与推送设置保持当前配置。'+(candidate.target.enabled?'自动检查已启用，修改后的频率和关键词会用于后续检查。':'自动检查暂停；保存不会启动读取。')+'</p><label class="eco-check"><input type="checkbox" required>我已核对原结果、范围与处理理由，确认这次观察规则处理</label>','确认保存',async values=>{
      const choice=values.get('resolution');await mutate('watch.result.resolve',{id:candidate.watch_id,expected_rev:candidate.target.object_rev,proposal_id:candidate.id,basis_hash:candidate.basis_hash,resolution:choice,rule:choice==='keep'?original:{question:values.get('question'),keywords:String(values.get('keywords')).split(/[,，]/).map(v=>v.trim()).filter(Boolean),interval_minutes:Number(values.get('interval'))},reason:values.get('reason'),consent:'result-observation-adjustment-v1'});
    });
    modal.querySelector('[name=resolution]').onchange=event=>{const modify=event.target.value==='modify',value=modify?proposed:original;for(const [name,field]of [['question','question'],['keywords','keywords'],['interval','interval_minutes']]){const node=modal.querySelector('[name='+name+']');node.readOnly=!modify;node.value=field==='keywords'?value[field].join(', '):value[field];}};
  }
  function adopt(item,kind){
    const personal=!!safeState().context.project.app_owner;
    const destination=personal?select('destination','保存到哪里',[[aiProjectId,'当前个人空间'],...data.projects.filter(p=>!p.personal&&p.id!==aiProjectId).map(p=>[p.id,p.name+' · 续芽项目'])],aiProjectId):'';
    dialog(kind==='room'?'采纳讨论内容':'建立复核任务',destination+select('target','加入项目的方式',kind==='room'?[['task','任务'],['decision','决策']]:[['task','复核任务']],'task')+input('title','标题',kind==='room'?item.title:'复核：'+item.title,'required maxlength="200"')+area('rationale','采纳理由、适用条件与仍需核实的内容','','required maxlength="4000"')+'<p class="eco-muted">保存你的判断与原记录版本。选择续芽项目可保存待执行任务或决策；保留你的采纳理由与来源版本。</p>','确认保存',async form=>{const target=form.get('destination')||aiProjectId;let version=safeState().project_version;if(target!==aiProjectId){const preview=await client.readProject(target);version=preview.project_version;}await mutate(kind+'.adopt',{id:item.id,expected_rev:item.object_rev||0,brief_revision:item.brief?.revision,target:form.get('target'),title:form.get('title'),rationale:form.get('rationale'),target_project_id:target,target_project_version:version});});
  }
  function preview(room){
    const send={project:room.context,question:room.question,constraints:room.constraints||'',materials:room.materials||[],review_of:room.review_of||null,previous_messages:room.messages,source_change:room.source_change||null,roles:room.participants.map(p=>({name:p.name,model:p.model,engine:p.engine,instructions:p.instructions}))};
    if(room.history_source)send.history_source=room.history_source;
    dialog('预览本轮讨论输入','<details><summary>查看发送内容</summary><pre class="eco-context">'+esc(JSON.stringify(send,null,2))+'</pre></details><p class="eco-muted">本轮最多 '+room.participants.length+' 个角色调用/回复，剩余配额 '+(room.max_calls-room.used_calls)+'。发送上面列出的记录、选取材料与当前评审内容。</p><label class="eco-check"><input type="checkbox" required>我已查看输入，同意将上述内容交给所选角色进行本轮讨论</label>','开始本轮',async()=>{await mutate('room.start',{id:room.id,consent:'discussion-project-records-v1'});});
  }
  function roomMarkdown(room,projectName){
    const lines=['# '+room.title,'',room.question,'','项目：'+projectName,'上下文版本：'+room.context.context_hash,'状态：'+labels[room.status],'轮次：'+room.round+' / '+room.max_rounds,'已耗调用 / 回复配额：'+room.used_calls+' / '+room.max_calls,'角色：'+room.participants.map(p=>p.name+'（'+(p.model||'外部 Agent')+'）').join('、'),'','AI 发言为未独立核验建议。'];
    for(const f of room.failures)lines.push('','## 未解决的执行失败','第 '+f.round+' 轮：'+f.message);
    for(const m of room.messages){lines.push('','## 第 '+m.round+' 轮 · '+m.author);if(m.kind==='human')lines.push(m.content);else for(const [key,label]of Object.entries(fields))lines.push('','### '+label,m.output[key]);}
    for(const a of room.adoptions)lines.push('','## 人工采纳',a.title,a.rationale,'来源版本：'+a.source_version);
    return lines.join('\n');
  }
  async function exportRoom(room){
    const exported=room.mode==='review'?await client.brief(aiProjectId,room.id):null;
    const markdown=exported?exported.markdown:roomMarkdown(room,safeState().context.project.name);
    const modal=dialog(room.mode==='review'?'导出评审简报':'导出讨论记录',area('markdown','Markdown 记录',markdown,'readonly')+'<p class="eco-muted">包含选取材料、原始回复、修订理由、失败记录与已耗配额；分享前可检查材料范围。可以复制保存；下载取决于当前浏览器或桌面宿主的文件下载支持。</p>',null,null);
    const actions=modal.querySelector('.eco-actions');
    const copy=document.createElement('button');copy.type='button';copy.className='eco-button';copy.textContent='复制 Markdown';
    copy.onclick=async()=>{try{await navigator.clipboard.writeText(markdown);copy.textContent='已复制';}catch(error){modal.querySelector('.eco-form-error').textContent=error.message;}};
    const download=document.createElement('button');download.type='button';download.className='eco-button';download.textContent='下载 Markdown';
    download.onclick=()=>{const url=URL.createObjectURL(new Blob([markdown],{type:'text/markdown;charset=utf-8'})),link=document.createElement('a');link.href=url;link.download=exported?exported.filename:'续芽讨论-'+room.id+'.md';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
    actions.prepend(copy,download);
  }
  async function action(name,node){
    const state=safeState(); if(name==='refresh')return refresh(); if(!state)return;
    const room=selected('room'),alert=selected('alert');
    if(name==='connection-settings'){if(typeof appSettings==='function')await appSettings();else aiOpen('agents');}
    else if(name==='focus-chat-search'){const input=$('chatSearch');input?.focus();}
    else if(name==='radar-tab'){eco.radarTab=node.dataset.tab;eco.radarReaderOpen=true;render();}
    else if(name==='radar-close-reader'){eco.radarReaderOpen=false;render();}
    else if(name==='radar-source-select'){eco.radarSource=node.dataset.id;eco.selection=null;eco.radarTab='discoveries';eco.radarReaderOpen=false;render();}
    else if(name==='new-group')groupForm();
    else if(name==='group-details'){eco.groupDetails=!eco.groupDetails;render();}
    else if(name==='edit-group')groupForm(selected('group'));
    else if(name==='open-group-review'){eco.tab='rooms';eco.selection=node.dataset.id;render();}
    else if(name==='select-group'){eco.tab='groups';eco.selection=node.dataset.id;render();}
    else if(name==='stop-group'){const group=selected('group');if(group?.active_room_id)await mutate('room.stop',{id:group.active_room_id});}
    else if(name==='chat-tab'){eco.tab=node.dataset.tab;eco.groupDetails=false;eco.selection=null;eco.filter='';render();}
    else if(name==='back'){eco.selection=null;render();}
    else if(name==='group-inbox'){eco.tab='inbox';eco.selection=null;render();}
    else if(name==='discuss-inbox-group'){await discussIncoming(state.inbox.find(i=>i.id===(node.dataset.id||eco.selection)));}
    else if(name==='open-inbox-group'){const incoming=selected('inbox');eco.tab='groups';eco.selection=incoming.group_id;render();}
    else if(name==='select-inbox'){eco.tab='inbox';eco.selection=node.dataset.id;render();}
    else if(name==='mark-inbox'||name==='dismiss-inbox'){const incoming=selected('inbox');await mutate('inbox.review',{id:incoming.id,status:name==='mark-inbox'?'seen':'dismissed'});}
    else if(name==='discuss-inbox'){const incoming=selected('inbox');newReview(incoming.source_change,incoming);}
    else if(name==='open-inbox-room'){eco.selection=selected('inbox').room_id;eco.tab='rooms';if(typeof appSetSection==='function')appSetSection(false);render();}
    else if(name==='select-room'||name==='select-alert'){eco.selection=node.dataset.id;if(name==='select-alert'){eco.radarTab='discoveries';eco.radarReaderOpen=true;}render();}
    else if(name==='profiles')profiles();
    else if(name==='new-room')newRoom();
    else if(name==='new-review')newReview();
    else if(name==='edit-brief')editBrief(room);
    else if(name==='history-review')historicalReview(room);
    else if(name==='import-pack')importSourcePack();
    else if(name==='new-watch')await watchForm();
    else if(name==='result-watch')resultWatchForm(state.result_observation?.candidates.find(p=>p.id===node.dataset.id));
    else if(name==='edit-watch')await watchForm(state.watches.find(w=>w.id===node.dataset.id));
    else if(name==='choose-executor'){if(!state.profiles.length){profiles();return;}dialog('选择评审执行器',select('profile','执行器',state.profiles.map(p=>[p.id,p.name+' · '+(p.model||'外部 Agent')]),state.profiles[0]?.id),'保存选择',async form=>mutate('review.executor',{id:room.id,expected_rev:room.object_rev||0,profile_id:form.get('profile')}));}
    else if(name==='start-room')preview(room);
    else if(name==='stop-room')await mutate('room.stop',{id:room.id});
    else if(name==='compare'){eco.comparison=!eco.comparison;render();}
    else if(name==='export-room')await exportRoom(room);
    else if(name==='message')dialog('补充想法',area('content','补充内容','','required maxlength="4000"'),'保存',async form=>mutate('room.message',{id:room.id,content:form.get('content')}));
    else if(name==='adopt-room')adopt(room,'room');
    else if(name==='adopt-alert')adopt(alert,'alert');
    else if(name==='push-alert'){
      const choices=await pushChoices(state);if(safeState()!==state)throw Error('来源记录已变化，请重新查看');
      dialog('推送雷达发现',select('route','送到哪里',choices,choices[0][0])+'<p>只创建待讨论项并提醒，不启动模型。</p>','确认推送',async form=>{const [mode,group_id]=JSON.parse(form.get('route'));await mutate('alert.push',{id:alert.id,expected_rev:alert.object_rev,target:mode==='personal'?'ecosystem-personal-discussion':aiProjectId,group_id});});
    }
    else if(name==='open-source-alert'){const source=room.source_change;window.open('/apps/radar/?project='+encodeURIComponent(source.project_id)+'&item='+encodeURIComponent(source.id),'_blank','noopener');}
    else if(name==='review-alert'||name==='dismiss-alert')await mutate('alert.review',{id:alert.id,status:name==='review-alert'?'reviewed':'dismissed'});
    else if(name==='check-watch'){const w=state.watches.find(w=>w.id===node.dataset.id);dialog('检查公开来源','<p class="eco-muted">读取 '+esc(w.url)+'，与最近一次成功保存的版本比较。首次检查建立基线。</p>','检查一次',async()=>mutate('watch.check',{id:w.id,consent:'radar-public-source-v1'}));}
    else if(name==='context')dialog('当前项目上下文','<pre class="eco-context">'+esc(JSON.stringify(state.context,null,2))+'</pre>',null,null);
    else if(name==='copy-context'){await navigator.clipboard.writeText('续芽项目：'+state.context.project.name+'\n目标：'+(state.context.project.goal||'未填写')+'\n上下文版本：'+state.context.context_hash+'\n执行前重新读取 project.get_context，核对目标、范围、来源和已耗预算。\n'+JSON.stringify(state.context,null,2));node.textContent='已复制';}
  }
  function bind(host){host.querySelectorAll('[data-eco]').forEach(node=>node.onclick=async()=>{try{await action(node.dataset.eco,node);}catch(error){domain.error=error.message;render();}});}

  function resultReferenceMarkup(result,state){
    const linked=(state.result_observation?.candidates||[]).filter(p=>p.source.result.id===result.id);
    return '结果：'+esc(result.outcome)+' · '+esc(result.verification_status||'未知')+' · '+esc(result.summary)+(linked.length?'<br><a href="/?mode=observe&project='+encodeURIComponent(state.project_id)+'#result-observation">查看关联来源的观察调整建议 · '+linked.length+'</a>':'');
  }

  function projectReferences(state){
    const impacts=state.impacts||[],lineage=state.lineage||[];if(!impacts.length&&!lineage.length)return '';
    return '<section class="observation-coverage"><h3>判断与依据</h3>'+impacts.map(d=>'<p>待复核：'+esc(d.title)+' · <a href="/?mode=observe&project='+encodeURIComponent(state.project_id)+'&item='+encodeURIComponent(d.alert_id)+'">查看来源变化</a></p>').join('')+(lineage.length?'<details><summary>已采纳判断与行动的引用 · '+lineage.length+'</summary>'+lineage.map(row=>'<section><h4>'+esc(row.title)+'</h4><p>'+(row.origin_available?'<a href="/?mode=review&project='+encodeURIComponent(row.review_ref.space_id)+'&item='+encodeURIComponent(row.review_ref.room_id)+'">查看评审简报 · 版本 '+row.review_ref.brief_revision+'</a>':'原评审不可用，保留采纳时的引用')+'</p><small>'+esc(row.material_refs.map(m=>m.title+' · '+m.version.slice(0,12)).join('、'))+'</small><p>复核条件：'+esc(row.recheck_conditions||'未补充')+'</p>'+row.actions.map(a=>'<p>行动：'+esc(a.goal)+' · '+esc(a.status)+'<br>'+a.results.map(r=>resultReferenceMarkup(r,state)).join('<br>')+'</p>').join('')+'<small>'+esc(row.boundary)+'</small></section>').join('')+'</details>':'')+'</section>';
  }

  const oldContent=aiRenderContent,oldInspector=aiRenderInspector,oldRefresh=aiRefresh,oldRender=render;
  const oldOpen=aiOpen;aiOpen=function(mode){if(typeof STANDALONE_APP==='undefined'&&['discussion','radar'].includes(mode)){const q=new URLSearchParams();if(aiProjectId)q.set('project',aiProjectId);location.assign('/apps/'+mode+'/?'+q);return Promise.resolve();}if(typeof STANDALONE_APP==='undefined'&&!['discussion','radar'].includes(mode)&&!data.projects.some(p=>p.id===aiProjectId)){aiProjectId=data.projects[0]?.id||'';if(typeof aiResetProjectCache==='function')aiResetProjectCache();}return oldOpen.apply(this,arguments);};
  aiRenderContent=function(){if(active())return content();const value=oldContent.apply(this,arguments);const state=eco.projectState;if(aiView==='project'&&state?.project_id===aiProjectId){$('content').insertAdjacentHTML('afterbegin',projectReferences(state));}return value;};
  aiRenderInspector=function(){if(active())return inspector();return oldInspector.apply(this,arguments);};
  aiRefresh=async function(){if(active())return refresh();const value=await oldRefresh.apply(this,arguments);const project=aiProjectId,mode=aiView;if(mode==='project'&&project){try{const state=await client.readProject(project);if(aiProjectId===project&&aiView===mode){eco.projectState=state;render();}}catch(_){if(aiProjectId===project&&aiView===mode)eco.projectState=null;}}return value;};
  render=function(){document.body.classList.toggle('yanxu-radar-focus',aiView==='radar');document.body.classList.toggle('yanxu-chat-focus',aiView==='discussion'&&eco.tab==='groups');document.body.classList.toggle('yanxu-chat-info-open',aiView==='discussion'&&eco.tab==='groups'&&eco.groupDetails);oldRender.apply(this,arguments);navigation();if(!active())return;
    $('title').textContent=aiView==='discussion'?'聊天室':'雷达';$('subtitle').textContent=safeState()?.context.project.app_owner?'个人空间 · 独立使用，随时关联续芽项目':'已关联续芽项目 · '+(safeState()?.context.project.name||'');
    $('toolbar').innerHTML='<div class="rd-toolbar-left">'+(typeof STANDALONE_APP!=='undefined'&&STANDALONE_APP?'':(eco.tab==='groups'?[]:[['discussion','聊天室'],['radar','观察']]).map(([mode,label])=>'<button class="rd-tab '+(aiView===mode?'is-active':'')+'" type="button" data-eco-mode="'+mode+'">'+label+'</button>').join(''))+(aiView==='discussion'?['groups','rooms','inbox'].map((tab,i)=>'<button class="rd-tab '+(eco.tab===tab?'is-active':'')+'" type="button" data-eco="chat-tab" data-tab="'+tab+'">'+['群聊','评审','收件箱'][i]+'</button>').join(''):'')+'</div><div class="rd-toolbar-right">'+(eco.spaces.length?'<select aria-label="记录空间">'+eco.spaces.map(p=>'<option value="'+esc(p.id)+'" '+(p.id===aiProjectId?'selected':'')+'>'+esc(p.personal?'个人空间':p.name+' · 项目')+'</option>').join('')+'</select>':aiProjectPicker())+(aiView==='discussion'&&eco.tab==='groups'?'':button('refresh','刷新'))+'<button class="rd-tool-button rd-os-inspector-toggle" data-eco-inspector type="button">详情</button></div>';
    $('toolbar').querySelectorAll('[data-eco-mode]').forEach(b=>b.onclick=()=>open(b.dataset.ecoMode).catch(error=>{domain.error=error.message;render();}));
    $('toolbar').querySelector('select')?.addEventListener('change',e=>{eco.selection=null;eco.radarSource='';eco.radarQuery='';eco.radarStatus='all';domain.value=null;aiSelectProject(e.target.value);});
    $('toolbar').querySelector('[data-eco-inspector]').onclick=()=>{if(aiView==='discussion'&&eco.tab==='groups')eco.groupDetails=!eco.groupDetails;else aiInspectorOpen=!aiInspectorOpen;render();};bind($('toolbar'));
  };
  globalThis.appOpenInbox=function(id=null){eco.tab='inbox';eco.selection=id;if(typeof appSetSection==='function')appSetSection(true);render();};
  globalThis.appOpenHome=function(){eco.tab='groups';eco.selection=null;if(typeof appSetSection==='function')appSetSection(false);render();};
  globalThis.appOpenItem=function(id){eco.selection=id;if(aiView==='radar'){eco.radarTab='discoveries';eco.radarReaderOpen=true;}render();};
  navigation();
  setInterval(()=>{if(active()&&!document.hidden)refresh();},4000);
  const query=new URLSearchParams(location.search),mode=query.get('app')||({review:'discussion',chat:'discussion',observe:'radar'})[query.get('mode')];
  if(query.get('mode')==='review')eco.tab='rooms';if(query.get('inbox')==='1')eco.tab='inbox';
})();
