const fs=require('fs'),assert=require('assert'),path=require('path');
const css=fs.readFileSync(path.join(__dirname,'../ecosystem.css'),'utf8');
const clean=css.replace(/\/\*[\s\S]*?\*\//g,'');
const vars=selector=>Object.fromEntries([...clean.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter(m=>m[1].trim()===selector).flatMap(m=>[...m[2].matchAll(/(--[\w-]+):([^;]+)/g)].map(x=>[x[1],x[2].trim()])));
const light=vars(':root'),dark={...light,...vars(':root[data-theme="dark"]')};
const luminance=h=>{h=h.slice(1);if(h.length===3)h=[...h].map(c=>c+c).join('');const v=[0,2,4].map(i=>parseInt(h.slice(i,i+2),16)/255).map(c=>c<=.04045?c/12.92:((c+.055)/1.055)**2.4);return .2126*v[0]+.7152*v[1]+.0722*v[2];};
const ratio=(a,b)=>{const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);};
for(const [name,v] of [['light',light],['dark',dark]]){
 for(const bg of ['--eco-accent','--eco-accent-hover'])assert(ratio(v['--eco-on-accent'],v[bg])>=4.5,`${name} button on ${bg}`);
 if(name==='dark')for(const bg of ['--eco-surface','--eco-subtle','--eco-selection','--eco-diff-added','--eco-diff-removed'])for(const fg of ['--eco-text','--eco-muted'])assert(ratio(v[fg],v[bg])>=4.5,`${name} ${fg} on ${bg}: ${ratio(v[fg],v[bg])}`);
}
assert(css.includes('color:var(--eco-on-accent)!important'));
assert(css.includes('background:var(--eco-diff-added);min-width:0'));
assert(css.includes('order:-1;background:var(--eco-diff-removed)'));
const darkRules=css.slice(css.indexOf('/* Dark surfaces'));
const chat=fs.readFileSync(path.join(__dirname,'../chat_ui.js'),'utf8');assert(chat.includes('class="chat-list-tools"'));
for(const s of ['.chat-list-tools input','.chat-list','.chat-composer','.chat-options-panel','.radar-source-pane','.radar-discovery-pane','.radar-reading-pane','#toolbar select'])assert(darkRules.includes(s),s);
console.log(`Ecosystem palette PASS: buttons and dark text >=4.5:1 on declared tokens; dark primary ${ratio(dark['--eco-on-accent'],dark['--eco-accent']).toFixed(2)}:1, diff text ${ratio(dark['--eco-text'],dark['--eco-diff-added']).toFixed(2)} / ${ratio(dark['--eco-text'],dark['--eco-diff-removed']).toFixed(2)}:1. Static tokens only; browser cascade/visual QA separate.`);
