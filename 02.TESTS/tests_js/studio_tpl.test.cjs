const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..','..');

test('production template edit adapter writes through the admitted owner and fences a changed account',async()=>{
 const vm=require('node:vm'),context=vm.createContext({URLSearchParams,TextEncoder});
 vm.runInContext(fs.readFileSync(path.join(root,'01.APP/nodelang/studio/studio-existing-workshop.js'),'utf8'),context);
 const calls=[];let resolve;
 const api=context.ArchHubExistingWorkshop.create({get:async()=>({}),post:async(url,body)=>{
  calls.push({url,body});return await new Promise(done=>resolve=done);
 }});
 const canvas={graph_id:'graph-a',root:'scope-a',revision:1,authorization:{subject:'owner-a',session:'view-a'},workshops:[]};
 api.setCanvas(canvas);
 const saving=api.editHomeTemplate('tpl-sheet-register',{delete:true});
 assert.equal(calls[0].url,'/api/universal/node-create');
 assert.deepEqual(JSON.parse(JSON.stringify(calls[0].body)),{template:'tpl-sheet-register',delete:true});
 resolve({ok:true,template:'tpl-sheet-register',revision:2});await saving;
 const stale=api.editHomeTemplate('tpl-sheet-register',{delete:true});
 api.setCanvas({...canvas,authorization:{subject:'owner-b',session:'view-b'}});
 resolve({ok:true,template:'tpl-sheet-register',revision:3});await assert.rejects(stale,/workspace changed/);
});
