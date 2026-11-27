// Everything check: on every surface (Home, Canvas, each Settings page, the Workspaces dialog, the Thread dock) press every
// visible control once and record what it did, with a screenshot of each surface and of every failure. Effects never
// leave the page: non-GET calls that would act outside are answered by a stub (CDP Fetch) and recorded.
// Run it on the installed build and on the candidate, then compare the two crawl.json files with crawl_compare.py:
// anything that worked on the installed build and fails or is gone on the candidate fails the candidate.
import assert from 'node:assert/strict';
import {writeFileSync} from 'node:fs';
import path from 'node:path';
import {english} from './english.mjs';

const widths = [[1920,1032],[944,968]];
const AREAS=['Account','Projects','Agents','Connections','This PC'];
const surfaces = ['Home','Canvas',...AREAS.map(a=>'Settings:'+a),'Workspaces','Thread dock'];


export const steps = widths.flatMap(([w,h]) => surfaces.map(s => `Crawl ${s} at ${w}x${h}`));
const FORBIDDEN = /^(Social media|Dependencies|Logs (&|and) receipts|Team|Brain|Plan (&|and) access|Model routing|Feedback|Runs|Workshop|Meetings|Present|Model review|X-RAY|Watcher|Interface studio|First run)$/i;
const OLD_SCREENS = ['social','meetings','model-review','watcher','interface','community','desktop','dependencies','receipts','brain','team','plan','routing','feedback','runs','workshop','present','xray','firstrun','first-run'];
// Never pressed: leave the app, act on the outside world, or sign with the protected key.
const SKIP = /quit|sign ?out|log ?out|minimi|maximi|restore down|close (the )?window|^close archhub|uninstall|^(add|remove|republish|stop governing)$|delete|archive|stop everything|reset (all|page|everything)|^reset$/i;

// Page-side: no effect stubbing (api is frozen); only window.open/links and error counters.
const INSTALL = `(()=>{ if(window.__gate)return true; const log=[];
 window.open=(...a)=>{log.push('window.open:'+a[0]);return null;};
 try{ if(typeof window.ARCHHUB_WINDOW_ACTION==='function') window.ARCHHUB_WINDOW_ACTION=async a=>{log.push('window:'+a);return {visible:true};}; }catch{}
 document.addEventListener('click',e=>{const a=e.target.closest?.('a[href]');if(a&&(/^https?:|^mailto:/.test(a.getAttribute('href'))||a.target==='_blank')){e.preventDefault();log.push('link:'+a.getAttribute('href'));}},true);
 const errs=[]; window.addEventListener('error',e=>errs.push(String(e.message)));window.addEventListener('unhandledrejection',e=>errs.push(String(e.reason?.message||e.reason)));
 let n=0; const of=window.fetch; window.fetch=(u,o)=>{n++;return of(u,o);};
 window.__gate={log,errs,fetches:()=>n}; return true;})()`;
