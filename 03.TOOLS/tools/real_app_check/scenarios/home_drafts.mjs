// Two real sessions on the Home map: a different draft in each, switching back and forth keeps each session's own draft.
// The Home composer keys its draft by the picked session (ui.jsx Composer draftKey); before that, every pick shared one box.
export const steps = Object.freeze([
  'the real app opens to the Studio with two sessions on the Home map',
  'pick session A on the map and type its draft',
  'pick session B: its box is empty; type its own draft',
  'back to A: A keeps its draft',
  'back to B: B keeps its draft',
  'A, then New session on the scope chip: a new-session draft that never leaks into A',
  'first drafts in C and D at the same revision: exactly one send in each thread',
]);

const card = title => `[...document.querySelectorAll('[data-design="home.card"]')].find(n => (n.querySelector('.home-card-head b') || {}).textContent === ${JSON.stringify(title)})`;
const box = `document.querySelector('.global-composer textarea[aria-label="Message"]')`;
const value = ctx => ctx.js(`(${box} || {}).value`);
// A real pointer click on the drawn map card (xyflow onNodeClick picks it), then wait until the box shows what is expected.
const pick = async (ctx, title, expected) => {
  const point = await ctx.rectOf(card(title));
  if (!point) return {clicked: false, value: await value(ctx)};
  await ctx.mouse(point);
  return {clicked: true, value: await ctx.until(() => value(ctx), shown => shown === expected)};
};
const type = async (ctx, text) => {
  await ctx.js(`(() => { const f = ${box}; if (!f) return false; f.focus();
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(f, ${JSON.stringify(text)});
    f.dispatchEvent(new Event('input', {bubbles: true})); return true; })()`);
  return ctx.until(() => value(ctx), shown => shown === text);
};

export default async function (ctx) {
  const { step, js, until, clickText } = ctx;
  await step('the real app opens to the Studio with two sessions on the Home map', async () => {
    await until(() => js(`!!(window.ArchHubAPI && window.ArchHubAPI.getSnapshot)`), Boolean);
    await clickText('Open Studio');
    const made = await js(`(async () => { const a = await window.ArchHubAPI.createTask('Draft probe A'); const b = await window.ArchHubAPI.createTask('Draft probe B');
      await window.ArchHubAPI.listTasks(); return JSON.stringify([a && a.taskId, b && b.taskId]); })()`).then(JSON.parse);
    const every = await js(`(() => { const b = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Show every session'); if (b) b.click(); return !!b; })()`);
    const shown = await until(() => js(`[${card('Draft probe A')}, ${card('Draft probe B')}].filter(Boolean).length`), n => n === 2);
    return { pass: shown === 2, why: shown === 2 ? '' : 'cards on the map: ' + shown, got: { made, every } };
  });
  await step('pick session A on the map and type its draft', async () => {
    const picked = await pick(ctx, 'Draft probe A', '');
    const typed = await type(ctx, 'Draft for A');
    const ok = picked.clicked && typed === 'Draft for A';
    return { pass: ok, why: ok ? '' : picked.clicked ? 'box shows ' + JSON.stringify(typed) : 'card A is not on the map', got: { picked, typed } };
  });
  await step('pick session B: its box is empty; type its own draft', async () => {
    const picked = await pick(ctx, 'Draft probe B', '');
    const typed = await type(ctx, 'Draft for B');
    const ok = picked.clicked && picked.value === '' && typed === 'Draft for B';
    return { pass: ok, why: ok ? '' : 'B showed ' + JSON.stringify(picked.value) + ' on pick', got: { picked, typed } };
  });
  await step('back to A: A keeps its draft', async () => {
    const picked = await pick(ctx, 'Draft probe A', 'Draft for A');
    const ok = picked.value === 'Draft for A';
    return { pass: ok, why: ok ? '' : 'A shows ' + JSON.stringify(picked.value), got: picked };
  });
  await step('back to B: B keeps its draft', async () => {
    const picked = await pick(ctx, 'Draft probe B', 'Draft for B');
    const ok = picked.value === 'Draft for B';
    return { pass: ok, why: ok ? '' : 'B shows ' + JSON.stringify(picked.value), got: picked };
  });
  // The scope chip on the Home composer toggles between the picked session and a New session (its aria-label names both).
  const chip = `document.querySelector('[data-design="composer.to"]')`;
  const pressChip = async () => {
    const point = await ctx.rectOf(chip);
    if (!point) return false;
    await ctx.mouse(point);
    return true;
  };
  await step('A, then New session on the scope chip: a new-session draft that never leaks into A', async () => {
    const picked = await pick(ctx, 'Draft probe A', 'Draft for A');
    const toNew = await pressChip();
    const fresh = await until(() => value(ctx), shown => shown !== 'Draft for A');
    const typed = await type(ctx, 'Draft for a new session');
    const back = await pressChip();
    const a = await until(() => value(ctx), shown => shown === 'Draft for A');
    const ok = picked.value === 'Draft for A' && toNew && fresh !== 'Draft for A' && typed === 'Draft for a new session' && back && a === 'Draft for A';
    return { pass: ok, why: ok ? '' : 'new-session box ' + JSON.stringify(fresh) + ', A after return ' + JSON.stringify(a),
      got: { picked, toNew, fresh, typed, back, a } };
  });
  await step('first drafts in C and D at the same revision: exactly one send in each thread', async () => {
    const ids = await js(`(async () => { const c = await window.ArchHubAPI.createTask('Draft probe C'); const d = await window.ArchHubAPI.createTask('Draft probe D');
      await window.ArchHubAPI.listTasks(); return JSON.stringify([c.taskId, d.taskId]); })()`).then(JSON.parse);
    await until(() => js(`[${card('Draft probe C')}, ${card('Draft probe D')}].filter(Boolean).length`), n => n === 2);
    // Every chat request the page posts, by thread: the router chat carries the session as task.
    await js(`(() => { if (window.__sends) return; window.__sends = []; const real = window.fetch;
      window.fetch = (url, options = {}) => { if (String(url).includes('/api/router/chat')) { try { window.__sends.push(JSON.parse(options.body).task || ''); } catch (e) { window.__sends.push('?'); } }
        return real(url, options); }; })()`);
    const submit = `(() => { const f = ${box}; const form = f && f.closest('form'); if (!form) return false; form.requestSubmit(); return true; })()`;
    const c = await pick(ctx, 'Draft probe C', '');
    await type(ctx, 'First message to C');
    const sentC = await js(submit);
    const d = await pick(ctx, 'Draft probe D', '');
    await type(ctx, 'First message to D');
    const sentD = await js(submit);
    const sends = await until(() => js(`JSON.stringify(window.__sends)`).then(JSON.parse), rows => rows.length >= 2);
    const count = id => sends.filter(task => task === id).length;
    const ok = c.clicked && d.clicked && sentC && sentD && count(ids[0]) === 1 && count(ids[1]) === 1 && sends.length === 2;
    // This private profile has no model, so the router answers each admitted chat 400; what is counted is the page's sends.
    return { pass: ok, why: ok ? '' : 'sends by thread ' + JSON.stringify(sends) + ' for ' + JSON.stringify(ids), got: { ids, sends }, expected_http: ['400 /api/router/chat'] };
  });
}
