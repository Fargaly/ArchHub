const test = require('node:test');
const assert = require('node:assert/strict');
const {mount,providers,names} = require('./social3_surface_helpers.cjs');

test('SOCIAL3 six visible provider buttons connect through the shared broker and show callback identity', async () => {
  const s = await mount();
  try {
    assert.equal(s.doc.querySelectorAll('[data-social-provider]').length,6);
    for(const provider of providers) {
      const row=s.doc.querySelector(`[data-social-provider="${provider}"]`);
      assert.match(row.textContent,/Not connected/);
      assert.match(row.querySelector('button').title,/Ctrl\+K/);
      await s.click(row.querySelector('button'));
      assert.match(row.textContent,/Connected as @founder/);
    }
    assert.deepEqual(s.calls.start,providers);
    assert.deepEqual(s.calls.finish.map(row=>row[0]),providers);
    assert.equal(s.doc.querySelectorAll('input,textarea,select').length,0,'no key, token, ID or secret field');
  } finally {s.close();}
});

test('SOCIAL3 named missing configuration and provider approval blockers stay visible', async () => {
  const s=await mount({rows:providers.map((provider,i)=>({provider,name:names[i],state:'blocked',blocker:i===0?'Waiting for Meta approval: instagram_content_publish pending':`${names[i]} developer app not created`}))});
  try {
    assert.match(s.doc.body.textContent,/instagram_content_publish pending/);
    assert.match(s.doc.body.textContent,/X developer app not created/);
    assert.equal(s.doc.querySelectorAll('[data-social-provider] button:disabled').length,6);
    assert.equal(s.doc.querySelectorAll('input').length,0);
  } finally {s.close();}
});

test('SOCIAL3 Connections application node mounts the same six rows and retains graph-held parameter writes', async()=>{
  const s=await mount({node:true,nodeParams:[{k:'relay_state',label:'Relay state',v:'open',editable:false},
    {k:'notifications',label:'Notifications',type:'boolean',v:false,editable:true}]});
  try {
    assert.equal(s.doc.querySelectorAll('[data-social-provider]').length,6);
    assert.match(s.doc.querySelector('[data-sysnode-param=relay_state]')?.textContent || '',/Relay state.*open/);
    await s.click(s.doc.querySelector('[data-sysnode-param=notifications] [role=switch]'));
    assert.deepEqual(s.calls.params,[['connections','notifications',true]]);
    await s.click(s.doc.querySelector('[data-social-provider="x"] button'));
    assert.deepEqual(s.calls.start,['x']);
    assert.match(s.doc.body.textContent,/Connected as @founder/);
  } finally {s.close();}
});

test('SOCIAL3 provider-discovered account choices and cancellation never ask for IDs',async()=>{
  const s=await mount({statuses:{facebook:{provider:'facebook',state:'choosing',accounts:[{id:'a',name:'Studio Page'},{id:'b',name:'Office Page'}]},x:{provider:'x',state:'connecting'}}});
  try {
    await s.click(s.doc.querySelector('[data-social-provider="facebook"] button'));
    await s.click([...s.doc.querySelectorAll('button')].find(b=>b.textContent==='Use Studio Page'));
    assert.deepEqual(s.calls.finish,[['facebook','a']]);
    await s.click(s.doc.querySelector('[data-social-provider="x"] button'));
    assert.match(s.doc.querySelector('[data-social-provider="x"]').textContent,/Connecting/);
    await s.click([...s.doc.querySelectorAll('[data-social-provider="x"] button')].find(b=>b.textContent==='Cancel'));
    assert.deepEqual(s.calls.cancel,['x']);
    assert.equal(s.doc.querySelectorAll('input').length,0);
  } finally {s.close();}
});

test('SOCIAL3 transport failure names the unavailable broker instead of claiming disconnected', async()=>{
  const s=await mount({start:async()=>{throw new Error('Cloud account sign-in required');}});
  try {await s.click(s.doc.querySelector('[data-social-provider="linkedin"] button'));assert.match(s.doc.body.textContent,/Cloud account sign-in required/);}
  finally{s.close();}
});

test('SOCIAL3 command palette exposes all six visible connect actions and Enter uses the same provider handler',async()=>{
  const s=await mount();
  try {
    await s.openPalette();
    const palette=s.doc.querySelector('[data-command-bar]');
    assert.equal(palette.querySelectorAll('button').length,6);
    for(const name of names) assert.ok(palette.textContent.includes('Connect · '+name));
    const input=palette.querySelector('input');
    s.w.ReactDOM.flushSync(()=>input.dispatchEvent(new s.w.KeyboardEvent('keydown',{key:'Enter',bubbles:true})));
    await s.settle();
    assert.deepEqual(s.calls.start,['instagram']);
    assert.match(s.doc.querySelector('[data-social-provider=instagram]').textContent,/Connected as @founder/);
    assert.equal(s.w.__paletteClosed,true);
  } finally {s.close();}
});

test('SOCIAL3 connected identity still shows exact pending review permission and preserves real names',async()=>{
  const s=await mount({rows:providers.map(provider=>({provider,state:provider==='instagram'||provider==='linkedin'?'connected':'not_connected',
    display_name:provider==='linkedin'?'Founder Name':'founder',publish_blocker:provider==='instagram'?'Meta app review: instagram_content_publish pending':'',review_state:provider==='instagram'?'unverified':'approved'}))});
  try {
    const instagram=s.doc.querySelector('[data-social-provider=instagram]');
    assert.match(instagram.textContent,/Connected as @founder/);
    assert.match(instagram.textContent,/Waiting for Instagram approval/);
    assert.match(instagram.textContent,/instagram_content_publish pending/);
    assert.match(s.doc.querySelector('[data-social-provider=linkedin]').textContent,/Connected as Founder Name/);
    assert.doesNotMatch(s.doc.querySelector('[data-social-provider=linkedin]').textContent,/@Founder Name/);
  } finally {s.close();}
});
