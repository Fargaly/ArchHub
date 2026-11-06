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
    const pointer=(type,x,y,pressed=false,button='left')=>inputSession.send('Input.dispatchMouseEvent',{type,x,y,...(type==='mouseMoved'?pressed?{button,buttons:button==='middle'?4:1}:{}:{button,buttons:pressed?button==='middle'?4:1:0,clickCount:1})});
    const key = async (name, code) => {
      await inputSession.send('Input.dispatchKeyEvent',{type:'keyDown',key:name,code:name,windowsVirtualKeyCode:code,...(name==='Enter'?{text:String.fromCharCode(13)}:{})});
      await inputSession.send('Input.dispatchKeyEvent',{type:'keyUp',key:name,code:name,windowsVirtualKeyCode:code});
    };
    const errors = [];
    page.on('pageerror', error => {errors.push(error.message);console.error('PAGEERROR '+error.message);});
    await page.goto(input.url);
    let preview = page.getByRole('complementary',{name:'Properties'});
    await preview.waitFor({timeout:45000}).catch(async error=>{throw Error(error.message+' errors='+JSON.stringify(errors)+' body='+await page.locator('body').innerText());});
    await page.getByRole('button',{name:/Drawing set review/}).first().click();
    await preview.getByRole('heading',{name:'Drawing set review'}).waitFor();

    assert.equal(await page.evaluate(() => localStorage.getItem('archhub.home.layout.v1')),null);
    await page.evaluate(() => document.fonts.ready);
    assert.equal(await page.evaluate(() => [...document.fonts].some(face => face.family === 'Inter' && face.status === 'loaded')),true);
    assert.equal(await page.evaluate(() => window.devicePixelRatio),1);
    console.log('Fonts '+JSON.stringify(await page.evaluate(() => ({dpr:window.devicePixelRatio,faces:[...document.fonts].map(f=>({family:f.family,status:f.status,weight:f.weight})),title:window.getComputedStyle(document.querySelector('.dx-tasks h1')).font}))));
    if (input.polish) {
      if (input.board === 'canvas_fit') return;
      if (input.board === 'workshop') {
        await preview.getByRole('button',{name:'Open task',exact:true}).click();
        await page.getByRole('button',{name:'Workshop view',exact:true}).click();
        await page.getByRole('heading',{name:'Thread activity',exact:true}).waitFor();
      } else if (input.board === 'canvas') {
        await preview.getByRole('button',{name:'Open task',exact:true}).click();
        await page.getByRole('button',{name:'Canvas view',exact:true}).click();
        await page.locator('.react-flow__node[data-id="pdf"]').waitFor();
      } else if (input.board === 'settings') {
        await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Settings',exact:true}).click();
        await page.getByRole('navigation',{name:'Settings categories'}).getByRole('button',{name:'Appearance',exact:true}).click();
        await page.getByRole('combobox',{name:'Theme',exact:true}).waitFor();
        await page.getByText('Reading settings…',{exact:true}).waitFor({state:'hidden'});
      }
      const out=path.resolve('05.EVIDENCE/designpolish',input.board);
      fs.mkdirSync(out,{recursive:true});
      const reference=path.join('C:/Users/fargaly/00.ARCHUB/30.KNOWLEDGE/35.DESIGN-SYSTEM/35.02-APP-DESIGN/01.WIP',input.board==='settings'?'penpot-settings-1680-r1963-native.png':`penpot-${input.board}-r1970-native.png`);
      fs.copyFileSync(reference,path.join(out,'reference.png'));
      for (const size of [{width:1366,height:768},{width:1680,height:893}]) {
        await page.setViewportSize(size);
        await page.evaluate(()=>document.fonts.ready);
        await page.waitForTimeout(300);
        const name=`${size.width}x${size.height}`;
        await page.screenshot({path:path.join(out,`${input.polish}-${name}.png`)});
        const measured=await page.evaluate(()=>{
          const visible=el=>{const r=el.getBoundingClientRect();return r.width>1&&r.height>1&&window.getComputedStyle(el).opacity!=='0'&&window.getComputedStyle(el).visibility!=='hidden'&&window.getComputedStyle(el).display!=='none';};
          const text=[...document.querySelectorAll('body *')].filter(el=>visible(el)&&[...el.childNodes].some(n=>n.nodeType===3&&n.textContent.trim()));
          const small=text.filter(el=>parseFloat(window.getComputedStyle(el).fontSize)<11).map(el=>({text:el.textContent.slice(0,60),size:window.getComputedStyle(el).fontSize,cls:el.className}));
          const rgb=s=>(s.match(/[\d.]+/g)||[]).map(Number);
          const luminance=c=>c.slice(0,3).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
          const secondary=text.filter(el=>{const c=window.getComputedStyle(el).color;return ['--color-ink-soft','--color-ink-muted','--color-ink-dim'].some(name=>{const probe=document.createElement('i');probe.style.color=`var(${name})`;document.body.append(probe);const value=window.getComputedStyle(probe).color;probe.remove();return c===value;});}).map(el=>{
            let ancestor=el,bg;
            while(ancestor){bg=rgb(window.getComputedStyle(ancestor).backgroundColor);if(bg.length<4||bg[3]===1)break;ancestor=ancestor.parentElement;}
            const fg=luminance(rgb(window.getComputedStyle(el).color)),back=luminance(bg||[14,14,17]);
            return {text:el.textContent.slice(0,60),ratio:(Math.max(fg,back)+.05)/(Math.min(fg,back)+.05)};
          });
          const accentRGB=['--color-accent','--color-accent-hi','--color-accent-soft','--color-accent-dim'].map(name=>{const probe=document.createElement('i');probe.style.color=`var(${name})`;document.body.append(probe);const value=window.getComputedStyle(probe).color;probe.remove();return value;});
          const accents=[...document.querySelectorAll('body *')].filter(visible).flatMap(el=>{const css=window.getComputedStyle(el),props=['backgroundColor','borderTopColor','borderRightColor','borderBottomColor','borderLeftColor','outlineColor'];if([...el.childNodes].some(n=>n.nodeType===3&&n.textContent.trim()))props.push('color');const used=props.filter(prop=>accentRGB.includes(css[prop])&&(prop!=='outlineColor'||css.outlineStyle!=='none')&&(!prop.startsWith('border')||parseFloat(css[prop.replace('Color','Width')])>0));return used.length?[{text:el.textContent.slice(0,70),tag:el.tagName,cls:el.getAttribute('class'),properties:used}]:[];});
          const area=document.querySelector('[aria-label="Workflow canvas"]'),panel=document.querySelector('.shared-properties'),box=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom};};
          const canvas=area?{area:box(area),nodes:[...area.querySelectorAll('.react-flow__node')].map(box),viewport:window.ArchHubAPI.getSnapshot().graph.viewport,transform:document.querySelector('.react-flow__viewport')?.style.transform}:null;
          const panelOverflow=panel?[...panel.querySelectorAll('input,textarea,select,.spread,.row')].filter(visible).filter(el=>box(el).right>box(panel).right-15).map(el=>({tag:el.tagName,text:el.textContent.slice(0,40),box:box(el)})):[];
          return {canvas,panelOverflow,small,secondary,accentCount:accents.length,accents,font:{check:document.fonts.check('13px Inter'),body:window.getComputedStyle(document.body).fontFamily,loaded:[...document.fonts].filter(f=>f.family==='Inter').map(f=>({weight:f.weight,status:f.status}))},deliveryUnverified:document.body.innerText.includes('Delivery unverified')};
        });
        fs.writeFileSync(path.join(out,`${input.polish}-${name}.json`),JSON.stringify(measured,null,2)+'\n');
        if(input.polish==='after') {
          const comparison=await context.newPage();
          await comparison.setViewportSize({width:size.width*3,height:size.height+32});
          await comparison.setContent('<body style="margin:0;display:flex;background:#15151a;color:#ece8e0;font:13px sans-serif">'+['reference.png',`before-${name}.png`,`after-${name}.png`].map((file,index)=>`<figure style="margin:0"><figcaption style="height:32px">${['Penpot '+(input.board==='settings'?'r1963 (r1970 unavailable)':'r1970'),'Before','After'][index]}</figcaption><img width="${size.width}" height="${size.height}" src="data:image/png;base64,${fs.readFileSync(path.join(out,file)).toString('base64')}"></figure>`).join(''));
          await comparison.screenshot({path:path.join(out,`comparison-${name}.png`)});
          await comparison.close();
          assert.equal(measured.font.check,true);
          assert.match(measured.font.body,/Inter/);
          assert.deepEqual(measured.small,[],JSON.stringify(measured.small));
          assert.deepEqual(measured.secondary.filter(row=>row.ratio<4.5),[]);
          assert.equal(measured.deliveryUnverified,false);
          if(input.board==='canvas') {
            assert.deepEqual(measured.panelOverflow,[]);
            for(const box of measured.canvas.nodes) assert.ok(box.x>=measured.canvas.area.x+23 && box.right<=measured.canvas.area.right-23 && box.bottom<=measured.canvas.area.bottom-23,JSON.stringify(measured.canvas));
            assert.equal(await page.getByRole('complementary',{name:'Library shelf'}).count(),0);
            assert.equal(await page.getByLabel('Workflow status',{exact:true}).innerText(),'3 complete · 1 out of date');
          }
          assert.equal(await page.locator('h1').count(),1);
          if(input.board!=='settings') {
            const panel=page.getByRole('complementary',{name:'Properties'});
            const actions=panel.locator('.dx-preview-actions');
            if(await actions.count()) {
              const first=await actions.boundingBox();
              await panel.locator('.shared-properties-task').evaluate(el=>el.scrollTop=el.scrollHeight);
              assert.deepEqual(await actions.boundingBox(),first);
              assert.ok(first.y+first.height<=size.height);
              await panel.locator('.shared-properties-task').evaluate(el=>el.scrollTop=0);
            }
          }
        }
        console.log(`${input.polish} ${input.board} ${name}: small=${measured.small.length}, contrastFailures=${measured.secondary.filter(row=>row.ratio<4.5).length}`);
      }
      if(input.board==='canvas' && input.polish==='after') {
        await page.locator('.react-flow__node[data-id="pdf"] [data-node-card-title]').click();
        const swatch=await page.getByLabel('Node colour',{exact:true}).boundingBox();
        assert.equal(swatch.width,20);assert.equal(swatch.height,20);
        const selected=await page.locator('.react-flow__node[data-id="pdf"] [data-ds-node]').evaluate(el=>({outline:parseFloat(window.getComputedStyle(el).outlineWidth),logical:el.style.outlineWidth,offset:window.getComputedStyle(el).outlineOffset}));
        assert.equal(selected.logical,'1.5px');assert.ok(selected.outline>=1&&selected.outline<=1.5);assert.equal(selected.offset,'2px');
        await page.screenshot({path:path.join(out,'selected-1680x893.png')});
      }
      if(input.board==='home' && input.polish==='after') {
        await page.getByRole('button',{name:/Sheet index check/}).first().dblclick();
        await page.getByRole('textbox',{name:'Task title',exact:true}).waitFor();
        assert.equal(await page.getByRole('textbox',{name:'Task title',exact:true}).inputValue(),'Sheet index check');
      }
      if(input.board==='workshop' && input.polish==='after') {
        assert.equal(await page.locator('[data-delivery-attention]:visible').count(),0);
        assert.deepEqual(await page.evaluate(()=>['delivered','sent_unconfirmed','queued','failed','not_delivered'].map(state=>window.UI.deliveryAttention({state}))),['','','Queued','failed','not delivered']);
        assert.equal(await page.evaluate(()=>window.UI.deliveryAttention({live:[{state:'delivered'},{state:'queued'},{state:'failed'}]})),'failed');
      }
      assert.deepEqual(errors,[]);
      return;
    }
    if(input.board==='canvas_fit') {
      await preview.getByRole('button',{name:'Open task',exact:true}).click();
        await page.getByRole('button',{name:'Canvas view',exact:true}).click();
      await page.locator('.react-flow__node[data-id="slice"]').waitFor();
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().sessionDirty===false);
      const area=await page.getByLabel('Workflow canvas',{exact:true}).boundingBox();
      const cards=await page.locator('.react-flow__node').all();
      for(const card of cards) {
        const box=await card.boundingBox();
        assert.ok(box.x>=area.x+10&&box.x+box.width<=area.x+area.width-10,JSON.stringify({box,area}));
        assert.equal(Math.round(box.width),256);
      }
      assert.ok(Number((await page.getByTitle('Reset zoom').innerText()).replace('%',''))>=75);
      assert.ok(Number((await page.getByTitle('Reset zoom').innerText()).replace('%',''))<=100);
      await page.screenshot({path:'05.EVIDENCE/designbuild/canvas/initial-two-nodes.png'});
      await page.getByRole('button',{name:'Zoom in',exact:true}).click();
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().graph.viewport.zoom>1);
      await page.evaluate(()=>window.ArchHubAPI.saveSession());
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().sessionDirty===false);
      const saved=await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.viewport);
      await page.getByRole('button',{name:'Workshop view',exact:true}).click();
      await page.getByRole('button',{name:'Canvas view',exact:true}).click();
      await page.waitForFunction(expected=>{const element=document.querySelector('.react-flow__viewport');if(!element)return false;const matrix=new window.DOMMatrix(window.getComputedStyle(element).transform);return Math.abs(matrix.a-expected.zoom)<0.001&&Math.abs(matrix.e-expected.x)<0.1&&Math.abs(matrix.f-expected.y)<0.1;},saved);
      assert.deepEqual(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.viewport),saved);
      assert.deepEqual(errors,[]);
      console.log('PASS two-node initial frame100% inside canvas; explicit viewport retained across Workshop/Canvas re-entry');
      return;
    }
    const capture = async referenceName => {
    const out = path.resolve('05.EVIDENCE/designbuild',input.board);
    fs.mkdirSync(out,{recursive:true});
    const reference = 'C:/Users/fargaly/00.ARCHUB/30.KNOWLEDGE/35.DESIGN-SYSTEM/35.02-APP-DESIGN/01.WIP/' + referenceName;
    const referenceFile=input.board==='settings'?'penpot-r1963.png':'penpot-r1970.png';
    fs.copyFileSync(reference,path.join(out,referenceFile));
    await page.screenshot({path:path.join(out,'studio.png')});
    const pair = await context.newPage();
    const size=page.viewportSize();
    await pair.setViewportSize({width:size.width*2,height:size.height});
    await pair.setContent('<body style="margin:0;display:flex">'+[referenceFile,'studio.png'].map(name => '<img width="'+size.width+'" height="'+size.height+'" src="data:image/png;base64,'+fs.readFileSync(path.join(out,name)).toString('base64')+'">').join(''));
    await pair.screenshot({path:path.join(out,'comparison.png')});
    await pair.close();
    const sha=file=>require('node:crypto').createHash('sha256').update(fs.readFileSync(file)).digest('hex');
    fs.writeFileSync(path.join(out,'evidence.json'),JSON.stringify({board:input.board,penpotFile:'751e8d0c-7080-8124-8008-d8e6f6eedbb6',referenceRevision:input.board==='settings'?1963:1970,referenceSha256:sha(reference),viewport:page.viewportSize(),compiledManifestSha256:sha('01.APP/nodelang/studio/compiled/manifest.json'),profile:'real isolated temporary owners',installedVerified:false,observedNodeMode:input.board==='canvas'?'full':'not applicable',openItems:input.board==='canvas'?['Compact primary cards are concept references; full NodeCard controls retained.','PDF output contract reconciliation remains with R&D; only current engine-declared sockets rendered.']:[]},null,2)+'\n');
    };
    if(input.board==='settings') {
      await page.setViewportSize({width:1680,height:893});
      await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Settings',exact:true}).click();
      await page.getByRole('navigation',{name:'Settings categories'}).getByRole('button',{name:'Appearance',exact:true}).click();
      await page.getByRole('combobox',{name:'Theme',exact:true}).waitFor();
      await page.getByText('Reading settings…',{exact:true}).waitFor({state:'hidden'});
      const geometry=await page.evaluate(()=>{const box=s=>{const r=document.querySelector(s).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};};return {page:box('.settings-sheet'),header:box('.settings-sheet>header'),categories:box('.sheet-tabs'),content:box('.sheet-content')};});
      assert.deepEqual(geometry.header,{x:64,y:48,width:1616,height:92});
      assert.deepEqual(geometry.categories,{x:64,y:140,width:278,height:753});
      assert.equal(await page.title(),'ArchHub · Settings');
      await capture('penpot-settings-1680-r1963-native.png');
      await page.getByRole('button',{name:'Show advanced',exact:true}).click();
      await page.getByRole('spinbutton',{name:'Row spacing',exact:true}).fill('8');
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().settings.find(row=>row.id==='Appearance.Row spacing').value===8);
      await page.getByRole('spinbutton',{name:'Node radius',exact:true}).fill('12');
      await page.getByRole('spinbutton',{name:'Text scale',exact:true}).fill('150');
      await page.waitForFunction(()=>window.getComputedStyle(document.querySelector('.settings-sheet h1')).fontSize==='42px');
      for(const size of [{width:1680,height:893},{width:1366,height:768},{width:800,height:500}]) {
        await page.setViewportSize(size);
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),size.width);
        const clipped=await page.locator('.sheet-content').evaluate(el=>el.scrollWidth>el.clientWidth);
        if(clipped) await page.screenshot({path:'.cache/designbuild/settings-overflow.png'});
        assert.equal(clipped,false,JSON.stringify(await page.locator('.sheet-content').evaluate(el=>({width:el.clientWidth,scroll:el.scrollWidth,offenders:[...el.querySelectorAll('*')].filter(child=>child.getBoundingClientRect().right>el.getBoundingClientRect().right).map(child=>({tag:child.tagName,cls:child.className,text:child.textContent.slice(0,80),width:child.getBoundingClientRect().width})).slice(0,10)}))));
      }
      await page.getByRole('spinbutton',{name:'Text scale',exact:true}).fill('100');
      await page.getByRole('combobox',{name:'Theme',exact:true}).selectOption('Light');
      await page.waitForFunction(()=>document.documentElement.dataset.theme==='Light');
      await page.getByRole('combobox',{name:'Theme',exact:true}).selectOption('Dark');
      await page.waitForFunction(()=>document.documentElement.dataset.theme==='Dark');
      await page.close();page=await context.newPage();await page.goto(input.url);
      await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Settings',exact:true}).click();
      await page.getByRole('navigation',{name:'Settings categories'}).getByRole('button',{name:'Appearance',exact:true}).click();
      await page.getByRole('button',{name:'Show advanced',exact:true}).click();
      assert.equal(await page.getByRole('spinbutton',{name:'Row spacing',exact:true}).inputValue(),'8');
      assert.equal(await page.getByRole('spinbutton',{name:'Node radius',exact:true}).inputValue(),'12');
      await page.getByRole('button',{name:'Changed only',exact:true}).click();
      assert.equal(await page.getByRole('combobox',{name:'Theme',exact:true}).count(),0);
      await page.getByRole('button',{name:'Changed only',exact:true}).click();
      await page.getByRole('button',{name:'Reset Appearance',exact:true}).click();
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().settings.find(row=>row.id==='Appearance.Row spacing').value===4);
      await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Home',exact:true}).click();
      preview=page.getByRole('complementary',{name:'Properties'});
      await page.getByRole('button',{name:/Drawing set review/}).first().click();
      console.log('PASS Settings separate page, source1680 geometry, scale150 three widths, density/radius close/reopen and Reset');
    }
    const sharedHeader=()=>page.locator('.shared-properties-head').boundingBox();
    const homeHeader=await sharedHeader();
    const homeScope=await preview.locator('.dx-edit-field').filter({has:page.locator('summary>span:first-child').filter({hasText:/^Scope$/})}).boundingBox();
    if(input.board === 'workshop') {
      await preview.getByRole('button',{name:'Open task',exact:true}).click();
        await page.getByRole('button',{name:'Workshop view',exact:true}).click();
      await page.getByRole('heading',{name:'Thread activity',exact:true}).waitFor();
      await page.waitForFunction(() => window.ArchHubAPI.getSnapshot().sessionDirty === false).catch(async error => {throw Error(error.message+' state='+JSON.stringify(await page.evaluate(() => {const s=window.ArchHubAPI.getSnapshot();return {dirty:s.sessionDirty,sync:s.sync,notice:s.connectionNotice,last:s.lastResult};})));});
      assert.match(await page.locator('.dx-session-meta').innerText(), /Saved$/);
      preview=page.getByRole('region',{name:'Task parameters',exact:true});
      await page.getByRole('complementary',{name:'Threads',exact:true}).waitFor();
      assert.equal((await sharedHeader()).x,homeHeader.x);
      assert.equal((await sharedHeader()).width,homeHeader.width);
      const scope=await preview.locator('.dx-edit-field').filter({has:page.locator('summary>span:first-child').filter({hasText:/^Scope$/})}).boundingBox();
      assert.equal(scope.x,homeScope.x);
      const progress=preview.locator('.dx-plan-summary');
      await progress.locator('summary').focus();await key('Enter',13);
      assert.equal(await progress.locator('li').count(),3);
      assert.equal(await progress.locator('li[data-step="done"]').count(),2);
      assert.equal(await progress.getByRole('textbox').count(),0);
      await progress.locator('summary').press('Enter');
      assert.equal(await preview.locator('[data-dx-list="References"] .dx-edit-label').innerText(),'Edit');

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
      return {rail:box('nav[aria-label="Main navigation"]'), list:box('.dx-tasks'),properties:box('.dx-home-preview'),title:box('.dx-tasks h1'),font:window.getComputedStyle(document.querySelector('.dx-tasks')).fontFamily};
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
      await preview.getByRole('button',{name:'Open task',exact:true}).click();
        await page.getByRole('button',{name:'Canvas view',exact:true}).click();
      await page.locator('.react-flow__node[data-id="slice"]').waitFor();
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().sessionDirty===false);
      const cleanSession=await page.evaluate(()=>({id:window.ArchHubAPI.getSnapshot().graph.id,path:window.ArchHubAPI.getSnapshot().sessionFile}));

      await page.waitForFunction(()=>document.title==='ArchHub · Canvas');
      assert.ok(Number((await page.getByTitle('Reset zoom').innerText()).replace('%',''))>=75);
      assert.ok(Number((await page.getByTitle('Reset zoom').innerText()).replace('%',''))<=100);
      assert.equal(await page.locator('.react-flow__node[data-id="slice"] [data-ds-node]').evaluate(el=>el.offsetWidth),256);
      const initial=await page.locator('.react-flow__node[data-id="list"]').boundingBox();
      const canvasBounds=await page.getByLabel('Workflow canvas',{exact:true}).boundingBox();
      assert.ok(initial.x>=canvasBounds.x&&initial.x+initial.width<=canvasBounds.x+canvasBounds.width);
      await page.screenshot({path:'05.EVIDENCE/designbuild/canvas/initial.png'});
      await page.getByRole('button',{name:'Fit',exact:true}).click();
      await page.evaluate(()=>window.ArchHubAPI.saveSession());
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().sessionDirty===false);

      const pane=page.locator('[data-properties-pane]');
      const bounds=()=>pane.boundingBox();
      assert.deepEqual(await bounds(),{x:1046,y:87,width:320,height:681});
      await page.waitForFunction(()=>[...document.querySelectorAll('[role=tab]')].find(tab=>tab.textContent==='Selection')?.getAttribute('aria-selected')==='true');
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
          await page.waitForFunction(()=>[...document.querySelectorAll('[role=tab]')].find(tab=>tab.textContent==='Selection')?.getAttribute('aria-selected')==='true');
        }
      }
      assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().sessionDirty),false);
      assert.deepEqual(await page.evaluate(()=>({id:window.ArchHubAPI.getSnapshot().graph.id,path:window.ArchHubAPI.getSnapshot().sessionFile})),cleanSession);
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
      const number=inspector.getByRole('spinbutton',{name:'Review first sheets count',exact:true});
      assert.ok((await number.boundingBox()).width>100);
      await number.fill('4');
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
      await page.waitForFunction(()=>new window.DOMMatrix(window.getComputedStyle(document.querySelector('.react-flow__viewport')).transform).a===1);
      await page.locator('[data-node-inspector="slice"]').waitFor();
      assert.equal(await page.getByRole('tab',{name:'Selection',exact:true}).getAttribute('aria-selected'),'true');
      assert.equal(await page.getByRole('region',{name:'Task parameters',exact:true}).count(),0);
      const selectedBox=await node.boundingBox(),area=await page.getByLabel('Workflow canvas',{exact:true}).boundingBox();
      const start={x:area.x+area.width*.6,y:area.y+area.height-80},shift=96-selectedBox.x;
      await pointer('mouseMoved',start.x,start.y);
      await pointer('mousePressed',start.x,start.y,true,'middle');
      await pointer('mouseMoved',start.x+shift,start.y,true,'middle');
      await page.waitForFunction(()=>document.querySelector('.react-flow__node[data-id="slice"]').getBoundingClientRect().x>=64);
      await pointer('mouseReleased',start.x+shift,start.y,false,'middle');
      await page.waitForFunction(()=>document.querySelector('.react-flow__node[data-id="slice"]').getBoundingClientRect().x>=64);

      await page.evaluate(()=>window.ArchHubAPI.saveSession());
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().sessionDirty===false);
      await capture('penpot-canvas-r1970-native.png');
      await page.evaluate(()=>window.ArchHubAPI.setSetting('Appearance.Theme','Light'));
      await page.waitForFunction(()=>window.getComputedStyle(document.querySelector('.react-flow__node[data-id="count"] [data-ds-node]')).backgroundColor==='rgb(251, 249, 244)');
      await page.evaluate(()=>window.ArchHubAPI.setSetting('Appearance.Theme','Dark'));
      await page.waitForFunction(()=>window.getComputedStyle(document.querySelector('.react-flow__node[data-id="count"] [data-ds-node]')).backgroundColor==='rgb(21, 21, 26)');
      await page.evaluate(()=>window.ArchHubAPI.setSetting('Appearance.Row spacing',8));
      await page.waitForFunction(()=>window.getComputedStyle(document.documentElement).getPropertyValue('--layout-node-row-gap').trim()==='8px');
      const splitter=page.getByRole('separator',{name:'Resize the Properties pane',exact:true});
      const box=await splitter.boundingBox();
      await pointer('mouseMoved',box.x+box.width/2,box.y+box.height/2);
      await pointer('mousePressed',box.x+box.width/2,box.y+box.height/2,true);await pointer('mouseMoved',box.x+box.width/2-80,box.y+box.height/2,true);await pointer('mouseReleased',box.x+box.width/2-80,box.y+box.height/2);
      await page.waitForFunction(()=>Math.abs(window.ArchHubAPI.getSnapshot().settings.find(r=>r.id==='Appearance.Inspector width').value-400)<=5);
      await page.getByRole('button',{name:'Workshop view',exact:true}).click();
      await page.waitForFunction(()=>Math.abs(document.querySelector('[data-properties-pane]').getBoundingClientRect().width-400)<=1);
      await page.getByRole('button',{name:'Canvas view',exact:true}).click();
      await page.waitForFunction(()=>[...document.querySelectorAll('[role=tab]')].find(tab=>tab.textContent==='Selection')?.getAttribute('aria-selected')==='true');
      await page.waitForFunction(()=>Math.abs(document.querySelector('[data-properties-pane]').getBoundingClientRect().width-400)<=1);
      await page.getByRole('tab',{name:'Task',exact:true}).click();
      await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Home',exact:true}).click();
      await page.waitForFunction(()=>Math.abs(document.querySelector('[data-properties-pane]').getBoundingClientRect().width-400)<=1);
      await page.getByRole('complementary',{name:'Properties'}).getByRole('button',{name:'Open task',exact:true}).click();
      await page.getByRole('button',{name:'Workshop view',exact:true}).click();
      await page.getByRole('heading',{name:'Thread activity',exact:true}).waitFor();
      preview=page.getByRole('region',{name:'Task parameters',exact:true});
    }
    if(input.board==='home') {
      const plan=preview.locator('.dx-plan-summary');
      await plan.locator('summary').focus();await key('Tab',9);
      assert.equal(await page.getByRole('button',{name:'Open task',exact:true}).evaluate(el=>el===document.activeElement),true);
      assert.equal((await sharedHeader()).x,homeHeader.x);
      assert.equal((await sharedHeader()).width,homeHeader.width);
      await key('Enter',13);
      await page.getByRole('button',{name:'Canvas view',exact:true}).click();
      await page.locator('[data-screen=canvas]').waitFor();
      await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Home',exact:true}).click();
      preview=page.getByRole('complementary',{name:'Properties'});
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
    const savedViewport=input.board==='canvas'?await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.viewport):null;
    await page.close();
    page = await context.newPage();
    page.on('pageerror', error => {errors.push(error.message);console.error('PAGEERROR '+error.message);});
    await page.goto(input.url);
    preview = page.getByRole('complementary',{name:'Properties'});
    await preview.waitFor();
    await page.getByRole('button',{name:/Drawing set review/}).first().click();
    if(input.board==='workshop'||input.board==='canvas'){await preview.getByRole('button',{name:'Open task',exact:true}).click();
        await page.getByRole('button',{name:'Workshop view',exact:true}).click();preview=page.getByRole('region',{name:'Task parameters',exact:true});}
    await preview.getByText('Review the current issue',{exact:true}).waitFor();

    if(input.board==='canvas') {
      await page.getByRole('button',{name:'Canvas view',exact:true}).click();
      assert.ok(Math.abs((await page.locator('[data-properties-pane]').boundingBox()).width-400)<=5);
      const saved=await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.nodes.find(n=>n.id==='slice'));
      assert.deepEqual(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.viewport),savedViewport);
      assert.equal(saved.title,'Review first sheets');assert.equal(saved.color,'#743b27');assert.equal(saved.icon,'docs');
      assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().settings.find(row=>row.id==='Appearance.Row spacing').value),8);
      assert.equal(await page.evaluate(()=>window.getComputedStyle(document.documentElement).getPropertyValue('--layout-node-row-gap').trim()),'8px');
      await page.evaluate(()=>window.dispatchEvent(new CustomEvent('archhub:open-task',{detail:{task_id:'unknown'}})));
      assert.equal(await page.locator('[data-screen=canvas]').count(),1);
    }
    if(input.board==='home') assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().settings.find(row=>row.id==='Appearance.Inspector width').value),391);
    if(input.board==='settings') {
      const task=await page.evaluate(()=>window.ArchHubAPI.getSnapshot().tasks.find(task=>task.title==='Sheet index check'));
      const opens=[];
      page.on('request',request=>{try{const body=request.postDataJSON();if(body?.function==='openTaskGraph')opens.push(body.args[0]);}catch{}});
      await page.evaluate(id=>window.dispatchEvent(new CustomEvent('archhub:open-task',{detail:{task_id:id}})),task.id);
      await page.getByRole('textbox',{name:'Task title',exact:true}).waitFor();
      await page.waitForFunction(()=>document.querySelector('input[aria-label="Task title"]')?.value==='Sheet index check');
      assert.deepEqual(opens,[task.id]);
      const session=await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.id);
      await page.evaluate(()=>window.dispatchEvent(new CustomEvent('archhub:open-task',{detail:{task_id:'missing-task'}})));
      await page.getByRole('alert').filter({hasText:/task/i}).waitFor();
      assert.deepEqual(opens,[task.id,'missing-task']);
      assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.id),session);
      assert.equal(await page.getByRole('textbox',{name:'Task title',exact:true}).inputValue(),'Sheet index check');
      const nav=page.getByRole('navigation',{name:'Main navigation'});
      await nav.getByRole('button',{name:'Settings',exact:true}).click();
      await page.getByRole('button',{name:'Back to task',exact:true}).click();
      await page.getByRole('textbox',{name:'Task title',exact:true}).waitFor();
      assert.equal(await page.getByRole('textbox',{name:'Task title',exact:true}).inputValue(),'Sheet index check');
      assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.id),session);
      await nav.getByRole('button',{name:'Docs',exact:true}).click();
      await page.waitForFunction(()=>document.querySelector('nav[aria-label="Main navigation"] button[aria-current="page"]')?.textContent==='Docs');
      await nav.getByRole('button',{name:'Settings',exact:true}).click();
      await page.getByRole('button',{name:'Back to task',exact:true}).click();
      assert.equal(await nav.getByRole('button',{name:'Docs',exact:true}).getAttribute('aria-current'),'page');
      assert.deepEqual(opens,[task.id,'missing-task']);
      console.log('PASS native task event: one owner request per event after rebinds; known opens exact task, unknown reports and preserves session');
    }
    assert.deepEqual(errors,[]);
    console.log('PASS '+input.board+': real owner edits saved, page closed/reopened, geometry and computed plan checked');
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
