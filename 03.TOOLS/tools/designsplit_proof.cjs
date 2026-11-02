const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {spawn, execFileSync} = require('node:child_process');
const {chromium} = require('playwright');

const root = process.cwd(), stage = process.argv[2] || 'settings';
const scratch = path.join(root, '.cache/designsplit');
const profile = path.join(scratch, 'profile');
const proof = 'C:/Users/fargaly/AppData/Local/Temp/designexact-proof';
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
    if(name.startsWith('settings-')){
      const geometry=await page.evaluate(()=>{
        const sheet=document.querySelector('.settings-sheet');
        const field=sheet.querySelector('.sheet-field');
        const action=sheet.querySelector('.sheet-action');
        const cols=window.getComputedStyle(sheet.querySelector('.sheet-columns'));
        const box=el=>el.getBoundingClientRect();
        const label=field&&field.querySelector('span');
        return {width:box(sheet).width,height:box(sheet).height,title:window.getComputedStyle(sheet.querySelector('h1')).fontSize,section:window.getComputedStyle(sheet.querySelector('h2')).fontSize,body:window.getComputedStyle(sheet.querySelector('p')).fontSize,meta:label?window.getComputedStyle(label).fontSize:null,row:field?box(field).height:null,action:box(action).height,gap:cols.columnGap,pad:window.getComputedStyle(sheet).paddingLeft,columns:cols.gridTemplateColumns};
      });
      assert.ok(Math.abs(geometry.width-1280)<1,JSON.stringify(geometry));
      assert.ok(geometry.height>=672,JSON.stringify(geometry));
      assert.equal(geometry.title,'24px');
      assert.equal(geometry.section,'18px');
      assert.equal(geometry.body,'14px');
      if(geometry.meta)assert.equal(geometry.meta,'13px');
      if(geometry.row!==null)assert.ok(Math.abs(geometry.row-64)<1,JSON.stringify(geometry));
      assert.ok(Math.abs(geometry.action-36)<1,JSON.stringify(geometry));
      assert.equal(geometry.gap,'32px');
      assert.equal(geometry.pad,'32px');
      metrics.push({name,geometry});
    }
    await page.setViewportSize({width:1440,height:900});
    await page.screenshot({path:path.join(proof,name+'-1440.png')});
    const measure=await page.evaluate(()=>{
      const frame=document.querySelector('.app-window').getBoundingClientRect();
      const stage=document.querySelector('.settings-sheet-stage')||document.querySelector('.screen-with-composer');
      const stageBox=stage.getBoundingClientRect();
      const offenders=[];
      for(const el of stage.querySelectorAll('*')){
        const box=el.getBoundingClientRect();
        if(box.width<1||box.height<1)continue;
        if(box.left<stageBox.left-1||box.right>stageBox.right+1)offenders.push((el.className&&el.className.toString())||el.tagName);
      }
      return {viewport:window.innerWidth,document:document.documentElement.scrollWidth,frame:frame.width,offenders:offenders.slice(0,8),main:[...document.querySelectorAll('.settings-sheet,.library-shelf,.docs-article')].map(e=>({width:e.clientWidth,scroll:e.scrollWidth}))};
    });
    assert.ok(measure.document<=1440,JSON.stringify(measure));
    assert.deepEqual(measure.offenders,[],JSON.stringify(measure));
    assert.ok(measure.main.every(e=>e.scroll<=e.width+1),JSON.stringify(measure));
    metrics.push({name,...measure});await page.setViewportSize({width:1680,height:893});
  }
  if(stage==='settings'||stage==='all'){
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
    await page.getByRole('button',{name:'Advanced',exact:true}).click();
    await page.getByRole('table',{name:'Router requests'}).waitFor({});
    assert.equal(await page.getByRole('table',{name:'Router requests'}).locator('tfoot').innerText(),'Total\t0\tNot reported\tNot measured');
    await page.screenshot({path:path.join(proof,'settings-agents.png')});
  }
  if(stage==='library'||stage==='all'){
    await page.evaluate(()=>window.ArchHubAPI.setLibraryCollapsed([]));
    await page.getByRole('button',{name:'Canvas',exact:true}).click();
    const shelf=page.getByRole('complementary',{name:'Library shelf'});
    if(!await shelf.isVisible()){
      await page.getByRole('button',{name:'More canvas actions'}).click();
      await page.getByRole('button',{name:'Show Library',exact:true}).click();
    }
    await shelf.waitFor();
    const first=shelf.locator('.shelf-category').first();
    await first.click();
    await page.waitForFunction(()=>document.querySelector('.shelf-category')?.getAttribute('aria-expanded')==='false');
    assert.equal(await first.getAttribute('aria-expanded'),'false');
    await page.getByRole('button',{name:'Settings',exact:true}).click();
    await page.getByRole('button',{name:'Canvas',exact:true}).click();
    assert.equal(await shelf.locator('.shelf-category').first().getAttribute('aria-expanded'),'false');
    await page.reload();await page.waitForSelector('.app-window');
    await page.getByRole('button',{name:'Canvas',exact:true}).click();
    if(!await shelf.isVisible()){
      await page.getByRole('button',{name:'More canvas actions'}).click();
      await page.getByRole('button',{name:'Show Library',exact:true}).click();
    }
    assert.equal(await shelf.locator('.shelf-category').first().getAttribute('aria-expanded'),'false');
    await shelf.locator('.shelf-category').first().click();
    await page.waitForFunction(()=>document.querySelector('.shelf-category')?.getAttribute('aria-expanded')==='true');
    const previous=await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.id);
    await shelf.getByRole('button',{name:'New canvas session',exact:true}).click();
    await page.waitForFunction(id=>window.ArchHubAPI.getSnapshot().graph.id!==id,previous);
    const catalogue=await page.evaluate(()=>window.ArchHubAPI.getSnapshot().catalogue.map(row=>({id:row.id,name:row.name})));
    const operation=catalogue.find(row=>/^(Filter|Add|Format|Text)$/i.test(row.name))||catalogue.find(row=>!/(Number|Temperature|Dataset|Field)/i.test(row.name));
    assert.ok(operation,'The real node catalogue must be available');
    await page.evaluate(id=>window.ArchHubAPI.addNode(id,{x:360,y:120}),operation.id);
    const addParameter=page.getByRole('button',{name:/Add parameter to/}).first();
    if(await addParameter.count()){
      await addParameter.click();
      const min=page.getByRole('spinbutton',{name:'Parameter min',exact:true}),max=page.getByRole('spinbutton',{name:'Parameter max',exact:true});
      assert.equal(await min.inputValue(),'');assert.equal(await max.inputValue(),'');
      await page.getByRole('textbox',{name:'Parameter name',exact:true}).fill('Limit');
      await page.getByRole('spinbutton',{name:'Parameter value',exact:true}).fill('0');
      await min.fill('-5');await max.fill('10');
      await page.getByRole('button',{name:'Add parameter',exact:true}).click();
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().graph.nodes.some(node=>node.paramDefs?.some(def=>def.name==='Limit'&&def.min===-5&&def.max===10)));
      const another=page.getByRole('button',{name:/Add parameter to/}).first();await another.click();
      await page.getByRole('textbox',{name:'Parameter name',exact:true}).fill('Unbounded');
      await page.getByRole('spinbutton',{name:'Parameter value',exact:true}).fill('-17');
      await page.getByRole('button',{name:'Add parameter',exact:true}).click();
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().graph.nodes.some(node=>node.paramDefs?.some(def=>def.name==='Unbounded'&&def.min===undefined&&def.max===undefined)));
    }else throw Error('The selected operation must expose the real Add parameter editor');
    const numberId=await page.evaluate(async()=>{
      const node=await window.ArchHubAPI.addNode('n_number',{x:680,y:120});
      await window.ArchHubAPI.setNodeParam(node.id,'value',0);
      await window.ArchHubAPI.runNode(node.id);
      return node.id;
    });
    const numberCard=page.locator(`.react-flow__node[data-id="${numberId}"]`);
    await numberCard.waitFor();
    const minimum=numberCard.getByRole('spinbutton',{name:'Number min',exact:true});
    const maximum=numberCard.getByRole('spinbutton',{name:'Number max',exact:true});
    assert.equal(await minimum.inputValue(),'');assert.equal(await maximum.inputValue(),'');
    await minimum.fill('-5');
    await page.waitForFunction(id=>window.ArchHubAPI.getSnapshot().graph.nodes.find(node=>node.id===id).params.min===-5,numberId);
    await maximum.fill('10');
    await page.waitForFunction(id=>window.ArchHubAPI.getSnapshot().graph.nodes.find(node=>node.id===id).params.max===10,numberId);
    await minimum.clear();
    await page.waitForFunction(id=>window.ArchHubAPI.getSnapshot().graph.nodes.find(node=>node.id===id).params.min===null,numberId);
    await maximum.clear();
    await page.waitForFunction(id=>window.ArchHubAPI.getSnapshot().graph.nodes.find(node=>node.id===id).params.max===null,numberId);
    assert.equal(await numberCard.locator('[data-parameter="value"]').count(),1);
    assert.equal(await numberCard.locator('[data-port-row="in"]').count(),0);
    assert.equal(await numberCard.locator('[data-node-result]').count(),0);
    assert.equal(await numberCard.locator('[data-node-status]').filter({hasText:'Done'}).count(),0);
    const linked=await page.evaluate(async source=>{
      const api=window.ArchHubAPI;
      const parameter=await api.addNode('n_number',{x:1040,y:120});
      const input=await api.addNode('n_number',{x:680,y:390});
      await api.connectSockets({from:source,fromPort:'value',to:parameter.id,toPort:'param:value'});
      await api.connectSockets({from:source,fromPort:'value',to:input.id,toPort:'value'});
      await api.setNodeParam(source,'value',7);await api.runNode();
      return [parameter.id,input.id];
    },numberId);
    const wired=await page.evaluate(ids=>ids.map(id=>window.ArchHubAPI.getSnapshot().graph.nodes.find(node=>node.id===id).output.value),linked);
    assert.deepEqual(wired,[7,7]);
    for(const id of linked)assert.equal(await page.locator(`.react-flow__node[data-id="${id}"] [data-node-result]`).count(),1);
    assert.equal(await page.locator('.react-flow__edge').count(),2);
    await capture('library','archhub-current-canvas-full-nodes.svg');
  }

  if(stage==='docs'||stage==='all'){
    await page.getByRole('button',{name:'Docs',exact:true}).click();
    await page.locator('.docs-guide-content').waitFor();
    const data=await page.evaluate(()=>({title:window.ArchHubAPI.getSnapshot().docs.find(page=>page.id==='getting-started').title,pages:window.ArchHubAPI.getSnapshot().docs.length,terms:window.ArchHubAPI.getSnapshot().bookGlossary.length}));
    await page.locator('.docs-article').getByRole('heading',{name:data.title,exact:true}).waitFor();
    assert.equal(await page.getByRole('heading',{name:/No guide matches/}).count(),0);
    const search=page.getByRole('textbox',{name:'Search docs'});
    await search.fill('no-such-guide-designsplit');
    await page.getByRole('heading',{name:/No guide matches/}).waitFor();
    await search.fill('   ');
    await page.locator('.docs-article').getByRole('heading',{name:data.title,exact:true}).waitFor();
    assert.equal(await page.locator('.docs-toc .listbutton').count(),data.pages+2);
    await search.fill('');
    await page.locator('.docs-toc').getByRole('button',{name:/^Glossary/}).click();
    await page.locator('.docs-glossary').waitFor();
    assert.ok(data.terms>0);assert.equal(await page.locator('.docs-glossary dt').count(),data.terms);
    await search.fill('Socket');
    assert.equal(await page.locator('.docs-glossary dt').filter({hasText:/^Socket$/}).count(),1);
    await search.fill('');
    await page.locator('.docs-toc').getByRole('button',{name:data.title,exact:true}).click();
    await page.locator('.docs-guide-content').waitFor();
    await capture('docs','archhub-current-docs.svg');
    metrics.push({name:'docs-data',guide_pages:data.pages,glossary_terms:data.terms});
  }
  const revision=execFileSync('git',['-c','core.fsmonitor=false','rev-parse','HEAD'],{cwd:root,encoding:'utf8',windowsHide:true}).trim();
  const clean=!execFileSync('git',['-c','core.fsmonitor=false','status','--porcelain','--untracked-files=no'],{cwd:root,encoding:'utf8',windowsHide:true}).trim();
  const manifest=require('node:crypto').createHash('sha256').update(fs.readFileSync(path.join(root,'01.APP/nodelang/studio/compiled/manifest.json'))).digest('hex');
  const report={stage,source_revision:revision,tracked_source_clean:clean,browser_version:browser.version(),build_manifest_sha256:manifest,metrics,errors};
  console.log(JSON.stringify(report,null,2));
  for(const screen of ['settings','library','docs']){const scoped=metrics.filter(row=>row.name.startsWith(screen));if(scoped.length)fs.writeFileSync(path.join(proof,screen+'-checks.json'),JSON.stringify({...report,stage:screen,metrics:scoped},null,2));}
  assert.deepEqual(errors,[]);
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();server.kill();});