// Network-side: real effects never leave the page (CDP Fetch); every non-GET to these is answered by a stub.
const URL_DENY = /cloud-sign|cloud-session|application-update|social-approve|social-connection(?!s)|social-credential|workshop-model-approval|run-graph|stop-all|pick-file|brain-export|workspace-roots|\/api\/universal\/mods|\/api\/universal\/providers|\/api\/universal\/hosts|agents-transcript|selftest/i;
const BODY_DENY = /"(function|action|verb|op)"\s*:\s*"(openProgram|send\w*|approve\w*|decline\w*|signIn\w*|signOut\w*|install\w*|quit|backUpNow|rollBack|exportData|invitePerson|grantAccess|changePlan|stopEverything|remove\w*|delete\w*|disconnect\w*|transfer\w*|connect\w*|checkout\w*|prepareCheckout|completeCheckout|setBilling|joinMeeting|publish\w*|post\w*|run(?!s")\w*|update(Profile)?|manageDependency|ensureDependency|sync\w*)"/i;
const OBSERVE = `(()=>{const vis=e=>e&&e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const screens=[...document.querySelectorAll('[data-screen]')].filter(vis).map(e=>e.getAttribute('data-screen'));
 const pages=[...document.querySelectorAll('main.page,[data-screen]')].filter(vis).map(e=>e.getAttribute('data-screen')||'page').filter(s=>${JSON.stringify(OLD_SCREENS)}.includes(s));
 const dlg=[...document.querySelectorAll('[role=dialog],[role=alertdialog],dialog[open]')].filter(vis);
 const menus=[...document.querySelectorAll('[role=menu],[role=listbox]')].filter(vis).length;
 const soon=[...document.querySelectorAll('[data-soon]')].filter(vis).length;  // UI.Soon marks every unbuilt control
 const status=[...document.querySelectorAll('[role=status],[role=alert],.toast')].filter(vis).map(e=>e.innerText.trim()).filter(Boolean).join(' | ').slice(0,200);
 const t=document.body.innerText; let h=0; for(let i=0;i<t.length;i+=3)h=(h*31+t.charCodeAt(i))|0;
 return {title:document.title,screens,pages,dialogs:dlg.map(d=>(d.getAttribute('aria-label')||d.innerText.split('\\n')[0]).slice(0,60)),menus,soon,status,hash:h+':'+document.querySelectorAll('*').length,
  log:window.__gate?window.__gate.log.length:0,errs:window.__gate?window.__gate.errs.length:0,fetches:window.__gate?window.__gate.fetches():0,focusExpanded:document.activeElement?.getAttribute?.('aria-expanded')};})()`;

const LIST = scope => `(()=>{const root=${scope};if(!root)return [];const vis=e=>{const r=e.getBoundingClientRect();return r.width>2&&r.height>2&&r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth&&getComputedStyle(e).visibility!=='hidden';};
 const els=[...root.querySelectorAll('button,[role=button],[role=menuitem],[role=tab],[role=switch],[role=checkbox],a[href],summary,select')].filter(e=>vis(e)&&!e.disabled&&e.getAttribute('aria-disabled')!=='true'&&!e.closest('.react-flow__minimap'));
 const seen={};return els.map(e=>{const name=(e.getAttribute('aria-label')||e.getAttribute('title')||e.innerText||e.getAttribute('data-design')||'').trim().replace(/\\s+/g,' ').slice(0,70);const key=name+'|'+(e.getAttribute('data-design')||'');seen[key]=(seen[key]||0)+1;return {name,design:e.getAttribute('data-design')||'',nth:seen[key]-1,tag:e.tagName,role:e.getAttribute('role')||'',chrome:!!e.closest('header,nav,[data-window-caption]')};});})()`;

const FIND = c => `(()=>{const vis=e=>{const r=e.getBoundingClientRect();return r.width>2&&r.height>2&&r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth;};
 const els=[...document.querySelectorAll('button,[role=button],[role=menuitem],[role=tab],[role=switch],[role=checkbox],a[href],summary,select')].filter(e=>vis(e)&&!e.disabled);
 const m=els.filter(e=>((e.getAttribute('aria-label')||e.getAttribute('title')||e.innerText||e.getAttribute('data-design')||'').trim().replace(/\\s+/g,' ').slice(0,70))===${JSON.stringify(c.name)}&&(e.getAttribute('data-design')||'')===${JSON.stringify(c.design)});
 const e=m[${c.nth}]||m[0];if(!e)return null;const r=e.getBoundingClientRect();const x=r.left+Math.min(r.width/2,r.width-3),y=r.top+r.height/2;const hit=document.elementFromPoint(x,y);
 return {x,y,w:r.width,h:r.height,covered:!(hit&&(e===hit||e.contains(hit)||hit.contains(e))),coveredBy:hit&&!(e===hit||e.contains(hit))?(hit.getAttribute('aria-label')||hit.className||hit.tagName).toString().slice(0,60):''};})()`;

const keyOf = (surface, w, h, c) => [surface, w + 'x' + h, String(c.name).replace(/\d+([.:,]\d+)*/g, '#'), c.design || '', c.nth].join('|');

