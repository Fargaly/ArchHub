import assert from 'node:assert/strict';
import path from 'node:path';

export const steps = ['WhatsApp Business shows its account status and opens from the Connections tile'];

export default async function run({js,cdp,on,step,shot,mouse,until,rectOf,clickText}) {
  await step(steps[0], async () => {
    assert.equal(await js('window.ArchHubAPI.getSnapshot().desktopAccess.admitted'),true);
    const settings=await until(()=>js('(()=>{const label=window.UI?.productLabel("Settings",window.ArchHubAPI.getSnapshot().settings);return label&&[...document.querySelectorAll("nav button")].some(e=>e.getAttribute("aria-label")===label&&e.getClientRects().length)&&label;})()'),Boolean);
    assert.ok(settings&&await clickText(settings,'nav button'),'Settings rail did not become available');
    const category = 'nav[aria-label="Settings categories"] button[aria-label="Connections"]';
    assert.ok(await until(() => rectOf('document.querySelector('+JSON.stringify(category)+')'),Boolean));
    assert.ok(await clickText('Connections',category));
    const selector = 'button.sheet-connection-tile[aria-label^="WhatsApp Business"]';
    const tile = 'document.querySelector('+JSON.stringify(selector)+')';
    assert.ok(await until(()=>js('Boolean('+tile+')'),Boolean),'WhatsApp Business tile missing');
    await js(tile+'.scrollIntoView({block:"center",behavior:"instant"})');
    const before=await until(()=>js(`(()=>{const e=${tile};if(!e)return null;
      const r=e.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2;
      const top=document.elementFromPoint(x,y);
      return {x,y,label:e.getAttribute('aria-label'),disabled:e.disabled,hit:!!r.width&&!!r.height&&
        (e.contains(top)||(e.disabled&&e.closest('[data-soon]')?.contains(top))),hitElement:top?.tagName,hitClass:top?.className,
        dialogs:document.querySelectorAll('[role="dialog"],dialog[open]').length};})()`),p=>p?.hit,16,120);
    if(!before?.hit)return {not_exercised:'Could not target the visible WhatsApp tile safely',got:before};
    const beforeShot=path.basename(await shot('WhatsApp Business before click'));
    const errors=[];
    const errorName=value=>String(value||'Error').match(/\b(?:TypeError|ReferenceError|RangeError|SyntaxError|Error)\b/)?.[0]||'Error';
    await cdp('Runtime.enable');
    on('Runtime.exceptionThrown',e=>errors.push(errorName(e.exceptionDetails?.exception?.className)));
    on('Runtime.consoleAPICalled',e=>{if(e.type==='error')errors.push(errorName(e.args?.[0]?.className||e.args?.[0]?.value));});
    await mouse(before);
    const after=await until(()=>js(`(()=>{const all=[...document.querySelectorAll('[role="dialog"],dialog[open]')].filter(e=>e.getClientRects().length);
      return {dialogs:all.length,heading:all.at(-1)?.getAttribute('aria-label')||all.at(-1)?.querySelector('h1,h2,h3')?.textContent||'',
      includesProvider:all.some(e=>/whatsapp/i.test(e.innerText))};})()`),v=>v.dialogs>before.dialogs,12,150);
    const afterShot=path.basename(await shot('WhatsApp Business after click'));
    // Refresh publishes the owner rows into the sheet. Collect it only after observing the untouched tile.
    const owner = await js(`(async()=>{const all=await window.ArchHubAPI.refreshSocialConnections();
      const row=all.find(r=>r.provider==='whatsapp'||r.id==='whatsapp');
      return row ? {state:row.state,blocker:row.blocker??null,can_connect:row.can_connect??null} : null;})()`);
    const pass=!!owner&&after.dialogs>before.dialogs&&after.includesProvider;
    return {pass,why:pass?undefined:'Click did not open a WhatsApp Business connection dialog backed by the account owner',
      got:{owner,before,beforeShot,after,errors:[...new Set(errors)],afterShot}};
  });
}
