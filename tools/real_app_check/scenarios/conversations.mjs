// Saved conversations: create one from the Workshop's Conversations menu, reach it from its row
// (the catalog's scope walk), and reopen it from the same row after the Studio page is reloaded.
// Never presses Add/Remove/Republish (the harness refuses them).

export const steps = Object.freeze([
  'the real app opens to the Studio',
  'open the Workshop tab',
  'create a saved conversation from the Conversations menu',
  'its row is listed in the catalog',
  'select it from its row: the room opens',
  'reload the Studio page',
  'reopen it from its row after the reload',
]);

const TITLE = 'Real-app saved conversation';
const conversationsLabel = ctx => ctx.js(`(document.querySelector('button[aria-label="Conversations"]') || {}).title || ''`);
const menuOpen = ctx => ctx.js(`!!document.querySelector('[role=dialog][aria-label="Workshop conversations"]')`);
const rowOf = title => `[...document.querySelectorAll('[role=dialog][aria-label="Workshop conversations"] button')].find(b => b.querySelector('div') && b.querySelector('div').textContent.trim() === ${JSON.stringify(title)})`;

async function openMenu(ctx) {
  if (!(await menuOpen(ctx))) await ctx.clickText('Conversations');
  return ctx.until(() => menuOpen(ctx), Boolean, 20, 300);
}

async function openStudio(ctx) {
  const { js, sleep, until, clickText } = ctx;
  await until(() => js(`[...document.querySelectorAll('button')].some(b => ['Canvas', 'Open Studio'].includes(b.textContent.trim()))`), Boolean, 60, 1000);
  await sleep(3000);
  if (await clickText('Open Studio')) await sleep(4000);
  return js(`!document.querySelector('[data-studio-screen=onboarding]') && [...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Canvas')`);
}

// Exported for its court (tests_replica/test_real_app_check_tool.py); the run calls it twice.
export async function selectRow(ctx) {
  const { js, until, mouse, rectOf } = ctx;
  if (!(await openMenu(ctx))) return { pass: false, why: 'the Conversations menu did not open' };
  // Rows are disabled while the menu reads the catalog; click only an enabled row.
  const enabled = await until(() => js(`(() => { const b = ${rowOf(TITLE)}; return !!b && !b.disabled; })()`), Boolean, 40, 500);
  if (!enabled) return { pass: false, why: 'the row for ' + TITLE + ' never became enabled' };
  const row = await rectOf(rowOf(TITLE));
  if (!row) return { pass: false, why: 'no row for ' + TITLE };
  const note = await js(`(${rowOf(TITLE)}.querySelector('small') || {}).textContent || ''`);
  await mouse(row);
  const label = await until(() => conversationsLabel(ctx), value => value === TITLE, 60, 500);
  const error = await js(`([...document.querySelectorAll('[role=alert]')].map(e => e.textContent).join(' | '))`);
  return { pass: label === TITLE, why: label === TITLE ? '' : 'the Conversations button reads ' + JSON.stringify(label) + (error ? '; ' + error : ''),
    got: { row_note: note, label, scope_label: await js(`document.body.innerText.match(/Workshop Workbench|Workbench/) ? 'Workbench in view' : ''`) } };
}

export default async function (ctx) {
  const { step, js, sleep, until, clickText } = ctx;
  await step('the real app opens to the Studio', async () => {
    const ok = await openStudio(ctx);
    return { pass: ok, why: ok ? '' : 'Studio not reachable' };
  });
  await step('open the Workshop tab', async () => {
    const ok = await clickText('Workshop');
    await sleep(2500);
    const menu = await until(() => js(`!!document.querySelector('button[aria-label="Conversations"]')`), Boolean, 30, 500);
    return { pass: ok && menu, why: !ok ? 'no Workshop tab' : menu ? '' : 'no Conversations menu in the Workshop' };
  });
  await step('create a saved conversation from the Conversations menu', async () => {
    if (!(await openMenu(ctx))) return { pass: false, why: 'the Conversations menu did not open' };
    const offered = await until(() => clickText('＋ New conversation'), Boolean, 20, 500);
    if (!offered) return { pass: false, why: 'no New conversation button (catalog cannot create here)' };
    await until(() => js(`document.activeElement && document.activeElement.placeholder === 'Wall conversion workflow'`), Boolean, 10, 300);
    await ctx.cdp('Input.insertText', { text: TITLE });
    await until(() => js(`(document.querySelector('input[placeholder="Wall conversion workflow"]') || {}).value === ${JSON.stringify(TITLE)}`), Boolean, 10, 300);
    await clickText('Create conversation');
    const saved = await until(() => js(`[...document.querySelectorAll('[role=status]')].some(e => e.textContent.includes(${JSON.stringify('Saved: ' + TITLE)}))`), Boolean, 60, 500);
    const status = await js(`[...document.querySelectorAll('[role=status],[role=alert]')].map(e => e.textContent.trim()).join(' | ')`);
    return { pass: !!saved, why: saved ? '' : 'creation not confirmed: ' + status, got: { status } };
  });
  await step('its row is listed in the catalog', async () => {
    await clickText('Done');
    await clickText('Refresh conversations');
    const row = await until(() => js(`!!${rowOf(TITLE)}`), Boolean, 40, 500);
    const note = row ? await js(`(${rowOf(TITLE)}.querySelector('small') || {}).textContent || ''`) : '';
    return { pass: !!row, why: row ? '' : 'the catalog does not list ' + TITLE, got: { row_note: note } };
  });
  await step('select it from its row: the room opens', () => selectRow(ctx));
  await step('reload the Studio page', async () => {
    await ctx.cdp('Page.reload', { ignoreCache: false });
    await sleep(4000);
    const ok = await openStudio(ctx);
    if (ok) { await clickText('Workshop'); await sleep(2500); }
    const menu = ok && await until(() => js(`!!document.querySelector('button[aria-label="Conversations"]')`), Boolean, 30, 500);
    return { pass: !!menu, why: menu ? '' : 'the Studio did not come back with its Conversations menu' };
  });
  await step('reopen it from its row after the reload', () => selectRow(ctx));
}
