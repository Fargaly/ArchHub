import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import path from 'node:path';
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
    const fixture = await js(`(async()=>{
      const api=window.ArchHubAPI, task=await api.createTask(${JSON.stringify(title)});
      await api.openTaskGraph(task.taskId);
      const node=await api.addNode('n_number',{x:80,y:120});
      await api.saveSession();
      const selected=await api.createTask(${JSON.stringify(title+' selected')});
      await api.openTaskGraph(selected.taskId);
      await api.saveSession();
      await api.listTasks();
      return {id:task.taskId,path:task.path,node:node.id,selected:selected.taskId,selectedPath:selected.path};
    })()`);
    const {id}=fixture, before=readFileSync(fixture.path);
    assert.ok(JSON.parse(before).nodes.some(node=>node.id===fixture.node));
    assert.equal(await js('window.ArchHubAPI.getSessionDocument().properties.taskContext.task'),fixture.selected);
    const target = `[data-design="home.card"][data-home-task=${JSON.stringify(id)}] .home-card-head b`;
    if (!await visible(target) && await visible('[data-home-history][aria-pressed="false"]')) await press('[data-home-history]');
    const {menu, actions} = await inspectMenu(target, 'Home session menu', ['Open session','Open the thread','Run','Add to another task','Make this an automation',
      'Settings for this session','Rename','Duplicate','Keep at the top','Archive'], ['Fork','Rerun','Invite to watch…']);
    await press(target, 'right');
    const watch=await js(`(()=>{const button=[...document.querySelectorAll(${JSON.stringify(menu+' button')})]
      .find(b=>b.querySelector('span')?.textContent.trim()==='Invite to watch…');
      return button && {disabled:button.disabled,reason:button.title};})()`);
    assert.deepEqual(watch,{disabled:true,reason:'Read-only watcher invitations are unavailable.'});
    await press(menu + ' [data-design="menu.rename"]');
    const input = '[role="dialog"] input[aria-label="Task name"]';
    assert.ok(await until(() => visible(input), Boolean));
    assert.equal(await js(`document.querySelector(${JSON.stringify(input)}).value`), title);
    await shot('Home rename dialog for disposable task');
    await escape(input);
    await press(target,'right');
    await press(menu+' [data-design="menu.duplicate"]');
    const copied=await until(()=>js(`(()=>{const api=window.ArchHubAPI, doc=api.getSessionDocument();
      return doc?.title===${JSON.stringify(title+' (fork)')} && {id:doc.properties.taskContext.task,path:api.getSessionPath()};})()`),Boolean);
    assert.ok(copied?.id && copied.id!==id && copied.id!==fixture.selected);
    assert.notEqual(path.resolve(copied.path).toLowerCase(),path.resolve(fixture.path).toLowerCase());
    const fork=JSON.parse(readFileSync(copied.path));
    assert.equal(fork.properties.taskContext.task,copied.id);
    assert.ok(fork.nodes.some(n=>n.id===fixture.node));
    assert.deepEqual(readFileSync(fixture.path),before,'Duplicate changed the original file');
    const selectedCard = `[data-design="home.card"][data-home-task=${JSON.stringify(fixture.selected)}]`;
    const selectA = async () => {
      if (!await visible('[data-home-page]')) assert.ok(await clickText('Home'), 'Home navigation missing');
      assert.ok(await until(()=>visible('[data-home-history]'),Boolean));
      if (await visible('[data-home-history][aria-pressed="false"]')) await press('[data-home-history]');
      await press(selectedCard+' .home-card-head b');
      assert.ok(await until(()=>visible(selectedCard+'.sel'),Boolean),'A is not selected on Home');
    };
    const chooseB = async command => {
      await press(target,'right');
      await press(menu+` [data-design="menu.${command}"]`);
    };
    const inspectB = async (tab, detail) => {
      const witness = await until(()=>js(`(()=>{
        const pane=[...document.querySelectorAll('[data-properties-pane]')].find(p=>p.querySelector('[data-design="inspector.${tab}"][aria-selected="true"]')?.getClientRects().length);
        const control=pane?.querySelector(${JSON.stringify(detail)});
        if(!control?.getClientRects().length)return false;
        const tab=pane.querySelector('[role="tab"][aria-selected="true"]');
        const box=tab.getBoundingClientRect(), x=box.left+box.width/2, y=box.top+box.height/2;
        return tab.contains(document.elementFromPoint(x,y)) &&
          pane.querySelector('h2')?.textContent.trim()===${JSON.stringify(title)} &&
          document.querySelector('[aria-label="Open tasks"] [role="tab"][aria-selected="true"]')?.textContent.trim()===${JSON.stringify(title)} &&
          window.ArchHubAPI.getSessionDocument()?.properties?.taskContext?.task===${JSON.stringify(id)};
      })()`),Boolean);
      assert.ok(witness,'B lacks a visible '+tab+' inspector with its task tab selected');
    };
    await selectA();
    const selectedBytes=readFileSync(fixture.selectedPath), forkBytes=readFileSync(copied.path);
    await chooseB('settings-for-this-session');
    await inspectB('task','[data-design="inspector.session.donewhen"]');
    await selectA();
    await chooseB('make-this-an-automation');
    await inspectB('automate','.shared-properties-task:not([hidden]) button');
    const automated=JSON.parse(readFileSync(fixture.path));
    const schedules=automated.nodes.filter(n=>n.type==='trigger.schedule');
    assert.equal(schedules.length,1);
    assert.equal(schedules[0].params.armed,false);
    const scheduleTitle=await js(`document.querySelector('[data-properties-pane] .shared-properties-task:not([hidden]) button')?.textContent.trim()`);
    assert.equal(scheduleTitle,schedules[0].title);
    await selectA();
    const statusOfB=()=>js(`(()=>{const t=window.ArchHubAPI.getSnapshot().tasks.find(t=>t.id===${JSON.stringify(id)});return t&&{status:t.status,path:t.sessionPath};})()`);
    const prior=await statusOfB(), beforeArchive=JSON.parse(readFileSync(fixture.path));
    assert.ok(prior?.path && path.resolve(prior.path)===path.resolve(fixture.path));
    await chooseB('archive');
    const dialog='[role="dialog"]';
    assert.ok(await until(()=>js(`document.querySelector(${JSON.stringify(dialog)})?.innerText.includes(${JSON.stringify('Archive '+title+'?')})`),Boolean));
    assert.ok(await clickText('Confirm',dialog+' button'));
    const archivedToast=()=>js(`[...document.querySelectorAll('[role="alert"]')].some(e=>e.getClientRects().length && e.querySelector('span')?.textContent===${JSON.stringify(title+' archived.')} && [...e.querySelectorAll('button')].some(b=>b.textContent.trim()==='Undo'))`);
    assert.ok(await until(archivedToast,Boolean),'Missing Undo toast for B');
    assert.equal(JSON.parse(readFileSync(fixture.path)).properties.state,'archived');
    assert.equal((await statusOfB())?.status,'ARCHIVED','B is not archived in the Workshop');
    assert.ok(await clickText('Undo','[role="alert"] button'));
    const restored=await until(statusOfB,t=>t?.status===prior.status && t.path===prior.path);
    assert.deepEqual(restored,prior);
    const reopened=JSON.parse(readFileSync(fixture.path));
    assert.equal(reopened.properties.state,'open');
    assert.equal(reopened.id,automated.id);
    assert.equal(reopened.properties.taskContext.task,id);
    assert.deepEqual(reopened.nodes,beforeArchive.nodes);
    assert.deepEqual(reopened.wires,beforeArchive.wires);
    assert.deepEqual(readFileSync(fixture.selectedPath),selectedBytes,'B actions changed A');
    assert.deepEqual(readFileSync(copied.path),forkBytes,'B actions changed the unrelated fork');
    return {actions,watch,escapeDismissed:true,renameDialogShowedFixture:true,distinctFork:true,originalBytesPreserved:true,
      taskInspector:true,automateInspector:true,pausedSchedule:true,archiveUndo:true,unrelatedFilesPreserved:true};
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
