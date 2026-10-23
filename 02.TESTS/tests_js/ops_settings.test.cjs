const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
async function adapter(serve){
 const calls=[],notices=[];
 const canvas={root:'graph',scope:{current:'graph'},nodes:[],wires:[],catalog:[],workshops:[]};
 const window={structuredClone:globalThis.structuredClone,crypto:require('node:crypto').webcrypto,ARCHHUB_BOOT:{home_load_ms:60000,token:'local',csrf:'local'},
  document:{hidden:true,addEventListener(){}},addEventListener(){},dispatchEvent(event){notices.push(event.detail.message);},
  ArchHubStudioAuthority:{create:({get})=>({load:()=>get('/api/universal/canvas')})}};
 const fetch=async(url,options={})=>{
  const body=options.body?JSON.parse(options.body):null;calls.push({url,body,headers:options.headers});
  const data=url==='/api/universal/canvas'?canvas:await serve(url,body);
  return {ok:data.ok!==false,status:data.ok===false?409:200,json:async()=>data};
 };
 const context={window,document:window.document,fetch,CustomEvent:class{constructor(type,options){this.detail=options.detail;}},
  setTimeout,clearTimeout,URLSearchParams,AbortSignal:globalThis.AbortSignal,console};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../01.APP/nodelang/studio/api.js'),'utf8'),context);
 await window.ArchHubAPI.ready;await new Promise(resolve=>setTimeout(resolve,0));
 return {api:window.ArchHubAPI,calls,notices};
}
test('Settings commands use one authenticated owner and publish only confirmed policy and membership',async()=>{
 let deny=false;
 const {api,calls,notices}=await adapter((url,body)=>{
  if(url==='/api/universal/workspace-roots')return {ok:true,roots:[{root_id:'workspace',path:'C:/FIXTURE',privacy:'private'}]};
  if(url==='/api/universal/settings-action'){
   if(deny)return {ok:false,error:'Owner refused: refresh this workspace'};
   if(body.function==='setWorkspaceRules')return {ok:true,result:{workspacePolicies:{workspace:body.args[1]},message:'Policy confirmed'}};
   if(body.function==='setGraphWorkspaces')return {ok:true,result:{workspaceIds:body.args[1]}};
  }
  return {ok:true,result:[]};
 });
 await api.listWorkspaces();
 await api.setWorkspaceRules('workspace',{rules:'Keep drawings private',privacy:'Secret'});
 await api.setGraphWorkspaces(['workspace']);
 assert.equal(api.getSnapshot().workspaces[0].rules,'Keep drawings private');
 assert.equal(api.getSnapshot().graph.workspaceIds[0],'workspace');
 assert.ok(notices.includes('Policy confirmed'));
 const saved=JSON.stringify(api.getSnapshot());deny=true;
 await assert.rejects(api.setWorkspaceRules('workspace',{rules:'Rejected'}),/Owner refused/);
 assert.equal(JSON.stringify(api.getSnapshot()),saved);
 const command=calls.find(row=>row.body?.function==='setGraphWorkspaces');
 assert.equal(command.body.args[0],'graph');
 assert.equal(command.headers['X-ArchHub-Session'],'local');
 assert.equal(command.headers['X-ArchHub-CSRF'],'local');
});
test('Recovery, device and permission results preserve their actual outcome; errors never become success',async()=>{
 const {api,notices}=await adapter((url,body)=>{
  if(url!=='/api/universal/settings-action')return {ok:true,result:[]};
  if(body.function==='backUpNow')return {ok:true,result:{backups:[{id:'verified',name:'Verified copy'}],message:'Verified copy created'}};
  if(body.function==='rollBack')return {ok:true,result:{status:'prepared',restored:false,message:'Restore prepared; activation required'}};
  return {ok:false,error:'Owner: open the admitted node and retry'};
 });
 await api.backUpNow();assert.equal(api.getSnapshot().backups[0].id,'verified');
 const result=await api.rollBack('verified');assert.equal(result.restored,false);
 assert.ok(notices.includes('Restore prepared; activation required'));
 const saved=JSON.stringify(api.getSnapshot());
 await assert.rejects(api.selectDevice('missing'),/admitted node/);
 await assert.rejects(api.grantAccess('missing'),/admitted node/);
 assert.equal(JSON.stringify(api.getSnapshot()),saved);
});
