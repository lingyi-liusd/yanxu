const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8'),ctx={};vm.createContext(ctx);
vm.runInContext(html.slice(html.indexOf('function osResultStatus('),html.indexOf('function osResultDot(')),ctx);
vm.runInContext(html.slice(html.indexOf('function osResultBranches('),html.indexOf('function osRenderEvidence(')),ctx);
const rows=[{id:'f',outcome:'FAIL'},{id:'f2',outcome:'failure'},{id:'s',outcome:'PASS',verification_status:'UNVERIFIED'},{id:'s2',outcome:'success'},{id:'p',outcome:'PARTIAL'},{id:'u',outcome:'INCONCLUSIVE'},{id:'u2',outcome:'UNKNOWN'},{id:'u3',outcome:'NOT_RUN'},{id:'u4',outcome:'PASS_CONDITIONAL'}];
const before=JSON.stringify(rows),tree=ctx.osResultBranches(rows,r=>'<article data-id="'+r.id+'">'+(r.verification_status||'UNVERIFIED')+'</article>');
assert.equal((tree.match(/class="rd-result-branch"/g)||[]).length,4);assert(!tree.includes('<details open'));assert(!tree.includes(' open>'));assert.equal((tree.match(/data-id=/g)||[]).length,rows.length);assert.equal(JSON.stringify(rows),before);
for(const [state,ids] of [['failure',['f','f2']],['success',['s','s2']],['partial',['p']],['unknown',['u','u2','u3','u4']]]){
 const own=tree.split('data-result-status="'+state+'"')[1].split('</details>')[0];for(const id of ids)assert(own.includes('data-id="'+id+'"'));assert(own.includes(ids.length+' 条结果'));
}
assert(tree.includes('UNVERIFIED'));const empty=ctx.osResultBranches([],()=>{throw Error('unexpected')});assert.equal((empty.match(/0 条结果/g)||[]).length,5);assert(tree.includes('rd-result-root'));assert(tree.includes('rd-result-forks'));assert.equal((tree.match(/<section class="rd-result-branch"/g)||[]).length,4);assert(!tree.includes('<details class="rd-result-branch"'));
console.log('Result branches PASS: red failure/green reported pass/yellow partial/neutral unknown; exact exclusive counts; closed by default; every original retained; no conditional or NOT_RUN promoted; immutable records');
