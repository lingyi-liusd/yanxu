/* Review presentation: escaped text and explicit material locations, no HTML from models. */
globalThis.YanxuReview = (() => {
  const fields={recommendation:'建议与理由',alternatives:'候选方案',tradeoffs:'关键取舍',disagreements:'分歧与反例',unknowns:'缺失信息与待验证假设',next_step:'下一步',recheck_conditions:'何时重新评审'};
  const relation={source:'已定位来源 · 尚未核实支持程度',inference:'推断',unknown:'未知'};
  function render(room){
    const brief=room.brief;
    let html='<p class="eco-muted">本次边界：'+esc(room.constraints||'未补充约束')+'</p>';
    if(room.history_source){const h=room.history_source;html+='<section class="eco-notice"><h3>本次使用历史快照</h3><p>'+esc(h.reason)+'</p><details><summary>查看历史来源与版本</summary><p>原评审 '+esc(h.room_id)+' · 对象版本 '+h.object_rev+' · 原消耗 '+h.source_used_calls+' / '+h.source_max_calls+'</p><p>原上下文：'+esc(h.context_hash)+'</p>'+h.bindings.map(b=>'<p>'+esc(b.material_id+' ← '+b.kind+'/'+b.id+' · '+b.version)+'</p>').join('')+'</details><p>历史材料不代表当前状态；新评审不重置原消耗，来源仍未核验。</p></section>';}
    if(room.context?.selection)html+='<details><summary>本次项目记录范围</summary><p>'+esc(room.context.boundary)+'</p>'+[['tasks','任务'],['decisions','判断'],['results','结果']].map(([key,label])=>'<p>'+label+' · '+room.context[key].length+' 条：'+esc(room.context[key].map(r=>r.title||r.summary||r.id).join('、')||'未选取')+'</p>').join('')+'</details>';
    if(brief){
      html+='<div class="review-brief"><p class="eco-muted">简报版本 '+brief.revision+' · '+(brief.status==='human_edited'?'人工修订':'AI 草稿')+' · 未核验</p>';
      for(const [key,label]of Object.entries(fields))html+='<section><h3>'+label+'</h3><p>'+esc(brief.content[key]||'未提供')+'</p></section>';
      html+='<section><h3>论断与引用</h3>'+(brief.content.citations.length?brief.content.citations.map(c=>'<article class="review-citation"><p>'+esc(c.claim)+'</p><small>'+esc(relation[c.relation])+'</small>'+(c.material_id?'<button class="eco-button" type="button" data-review-material="'+esc(c.material_id)+'" data-review-line="'+esc(c.locator.split('-')[0])+'">'+esc(c.material_id+' · '+c.locator)+'</button>':'')+'</article>').join(''):'<p>没有登记可定位引用；需要人工检查依据。</p>')+'</section></div>';
    }else html+='<p class="eco-notice">材料已经保存。预览并确认后运行一次评审，获得建议、取舍、未知项与下一步。</p>';
    html+='<details class="review-materials" '+(!brief?'open':'')+'><summary>本次选取的材料 · '+room.materials.length+' 份</summary>';
    for(const m of room.materials)html+='<section id="review-material-'+esc(m.id)+'"><h3>'+esc(m.id+' · '+m.title)+'</h3><p class="eco-muted">'+esc(m.reference||'用户选取材料')+' · 版本 '+esc(m.version.slice(0,12))+'</p><pre>'+m.content.split(/\r\n|\r|\n/).map((line,i)=>'<span id="review-line-'+esc(m.id)+'-L'+(i+1)+'">'+esc('L'+(i+1)+': '+line)+'</span>').join('\n')+'</pre></section>';
    html+='</details><p class="eco-muted">材料是本次保存的摘录；引用定位不代表论断正确，也不代表覆盖了整个来源。</p>';
    if(room.review_of)html+='<details><summary>本次复核的原判断</summary><p>'+esc(room.review_of.title||room.review_of.question)+'</p><p>'+esc(room.review_of.answer||room.review_of.note||'')+'</p><p>原判断保留；本次评审不会自动替代它。</p></details>';
    return html;
  }
  function editor(room,form){
    return Object.entries(fields).map(([key,label])=>form(key,label,room.brief.content[key],'maxlength="12000"')).join('')+
      '<h3>论断与引用</h3><div data-citation-rows>'+room.brief.content.citations.map(c=>citationRow(room,c,form)).join('')+'</div><button type="button" class="eco-button" data-add-citation>添加引用</button>'+
      form('reason','修订理由','','required maxlength="2000"');
  }
  function citationRow(room,c,form){
    const options=(name,values,current)=>'<label class="eco-field">'+name+'<select name="'+(name==='依据类型'?'relation':'material_id')+'">'+values.map(([value,label])=>'<option value="'+esc(value)+'" '+(current===value?'selected':'')+'>'+esc(label)+'</option>').join('')+'</select></label>';
    return '<fieldset class="review-citation">'+form('claim','这条引用支持什么论断？',c.claim||'','required maxlength="2000"')+options('依据类型',Object.entries(relation),c.relation||'unknown')+options('材料',[['','没有可定位来源'],...room.materials.map(m=>[m.id,m.id+' · '+m.title])],c.material_id||'')+'<label class="eco-field">材料行号，例如 L1-L3<input name="locator" value="'+esc(c.locator||'')+'" maxlength="40"></label><button type="button" class="eco-button" data-remove-citation>移除此引用</button></fieldset>';
  }
  function bindEditor(host,room,form){
    const rows=host.querySelector('[data-citation-rows]');
    const bindRows=()=>rows.querySelectorAll('[data-remove-citation]').forEach(button=>button.onclick=()=>button.closest('fieldset').remove());
    host.querySelector('[data-add-citation]').onclick=()=>{if(rows.children.length>=24)return;rows.insertAdjacentHTML('beforeend',citationRow(room,{},form));bindRows();};bindRows();
  }
  function editedContent(form){
    const result=Object.fromEntries(Object.keys(fields).map(key=>[key,String(form.get(key)||'')]));
    result.citations=form.getAll('claim').map((claim,i)=>({claim:String(claim),relation:String(form.getAll('relation')[i]),material_id:String(form.getAll('material_id')[i]),locator:String(form.getAll('locator')[i])}));return result;
  }
  function bind(host){host.querySelectorAll('[data-review-material]').forEach(button=>button.onclick=()=>{
    const details=host.querySelector('.review-materials');if(details)details.open=true;
    const line=document.getElementById('review-line-'+button.dataset.reviewMaterial+'-'+button.dataset.reviewLine);if(line){line.scrollIntoView({block:'center'});line.classList.add('review-highlight');setTimeout(()=>line.classList.remove('review-highlight'),2000);}
  });}
  return {fields,render,editor,bind,bindEditor,editedContent};
})();
