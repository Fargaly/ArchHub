const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const studio=path.resolve(__dirname,'../../01.APP/nodelang/studio');
const read=name=>fs.readFileSync(path.join(studio,name),'utf8');
const sources=()=>JSON.parse(read('compiled/manifest.json')).files.map(file=>read(file.source)).join('\n');

test('a: first screen and Studio shell never expose internal host-probe or unknown text',()=>{
 const visibleShell=read('ds_home2.jsx')+read('app.jsx');
 assert.doesNotMatch(visibleShell,/host probe is still running/i);
 assert.doesNotMatch(visibleShell,/>[^<]*\bunknown\b[^<]*</i);
});
test('v: provider rows show plain status words, never raw provider codes',()=>{
 const providers=read('agent-states.jsx')+read('ds_settings3.jsx');
 for(const raw of ['NO KEY','Paste a real key','Local runtime is running'])assert.equal(providers.includes(raw),false,raw);
});
test('row a: no internal host-probe wording anywhere the user can see',()=>{
 assert.doesNotMatch(sources()+read('studio.html'),/host probe is still running|hosts were not read|has answered a probe/i);
});
