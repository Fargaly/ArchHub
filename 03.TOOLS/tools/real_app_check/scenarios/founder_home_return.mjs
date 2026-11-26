import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {readFileSync} from 'node:fs';
import path from 'node:path';

const returns = ['Home rail', 'header breadcrumb', 'Escape'];
export const steps = [
  'Home displays the saved QA task in the work area',
  ...returns.map(via => 'Home restores the saved task and visible map via ' + via),
  'Home Inspector opens the selected task Canvas and returns to its map',
];

export function mapReadback(id) {
  const root = document.querySelector('[data-home-page]');
  const map = root?.querySelector('[data-home-map]');
  const bounds = map?.getBoundingClientRect();
  const viewport = map?.querySelector('.react-flow__viewport');
  const cards = [...(map?.querySelectorAll('[data-home-task]') || [])];
  const reachable = card => {
    const heading = card.querySelector('.home-card-head b') || card;
    const box = heading.getBoundingClientRect();
    const x = box.left + box.width / 2, y = box.top + box.height / 2;
    return !!bounds && box.width > 0 && box.height > 0 && x > Math.max(0, bounds.left)
      && x < Math.min(window.innerWidth, bounds.right) && y > Math.max(0, bounds.top)
      && y < Math.min(window.innerHeight, bounds.bottom) && card.contains(document.elementFromPoint(x, y));
  };
  return {home: !!root, map: !!bounds, area: bounds && [Math.round(bounds.width),Math.round(bounds.height)],
    transform:viewport?window.getComputedStyle(viewport).transform:null,
    loading:!!root&&/Loading sessions|جار.{0,8}تحميل/.test(root.innerText),
    allSelected:root?.querySelector('[data-home-kind="all"]')?.getAttribute('aria-pressed')==='true',
    ownerTasks:(window.ArchHubAPI?.getSnapshot()?.tasks||[]).length,
    taskInOwner: (window.ArchHubAPI?.getSnapshot()?.tasks || []).some(t => t.id === id),
    taskInDom: cards.some(c => c.getAttribute('data-home-task') === id),
    taskVisible: cards.some(c => c.getAttribute('data-home-task') === id && reachable(c)),
    visibleCards: cards.filter(reachable).length, mountedCards: cards.length};
}

export async function saveTaskFile(title) {
  const api = window.ArchHubAPI, made = await api.createTask(title);
  await api.openTaskGraph(made.taskId);
  const node = await api.addNode('n_number', {x:80, y:100});
  await api.saveSession();
  await api.listTasks();
  return {id:made.taskId, file:made.path, document:api.getSessionDocument().id, node:node.id};
}

export default async function run(ctx) {
  const {js,step,cdp,mouse,rectOf,until,shot} = ctx;
  const profile = await js('(()=>{const a=window.ArchHubAPI?.getSnapshot()?.desktopAccess;return {admitted:a?.admitted===true, email:a?.email, subject:a?.subject}})()');
  const wanted = ctx.input?.qaEmail;
  assert.ok(wanted && profile.admitted && [profile.email,profile.subject].includes(wanted),
    'A matching dedicated QA account must be admitted before creating a test task.');
  const read = (fn, value) => js('(' + fn.toString() + ')(' + JSON.stringify(value) + ')');
  const get = selector => 'document.querySelector(' + JSON.stringify(selector) + ')';
  const active = async selector => js('!!' + get(selector) + '?.getClientRects().length');
  const press = async (selector, twice = false) => {
    const expression = get(selector);
    const point = await until(async () => {
      const p = await rectOf(expression);
      if (!p?.w || !p.h) return null;
      return await js(expression + '?.contains(document.elementFromPoint(' + p.x + ',' + p.y + '))') ? p : null;
    }, Boolean, 15, 150);
    assert.ok(point, 'No reachable control for ' + selector);
    await mouse(point);
    if (twice) await mouse(point, 'left', 2);
  };
  const rail = 'nav button[aria-label="Home"]';
  const canvas = '[data-screen="canvas"],[data-screen="task-file"]';
  let task, card;
  const map = () => read(mapReadback,task.id);
  const goHome = async () => {
    if (!await active('[data-home-page]')) await press(rail);
    assert.ok(await until(() => active('[data-home-page]'), Boolean, 25, 180), 'Home route did not open');
  };
  const open = async inspector => {
    assert.ok(task, 'Missing saved QA fixture');
    await goHome();
    if (inspector) {
      await press(card);
      await press('[data-design="home1.open"]');
    } else {
      await press(card, true);
    }
    const actual = await until(() => js('({surface:' + get(canvas) + '?.getAttribute("data-screen"),'
      + 'id:ArchHubAPI.getSessionDocument()?.id, node:ArchHubAPI.getSessionDocument()?.nodes?.some(n=>n.id==='
      + JSON.stringify(task.node) + '), nodeVisible:!!document.querySelector(' + JSON.stringify('[data-graph-node="' + task.node + '"]') + ')?.getClientRects().length})'),
    r => r?.surface && r.id === task.document && r.node && r.nodeVisible, 25, 180);
    assert.ok(actual?.surface && actual.id === task.document && actual.node && actual.nodeVisible,
      'The selected task did not open its saved canvas: ' + JSON.stringify(actual));
    return actual;
  };
  await step(steps[0], async () => {
    await goHome();
    const title = 'QA Home return ' + randomUUID().slice(0,8);
    task = await read(saveTaskFile, title);
    const file = JSON.parse(readFileSync(task.file, 'utf8'));
    assert.ok(file.id === task.document && file.nodes.some(n => n.id === task.node), 'Saved task file readback differs');
    card = '[data-home-map] [data-home-task="' + task.id + '"] .home-card-head b';
    await goHome();
    for (const filter of ['[data-home-history][aria-pressed="true"]', '[data-home-filter][aria-pressed="true"]',
      '[data-home-kind="all"][aria-pressed="false"]']) if (await active(filter)) await press(filter);
    const before = await until(map, v => v.taskVisible, 28, 160);
    assert.ok(before.taskVisible, 'Seeded task is missing from the visible Home map: ' + JSON.stringify(before));
    return {pass:true,got:{...before, savedFile:path.basename(task.file), savedNode:true}};
  });
  for (const [index,via] of [...returns, 'Inspector and Home rail'].entries()) {
    await step(steps[index+1], async () => {
      const inspector = index === returns.length;
      const opened = await open(inspector);
      const canvasShot = path.basename(await shot('Canvas before returning by ' + via));
      if (via === 'Escape') {
        const pane = '[data-screen="canvas"] .react-flow__pane,[data-screen="task-file"] .react-flow__pane';
        if (await active(pane)) {
          const p = await read(selector => {
            const el = document.querySelector(selector), r = el.getBoundingClientRect();
            for (const fx of [0.2,0.5,0.8]) for (const fy of [0.25,0.5,0.75]) {
              const x = r.left+r.width*fx, y=r.top+r.height*fy;
              if (document.elementFromPoint(x,y) === el) return {x,y};
            }
            return null;
          },pane);
          if (p) await mouse(p);
        }
        for (const type of ['rawKeyDown','keyUp']) await cdp('Input.dispatchKeyEvent',{type,key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
      } else await press(via === 'header breadcrumb' ? 'button.header-page' : rail);
      const after = await until(map,v => v.home && v.taskVisible,25,180);
      const why = !after.home ? 'Navigation did not return to Home' : !after.taskVisible ? 'Home opened with its saved card missing from view' : undefined;
      return {pass:!why, why, got:{via,opened,canvasShot,after}};
    });
  }
}
