const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const studio=path.resolve(__dirname,'../../01.APP/nodelang/studio');
const babel={};vm.runInNewContext(fs.readFileSync(path.join(studio,'vendor/babel.js'),'utf8'),babel);
const code=babel.Babel.transform(fs.readFileSync(path.join(studio,'account-tools.jsx'),'utf8'),{presets:['react'],sourceType:'script'}).code;

function render(controlErrors,officeInvitations=[]){
 const state={firms:[],activeFirm:'',officeInvitations,controlErrors};
 const UI={A:{},api:{},useData:()=>state,useApp:()=>({}),Btn:'button',Card:'section',Chip:'span',
  useRegisteredActions:()=>({runAction(){},actionState:{},retryAction(){}}),RegisteredActionStatus:'status'};
 const React={Fragment:'fragment',createElement:(type,props,...children)=>({type,props:props||{},children})};
 vm.runInNewContext(code,{window:{UI},React});
 return UI.AccountIdentity();
}

test('missing invitations is visibly unavailable, not an empty successful list',()=>{
 const message='Signed in. Office invitations unavailable until the cloud service is updated.';
 assert.ok(JSON.stringify(render({officeInvitations:message})).includes(message));
});

test('recovery removes availability notice and retains real invitation controls',()=>{
 const tree=JSON.stringify(render({},[{id:'invite',office:'Actual office',status:'Pending'}]));
 assert.ok(tree.includes('Actual office'));
 assert.ok(tree.includes('Accept invitation'));
 assert.ok(tree.includes('Decline invitation'));
 assert.ok(!tree.includes('unavailable'));
});
