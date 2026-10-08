// Pure Node VM regression: synthetic DOM only; no browser, service, model, or user records.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
for(const script of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi))new vm.Script(script[1]);
function code(start,end) {
  const first=html.indexOf(start),last=html.indexOf(end,first);
  assert(first>=0&&last>first,'Missing source anchor: '+start);
  return html.slice(first,last);
}
class Element {
  constructor(tag,attrs={},text='') {
    this.tagName=tag.toUpperCase();this.attrs={...attrs};this.children=[];this.parentElement=null;
    this.text=text;this.open=!!attrs.open;this.scrollLeft=0;this._top=0;this._html='';
    this.classList={add(){},remove(){},toggle(){}};
  }
  get id(){return this.attrs.id||'';}
  get textContent(){return this.text+this.children.map(n=>n.textContent).join('');}
  getAttribute(name){return this.attrs[name]??null;}
  setAttribute(name,value){this.attrs[name]=value;}
  hasAttribute(name){return Object.hasOwn(this.attrs,name);}
  append(...nodes){nodes.forEach(n=>{n.parentElement=this;this.children.push(n);});return this;}
  remove(){this.parentElement.children=this.parentElement.children.filter(n=>n!==this);}
  cloneNode(deep){const copy=new Element(this.tagName,this.attrs,this.text);if(deep)this.children.forEach(n=>copy.append(n.cloneNode(true)));return copy;}
  querySelectorAll(selector){const tags=selector.split(',').map(s=>s.toUpperCase()),out=[];function walk(n){n.children.forEach(child=>{if(tags.includes(child.tagName))out.push(child);walk(child);});}walk(this);return out;}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  // Model the browser clamping a panel's scroll when a rebuild collapses its content.
  get limit(){return this.querySelectorAll('details').some(n=>n.open)?1500:80;}
  get scrollTop(){return Math.min(this._top,this.limit);}
  set scrollTop(value){this._top=Math.max(0,Math.min(Number(value)||0,this.limit));}
  set innerHTML(value){this._html=value;this.children=[];this.scrollTop=this._top;}
  get innerHTML(){return this._html;}
  rebuild(...nodes){this.children=[];this.append(...nodes);this.scrollTop=this._top;}
}
function disclosure(label,{key,open=false,agent,strong=false,count=''}={}) {
  const attrs={};if(key)attrs['data-rd-disclosure']=key;if(agent)attrs['data-agent-name']=agent;if(open)attrs.open=true;
  const node=new Element('details',attrs),summary=new Element('summary');
  summary.append(new Element(strong?'strong':'span',{},label));if(count)summary.append(new Element('small',{},count));
  return node.append(summary);
}
function section(title,...nodes){return new Element('section').append(new Element('h3',{},title),...nodes);}
const panels={content:new Element('section',{id:'content'}),inspector:new Element('aside',{id:'inspector'})};
const chrome={},body=new Element('div'),app=new Element('div');
body.append(panels.content,panels.inspector);
let mounted=0,counter=1;
const ctx={aiView:'project',aiProjectId:'p1',aiSelection:null,aiRefreshSequence:0,aiProject:null,aiToday:null,
  data:{projects:[{id:'p1',name:'Fixture',goal:'目标',current_state:'旧说明：尚未绑定；UNKNOWN 保留。'},{id:'p2',name:'Second fixture'}]},
  $:id=>['content','inspector','agentConnectionTree'].includes(id)?panels[id]||null:chrome[id]||(chrome[id]=new Element('div',{id})),
  document:{querySelector:()=>app},aiInspectorOpen:false,pid:'p1',homeView:'projects',aiProjectPicker:()=>'',
  loadState:async()=>{},esc:s=>String(s??''),rdHumanText:s=>String(s??''),rdReadableText:s=>String(s??''),
  osInspectorText:s=>'<p>'+String(s??'')+'</p>',osInspectorSection:(title,body)=>'<section><h3>'+title+'</h3>'+body+'</section>',
  aiTime:s=>s,encodeURIComponent,Date,
  api:async route=>route.startsWith('project-focus')?{focus:null}:route.startsWith('project/manager')?null:{project:{id:ctx.aiProjectId}}};
