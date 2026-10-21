const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({URLSearchParams, TextEncoder});
vm.runInContext(fs.readFileSync('nodelang/studio/studio-existing-workshop.js','utf8'), context);
const providers = ['instagram','facebook','linkedin','whatsapp','x','tiktok'];
const plain = value => JSON.parse(JSON.stringify(value));

test('SOCIAL3 browser transport calls the real generic routes without accepting credentials', async () => {
  const posts=[],gets=[];
  const row=provider=>({provider,name:provider,state:'connected',display_name:'founder',token:'must-never-project'});
  const api=context.ArchHubExistingWorkshop.create({
    get:async url=>{gets.push(url);return url.includes('?') ? {ok:true,connection:row('x')} : {ok:true,items:providers.map(row)};},
    post:async (url,body)=>{posts.push({url,body});return {ok:true,connection:row(body.provider)};},
  });
  const rows=await api.listSocialConnections();
  assert.equal(rows.length,6);
  assert.equal(JSON.stringify(rows).includes('must-never-project'),false);
  for(const provider of providers) {
    await api.startSocialConnection(provider);
    await api.finishSocialConnection(provider);
    await api.cancelSocialConnection(provider);
  }
  assert.ok(posts.every(call=>call.url==='/api/universal/social-connection'));
  assert.deepEqual(plain(posts[0].body),{provider:'instagram',action:'start'});
  await api.socialConnectionStatus('x');
  assert.equal(gets.at(-1),'/api/universal/social-connection?provider=x');
  await assert.rejects(api.startSocialConnection('other'),/supported social network/);
});

test('SOCIAL3 transport preserves named blockers and lets configured review-pending sign-in open', async () => {
  const api=context.ArchHubExistingWorkshop.create({get:async()=>({ok:true,items:[
    {provider:'x',state:'blocked',blocker:'X developer app not created',can_connect:false},
    {provider:'instagram',state:'blocked',blocker:'Meta app review: instagram_content_publish pending',can_connect:true},
  ]}),post:async()=>({ok:false,error:'Named broker refusal'})});
  const rows=await api.listSocialConnections();
  assert.equal(rows[0].can_connect,false);
  assert.equal(rows[1].can_connect,true);
  assert.match(rows[1].blocker,/instagram_content_publish/);
  await assert.rejects(api.startSocialConnection('x'),/Named broker refusal/);
});
