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
test('Library owners retain preferences, reject invalid categories and preserve socket alias precedence',()=>{
  const root=path.resolve(studio,'../../..'),base=path.join(root,'.cache/designsplit');
  fs.mkdirSync(base,{recursive:true});
  const directory=fs.mkdtempSync(path.join(base,'library-owner-'));
  assert.ok(directory.startsWith(root+path.sep));
  const env={...process.env,PYTHONUTF8:'1',PYTHONPATH:path.join(root,'01.APP'),USERPROFILE:directory,HOME:directory,LOCALAPPDATA:directory,APPDATA:directory,TEMP:directory,TMP:directory};
  try{
    require('node:child_process').execFileSync('python',['-c',`
from pathlib import Path
from types import SimpleNamespace
from nodelang.nograph_server import JsonFile, Refused, r_settings_action
folder=Path(${JSON.stringify(directory.replaceAll('\\','/'))})
def owner():
    return SimpleNamespace(files={'settings':JsonFile(folder/'settings.json',{}),'companion':JsonFile(folder/'companion.json',{})})
def call(function,args):
    return r_settings_action(owner(),SimpleNamespace(body={'function':function,'args':args}))['result']
assert call('setLibraryCollapsed',[['Start','Change']])['libraryCollapsed']==['Start','Change']
assert call('readLibraryCollapsed',[])['libraryCollapsed']==['Start','Change']
try:
    call('setLibraryCollapsed',[['unknown']])
except Refused:
    pass
else:
    raise AssertionError('Invalid category accepted')
assert call('readLibraryCollapsed',[])['libraryCollapsed']==['Start','Change']
from nodelang.session_files import _params_and_feeds
node={'params':{'value':0},'paramDefs':[{'id':'value','type':'number'}]}
params,feeds=_params_and_feeds(node,'data.constant',{'value':7,'param:value':9})
assert params['value']==9 and feeds['value']==7 and 'param:value' not in feeds
`],{cwd:root,env,encoding:'utf8',windowsHide:true});
  }finally{fs.rmSync(directory,{recursive:true,force:true});}
});