vm.createContext(ctx);
ctx.osUpdateSetupIndicators=()=>{};
vm.runInContext(code('function aiRenderContent()','function aiTime('),ctx);
vm.runInContext(code('renderContent = function () { if (aiView)','home = function () { aiView'),ctx);
vm.runInContext(code('function osDisclosure(','/* Human-facing output only:'),ctx);
vm.runInContext(code('function aiRenderInspector()','function osSelect('),ctx);
vm.runInContext(code('async function aiRefresh()','function osUpdateAgentConnections('),ctx);
vm.runInContext(code('function osUpdateAgentConnections()','async function osPollAgentConnections()'),ctx);
const actualInspector=ctx.aiRenderInspector;
function projectBody(){panels.content.rebuild(section('项目设置',disclosure('自动总结设置',{key:'summary-settings'}),disclosure('未打开区域',{key:'untouched'}),disclosure('默认展开',{key:'default-open',open:true})));}
ctx.aiRenderProject=projectBody;
ctx.aiRenderToday=()=>panels.content.rebuild(section('Today',disclosure('自动总结设置',{key:'summary-settings'})));
ctx.aiRenderAgents=()=>panels.content.rebuild(new Element('div',{id:'agentConnectionTree'}).append(disclosure('Codex',{agent:'Codex',strong:true})));
ctx.aiRenderInspector=()=>{if(panels.inspector)ctx.aiKeepReadingState(['inspector'],()=>panels.inspector.rebuild(section('详情',disclosure('完整记录',{key:'full-record'}))));};
ctx.osMountStatus=()=>{mounted++;panels.content.append(section('自主管理 Agent',disclosure('运行边界与记录 · '+counter,{key:'run-records'})));};
ctx.aiOldRender=()=>{ctx.aiRenderContent();panels.inspector.rebuild();};
function get(root,key){return root.querySelectorAll('details').find(n=>n.getAttribute('data-rd-disclosure')===key);}
async function refresh(){assert.equal(await ctx.aiRefresh(),true);}
async function regressions(){
  await refresh();
  get(panels.content,'summary-settings').open=true;
  get(panels.content,'default-open').open=false;
  get(panels.content,'run-records').open=true;
  get(panels.inspector,'full-record').open=true;
  panels.content.scrollTop=640;panels.content.scrollLeft=45;panels.inspector.scrollTop=420;
  counter=12;await refresh();
  assert(get(panels.content,'summary-settings').open,'Background redraw must keep settings expanded');
  assert(get(panels.content,'run-records').open,'Mounted management records must survive changing counts');
  assert(!get(panels.content,'untouched').open,'Untouched disclosures keep their folded default');
  assert(!get(panels.content,'default-open').open,'A user close overrides an open HTML default');
  assert.equal(panels.content.scrollTop,640,'Restore scroll after disclosure height is restored');
  assert.equal(panels.content.scrollLeft,45);assert.equal(panels.inspector.scrollTop,420);
  // Capture at response commit, including interactions while the read is in flight.
  let release;const regularAPI=ctx.api;
  ctx.api=async route=>route.startsWith('project-focus')?new Promise(resolve=>{release=resolve;}):regularAPI(route);
  const pending=ctx.aiRefresh();await new Promise(resolve=>setImmediate(resolve));
  get(panels.content,'summary-settings').open=false;panels.content.scrollTop=710;
  release({focus:null});await pending;ctx.api=regularAPI;
  assert(!get(panels.content,'summary-settings').open,'Manual close during the read must remain effective');
  assert.equal(panels.content.scrollTop,710);
  // Same markup on another project/view must neither inherit disclosure state nor scroll.
  ctx.aiProjectId='p2';await refresh();
  assert(!get(panels.content,'run-records').open);assert(!get(panels.inspector,'full-record').open);
  assert.equal(panels.content.scrollTop,0);assert.equal(panels.content.scrollLeft,0);assert.equal(panels.inspector.scrollTop,0);
  get(panels.content,'summary-settings').open=true;panels.content.scrollTop=230;
  ctx.aiView='today';await refresh();assert(!get(panels.content,'summary-settings').open);assert.equal(panels.content.scrollTop,0);
  get(panels.content,'summary-settings').open=true;panels.content.scrollTop=160;
  ctx.aiView='project';await refresh();assert(get(panels.content,'summary-settings').open);assert.equal(panels.content.scrollTop,230);
  ctx.aiProjectId='p1';await refresh();assert(!get(panels.content,'summary-settings').open);assert(get(panels.content,'run-records').open);assert.equal(panels.content.scrollTop,710);
  // Inspector state is also tied to the selected record, even when section labels match.
  ctx.aiSelection={kind:'result',id:'r1'};ctx.aiRenderInspector();assert(!get(panels.inspector,'full-record').open);assert.equal(panels.inspector.scrollTop,0);
  get(panels.inspector,'full-record').open=true;panels.inspector.scrollTop=310;
  ctx.aiSelection={kind:'result',id:'r2'};ctx.aiRenderInspector();assert(!get(panels.inspector,'full-record').open);
  ctx.aiSelection={kind:'result',id:'r1'};ctx.aiRenderInspector();assert(get(panels.inspector,'full-record').open);assert.equal(panels.inspector.scrollTop,310);
  // Full render includes a legacy Inspector rewrite: nested panel captures must not replace state.
  ctx.aiSelection=null;ctx.aiKeepReadingState(['content','inspector'],()=>{
    ctx.aiRenderContent();panels.inspector.rebuild();ctx.aiRenderInspector();ctx.osMountStatus();
  });
  assert(get(panels.inspector,'full-record').open);assert.equal(panels.inspector.scrollTop,420);
  assert(get(panels.content,'run-records').open);assert.equal(panels.content.scrollTop,710);
  // Temporarily absent disclosures can return without losing their last explicit state.
  ctx.aiKeepReadingState(['content'],()=>panels.content.rebuild());
  ctx.aiKeepReadingState(['content'],()=>{projectBody();ctx.osMountStatus();});
  assert(get(panels.content,'run-records').open);
  assert.equal(panels.content.scrollTop,710,'A short placeholder must not erase the desired scroll position');
  // Exercise the real full-render wrapper, including project navigation through loading surfaces.
  ctx.aiRenderProject=()=>{if(ctx.aiProject?.project?.id)projectBody();else panels.content.rebuild();};
  ctx.aiProjectId='p2';ctx.aiProject=null;ctx.render();await refresh();
  assert(get(panels.content,'summary-settings').open);assert.equal(panels.content.scrollTop,230);
  ctx.aiProjectId='p1';ctx.aiProject=null;ctx.render();await refresh();
  assert(get(panels.content,'run-records').open);assert.equal(panels.content.scrollTop,710);
  // The existing disclosure generator provides count-independent identity without changing defaults.
  assert(ctx.osDisclosure('待复核提案 · 1','one').includes('data-rd-disclosure="待复核提案"'));
  assert(ctx.osDisclosure('待复核提案 · 12','many').includes('data-rd-disclosure="待复核提案"'));
  assert(!ctx.osDisclosure('运行边界与记录','fixture').includes(' open'));
  // Stable semantic keys, including parent identity, tolerate reorder and nested duplicate labels.
  ctx.aiView='artifacts';
  const renderTree=reverse=>ctx.aiKeepReadingState(['content'],()=>{
    const a=disclosure('A',{strong:true,count:'1 项'}).append(disclosure('原始记录'));
    const b=disclosure('B',{strong:true,count:'9 项'}).append(disclosure('原始记录'));
    panels.content.rebuild(section('树',...(reverse?[b,a]:[a,b])));
  });
  renderTree(false);let tree=panels.content.querySelectorAll('details');tree[0].open=true;tree[1].open=true;
  renderTree(true);tree=panels.content.querySelectorAll('details');assert(!tree[0].open);assert(!tree[1].open);assert(tree[2].open);assert(tree[3].open);
  // Interface translation after mounting must not change the identity of the old DOM.
  tree[2].children[0].children[0].text='Translated A';renderTree(false);tree=panels.content.querySelectorAll('details');assert(tree[0].open);
  // Removed panels and rendering failures release the transaction guard safely.
  ctx.aiView='project';const inspector=panels.inspector;delete panels.inspector;await refresh();actualInspector();panels.inspector=inspector;
  assert.throws(()=>ctx.aiKeepReadingState(['content'],()=>{throw Error('synthetic renderer failure');}),/synthetic/);
  ctx.aiView='project';await refresh();assert(get(panels.content,'run-records').open);
  // Heartbeat tree refresh uses the same transaction and retains a selected Inspector.
  ctx.aiView='agents';await refresh();
  const connectionTree=panels.content.querySelector('div');panels.agentConnectionTree=connectionTree;
  connectionTree.querySelector('details').open=true;panels.content.scrollTop=480;
  ctx.aiSelection={kind:'connection',id:'codex-managed'};ctx.aiRenderInspector();
  get(panels.inspector,'full-record').open=true;panels.inspector.scrollTop=240;
  Object.defineProperty(connectionTree,'innerHTML',{set(){this.rebuild(disclosure('Codex',{agent:'Codex',strong:true}));panels.content.scrollTop=panels.content.scrollTop;},configurable:true});
  ctx.osAgentConnectionTree=()=>'<fixture>';ctx.osUpdateAgentConnections();
  assert(connectionTree.querySelector('details').open);assert.equal(panels.content.scrollTop,480);
  assert(get(panels.inspector,'full-record').open);assert.equal(panels.inspector.scrollTop,240);
  delete panels.agentConnectionTree;assert.doesNotThrow(()=>ctx.osUpdateAgentConnections());
  ctx.aiSelection=null;ctx.aiView='project';await refresh();
  const content=panels.content;delete panels.content;delete panels.inspector;
  assert.doesNotThrow(()=>ctx.aiKeepReadingState(['content','inspector'],()=>{}));
  panels.content=content;panels.inspector=inspector;
  // An inactive AI surface leaves legacy scroll alone and later returns to its own state.
  ctx.aiView='';ctx.aiKeepReadingState(['content'],()=>panels.content.rebuild(disclosure('Legacy',{open:true})));
  panels.content.scrollTop=190;ctx.aiKeepReadingState(['content'],()=>{});assert.equal(panels.content.scrollTop,190);
  ctx.aiView='project';await refresh();assert(get(panels.content,'run-records').open);
  // Execute the real Inspector renderer and verify the saved original is still present.
  ctx.aiSelection=null;ctx.aiManagerStatus=null;actualInspector();
  assert(panels.inspector.innerHTML.includes('已保存状态说明（非实时）'));
  assert(panels.inspector.innerHTML.includes(ctx.data.projects[0].current_state));
  assert(!panels.inspector.innerHTML.includes('<h3>当前记录状态</h3>'));
  assert(mounted>10);
  console.log('UI disclosure PASS: refresh/late interaction, open and closed defaults, both panel scrolls, project/view/record isolation, nesting/reorder/counts/language, full render, absent DOM, legacy boundary, original saved-status text');
}
regressions().catch(error=>{console.error(error);process.exitCode=1;});
