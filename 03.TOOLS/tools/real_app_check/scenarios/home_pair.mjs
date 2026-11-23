import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {performance} from 'node:perf_hooks';
import {fileURLToPath} from 'node:url';

export const homeSteps = [
  'Home route and file readback from the base directory in an isolated profile',
  'Signed-in Home lists its task with a numeric, missing and restored lease',
  'Signed-in History expands Older and reopens the edited registration by path',
];

export async function homePair(ctx, {check, press, visible}) {
  const {installedRoot, build} = ctx.input;
  const fixture = mode => execFileSync(
    path.join(installedRoot, '.venv', 'Scripts', 'python.exe'),
    ['-I', '-B', fileURLToPath(new URL('../installed_home_pair.py', import.meta.url)),
      installedRoot, ctx.out, mode, build],
    {encoding: 'utf8'},
  );

  let files;
  await ctx.step(homeSteps[0], async () => {
    files = JSON.parse(fixture('seed'));
    fixture('missing');
    fixture('restored');
    if (ctx.label !== 'INSTALLED BUILD') {
      return {not_exercised: 'Overlay window: fixture checks used the base directory. Native installed acceptance was not exercised.',
        got: {window: ctx.label, backendSource: 'base directory only'}};
    }
    return {pass: true, got: {leases: ['numeric', 'missing', 'restored'], editedTolerance: 2.5}};
  });

  await check(homeSteps[1], async () => {
    assert.ok(files, 'Home fixtures were not seeded');
    for (const phase of ['numeric', 'missing', 'restored']) {
      if (phase !== 'numeric') fixture(phase);
      const found = await ctx.js(`(async () => {
        const rows = await ArchHubAPI.listTasks(false);
        return Array.isArray(rows) && rows.some(row => row.id === 'qa-home-lease');
      })()`);
      assert.ok(found, 'Missing Home task in ' + phase);
    }
    return {leases: ['numeric', 'missing', 'restored']};
  });

  await check(homeSteps[2], () => verifyHistory(ctx, {press, visible}, files));
}

// XYFlow fits the map after expansion. A visible heading can still move underneath another node.
async function clickMovingTarget(ctx, selector, doubleClick = false) {
  const sample = () => ctx.js(`(() => {
    const target = document.querySelector(${JSON.stringify(selector)});
    if (!target) return {blocker: 'missing heading'};
    const rect = target.getBoundingClientRect();
    const x = rect.left + rect.width / 2, y = rect.top + Math.min(rect.height / 2, 14);
    const hit = document.elementFromPoint(x, y);
    return {x, y, reachable: !!(rect.width && rect.height && target.contains(hit)),
      blocker: !hit ? 'outside viewport' : target.contains(hit) ? null : (hit.getAttribute('data-design') || [hit.tagName, ...hit.classList].join('.')).slice(0, 120)};
  })()`);
  let first, firstBlocked, anchor, last;
  let stableSince = 0;
  const ready = await ctx.until(async () => {
    last = await sample();
    first ??= last;
    if (!last.reachable) {
      firstBlocked ??= last;
      anchor = undefined;
    } else if (!anchor || Math.hypot(last.x - anchor.x, last.y - anchor.y) > 0.5) {
      anchor = last;
      stableSince = performance.now();
    } else if (performance.now() - stableSince >= 180) {
      return true;
    }
    return false;
  }, Boolean);
  assert.ok(ready, 'No stable, reachable History control: ' + JSON.stringify({first, firstBlocked, last}));
  await ctx.mouse(last);
  if (!doubleClick) return {first, firstBlocked: firstBlocked ?? null, clicked: last};
  const second = await sample();
  assert.ok(second.reachable && Math.hypot(second.x - last.x, second.y - last.y) <= 1,
    'Heading moved between clicks: ' + JSON.stringify({last, second}));
  await ctx.mouse(second, 'left', 2);
  return {first, firstBlocked: firstBlocked ?? null, clicked: second};
}

export async function verifyHistory(ctx, {press, visible}, files) {
  assert.ok(files, 'Home fixtures were not seeded');
  const before = [files.edited, files.untouched].map(filename => readFileSync(filename));
  if (!await visible('[data-home-page]')) assert.ok(await ctx.clickText('Home'));
  const history = '[data-home-history]';
  if (await visible(history + '[aria-pressed="true"]')) await press(history);
  await press(history + '[aria-pressed="false"]');
  const older = '[data-home-map] [data-design="group.node"] button[aria-label="Expand Older / archived"]';
  const card = filename => '[data-home-map] [data-home-session-path=' + JSON.stringify(filename) + ']';
  assert.ok(await ctx.until(() => visible(older), Boolean), 'History did not start with Older collapsed');
  assert.equal(await visible(card(files.edited)), false);
  const expandPointer = await clickMovingTarget(ctx, older);
  assert.ok(await ctx.until(() => visible(card(files.edited)), Boolean), 'Edited original missing after expand');
  assert.equal(await ctx.js('document.querySelectorAll(' + JSON.stringify(card(files.untouched)) + ').length'), 0);
  assert.notEqual(await ctx.js('ArchHubAPI.getSessionPath()'), files.edited);
  const pointer = await clickMovingTarget(ctx, card(files.edited) + ' .home-card-head b', true);
  const reopened = await ctx.until(() => ctx.js(`ArchHubAPI.getSessionPath() === ${JSON.stringify(files.edited)}
    && !!document.querySelector('[data-screen="canvas"]')`), Boolean);
  assert.ok(reopened, 'Edited original did not reopen');
  const tolerance = await ctx.js("ArchHubAPI.getSessionDocument().nodes.find(n => n.id === 'start')?.params.design_tolerance");
  assert.equal(tolerance, 2.5);
  const originalId = JSON.parse(before[0]).id;
  assert.ok(originalId);
  assert.equal(await ctx.js('ArchHubAPI.getSessionDocument().id'), originalId);
  // Observe both originals throughout the autosave debounce, including the final read.
  const openedAt = performance.now();
  const persisted = await ctx.until(() => {
    assert.deepEqual([files.edited, files.untouched].map(filename => readFileSync(filename)), before);
    return performance.now() - openedAt >= 1500;
  }, Boolean);
  assert.ok(persisted, 'File preservation was not observed through the autosave interval');
  return {expandedOlder: true, reopenedOriginal: true, untouchedHidden: true, expandPointer, pointer, tolerance};
}
