/* Shared preferences restore in peer shells without touching model connections. */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(require('path').join(__dirname,'../apps/shell.js'),'utf8');
const saved=new Map([['rd-theme','dark']]),events={},button={textContent:''};
const ctx={APP:'discussion',innerWidth:1280,document:{documentElement:{dataset:{}},querySelector:()=>button},window:{addEventListener:(name,fn)=>events[name]=fn},localStorage:{getItem:key=>saved.get(key),setItem:(key,value)=>saved.set(key,value)},fetch:()=>{throw Error('Theme must never access API');}};
vm.createContext(ctx);vm.runInContext(source,ctx);
assert.equal(ctx.document.documentElement.dataset.theme,'dark');
ctx.appToggleTheme();assert.equal(saved.get('rd-theme'),'light');assert.equal(button.textContent,'使用深色外观');
events.storage({key:'rd-theme',newValue:'dark'});assert.equal(ctx.document.documentElement.dataset.theme,'dark');
events.storage({key:'other',newValue:'light'});assert.equal(ctx.document.documentElement.dataset.theme,'dark');
events.storage({key:'rd-theme',newValue:null});assert.equal(ctx.document.documentElement.dataset.theme,'light');
console.log('Peer app theme PASS: saved preference, toggle, cross-tab storage updates, deletion fallback, no API access.');
