// Smoke: the installed app opens, its tabs answer, a library node is placed and undone, and
// Settings > Workspaces > Browse fills the folder field from the real Windows folder dialog.
// Never presses Add/Remove/Republish (the harness refuses them): those sign with the protected key.
import fs from 'node:fs';
import path from 'node:path';

export const steps = Object.freeze([
  'the real app opens to the Studio',
  'open the Chat tab', 'open the Workshop tab', 'open the System tab', 'open the Canvas tab',
  'place a library node (double-click list_walls)',
  'undo the placement (Undo button)',
  'open Settings > Workspaces',
  'Browse: the real Windows folder dialog puts the chosen folder in the field',
  'Add the browsed folder as a workspace',
]);

const nodes = ctx => ctx.js(`document.querySelectorAll('.lm-node[data-node-id]').length`);

export default async function (ctx) {
  const { step, js, sleep, until, clickText } = ctx;
  await step('the real app opens to the Studio', async () => {
    await until(() => js(`[...document.querySelectorAll('button')].some(b => ['Canvas', 'Open Studio'].includes(b.textContent.trim()))`), Boolean, 60, 1000);
    await sleep(3000);
    if (await clickText('Open Studio')) await sleep(4000);
    const ok = await js(`!document.querySelector('[data-studio-screen=onboarding]') && [...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Canvas')`);
    return { pass: ok, why: ok ? '' : 'Studio not reachable', got: { path: await js('location.pathname') } };
  });
  for (const tab of ['Chat', 'Workshop', 'System', 'Canvas']) {
    await step('open the ' + tab + ' tab', async () => {
      const ok = await clickText(tab);
      await sleep(2500);
      return { pass: ok, why: ok ? '' : 'no ' + tab + ' tab' };
    });
  }
  await step('place a library node (double-click list_walls)', async () => {
    const before = await nodes(ctx);
    const point = await ctx.rectOf(`[...document.querySelectorAll('*')].find(x => x.children.length === 0 && x.textContent.trim() === 'list_walls')`);
    if (!point) return { pass: false, why: 'list_walls is not in the library' };
    await ctx.mouse(point, 'left', 2);
    const after = await until(() => nodes(ctx), value => value === before + 1);
    return { pass: after === before + 1, why: after === before + 1 ? '' : 'cards ' + before + ' -> ' + after, got: { before, after } };
  });
  await step('undo the placement (Undo button)', async () => {
    const before = await nodes(ctx);
    const ok = await clickText('Undo');
    const after = await until(() => nodes(ctx), value => value === before - 1);
    return { pass: after === before - 1, why: after === before - 1 ? '' : (ok ? '' : 'no Undo button; ') + 'cards ' + before + ' -> ' + after, got: { before, after } };
  });
  await step('open Settings > Workspaces', async () => {
    let ok = await clickText('Settings', 'button,[role=button],a,[title]');
    await sleep(1500);
    ok = ok && await js(`(() => { const b = [...document.querySelectorAll('button')].find(b => /^\\s*Workspaces/.test(b.textContent)); if (!b) return false; b.click(); return true; })()`);
    await sleep(2500);
    const browse = await js(`!!document.querySelector('button[aria-label="Browse for a folder"]')`);
    const registry = await until(() => js(`(document.body.innerText.match(/The workspace registry[^\\n]*|Reading the workspace registry[^\\n]*|No workspace is registered yet\\./) || [''])[0]`),
      text => text && !/^Reading/.test(text), 20);
    if (!(ok && browse)) return { pass: false, why: browse ? 'Settings > Workspaces did not open' : 'no Browse button', got: { registry } };
    // The registry lives with ArchHub's graph owner. The run starts its own, freshly provisioned, so the
    // only pass is the read-success empty state; an alert, a hang or any registered row (not ours) fails.
    const read = registry === 'No workspace is registered yet.';
    return { pass: read, why: read ? '' : 'the registry was not read empty from the run\'s own graph owner: ' + (registry || 'no registry line'), got: { registry } };
  });
  await step('Browse: the real Windows folder dialog puts the chosen folder in the field', async () => {
    const folder = fs.mkdtempSync(path.join(ctx.out, 'picked-folder-'));
    const point = await ctx.rectOf(`document.querySelector('button[aria-label="Browse for a folder"]')`);
    await ctx.mouse(point);
    const answer = await ctx.native({ kind: 'pick-folder', title: 'Choose a folder for ArchHub to govern', folder });
    const value = await until(() => js(`(document.querySelector('input[placeholder^="Folder"]') || {}).value || ''`), Boolean);
    const same = value.replace(/[\\/]+$/, '').toLowerCase() === folder.replace(/[\\/]+$/, '').toLowerCase();
    return { pass: same, why: same ? '' : (value ? 'field shows ' + value : 'field stayed empty') + (answer.error ? '; ' + answer.error : ''),
      got: { chosen: folder, field: value, dialog: answer } };
  });
  await step('Add the browsed folder as a workspace', async () => ({
    // Add signs with the Windows user's protected key (ArchHub-workspace-roots-v1), which no
    // environment variable isolates: pressing it here would create or use the founder's real key.
    not_exercised: 'Add signs with the Windows user\'s protected Workspaces key; this run has no isolated key, so Add is not pressed',
  }));
}
