const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {spawn, execFileSync} = require('node:child_process');
const {chromium} = require('playwright');

const root = process.cwd(), stage = process.argv[2] || 'settings';
const scratch = path.join(root, '.cache/designsplit');
const profile = path.join(scratch, 'profile');
const proof = 'C:/Users/fargaly/AppData/Local/Temp/designsplit-proof';
for (const dir of [scratch, profile, proof, 'local', 'roaming', 'temp'].map(dir => path.isAbsolute(dir) ? dir : path.join(profile, dir))) fs.mkdirSync(dir, {recursive:true});
const env = {...process.env, PYTHONPATH:path.join(root,'01.APP'), PYTHONUTF8:'1', USERPROFILE:profile, HOME:profile,
  LOCALAPPDATA:path.join(profile,'local'), APPDATA:path.join(profile,'roaming'), TEMP:path.join(profile,'temp'), TMP:path.join(profile,'temp')};
Object.assign(process.env,env);
const server = spawn('python', ['-u', '-c', `
import json, threading
from pathlib import Path
from nodelang.nograph_server import NoGraphServer
s=NoGraphServer(Path(${JSON.stringify(profile.replaceAll('\\','/'))})/'state')
print(json.dumps({'url':s.public_url+'/studio?bootstrap='+s.browser_bootstrap_token}),flush=True)
s.httpd.serve_forever()
`], {cwd:root, env, windowsHide:true, stdio:['ignore','pipe','pipe']});
let browser;
(async()=>{
  let stderr='';server.stderr.on('data', bytes=>stderr+=bytes);
  const url = await new Promise((resolve,reject)=>{
    let raw='';server.stdout.on('data',bytes=>{raw+=bytes;const end=raw.indexOf('\n');if(end>=0)resolve(JSON.parse(raw.slice(0,end)).url);});
    server.on('exit',code=>reject(Error(`Proof server exited ${code}: ${stderr}`)));
  });
  browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true,env});
  const context=await browser.newContext({viewport:{width:1680,height:893},deviceScaleFactor:1});
  const page=await context.newPage(), errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(url);
  await page.waitForSelector('.app-window');
  await page.evaluate(()=>window.ArchHubAPI.ready);
  const source='C:/Users/fargaly/00.ARCHUB/30.KNOWLEDGE/35.DESIGN-SYSTEM/35.02-APP-DESIGN/01.WIP';
  const metrics=[];
  async function capture(name,svg){
    await page.evaluate(()=>document.fonts.ready);
    await page.screenshot({path:path.join(scratch,name+'-app.png')});
    const reference=await context.newPage();
    await reference.goto(new URL('/assets/fonts.css',url).href);
    const fonts=await reference.locator('body').innerText();
    await reference.setContent('<style>'+fonts.replaceAll('/assets/fonts/',new URL('/assets/fonts/',url).href)+'html,body{margin:0;background:#0e0e11}</style>'+fs.readFileSync(path.join(source,svg),'utf8'));
    await reference.evaluate(()=>document.fonts.ready);
    await reference.screenshot({path:path.join(scratch,name+'-svg.png')});await reference.close();
    execFileSync('python',['-c',`from PIL import Image;a=Image.open(${JSON.stringify(path.join(scratch,name+'-svg.png'))});b=Image.open(${JSON.stringify(path.join(scratch,name+'-app.png'))});o=Image.new('RGB',(a.width+b.width,max(a.height,b.height)));o.paste(a,(0,0));o.paste(b,(a.width,0));o.save(${JSON.stringify(path.join(proof,name+'.png'))})`],{env,windowsHide:true});
    await page.setViewportSize({width:1440,height:893});
    await page.screenshot({path:path.join(proof,name+'-1440.png')});
    const measure=await page.evaluate(()=>({viewport:window.innerWidth,document:document.documentElement.scrollWidth,main:[...document.querySelectorAll('[data-screen^="settings/"]>main,.settings-sheet,.docs-article')].map(e=>({width:e.clientWidth,scroll:e.scrollWidth}))}));
    assert.ok(measure.document<=1440,JSON.stringify(measure));
    assert.ok(measure.main.every(e=>e.scroll<=e.width),JSON.stringify(measure));
    metrics.push({name,...measure});await page.setViewportSize({width:1680,height:893});
  }
  if(stage==='settings'){
    await page.getByRole('button',{name:'Settings',exact:true}).click();
    await page.waitForSelector('[data-screen="settings/Account"]');
    await page.getByText('Reading settings…',{exact:true}).waitFor({state:'hidden'});
    await capture('settings-account','archhub-current-settings-account.svg');
    for(const [door,name] of [['Connections','connections'],['Automation & Brain','automation-brain'],['System','system'],['Interface','interface']]){
      await page.locator('.settings-section').getByText(door,{exact:true}).click();
      await page.getByText('Reading settings…',{exact:true}).waitFor({state:'hidden'});
      await capture('settings-'+name,'archhub-current-settings-'+name+'.svg');
    }
    await page.locator('.settings-section').getByText('Automation & Brain',{exact:true}).click();
    await page.locator('.sheet-below').getByText('Agents',{exact:true}).click();
    await page.getByRole('table',{name:'Router requests'}).waitFor({});
    assert.equal(await page.getByRole('table',{name:'Router requests'}).locator('tfoot').innerText(),'Total\t0\tNot reported\tNot measured');
    await page.screenshot({path:path.join(proof,'settings-agents.png')});
  }
  console.log(JSON.stringify({stage,metrics,errors},null,2));
  fs.writeFileSync(path.join(proof,stage+'-checks.json'),JSON.stringify({stage,metrics,errors},null,2));
  assert.deepEqual(errors,[]);
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();server.kill();});
