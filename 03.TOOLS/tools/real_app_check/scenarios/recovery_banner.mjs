// No false "Unsaved changes from a closed ArchHub window" banner; a real closed-window edit is kept as a copy and holds no update.
// The Qt profile is off-the-record, so a recovery draft only outlives a PAGE (reload) inside one app run: that is what is driven.
import fs from 'node:fs';
import path from 'node:path';

export const steps = Object.freeze([
  'open a saved session canvas',
  'move the view only, then the updater asks the page: nothing unsaved',
  'reload the page: no recovery banner, no draft',
  'a real edit the file never got (changed elsewhere), then the page is replaced',
  'after the reload the edit is a copy on disk, no banner, and no update hold',
  'Home opens at a readable zoom',
]);

const banner = `[...document.querySelectorAll('[role="alert"]')].some(n => /closed ArchHub window/.test(n.textContent))`;
const drafts = `Object.keys(localStorage).filter(k => k.startsWith('archhub.draft.')).length`;
const ready = ctx => ctx.until(() => ctx.js(`!!(window.ArchHubAPI && window.ArchHubAPI.getSnapshot && window.ArchHubAPI.getSnapshot().desktopAccess?.admitted && window.ArchHubAPI.getSessionDocument())`).catch(() => false), Boolean, 120, 250);
// The updater's own question (nograph_launcher consider_update), plus the server's answer to that report: unsaved = any view held.
const held = ctx => ctx.js(`(async () => { const real = window.fetch; let server = null;
  window.fetch = async (...args) => { const r = await real(...args); try { const b = JSON.parse(args[1]?.body || '{}'); if (b.action === 'edit_state') server = await r.clone().json(); } catch (e) {} return r; };
  try { const page = window.__archhubEditState(); for (let i = 0; i < 40 && server === null; i++) await new Promise(f => setTimeout(f, 100)); return JSON.stringify({page, server}); }
  finally { window.fetch = real; } })()`).then(JSON.parse);

export default async function (ctx) {
  const { step, js, until, cdp, clickText } = ctx;
  let file = '';
  await step('open a saved session canvas', async () => {
    await ready(ctx);
    const made = await js(`(async () => { const t = await window.ArchHubAPI.createTask('Recovery probe'); await window.ArchHubAPI.listTasks();
      const row = window.ArchHubAPI.getSnapshot().tasks.find(x => x.id === t.taskId); const p = t.path || row?.sessionPath;
      await window.ArchHubAPI.openSession(p); return JSON.stringify({id: t.taskId, path: window.ArchHubAPI.getSnapshot().sessionFile}); })()`).then(JSON.parse);
    file = made.path;
    return { pass: !!file && fs.existsSync(file), why: file ? '' : 'no session file opened', got: made };
  });
  await step('move the view only, then the updater asks the page: nothing unsaved', async () => {
    await js(`window.ArchHubAPI.setSessionViewport({x: 37, y: 41, zoom: .61})`);
    const answer = await until(() => held(ctx), a => a.page?.unsaved === false && a.server?.unsaved === false, 40, 250);
    const ok = answer?.page?.unsaved === false && answer?.server?.unsaved === false;
    return { pass: ok, why: ok ? '' : 'updater would wait: ' + JSON.stringify(answer), got: answer };
  });
  await step('reload the page: no recovery banner, no draft', async () => {
    await js(`window.ArchHubAPI.setSessionViewport({x: 90, y: 12, zoom: .7})`);  // dirty again at the moment the page goes
    await cdp('Page.reload', { ignoreCache: false });
    await ready(ctx);
    await until(() => js(`${drafts} + (window.ArchHubAPI.getSnapshot().orphanDrafts?.length || 0) + (${banner} ? 1 : 0)`), n => n === 0);
    const got = { banner: await js(banner), drafts: await js(drafts), orphans: await js(`window.ArchHubAPI.getSnapshot().orphanDrafts?.length || 0`) };
    const ok = !got.banner && got.drafts === 0 && got.orphans === 0;
    return { pass: ok, why: ok ? '' : 'after reload ' + JSON.stringify(got), got };
  });
  let copiesBefore = [];
  await step('a real edit the file never got (changed elsewhere), then the page is replaced', async () => {
    await js(`window.ArchHubAPI.openSession(${JSON.stringify(file)})`); await ready(ctx);
    copiesBefore = fs.readdirSync(path.dirname(file)).filter(n => n.includes('(my changes'));
    // Another writer moves the file on first (as two agents did on the founder's file), so this page's save is refused.
    const doc = JSON.parse(fs.readFileSync(file, 'utf8'));
    doc.properties = {...doc.properties, revision: (doc.properties?.revision || 0) + 5};
    fs.writeFileSync(file, JSON.stringify(doc));
    await js(`window.ArchHubAPI.addNote('REAL EDIT NOT IN THE FILE', {x: 120, y: 140}).catch(e => e.message)`);
    const stored = await until(() => js(drafts), n => n > 0, 40, 100);
    await cdp('Page.reload', { ignoreCache: false });
    return { pass: stored > 0, why: stored > 0 ? '' : 'the edit left no draft before the reload', got: { stored } };
  });
  await step('after the reload the edit is a copy on disk, no banner, and no update hold', async () => {
    await ready(ctx);
    const dir = path.dirname(file);
    const copy = await until(() => fs.readdirSync(dir).filter(n => n.includes('(my changes') && !copiesBefore.includes(n))[0], Boolean, 80, 250);
    const kept = copy && fs.readFileSync(path.join(dir, copy), 'utf8').includes('REAL EDIT NOT IN THE FILE');
    const got = { copy, kept, banner: await js(banner), drafts: await js(drafts), hold: await held(ctx) };
    const ok = kept && !got.banner && got.drafts === 0 && got.hold?.server?.unsaved === false;
    return { pass: ok, why: ok ? '' : 'after reload ' + JSON.stringify(got), got };
  });
  await step('Home opens at a readable zoom', async () => {
    const went = await clickText('Home');
    await until(() => js(`document.querySelectorAll('[data-design="home.card"]').length`), n => n > 0);
    const got = await js(`(() => { const v = document.querySelector('.home-map-canvas .react-flow__viewport'); const m = v && /scale\\(([\\d.]+)\\)/.exec(v.style.transform);
      const c = document.querySelector('[data-design="home.card"]')?.getBoundingClientRect();
      return JSON.stringify({zoom: m ? Number(m[1]) : null, cardWidth: c ? Math.round(c.width) : null, cards: document.querySelectorAll('[data-design="home.card"]').length}); })()`).then(JSON.parse);
    got.went = went;
    const ok = got.cards > 0 && got.zoom !== null && got.zoom >= .62;
    return { pass: ok, why: ok ? '' : 'Home map ' + JSON.stringify(got), got };
  });
}
