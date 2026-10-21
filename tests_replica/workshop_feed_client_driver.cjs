// Drives the REAL studio-existing-workshop.js against a REAL application server over HTTP:
// reads the Workshop's messages feed, then every older page, exactly as the founder's page does,
// and prints what the client admitted. argv: <server url> <cookie> <csrf> <graph id> <root> <scope> <revision>
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const [base, cookie, csrf, graph, root, scope, revision] = process.argv.slice(2);
const headers = {'Cookie': 'ArchHub-Session=' + cookie, 'X-ArchHub-CSRF': csrf, 'Origin': base, 'Content-Type': 'application/json'};
const sandbox = {TextEncoder, URLSearchParams, crypto:webcrypto};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'nodelang', 'studio', 'studio-existing-workshop.js'), 'utf8'), sandbox);
const pages = [];
const api = sandbox.ArchHubExistingWorkshop.create({
  pendingStorage:{getItem:() => null, setItem:() => {}},
  get:async url => { const answer = await (await fetch(base + url, {headers})).json();
    if (url.startsWith('/api/universal/workshop?')) pages.push({url, rows:Array.isArray(answer.messages) ? answer.messages.length : null,
      has_older:answer.has_older, next_before:answer.next_before ?? null, error:answer.error || null});
    return answer; },
  post:async (url, body) => (await fetch(base + url, {method:'POST', headers, body:JSON.stringify(body)})).json(),
});
(async () => {
  api.setCanvas({graph_id:graph, root:scope, revision:Number(revision), workshops:[{root, label:'Workshop'}]});
  const seen = [], admitted = [];
  let error = null;
  try {
    await api.showWorkshopFeed(root, 'messages');
    for (let i = 0; i < 20; i++) {
      const held = api.getSnapshot().workshop;
      if (!held || held.error) { error = held ? held.error : 'no page'; break; }
      admitted.push(held.messages.length);
      for (const row of held.messages) seen.push({root:row.root, relayed_from:row.relayed_from || null, reply_to:row.reply_to_root || null});
      if (!held.has_older) break;
      await api.loadOlderWorkshop(root);
    }
  } catch (failure) { error = String(failure && failure.message || failure); }
  process.stdout.write(JSON.stringify({error, admitted, seen, pages}) + '\n');
})();
