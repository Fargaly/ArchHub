/* Court (retention, SPEC 3.6): only a person's navigation is an "open". The
   Studio refreshes an open Workshop every 2.5 s and, after a failed read, the
   next refresh goes out without cursors; neither may be counted as activity.
   Production callbacks in memory only: no browser, network or database. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-existing-workshop.js'), 'utf8');
const context = vm.createContext({URLSearchParams, TextEncoder});
vm.runInContext(source, context);
const create = context.ArchHubExistingWorkshop.create;
const storage = () => { const data = new Map(); return {getItem:key => data.get(key) || null,
  setItem:(key, value) => data.set(key, value), removeItem:key => data.delete(key)}; };
const transcript = () => ({graph_id:'graph-a', root:'workshop-a', scope_root:'scope-a', revision:4,
  owner:'owner-a', view:'view-a', self:'owner-a', can_send:true, can_join:false, messages:[],
  participants:[{root:'owner-a', label:'Owner', attached:true}]});

function setup(answers) {
  const gets = [];
  const api = create({pendingStorage:storage(), uuid:() => 'u', hash:async value => value,
    get:async url => { gets.push(url); const next = answers.shift(); if (next instanceof Error) throw next;
      return next || transcript(); },
    post:async () => ({ok:true})});
  api.setCanvas({graph_id:'graph-a', root:'scope-a', revision:4,
    workshops:[{root:'workshop-a', label:'Workshop', send_category:'declared-message'}]});
  return {api, gets};
}
const opens = gets => gets.filter(url => new URLSearchParams(url.split('?')[1]).get('open') === '1').length;

test('navigation is an explicit open (open=1); a refresh poll never is', async () => {
  const fixture = setup([]);
  assert.equal(typeof fixture.api.openWorkshop, 'function', 'the Studio can say "a person opened this"');
  await fixture.api.openWorkshop('workshop-a');
  await fixture.api.refreshWorkshop('workshop-a');
  await fixture.api.refreshWorkshop('workshop-a');
  assert.equal(opens(fixture.gets), 1);
  assert.equal(new URLSearchParams(fixture.gets[0].split('?')[1]).get('open'), '1');
});

test('a refresh after a failed read goes out without cursors but is still not an open', async () => {
  const fixture = setup([new Error('timeout'), {ok:false, error:'Workshop changed; full refresh needed'}]);
  await fixture.api.refreshWorkshop('workshop-a').catch(() => {});
  await fixture.api.refreshWorkshop('workshop-a').catch(() => {});
  await fixture.api.refreshWorkshop('workshop-a');
  const cursorless = fixture.gets.filter(url => !/[?&](after|content_after)=/.test(url));
  assert.ok(cursorless.length >= 2, 'the reads after an error carry no cursor');
  assert.equal(opens(fixture.gets), 0);
});