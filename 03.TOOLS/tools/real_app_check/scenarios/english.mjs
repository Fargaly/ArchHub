// Put the shared QA profile back to English before an English-only scenario (state hygiene, not a product step).
// Same write path founder_screens.mjs uses for its language cases; retried while the startup graph settles.
export async function english(js, until, retryMs = 1500) {
  let last = '';
  for (let i = 0; i < 12; i++) {
    last = await js(`(async()=>{try{const a=ArchHubAPI;await a.getSettings();
      {await a.refreshPreferences();const s=a.getSnapshot();const n=s.settings.find(r=>/\.Numbers$/.test(r.id));if(n&&n.value!=='123'&&s.settingsDestination)await a.setSetting(n.id,'123',s.settingsDestination);}
      if(a.getSnapshot().settings.find(r=>r.id==='Account.App language')?.value==='English')return 'ok';
      await a.refreshPreferences();const s=a.getSnapshot();const row=s.settings.find(r=>r.id==='Account.App language');
      if(!row||!s.settingsDestination)return 'no destination';
      await a.setSetting(row.id,'English',s.settingsDestination);return 'ok'}catch(e){return String(e.message||e)}})()`);
    if (last === 'ok' && await until(() => js(`!!document.querySelector('nav button[aria-label="Home"]')`), Boolean, 20, 150)) return;
    await new Promise(r => setTimeout(r, retryMs));
  }
  throw Error('QA profile did not return to English: ' + last);
}