export default async function run(ctx) {
  const {js,cdp,step,until,mouse,native,sleep,shot,out} = ctx;
  // Waits (ms) after each kind of press; a slower PC passes larger ones as input.timing.
  const T = {yield:0, afterEscape:150, afterSelect:400, menuOpen:450, canvasOpen:500, areaOpen:600, afterClick:650, surfaceOpen:700, ...(ctx.input?.timing || {})};
  const esc = async () => { for (const type of ['rawKeyDown','keyUp']) await cdp('Input.dispatchKeyEvent',{type,key:'Escape',code:'Escape',windowsVirtualKeyCode:27}); };
  const rail = async label => { const p = await js(`(()=>{const e=[...document.querySelectorAll('nav button,nav [role=button]')].find(b=>(b.getAttribute('aria-label')||b.innerText||'').trim()===${JSON.stringify(label)});if(!e)return null;const r=e.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};})()`); if (!p) return false; await mouse(p); await sleep(T.surfaceOpen); return true; };
  const enter = {
    Home: async () => { await esc(); await esc(); await rail('Home'); },
    Canvas: async () => { await esc(); await esc(); await rail('Canvas'); },
  };
  for (const a of AREAS) enter['Settings:'+a] = async () => { await esc(); await esc(); await rail('Settings'); await until(()=>js(`Boolean(document.querySelector('nav[aria-label="Settings categories"]'))`),Boolean,20,150);
    const p = await js(`(()=>{const e=[...document.querySelectorAll('nav[aria-label="Settings categories"] button')].find(b=>b.innerText.trim().startsWith(${JSON.stringify(a)}));if(!e)return null;const r=e.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};})()`); if (p) { await mouse(p); await sleep(T.areaOpen); } };
  const openBy = async (from, pattern) => { await enter[from]();
    const p = await js(`(()=>{const e=[...document.querySelectorAll('button,[role=button]')].find(b=>b.getClientRects().length&&${pattern}.test((b.getAttribute('aria-label')||b.getAttribute('title')||b.innerText||'').trim()));if(!e)return null;const r=e.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};})()`);
    if (p) { await mouse(p); await sleep(T.surfaceOpen); } return Boolean(p); };
  enter.Workspaces = () => openBy('Home', '/^(add workspace|workspaces?|choose (a )?workspace)$|workspace/i');
  enter['Thread dock'] = () => openBy('Canvas', '/^(thread|show thread|open thread|threads)$/i');
  enter.Canvas = async () => { await esc(); await esc(); await rail('Canvas'); await sleep(T.canvasOpen);
    const n = await js(`document.querySelectorAll('.react-flow__node').length`); if (!n) { await js(`window.ArchHubAPI.addNode('n_number',{x:200,y:160})`); await sleep(T.surfaceOpen); }
    const p = await js(`(()=>{const e=document.querySelector('.react-flow__node');if(!e)return null;const r=e.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+12};})()`); if (p) { await mouse(p); await sleep(T.afterSelect); } };
  
  await english(js, until);
  const blocked = [];
  ctx.on('Fetch.requestPaused', p => { const r = p.request; const deny = r.method !== 'GET' && (URL_DENY.test(r.url) || BODY_DENY.test(r.postData || ''));
    if (deny) { blocked.push(r.method + ' ' + new URL(r.url).pathname + ' ' + String(r.postData || '').slice(0, 80));
      cdp('Fetch.fulfillRequest', {requestId: p.requestId, responseCode: 200, responseHeaders: [{name: 'Content-Type', value: 'application/json'}], body: Buffer.from('{"ok":true,"result":{},"blocked":true}').toString('base64')}).catch(() => {}); }
    else cdp('Fetch.continueRequest', {requestId: p.requestId}).catch(() => {}); });
  await cdp('Fetch.enable', {patterns: [{urlPattern: '*', requestStage: 'Request'}]});
  assert.ok(await js(INSTALL), 'page guards not installed');
  const probe = await js(`fetch('/api/universal/cloud-signin-selftest',{method:'POST',body:'{}'}).then(r=>r.json()).catch(e=>String(e))`);
  assert.ok(probe?.blocked === true && blocked.length === 1, 'network effect block not proven: ' + JSON.stringify(probe));
  const blk = () => blocked.length;
  const all = [], menuDone = new Set(), menuRows = [];
  for (const [w,h] of widths) {
    await native({kind:'window-frame',client:[w,h]});
    await cdp('Emulation.setDeviceMetricsOverride',{width:w,height:h,deviceScaleFactor:1,mobile:false,screenWidth:w,screenHeight:h});
    for (const surface of surfaces) await step(`Crawl ${surface} at ${w}x${h}`, async () => {
      const opened = await enter[surface]();
      if (opened === false) { all.push({surface, size:`${w}x${h}`, opened:false, rows:[]}); writeFileSync(path.join(out, 'crawl.json'), JSON.stringify({blocked, all, menuRows}, null, 1));
        return {not_exercised: surface + ' has no control to open it on this build'}; }
      const baseline = await js(OBSERVE);
      const shotBase = path.basename(await shot(`${surface}-${w}x${h}-base`));
      let controls = await js(LIST('document.body'));
      // Settings: also every area in its own nav.
      const rows = [];
      const cap = w === 1920 ? 100 : 60;
      const t0 = Date.now();
      for (const c of controls.slice(0, cap)) {
        if (Date.now() - t0 > (w === 1920 ? 110000 : 80000)) { rows.push({...c, key:keyOf(surface, w, h, c), cls:'NOT-CLICKED', why:'surface time bound'}); continue; }
        if (SKIP.test(c.name)) { rows.push({...c, key:keyOf(surface, w, h, c), cls:'SKIPPED', why:'leaves app / destructive / signing'}); continue; }
        const before = {...await js(OBSERVE), blk: blk()};
        const p = await js(FIND(c));
        if (!p) { rows.push({...c, key:keyOf(surface, w, h, c), cls:'NOT-FOUND'}); await enter[surface](); continue; }
        if (p.covered) { rows.push({...c, key:keyOf(surface, w, h, c), cls:'COVERED', why:p.coveredBy}); continue; }
        await mouse(p); await sleep(T.afterClick);
        await sleep(T.yield); const after = {...await js(OBSERVE), blk: blk()};
        let cls = 'did-its-action';
        const newPages = after.pages.filter(x => !before.pages.includes(x));
        const titleName = after.title.replace(/^ArchHub · /,'');
        if (after.errs > before.errs) cls = 'error';
        else if (newPages.length || (FORBIDDEN.test(titleName) && titleName !== before.title.replace(/^ArchHub · /,'') && !after.screens.includes('task-file'))) cls = 'opened-a-standalone-page';
        else if (after.title !== before.title || after.screens.join() !== before.screens.join()) cls = 'opened-a-design-place';
        else if (after.dialogs.length > before.dialogs.length || after.menus > before.menus) cls = 'opened-dialog-or-menu';
        else if (after.log > before.log || after.blk > before.blk) cls = 'did-its-action(stubbed-effect)';
        else if (after.hash === before.hash && after.fetches === before.fetches && after.status === before.status) cls = 'DEAD';
        const row = {...c, key:keyOf(surface, w, h, c), cls, title:after.title, screens:after.screens, newPages, dialogs:after.dialogs, status:after.status, stubbed: after.blk > before.blk ? blocked.slice(before.blk) : (after.log > before.log ? (await js('window.__gate.log.slice(-2)')) : undefined)};
        if (cls === 'DEAD' || cls === 'error' || cls === 'opened-a-standalone-page') row.shot = path.basename(await shot(`${surface}-${w}-${cls}-${c.name}`.replace(/[^\w.-]+/g,'_').slice(0,90)));
        // One level into menus/dialogs it opened: list their items (named, not pressed).
        if (cls === 'opened-dialog-or-menu') row.items = (await js(LIST(`[...document.querySelectorAll('[role=menu],[role=dialog]')].filter(e=>e.getClientRects().length).at(-1)`))).map(i => i.name).slice(0,30);
        rows.push(row);
        if (cls === 'opened-dialog-or-menu' && c.chrome && row.items?.length && !menuDone.has(c.name)) { menuDone.add(c.name); row.menuOf = true; }
        await esc(); await sleep(T.afterEscape);
        const now = await js(OBSERVE);
        if (now.title !== baseline.title || now.screens.join() !== baseline.screens.join() || now.dialogs.length || now.menus) await enter[surface]();
      }
      for (const opener of rows.filter(r => r.menuOf)) {
        for (const item of opener.items.slice(0, 25)) {
          if (!item || SKIP.test(item)) { menuRows.push({menu: opener.name, item, cls: 'SKIPPED'}); continue; }
          await enter[surface]();
          const o = await js(FIND(opener)); if (!o || o.covered) { menuRows.push({menu: opener.name, item, cls: 'OPENER-NOT-FOUND'}); continue; }
          await mouse(o); await sleep(T.menuOpen);
          const ip = await js(`(()=>{const m=[...document.querySelectorAll('[role=menu],[role=dialog]')].filter(e=>e.getClientRects().length).at(-1);if(!m)return null;
            const e=[...m.querySelectorAll('button,[role=button],[role=menuitem],[role=menuitemradio],[role=menuitemcheckbox],a[href]')].find(e=>(e.getAttribute('aria-label')||e.getAttribute('title')||e.innerText||'').trim().replace(/\s+/g,' ').slice(0,70)===${JSON.stringify(item)});
            if(!e)return null;const r=e.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};})()`);
          if (!ip) { menuRows.push({menu: opener.name, item, cls: 'ITEM-NOT-FOUND'}); await esc(); continue; }
          const before = {...await js(OBSERVE), blk: blk()};
          await mouse(ip); await sleep(T.afterClick);
          const after = {...await js(OBSERVE), blk: blk()};
          let cls = 'did-its-action';
          const newPages = after.pages.filter(x => !before.pages.includes(x));
          if (after.errs > before.errs) cls = 'error';
          else if (newPages.length || FORBIDDEN.test(after.title.replace(/^ArchHub · /,''))) cls = 'opened-a-standalone-page';
          else if (after.title !== before.title || after.screens.join() !== before.screens.join()) cls = 'opened-a-design-place';
          else if (after.dialogs.length > before.dialogs.length || after.menus > before.menus) cls = 'opened-dialog-or-menu';
          else if (after.blk > before.blk || after.log > before.log) cls = 'did-its-action(stubbed-effect)';
          else if (after.hash === before.hash && after.fetches === before.fetches && after.status === before.status) cls = 'DEAD';
          const mr = {menu: opener.name, item, cls, title: after.title, screens: after.screens, newPages, dialogs: after.dialogs, status: after.status, stubbed: after.blk > before.blk ? blocked.slice(before.blk) : undefined};
          if (['DEAD','error','opened-a-standalone-page'].includes(cls)) mr.shot = path.basename(await shot(`menu-${w}-${cls}-${opener.name}-${item}`.replace(/[^\w.-]+/g,'_').slice(0,90)));
          menuRows.push(mr); rows.push({...mr, name: opener.name + ' > ' + item, key: keyOf(surface, w, h, {name: opener.name + ' > ' + item, design: '', nth: 0})});
          await esc(); await esc();
        }
      }
      if (controls.length > cap) rows.push({cls:'NOT-CLICKED', why:`${controls.length - cap} controls past cap`});
      writeFileSync(path.join(out, 'crawl.json'), JSON.stringify({blocked, menuRows, all:[...all,{surface,size:`${w}x${h}`,rows}]}, null, 1));
      const soonText = await js(`[...document.querySelectorAll('[data-soon]')].filter(e=>e.getClientRects().length).map(e=>(e.closest('[data-card],section,li,.card,.row')?.innerText||e.textContent).trim().split(String.fromCharCode(10))[0].slice(0,80))`);
      all.push({surface, size:`${w}x${h}`, baseline:{title:baseline.title, soon:baseline.soon, soonText}, shot:shotBase, rows});
      writeFileSync(path.join(out, 'crawl.json'), JSON.stringify({blocked, all, menuRows}, null, 1));
      const bad = rows.filter(r => ['DEAD','error','opened-a-standalone-page'].includes(r.cls));
      return {pass: bad.length === 0, why: bad.length ? bad.map(b => b.cls + ': ' + b.name).join('; ').slice(0, 900) : undefined,
        got: {controls: controls.length, counts: rows.reduce((a, r) => (a[r.cls] = (a[r.cls] || 0) + 1, a), {})}};
    });
  }
}
