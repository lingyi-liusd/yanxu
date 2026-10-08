const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const context={document:{activeElement:null}};vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../chat_ui.js'),'utf8'),context);
const chat=context.YanxuChat,esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const group={id:'g',name:'<群聊>',members:[{id:'a',name:'模型 A',model:'A'},{id:'b',name:'模型 B',model:'B'}],timeline:[{kind:'human',author:'你',content:'<script>bad</script>'},{kind:'agent',author:'模型 A',model:'A',output:{position:'观点',evidence:'依据',objections:'反例',next_step:'继续'}}],entries:[{}],used_calls:2};
const state={project_id:'p',groups:[group]},button=(a,l)=>`<button data-eco="${a}">${l}</button>`;
let html=chat.render(state,group,'',esc,()=>'',button);assert(html.includes('&lt;script&gt;bad&lt;/script&gt;'));assert(!html.includes('<script>'));assert(html.includes('模型 B'));assert(html.includes('chat-send-options'));assert(!html.includes('累计模型调用'));assert(!html.includes('AI 回复，待核实'));assert(html.includes('查看完整回复与模型信息'));assert(html.includes('chat-bubble'));assert(html.includes('chatComposer'));assert(html.includes('最多')===false);
const d=chat.draft('p',group);d.text='未发草稿';d.recipients=['b'];d.history='5';d.optionsOpen=true;html=chat.render(state,group,'',esc,()=>'',button);assert(html.includes('未发草稿'));assert(html.includes('chat-send-options" open'));assert(html.includes('value="b" checked'));assert(!html.includes('value="a" checked'));
chat.clear('p','g','an older submitted message');assert.equal(d.text,'未发草稿','Late acknowledgment preserves newer typing');chat.clear('p','g','未发草稿');assert.equal(d.text,'');assert.equal(d.recipients.join(','),'b');assert.equal(d.history,'5');assert.notEqual(chat.draft('another',group),d);
assert(chat.shouldSend({key:'Enter'}));for(const e of [{key:'Enter',shiftKey:true},{key:'Enter',isComposing:true},{key:'Enter',keyCode:229},{key:'a'}])assert(!chat.shouldSend(e),'IME and newline must not send');
assert(chat.inspector(group,esc,button).includes('累计模型调用 2 次'));
// Conversation previews use the same human status as the feed; raw failure and
// consumption diagnostics remain available only inside the message disclosure.
for(const [id,label] of [['r-failure-0','有成员未能回复'],['r-stopped','本轮已停止']]){
  const g={...group,timeline:[{id,kind:'system',content:'RAW_DIAGNOSTIC <private>'}]};
  const rendered=chat.render({...state,groups:[g]},g,'',esc,()=>'',button);
  const list=rendered.split('</aside>')[0];assert(list.includes(label));assert(!list.includes('RAW_DIAGNOSTIC'));
  assert(rendered.includes('RAW_DIAGNOSTIC &lt;private&gt;'));
}
const empty={...group,timeline:[]};assert(chat.render({...state,groups:[empty]},empty,'',esc,()=>'',button).includes('发送消息，开始聊天'));
const alone={...empty,members:[]};assert(chat.render({...state,groups:[alone]},alone,'',esc,()=>'',button).includes('邀请模型，开始聊天'));
console.log('Group chat UI PASS: escaped messages, member selection, draft scope, recipients preserved and cumulative usage; synthetic only');

const delivered={...group,unread_count:2,pending_inbox:[{id:'i',title:'<script>source</script>'}],timeline:[{kind:'human',content:'问题',inbox_id:'i',source_title:'<unsafe>'}]};
const pendingHtml=chat.render({...state,groups:[delivered]},delivered,'',esc,()=>'',button);
assert(pendingHtml.includes('雷达送来 1 条待讨论发现'));assert(pendingHtml.includes('查看并讨论'));assert(pendingHtml.includes('chat-unread'));assert(pendingHtml.includes('&lt;script&gt;source&lt;/script&gt;'));assert(pendingHtml.includes('查看来源'));assert(!pendingHtml.includes('<unsafe>'));
// Eight distinct original avatars; each member and the human have different identities.
assert.equal(chat.avatarPool.length,8);assert.equal(new Set(chat.avatarPool.map((_,i)=>chat.catSVG(i))).size,8);
const six={...group,members:Array.from({length:6},(_,i)=>({id:'member-'+i,name:'成员 '+i,model:'合成模型'}))};
const avatarIds=chat.memberAvatars(six);assert.equal(new Set(avatarIds.values()).size,6);assert(![...avatarIds.values()].includes(7));
assert.deepEqual([...chat.memberAvatars({...six,members:[...six.members].reverse()})],[...avatarIds],'member ordering does not change avatars');
const agent={kind:'agent',participant_id:six.members[2].id,author:six.members[2].name,output:{position:'合成发言'}};
const rendered=chat.render({...state,groups:[six]}, {...six,timeline:[agent]},'',esc,()=>'',button);
assert(rendered.includes('chat-member-strip'));assert(rendered.includes('data-avatar-index="'+avatarIds.get(agent.participant_id)+'"'));
assert(chat.inspector(six,esc,button).includes('猫咪头像池 · 8 款'));
assert(chat.render(state,null,'模型 A',esc,()=>'',button).includes('&lt;群聊&gt;'),'search finds member names');
assert(chat.render(state,null,'bad',esc,()=>'',button).includes('&lt;群聊&gt;'),'search finds message content');
console.log('Cat avatar UI PASS: eight distinct assets, six unique members plus human, stable reorder, member and content search');
