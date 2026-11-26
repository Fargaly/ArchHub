import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {mapReadback,saveTaskFile} from './founder_home_return.mjs';

const sizes = [[1920,1032],[860,970],[944,968],[1009,968]];
const cases = sizes.flatMap(([width,height]) => ['English','Arabic'].flatMap(language =>
  [true,false].map(open => ({width,height,language,open}))));
cases.splice(4,0,{width:900,height:970,language:'Arabic',open:false});
const title = c => 'Rail Canvas and Home at ' + c.width + 'x' + c.height + ', ' + c.language + ', docks ' + (c.open?'open':'folded');
export const steps = ['Save a QA workflow for the screen audit',...cases.map(title)];

export default async function run(ctx) {
  const {js,cdp,step,until,rectOf,mouse,native,shot} = ctx;
  const read = (fn,arg) => js('(' + fn.toString() + ')(' + JSON.stringify(arg) + ')');
  const wanted = ctx.input?.qaEmail;
  assert.ok(await read(wanted => {
    const a = window.ArchHubAPI.getSnapshot().desktopAccess;
    return !!wanted && a.admitted && [a.email,a.subject].includes(wanted);
  }, wanted), 'Dedicated QA account required');
  const click = async selector => {
    const element = 'document.querySelector(' + JSON.stringify(selector) + ')';
    const p = await until(async () => {
      const point = await rectOf(element);
      if (!point?.w || !point.h) return null;
      return await js(element + '?.contains(document.elementFromPoint(' + point.x + ',' + point.y + '))') ? point : null;
    },Boolean,15,130);
    assert.ok(p, 'Missing or covered control: ' + selector);
    await mouse(p);
  };
  const route = async name => {
    const label = await read(name => window.UI.productLabel(name,window.ArchHubAPI.getSnapshot().settings),name);
    await click('nav button[aria-label=' + JSON.stringify(label) + ']');
    const target = name==='Home'?'[data-home-page]':'[data-screen="canvas"]';
    assert.ok(await until(() => read(sel => !!document.querySelector(sel)?.getClientRects().length,target),Boolean,25,180),
      'Rail did not reach ' + name);
  };
  const dock = () => read(() => {
    const box = selector => {
      const r = document.querySelector(selector)?.getBoundingClientRect();
      return r && [Math.round(r.width),Math.round(r.height)];
    };
    return Object.fromEntries(['left','right'].map(side => {
      const root = document.querySelector('[data-dock="'+side+'"]');
      return [side,{folded:root?.classList.contains('col') || false, size:box('[data-dock="'+side+'"]'),
        open:[...(root?.querySelectorAll('[data-slot]:not(.c)') || [])].map(s => s.getAttribute('aria-label'))}];
    }));
  },null);
  const setDocks = async open => {
    for (const side of ['left','right']) {
      const current = (await dock())[side];
      assert.ok(current.size?.[0], 'Missing ' + side + ' dock');
      if (current.folded === open) {
        const label = open ? 'Open the ' + side + ' dock' : 'Fold the ' + side + ' dock to icons';
        await click('[data-dock="'+side+'"] button[aria-label="'+label+'"]');
        assert.ok(await until(async () => (await dock())[side].folded===!open,Boolean,20,100),'Dock did not change');
      }
    }
    const current = await dock();
    if(open) {
      const active = [...current.left.open,...current.right.open];
      for(const label of ['Library','Inspector','Workshop']) assert.ok(active.includes(label),'Missing docked '+label);
    }
    return current;
  };
  const language = async value => {
    await read(async value => {
      const a=window.ArchHubAPI;
      await a.getSettings();
      const s=a.getSnapshot();
      const row=s.settings.find(r=>r.id==='Account.App language');
      if(!row) throw Error('No language owner');
      if(row.value!==value) await a.setSetting(row.id,value,s.settingsDestination);
    },value);
    assert.ok(await until(() => read(value => {
      const s=window.ArchHubAPI.getSnapshot();
      return s.settings.find(r=>r.id==='Account.App language')?.value===value &&
        !!document.querySelector('nav button[aria-label='+JSON.stringify(window.UI.productLabel('Home',s.settings))+']');
    },value),Boolean,20,150),'Native language choice did not reach the rail');
  };
  let fixture, initialLanguage;
  await step(steps[0],async () => {
    initialLanguage = await js("ArchHubAPI.getSnapshot().settings.find(r=>r.id==='Account.App language')?.value");
    await route('Home');
    fixture = await read(saveTaskFile,'QA Drawing coordination ' + randomUUID().slice(0,6) + ' · مراجعة الدور ٣');
    const file=JSON.parse(readFileSync(fixture.file,'utf8'));
    assert.ok(file.id===fixture.document && file.nodes.some(n => n.id===fixture.node));
    return {pass:true,got:{saved:true,nodeType:'Number',file:path.basename(fixture.file)}};
  });
  try {
    for (const c of cases) {
      await step(title(c), async () => {
        assert.ok(fixture,'Saved fixture unavailable');
        const frame = await native({kind:'window-frame',client:[c.width,c.height]});
        assert.ok(frame.client,frame.error||'Missing native client size');
        // Qt retains the probe's 1440x900 drawing surface even after the native HWND resizes.
        await cdp('Emulation.setDeviceMetricsOverride',{width:frame.client[0],height:frame.client[1],
          screenWidth:frame.client[0],screenHeight:frame.client[1],deviceScaleFactor:1,mobile:false});
        const viewport = await until(() => js('({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})'),
          v => Math.abs(v.width*v.dpr-c.width)<=1 && Math.abs(v.height*v.dpr-c.height)<=1,20,120);
        const correctSize = frame.client[0]===c.width && frame.client[1]===c.height &&
          Math.abs(viewport.width*viewport.dpr-c.width)<=1 && Math.abs(viewport.height*viewport.dpr-c.height)<=1;
        await language(c.language);
        await route('Home');
        const dockBefore=await setDocks(c.open);
        const map=()=>read(mapReadback,fixture.id);
        const before=await until(map,v=>v.taskVisible,25,150);
        const beforeShot=path.basename(await shot(title(c)+' before'));
        assert.ok(before.taskVisible,'Baseline Home did not display its saved task: '+JSON.stringify(before));
        await route('Canvas');
        const node=await until(() => read(t=>{
          const doc=window.ArchHubAPI.getSessionDocument(), el=document.querySelector('[data-graph-node="'+t.node+'"]');
          const r=el?.getBoundingClientRect();
          return {same:doc.id===t.document,inFile:doc.nodes.some(n=>n.id===t.node),rendered:!!(r?.width&&r.height)};
        },fixture),v=>v?.same&&v.inFile&&v.rendered,25,150);
        const canvasShot=path.basename(await shot(title(c)+' Canvas'));
        await route('Home');
        const after=await until(map,v=>v.taskVisible,28,150);
        const dockAfter=await dock();
        const why=!after.taskVisible?'The return reached Home but its saved card is missing from view':
          !node.same||!node.inFile||!node.rendered?'The Canvas rail did not display the saved workflow node':
          ['left','right'].some(side=>dockBefore[side].folded!==dockAfter[side].folded)?'Returning changed the dock state':
          !correctSize?'Actual Qt or Windows size differs from the requested geometry':undefined;
        return {pass:!why,why,got:{frame,viewport,language:c.language,dockBefore,before,beforeShot,node,canvasShot,after,dockAfter}};
      });
    }
  } finally {
    if(initialLanguage) await language(initialLanguage);
  }
}
