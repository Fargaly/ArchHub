// Full compiled Studio, real update transport, HTTP fixture, no app or screen.
const test = require('node:test');
const assert = require('node:assert/strict');
const {mountStudio, read} = require('./studio_home3_helpers.cjs');
const vm = require('node:vm');
const UPDATE = '/api/universal/application-update';
const LABEL = 'Update ready — Restart';
const ready = {ok:true,state:'ready',available_build:'fixture-new',current_build:'fixture-old',restart_supported:true};

async function fixture(options = {}) {
  const posts = [];
  const context = vm.createContext({setTimeout,clearTimeout,URLSearchParams,TextEncoder});
  vm.runInContext(read('01.APP/nodelang/studio/studio-existing-workshop.js'), context);
  const transport = context.ArchHubExistingWorkshop.create({get:async()=>ready,
    post:async (url, body) => {
      posts.push({url,body:JSON.parse(JSON.stringify(body))});
      if (options.refusal) throw new Error(options.refusal);
      return {...ready,state:'restarting'};
    }});
  await transport.refreshApplicationUpdate();
  const held = await mountStudio({snapshot:{applicationUpdate:options.idle ? {...ready,state:'idle',available_build:null}:ready},
    owner:{applicationUpdateAction:action=>transport.applicationUpdateAction(action)}});
  await held.settle();
  return {...held,posts};
}

test('compiled ready notice has exactly one live restart action and one click posts reload', async () => {
  const held = await fixture();
  try {
    const controls = [...held.doc.querySelectorAll('button')].filter(b=>b.textContent.trim() === LABEL);
    assert.equal(controls.length, 1);
    assert.match(controls[0].title, /Ctrl\+Shift\+U/);
    held.win.ReactDOM.flushSync(()=>controls[0].click());
    await held.settle();
    assert.deepEqual(held.posts,[{url:UPDATE,body:{action:'reload'}}]);
    assert.equal(held.doc.querySelector('[role="dialog"]'),null);
  } finally {held.close();}
});

test('compiled idle Studio offers no manual download or restart control', async () => {
  const held=await fixture({idle:true});
  try {
    assert.equal(held.button(LABEL),undefined);
    assert.doesNotMatch(held.doc.body.textContent,/Check and download|Update and reload/);
    assert.deepEqual(held.posts,[]);
  } finally {held.close();}
});

test('compiled restart refuses unsent text, preserves it, and works after it is saved', async () => {
  const held=await fixture();
  try {
    const draft=held.doc.createElement('textarea');
    draft.value='keep this unsent draft';draft.defaultValue=draft.value;held.doc.body.append(draft);
    held.win.ReactDOM.flushSync(()=>held.button(LABEL).click());
    await held.settle();
    assert.deepEqual(held.posts,[]);
    assert.equal(draft.value,'keep this unsent draft');
    assert.match(held.doc.body.textContent,/Save unsaved work before restarting\./);
    assert.equal(held.doc.querySelectorAll('[aria-label="Application update"] button').length,1);
    draft.value='';
    held.win.ReactDOM.flushSync(()=>held.button(LABEL).click());
    await held.settle();
    assert.deepEqual(held.posts,[{url:UPDATE,body:{action:'reload'}}]);
  } finally {held.close();}
});

test('compiled restart displays the real transport refusal for running Workshop work', async () => {
  const reason='A Workshop job is running; restart when it finishes.';
  const held=await fixture({refusal:reason});
  try {
    held.win.ReactDOM.flushSync(()=>held.button(LABEL).click());
    await held.settle();
    assert.deepEqual(held.posts,[{url:UPDATE,body:{action:'reload'}}]);
    assert.ok(held.doc.body.textContent.includes(reason));
  } finally {held.close();}
});

test('compiled keyboard restart uses the same single action', async () => {
  const held=await fixture();
  try {
    held.win.dispatchEvent(new held.win.KeyboardEvent('keydown',{ctrlKey:true,shiftKey:true,code:'KeyU',bubbles:true}));
    await held.settle();
    assert.deepEqual(held.posts,[{url:UPDATE,body:{action:'reload'}}]);
  } finally {held.close();}
});

test('compiled Ctrl+K command invokes the visible guarded restart', async () => {
  const held=await fixture();
  try {
    held.doc.body.dispatchEvent(new held.win.KeyboardEvent('keydown',{ctrlKey:true,key:'k',code:'KeyK',bubbles:true}));
    await held.settle();
    const palette=held.doc.querySelector('[data-command-bar]');
    assert.ok(palette,'Ctrl+K opens the command bar');
    const action=[...palette.querySelectorAll('button')].find(b=>b.textContent.includes(LABEL));
    assert.ok(action,'the visible update control is discoverable');
    held.win.ReactDOM.flushSync(()=>action.click());
    await held.settle();
    assert.deepEqual(held.posts,[{url:UPDATE,body:{action:'reload'}}]);
  } finally {held.close();}
});
