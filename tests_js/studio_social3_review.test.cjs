const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {transformSync} = require('esbuild');
const read = name => fs.readFileSync(name, 'utf8');
const compile = source => transformSync(source, {loader:'jsx'}).code;

test('SOCIAL3 mounted shared approval card sends exact approve and deny decisions', async () => {
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://localhost/',runScripts:'outside-only',pretendToBeVisual:true});
  const w = dom.window;
  w.fetch = () => {throw new Error('Live endpoints forbidden');};
  w.eval(read('nodelang/studio/vendor/react.js'));
  w.eval(read('nodelang/studio/vendor/react-dom.js'));
  w.eval(compile(read('nodelang/studio/tokens.jsx')));
  w.eval(compile(read('nodelang/studio/ds/index.jsx')));
  w.eval(compile(read('nodelang/studio/shared-data.jsx')));
  const source = read('nodelang/studio/studio-lm.jsx');
  const start = source.indexOf('const SettingsSocialApprovals =');
  const end = source.indexOf('const socialAccountView =', start);
  assert.ok(start >= 0 && end > start);
  w.eval(compile('const LM=window.AH;\n' + source.slice(start,end) + '\nwindow.SocialApprovalCourt=SettingsSocialApprovals;'));
  const drafts = [
    {delegation:'draft-to-approve',input_digest:'digest-exact-approve',operation:'x.post',account_id:'123',review_text:'First exact draft',account_binding:'provider-verified'},
    {delegation:'draft-to-deny',input_digest:'digest-exact-deny',operation:'whatsapp.message',account_id:'456',review_text:'Second exact draft',account_binding:'provider-verified'},
  ];
  const decisions = [];
  w.__transport = {
    listSocialApprovals:async () => drafts,
    decideSocialApproval:async body => {decisions.push(JSON.parse(JSON.stringify(body)));return {ok:true};},
  };
  const settle = async () => {for(let i=0;i<8;i++) await new Promise(resolve=>w.setTimeout(resolve,0));};
  w.eval('window.__root=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__root.render(React.createElement(window.SocialApprovalCourt,{transport:window.__transport})));');
  try {
    await settle();
    assert.equal(w.document.querySelectorAll('[data-approval-component]').length,2);
    assert.match(w.document.body.textContent,/First exact draft/);
    assert.match(w.document.body.textContent,/Second exact draft/);
    w.ReactDOM.flushSync(()=>w.document.querySelector('[data-workshop-primary="approve"]').click());
    await settle();
    assert.deepEqual(decisions,[{delegation:'draft-to-approve',input_digest:'digest-exact-approve',decision:'approve'}]);
    assert.equal(w.document.querySelectorAll('[data-approval-component]').length,1);
    assert.match(w.document.body.textContent,/Approved\. The agent can post it once\./);
    w.ReactDOM.flushSync(()=>w.document.querySelector('[data-workshop-primary="decline"]').click());
    await settle();
    assert.deepEqual(decisions[1],{delegation:'draft-to-deny',input_digest:'digest-exact-deny',decision:'deny'});
    assert.equal(w.document.querySelectorAll('[data-approval-component]').length,0);
    assert.match(w.document.body.textContent,/Denied\. It will not be posted\./);
  } finally {
    w.ReactDOM.flushSync(()=>w.__root.unmount());
    w.close();
  }
});
