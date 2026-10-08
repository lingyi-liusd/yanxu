/* Three peer applications. Switching apps navigates, never embeds another surface. */
(()=>{
 const standalone=typeof STANDALONE_APP!=='undefined'&&STANDALONE_APP;
 const q=new URLSearchParams(location.search);
 const requested=q.get('app')||({review:'discussion',chat:'discussion',observe:'radar'})[q.get('mode')];
 if(!standalone&&['discussion','radar'].includes(requested)){
  q.delete('app');if(q.get('mode')!=='review')q.delete('mode');location.replace('/apps/'+requested+'/?'+q+location.hash);return;
 }
 const current=standalone?APP:'research';
 const entries=[['research','续芽工作台','项目与行动','/','芽'],['discussion','聊天室','群聊与多模型讨论','/apps/discussion/','聊'],['radar','雷达','来源与变化发现','/apps/radar/','◎']];
 const host=document.querySelector(standalone?'.app-sidebar':'.rd-sidebar');if(!host)return;
 const switcher=document.createElement('details');switcher.className='ecosystem-launcher';
 switcher.innerHTML='<summary aria-label="切换应用"><span>应用</span><span aria-hidden="true">▦</span></summary><div class="ecosystem-launcher-panel"><small>续芽生态</small>'+entries.map(([id,name,desc,url,glyph])=>'<a aria-label="'+name+' · '+desc+'" href="'+url+'" '+(current===id?'aria-current="page"':'')+'><i class="launch-'+id+'">'+glyph+'</i><span><strong>'+name+'</strong><small>'+desc+'</small></span><b>'+(current===id?'当前':'↗')+'</b></a>').join('')+'</div>';
 const brand=host.querySelector(standalone?'.app-brand':'.rd-brand');brand.after(switcher);
 document.addEventListener('click',e=>{if(!switcher.contains(e.target))switcher.open=false;});
 switcher.addEventListener('keydown',e=>{if(e.key==='Escape'){switcher.open=false;switcher.querySelector('summary').focus();}});
})();
