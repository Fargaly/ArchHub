const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const studio=path.resolve(__dirname,'../../01.APP/nodelang/studio');
function settings(){
  const window={UI:{}};
  const manifest=JSON.parse(fs.readFileSync(path.join(studio,'compiled/manifest.json'),'utf8'));
  const source=fs.readFileSync(path.join(studio,'compiled',manifest.files.find(file=>file.source==='ds_settings3.jsx').output),'utf8');
  vm.runInNewContext(source,{window,React:{}});
  return window.UI;
}
test('profiling groups requests by agent/model/provider and sums only observed measurements',()=>{
  const rows=settings().requestGroups([
    {agent:'native-session',model:'model-a',provider:'local',tokens:120,ms:214},
    {agent:'native-session',model:'model-a',provider:'local',tokens:null,ms:0},
    {agent:'native-session',model:'model-b',provider:'local',tokens:0,ms:18},
  ],[{id:'native-session',name:'Codex'}],[]);
  assert.deepEqual(JSON.parse(JSON.stringify(rows.map(({key,...row})=>row))),[
    {agent:'Codex',model:'model-a',provider:'local',count:2,tokens:120,measuredTokens:1,ms:214,measuredTime:1},
    {agent:'Codex',model:'model-b',provider:'local',count:1,tokens:0,measuredTokens:1,ms:18,measuredTime:1},
  ]);
  assert.deepEqual(JSON.parse(JSON.stringify(settings().requestGroups([],[],[]))),[]);
});

test('unknown agent identities stay separate without exposing their ids',()=>{
 const groups=settings().requestGroups([{agent:'session-a',model:'m',provider:'p',ms:1},{agent:'session-b',model:'m',provider:'p',ms:2}],[],[]);
 assert.equal(groups.length,2);assert.ok(groups.every(row=>row.agent==='Unidentified agent'));
});
