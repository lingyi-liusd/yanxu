const assert=require('assert'),fs=require('fs'),vm=require('vm');
const source=fs.readFileSync(require('path').join(__dirname,'../apps/links.js'),'utf8');
function legacy(search,hash=''){
 let redirected;
 const ctx={URLSearchParams,location:{search,hash,replace:url=>redirected=url},document:{querySelector(){throw Error('Legacy redirect must precede UI mounting');}}};
 vm.runInNewContext(source,ctx);return redirected;
}
assert.equal(legacy('?mode=observe&project=p1&item=a1','#evidence'),'/apps/radar/?project=p1&item=a1#evidence');
assert.equal(legacy('?mode=review&project=p2&item=r1'),'/apps/discussion/?mode=review&project=p2&item=r1');
assert.equal(legacy('?app=discussion&inbox=1&item=i1'),'/apps/discussion/?inbox=1&item=i1');
for(const app of ['research','discussion','radar']){
 let launcher;
 const host={querySelector:()=>({after:x=>launcher=x})};
 const ctx={URLSearchParams,location:{search:'',hash:''},document:{querySelector:()=>host,createElement:()=>({addEventListener(){}}),addEventListener(){}},...(app!=='research'?{APP:app,STANDALONE_APP:true}:{})};
 vm.runInNewContext(source,ctx);
 assert.equal((launcher.innerHTML.match(/<a /g)||[]).length,3);
 assert.equal((launcher.innerHTML.match(/aria-current="page"/g)||[]).length,1);
 assert(launcher.innerHTML.includes('href="/"'));assert(launcher.innerHTML.includes('href="/apps/discussion/"'));assert(launcher.innerHTML.includes('href="/apps/radar/"'));
}
console.log('Peer app entries PASS: three pages, one current entry, legacy project/item/inbox/hash preserved, no API writes');
