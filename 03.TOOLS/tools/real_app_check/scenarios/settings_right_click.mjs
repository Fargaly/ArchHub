import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import settings, {steps as settingsSteps} from './settings.mjs';

const home = 'Right-click a disposable Home session card';
const canvas = 'Right-click a disposable Canvas node';
export const steps = [...settingsSteps, home, canvas];

export default async function run(ctx) {
  await settings(ctx);
  await rightClicks(ctx);
}

export async function rightClicks({step, js, until, rectOf, mouse, cdp, clickText, shot}) {
  const title = 'Right-click check ' + randomUUID();
  const visible = selector => js(`Boolean(document.querySelector(${JSON.stringify(selector)})?.getClientRects().length)`);
  const check = (name, action) => step(name, async () => {
    const state = await until(() => js('window.ArchHubAPI?.getSnapshot()?.desktopAccess?.state'), s => s && s !== 'pending');
    const admitted = await js('window.ArchHubAPI?.getSnapshot()?.desktopAccess?.admitted === true');
    if (!admitted) {
      assert.ok(['signed_out','session_invalid','unavailable'].includes(state), 'Missing admission verdict');
      assert.ok(await visible('[data-desktop-admission]'), 'Missing visible sign-in gate');
      return {not_exercised:'Installed sign-in gate is visible', got:{state, gateVisible:true}};
    }
    return {pass:true, got:await action()};
  });
  const press = async (selector, button = 'left') => {
    const expression = `document.querySelector(${JSON.stringify(selector)})`;
    assert.ok(await until(() => visible(selector), Boolean), 'Missing target: ' + selector);
    await js(`${expression}.scrollIntoView({block:'nearest', inline:'nearest'}); true`);
    const point = await rectOf(expression);
    assert.ok(point?.w && point.h && await js(`${expression}.contains(document.elementFromPoint(${point.x},${point.y}))`), 'Target is obscured: ' + selector);
    await mouse(point, button);
  };
  const escape = async selector => {
    for (const type of ['keyDown','keyUp']) await cdp('Input.dispatchKeyEvent', {type,key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
    assert.equal(await until(() => visible(selector), v => !v), false, 'Escape did not dismiss ' + selector);
  };
  const inspectMenu = async (target, label, expected, forbidden) => {
    const menu = `[role="menu"][aria-label="${label}"]`;
    await press(target, 'right');
    assert.ok(await until(() => visible(menu), Boolean), label + ' missing after right click');
    const actions = await js(`Array.from(document.querySelectorAll(${JSON.stringify(menu+' button:not(:disabled) > span')})).filter(e=>e.getClientRects().length).map(e=>e.textContent.trim())`);
    for (const action of expected) assert.ok(actions.includes(action), 'Missing ' + action);
    for (const action of forbidden) assert.ok(!actions.includes(action), 'Unexpected ' + action);
    await shot(label);
    await escape(menu);
    return {menu, actions};
  };

  await check(home, async () => {
    if (!await visible('[data-home-page] [data-home-ready]')) assert.ok(await clickText('Home'), 'Home navigation missing');
    assert.ok(await until(() => visible('[data-home-page] [data-home-ready]'), Boolean));
    const id = await js(`(async()=>{const api=window.ArchHubAPI;const task=await api.createTask(${JSON.stringify(title)});await api.listTasks();return task.taskId;})()`);
    assert.ok(id);
    const target = `[data-design="home.card"][data-home-task=${JSON.stringify(id)}] .home-card-head b`;
    if (!await visible(target)) await clickText('Show every session');
    const {menu, actions} = await inspectMenu(target, 'Home session menu', ['Open session','Rename'], ['Fork','Rerun']);
    await press(target, 'right');
    await press(menu + ' [data-design="menu.rename"]');
    const input = '[role="dialog"] input[aria-label="Task name"]';
    assert.ok(await until(() => visible(input), Boolean));
    assert.equal(await js(`document.querySelector(${JSON.stringify(input)}).value`), title);
    await shot('Home rename dialog for disposable task');
    await escape(input);
    return {actions, escapeDismissed:true, renameDialogShowedFixture:true};
  });
  await check(canvas, async () => {
    assert.ok(await clickText('Canvas'), 'Canvas navigation missing');
    const id = await js(`(async()=>{const api=window.ArchHubAPI;await api.newSession(${JSON.stringify(title)});return (await api.addNode('n_number',{x:100,y:180})).id;})()`);
    assert.ok(id);
    const target = `.react-flow__node[data-id=${JSON.stringify(id)}] [data-node-card-title]`;
    const {actions} = await inspectMenu(target, 'Node menu', ['Properties','Rerun','Fork'], ['Open session']);
    return {actions, escapeDismissed:true};
  });
}
