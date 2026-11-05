// Native compiled Studio and the real isolated owners; no UI/API substitutions.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');

(async () => {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const shell = fs.readdirSync(input.browserCache).filter(n => /^chromium_headless_shell-\d+$/.test(n)).sort((a,b) => Number(b.split('-').at(-1))-Number(a.split('-').at(-1)))[0];
  const full=fs.readdirSync(input.browserCache).filter(name=>/^chromium-\d+$/.test(name)).sort((a,b)=>Number(b.split('-').at(-1))-Number(a.split('-').at(-1)))[0];
  const executablePath=path.join(input.browserCache,shell || full, shell ? 'chrome-headless-shell-win64/chrome-headless-shell.exe' : 'chrome-win64/chrome.exe');
  const browser = await chromium.launch({headless:true, executablePath});
  try {
    const context = await browser.newContext({viewport:{width:1366,height:768}});
    await context.addCookies([{name:'archhub_studio',value:input.cookie,url:input.url}]);
    let page = await context.newPage();
    // CDP input is confined to this headless page; it never uses the desktop pointer.
    const inputSession=await context.newCDPSession(page);
    const pointer=(type,x,y,pressed=false)=>inputSession.send('Input.dispatchMouseEvent',{type,x,y,...(type==='mouseMoved'?pressed?{button:'left',buttons:1}:{}:{button:'left',buttons:pressed?1:0,clickCount:1})});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(input.url);
    let preview = page.getByRole('complementary',{name:'Properties'});
    await preview.waitFor({timeout:45000});
    await page.getByRole('button',{name:/Drawing set review/}).first().click();
    await preview.getByRole('heading',{name:'Drawing set review'}).waitFor();

    assert.equal(await page.evaluate(() => localStorage.getItem('archhub.home.layout.v1')),null);
    await page.evaluate(() => document.fonts.ready);
    assert.equal(await page.evaluate(() => [...document.fonts].some(face => face.family === 'Inter' && face.status === 'loaded')),true);
    assert.equal(await page.evaluate(() => window.devicePixelRatio),1);
    console.log('Fonts '+JSON.stringify(await page.evaluate(() => ({dpr:window.devicePixelRatio,faces:[...document.fonts].map(f=>({family:f.family,status:f.status,weight:f.weight})),title:window.getComputedStyle(document.querySelector('.dx-tasks h2')).font}))));
    const capture = async referenceName => {
    const out = path.resolve('05.EVIDENCE/designbuild',input.board);
    fs.mkdirSync(out,{recursive:true});
    const reference = 'C:/Users/fargaly/00.ARCHUB/30.KNOWLEDGE/35.DESIGN-SYSTEM/35.02-APP-DESIGN/01.WIP/' + referenceName;
    const referenceFile='penpot-r1970.png';
    fs.copyFileSync(reference,path.join(out,referenceFile));
    await page.screenshot({path:path.join(out,'studio.png')});
    const pair = await context.newPage();
    await pair.setViewportSize({width:2732,height:768});
    await pair.setContent('<body style="margin:0;display:flex">'+[referenceFile,'studio.png'].map(name => '<img width="1366" height="768" src="data:image/png;base64,'+fs.readFileSync(path.join(out,name)).toString('base64')+'">').join(''));
    await pair.screenshot({path:path.join(out,'comparison.png')});
    await pair.close();
    const sha=file=>require('node:crypto').createHash('sha256').update(fs.readFileSync(file)).digest('hex');
    fs.writeFileSync(path.join(out,'evidence.json'),JSON.stringify({board:input.board,penpotFile:'751e8d0c-7080-8124-8008-d8e6f6eedbb6',referenceRevision:1970,referenceSha256:sha(reference),viewport:page.viewportSize(),compiledManifestSha256:sha('01.APP/nodelang/studio/compiled/manifest.json'),profile:'real isolated temporary owners',installedVerified:false,observedNodeMode:input.board==='canvas'?'full':'not applicable',openItems:input.board==='canvas'?['Compact primary cards are concept references; full NodeCard controls retained.','PDF output contract reconciliation remains with R&D; only current engine-declared sockets rendered.']:[]},null,2)+'\n');
    };
    if(input.board === 'workshop') {
      await preview.getByRole('button',{name:'Open Workshop',exact:true}).click();
      await page.getByRole('heading',{name:'Thread activity',exact:true}).waitFor();
      await page.waitForFunction(() => window.ArchHubAPI.getSnapshot().sessionDirty === false).catch(async error => {throw Error(error.message+' state='+JSON.stringify(await page.evaluate(() => {const s=window.ArchHubAPI.getSnapshot();return {dirty:s.sessionDirty,sync:s.sync,notice:s.connectionNotice,last:s.lastResult};})));});
      assert.match(await page.locator('.dx-session-meta').innerText(), /Saved$/);
      preview=page.getByRole('region',{name:'Task parameters',exact:true});
      await page.getByRole('complementary',{name:'Threads',exact:true}).waitFor();
      const geometry=await page.evaluate(() => {
        const box = selector => {const r=document.querySelector(selector).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};};
        return {params:box('#params'),composer:box('.dx-composer'),conversation:box('[data-dx="conversation"]')};
      });
      assert.ok(geometry.params.x > geometry.conversation.x + geometry.conversation.width);
      assert.ok(geometry.composer.height <= 100);
      await capture('penpot-workshop-r1970-native.png');
      console.log('PASS Workshop layout: '+JSON.stringify(geometry));
      const session=await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.id);
      await page.getByRole('button',{name:'Handoff map',exact:true}).click();
      await page.locator('[data-screen=canvas]').first().waitFor();
      assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.id),session);
      await page.getByRole('button',{name:'Workshop view',exact:true}).click();
    } else if(input.board === 'home') {
      await capture('penpot-home-r1970-native.png');
    const bounds = await page.evaluate(() => {
      const box = selector => {const r=document.querySelector(selector).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};};
      return {rail:box('nav[aria-label="Main navigation"]'), list:box('.dx-tasks'),properties:box('.dx-home-preview'),title:box('.dx-tasks h2'),font:window.getComputedStyle(document.querySelector('.dx-tasks')).fontFamily};
    });
    console.log(JSON.stringify(bounds));
    assert.equal(bounds.rail.width,64);
    assert.equal(bounds.properties.x,1046);
    assert.equal(bounds.properties.width,320);
    assert.equal(bounds.properties.y,87);
    assert.equal(await preview.getByText('Drawing set review.archhub',{exact:true}).count(),1);
    assert.equal(await page.locator('.dx-task').filter({has:page.locator('b',{hasText:'Drawing set review'})}).locator('span').first().innerText(),'Drawing coordinator');
    assert.equal(await page.getByText('Accept edits',{exact:true}).count(),0);
    assert.equal(await preview.getByText('2 of 3 steps complete',{exact:true}).count(),1);
    }
    if(input.board === 'canvas') {
      await preview.getByRole('button',{name:'Open workflow',exact:true}).click();
      await page.locator('.react-flow__node[data-id="slice"]').waitFor();
      await page.waitForFunction(()=>document.title==='ArchHub · Canvas');
      assert.equal(await page.getByTitle('Reset zoom').innerText(),'100%');
      assert.equal(Math.round((await page.locator('.react-flow__node[data-id="slice"]').boundingBox()).width),304);
      await page.getByRole('button',{name:'Fit',exact:true}).click();
      const pane=page.locator('[data-properties-pane]');
      const bounds=()=>pane.boundingBox();
      assert.deepEqual(await bounds(),{x:1046,y:87,width:320,height:681});
      await page.waitForFunction(()=>[...document.querySelectorAll('[role=tab]')].find(tab=>tab.textContent==='Task')?.getAttribute('aria-selected')==='true');
      const node=page.locator('.react-flow__node[data-id="slice"]');
      assert.deepEqual(await node.locator('[data-node-card-title]').evaluate(el=>{const s=window.getComputedStyle(el);return [s.fontSize,s.fontWeight];}),['15px','600']);
      assert.equal(await node.locator('[data-ds-node]').evaluate(el=>window.getComputedStyle(el).backgroundColor),'rgb(21, 21, 26)');
      for(const viewport of [{width:1366,height:768},{width:1680,height:893}]) {
        await page.setViewportSize(viewport);
        const expected={x:viewport.width-320,y:87,width:320,height:viewport.height-87};
        const stable=await bounds();
        for(const key of Object.keys(expected)) assert.ok(Math.abs(stable[key]-expected[key])<0.05,JSON.stringify({stable,expected}));
        const toolbar=await page.locator('.dx-task-toolbar').boundingBox();
        for(let i=0;i<10;i++) {
          await node.locator('[data-node-card-title]').click();await page.locator('[data-node-inspector="slice"]').waitFor();
          assert.deepEqual(await bounds(),stable);
          const point=await page.locator('[data-graph-wire="first"]').evaluate(path=>{const p=path.getPointAtLength(path.getTotalLength()/2),q=new window.DOMPoint(p.x,p.y).matrixTransform(path.getScreenCTM());return {x:q.x,y:q.y};});
          await pointer('mousePressed',point.x,point.y,true);await pointer('mouseReleased',point.x,point.y);
          await page.locator('[data-wire-inspection]').waitFor();
          assert.deepEqual(await bounds(),stable);
          assert.deepEqual(await page.locator('.dx-task-toolbar').boundingBox(),toolbar);
          await page.locator('.react-flow__pane').click({position:{x:12,y:12}});
          await page.waitForFunction(()=>[...document.querySelectorAll('[role=tab]')].find(tab=>tab.textContent==='Task')?.getAttribute('aria-selected')==='true');
        }
      }
      await page.setViewportSize({width:1366,height:768});
      await node.locator('[data-node-card-title]').click();
      const inspector=page.locator('[data-node-inspector="slice"]');
      await inspector.getByRole('textbox',{name:'Node label',exact:true}).fill('Review first sheets');
      await inspector.getByRole('textbox',{name:'Node label',exact:true}).press('Tab');
      await inspector.getByLabel('Node icon',{exact:true}).selectOption('docs');
      await assert.rejects(()=>page.evaluate(()=>window.ArchHubAPI.setNodePresentation('slice',{color:'red'})),/six-digit/);
      await assert.rejects(()=>page.evaluate(()=>window.ArchHubAPI.setNodePresentation('slice',[])),/six-digit/);
      await inspector.getByLabel('Node colour',{exact:true}).fill('#743b27');
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().graph.nodes.find(n=>n.id==='slice')?.color==='#743b27');
      assert.equal(await inspector.locator('[data-linked-source]').count(),1);
      assert.ok(await node.locator('[data-parameter="count"] input[type="number"]').count()>0);
      assert.equal(await node.locator('[data-parameter="items"] input').count(),0);
      await node.locator('[data-parameter="count"] input').fill('4');
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().graph.nodes.find(n=>n.id==='count').output?.count===4);
      await page.getByRole('button',{name:'More canvas actions',exact:true}).click();
      await page.getByRole('menuitem',{name:'Undo · Ctrl Z',exact:true}).click();
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().graph.nodes.find(n=>n.id==='slice').params.count==='3');
      await page.getByRole('button',{name:'More canvas actions',exact:true}).click();
      await page.getByRole('menuitem',{name:'Redo · Ctrl Shift Z',exact:true}).click();
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().graph.nodes.find(n=>n.id==='count').output?.count===4);
      for(const [color,ink] of [['#ffffff','rgb(0, 0, 0)'],['#000000','rgb(255, 255, 255)']]) {
        await inspector.getByLabel('Node colour',{exact:true}).fill(color);
        await page.waitForFunction(({color,ink})=>{const node=document.querySelector('.react-flow__node[data-id="slice"] .node-header');return window.ArchHubAPI.getSnapshot().graph.nodes.find(n=>n.id==='slice').color===color&&window.getComputedStyle(node).color===ink;},{color,ink});
      }
      await inspector.getByLabel('Node colour',{exact:true}).fill('#743b27');
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().graph.nodes.find(n=>n.id==='slice').color==='#743b27');

      const pdf=page.locator('.react-flow__node[data-id="pdf"]');
      await pdf.locator('[data-parameter="folder"] input').fill('issued');
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().graph.nodes.find(n=>n.id==='pdf').status==='Out of date');
      await page.getByRole('button',{name:'Add node',exact:true}).click();
      const shelf=await page.getByRole('complementary',{name:'Library shelf'}).boundingBox();
      assert.ok(shelf.x+shelf.width < (await bounds()).x);
      await page.getByRole('button',{name:'Close Library',exact:true}).click();
      await page.getByRole('complementary',{name:'Library shelf'}).waitFor({state:'hidden'});
      await node.locator('[data-node-card-title]').click();
      await page.getByTitle('Reset zoom').click();
      await page.locator('[data-node-inspector="slice"]').waitFor();
      assert.equal(await page.getByRole('tab',{name:'Selection',exact:true}).getAttribute('aria-selected'),'true');
      await capture('penpot-canvas-r1970-native.png');
      const splitter=page.getByRole('separator',{name:'Resize the Properties pane',exact:true});
      const box=await splitter.boundingBox();
      await pointer('mouseMoved',box.x+box.width/2,box.y+box.height/2);
      await pointer('mousePressed',box.x+box.width/2,box.y+box.height/2,true);await pointer('mouseMoved',box.x+box.width/2-80,box.y+box.height/2,true);await pointer('mouseReleased',box.x+box.width/2-80,box.y+box.height/2);
      await page.waitForFunction(()=>Math.abs(window.ArchHubAPI.getSnapshot().settings.find(r=>r.id==='Appearance.Inspector width').value-400)<=5);
      await page.getByRole('button',{name:'Workshop view',exact:true}).click();
      await page.waitForFunction(()=>Math.abs(document.querySelector('[data-properties-pane]').getBoundingClientRect().width-400)<=1);
      await page.getByRole('button',{name:'Canvas view',exact:true}).click();
      await page.waitForFunction(()=>[...document.querySelectorAll('[role=tab]')].find(tab=>tab.textContent==='Task')?.getAttribute('aria-selected')==='true');
      await page.waitForFunction(()=>Math.abs(document.querySelector('[data-properties-pane]').getBoundingClientRect().width-400)<=1);
      await page.getByRole('tab',{name:'Task',exact:true}).click();
      await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Home',exact:true}).click();
      await page.waitForFunction(()=>Math.abs(document.querySelector('[data-properties-pane]').getBoundingClientRect().width-400)<=1);
      await page.getByRole('complementary',{name:'Properties'}).getByRole('button',{name:'Open Workshop',exact:true}).click();
      await page.getByRole('heading',{name:'Thread activity',exact:true}).waitFor();
      preview=page.getByRole('region',{name:'Task parameters',exact:true});
    }
    for(const [label,value] of [['Scope','Review the current issue'],['Rules','Review every sheet before export'],['References','Current drawing index'],['Folders','Dated issue folder renamed']]) {
      const field=preview.locator('details').filter({has:page.locator('summary>span:first-child').filter({hasText:new RegExp('^'+label+'$')})});
      await field.locator('summary').click();
      await field.getByRole('textbox').fill(value);
      await field.getByRole('textbox').press('Tab');
      await page.waitForFunction(() => !document.querySelector('[role="status"]')?.textContent?.includes('Saving'));
      await field.locator('summary').click();
    }
    if(input.board==='home') {
      await page.evaluate(()=>localStorage.setItem('archhub.home.layout.v1',JSON.stringify({inner:{params:30,main:70}})));
      await page.reload();
      await page.waitForFunction(()=>window.ArchHubAPI?.getSnapshot().settings.find(row=>row.id==='Appearance.Inspector width')?.value===391);
      assert.equal(await page.evaluate(()=>localStorage.getItem('archhub.home.layout.v1')),null);
    }
    await page.close();
    page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(input.url);
    preview = page.getByRole('complementary',{name:'Properties'});
    await preview.waitFor();
    await page.getByRole('button',{name:/Drawing set review/}).first().click();
    if(input.board==='workshop'||input.board==='canvas'){await preview.getByRole('button',{name:'Open Workshop',exact:true}).click();preview=page.getByRole('region',{name:'Task parameters',exact:true});}
    await preview.getByText('Review the current issue',{exact:true}).waitFor();

    if(input.board==='canvas') {
      await page.getByRole('button',{name:'Canvas view',exact:true}).click();
      assert.ok(Math.abs((await page.locator('[data-properties-pane]').boundingBox()).width-400)<=5);
      const saved=await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.nodes.find(n=>n.id==='slice'));
      assert.equal(saved.title,'Review first sheets');assert.equal(saved.color,'#743b27');assert.equal(saved.icon,'docs');
      await page.evaluate(()=>window.dispatchEvent(new CustomEvent('archhub:open-task',{detail:{task_id:'unknown'}})));
      assert.equal(await page.locator('[data-screen=canvas]').count(),1);
    }
    if(input.board==='home') assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().settings.find(row=>row.id==='Appearance.Inspector width').value),391);
    assert.deepEqual(errors,[]);
    console.log('PASS '+input.board+': real owner edits saved, page closed/reopened, geometry and computed plan checked');
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
