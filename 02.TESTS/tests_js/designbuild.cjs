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
    const assertReadable=async label=>{
      const measured=await page.evaluate(()=>{
        const visible=el=>{const r=el.getBoundingClientRect();return r.width>1&&r.height>1&&!el.closest('[hidden]')&&window.getComputedStyle(el).visibility!=='hidden'&&window.getComputedStyle(el).display!=='none';};
        const text=[...document.querySelectorAll('body *')].filter(el=>visible(el)&&[...el.childNodes].some(n=>{if(n.nodeType!==3||!n.textContent.trim())return false;const range=document.createRange();range.selectNodeContents(n);const box=range.getBoundingClientRect();return box.width>0&&box.height>0;}));
        const small=text.filter(el=>parseFloat(window.getComputedStyle(el).fontSize)<11).map(el=>({text:el.textContent.slice(0,60),size:window.getComputedStyle(el).fontSize}));
        const rgb=s=>(s.match(/[\d.]+/g)||[]).map(Number);
        const luminance=c=>c.slice(0,3).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
        const colors=['--color-ink-soft','--color-ink-muted','--color-ink-dim'].map(name=>{const probe=document.createElement('i');probe.style.color=`var(${name})`;document.body.append(probe);const color=window.getComputedStyle(probe).color;probe.remove();return color;});
        const secondary=text.filter(el=>colors.includes(window.getComputedStyle(el).color)||el.matches('[data-custom-header] [data-node-card-title],[data-custom-header] [data-node-card-subtitle]')).map(el=>{
          let ancestor=el,bg;
          while(ancestor){bg=rgb(window.getComputedStyle(ancestor).backgroundColor);if(bg.length<4||bg[3]===1)break;ancestor=ancestor.parentElement;}
          const fg=luminance(rgb(window.getComputedStyle(el).color)),back=luminance(bg||[14,14,17]);
          return {text:el.textContent.slice(0,60),ratio:(Math.max(fg,back)+.05)/(Math.min(fg,back)+.05)};
        });
        return {small,secondary};
      });
      assert.deepEqual(measured.small,[],label+': '+JSON.stringify(measured.small));
      assert.ok(measured.secondary.length>0,label+': secondary text must be measured');
      assert.deepEqual(measured.secondary.filter(row=>row.ratio<4.5),[],label+': contrast');
    };
    if(['approval_wrong','approval_nested'].includes(input.board)){
      await page.locator('.dx-task').filter({hasText:'Drawing set review'}).first().click();
      const region=page.getByRole('region',{name:'Resumed session',exact:true});
      await region.locator('[data-approval]').waitFor();
      const card=await page.evaluate(()=>window.ArchHubAPI.getSnapshot().approvals.find(card=>card.status==='pending'));
      assert.equal(await region.locator('[data-approval]').count(),1);
      assert.equal(await region.locator('[data-resume-step="held"] [data-approval]').count(),0,'A matching id from another canvas must not own this approval');
      if(input.board==='approval_wrong')assert.equal(await region.locator('[data-resume-step] [data-approval]').count(),0);
      else {
        assert.equal(card.canvasNodes.length,2);
        const parent=card.canvasNodes.find(ref=>ref.taskId===card.taskId);
        assert.equal(await region.locator('[data-resume-step="'+parent.nodeId+'"] [data-approval]').count(),1);
      }
      const answers=[];
      page.on('request',request=>{try{const body=request.postDataJSON();if(body?.function==='answerApproval'&&body.args[1]===card.id)answers.push(body.args);}catch{}});
      await region.getByRole('button',{name:'Approve',exact:true}).evaluate(button=>{button.click();button.click();});
      await page.waitForFunction(id=>window.ArchHubAPI.getSnapshot().approvals.find(card=>card.id===id)?.status==='approved',card.id);
      assert.equal(answers.length,1,'Double-click Approve sends one decision');
      assert.equal(await region.getByRole('button',{name:'Approve',exact:true}).count(),0);
      assert.deepEqual(errors,[]);
      console.log(`PASS ${input.board}: exact canvas step or session fallback; one card per digest; double-click sends one approval`);
      return;
    }
    if(['canvas_open','canvas_reading'].includes(input.board)){
      const nav=page.getByRole('navigation',{name:'Main navigation'});
      await nav.waitFor();
      await page.locator('.dx-task').filter({hasText:'Drawing set review'}).first().click();
      const measure=()=>page.getByLabel('Workflow canvas',{exact:true}).evaluate(area=>{
        const box=area.getBoundingClientRect(),matrix=new window.DOMMatrix(window.getComputedStyle(area.querySelector('.react-flow__viewport')).transform);
        const nodes=[...area.querySelectorAll('.react-flow__node')].map(node=>({id:node.dataset.id,...node.getBoundingClientRect().toJSON()}));
        const left=Math.min(...nodes.map(node=>node.left)),top=Math.min(...nodes.map(node=>node.top)),right=Math.max(...nodes.map(node=>node.right)),bottom=Math.max(...nodes.map(node=>node.bottom));
        return {area:box.toJSON(),nodes,left,top,right,bottom,zoom:matrix.a,x:matrix.e,y:matrix.f,readable:(right-left)/matrix.a*.62<=box.width-60&&(bottom-top)/matrix.a*.62<=box.height-60};
      });
      let positions, fitted=0, reading=0;
      for(const size of [{width:900,height:700},{width:1009,height:940},{width:1366,height:768},{width:1864,height:949}]){
        await page.setViewportSize(size);
        await page.getByRole('button',{name:'Open its Canvas',exact:true}).click();
        await page.locator('.react-flow__node').first().waitFor();await page.waitForTimeout(250);
        const view=await measure();
        assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().title),'Drawing set review');
        assert.equal(view.nodes.length,await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().nodes.length));
        if(input.board==='canvas_reading')assert.equal(view.readable,false,'The wide fixture must require the reading-size fallback');
        assert.ok(view.top>=view.area.top-1,JSON.stringify(view));
        if(view.readable){fitted++;assert.ok(view.zoom>=.62&&view.left>=view.area.left-1&&view.right<=view.area.right+1&&view.bottom<=view.area.bottom+1,JSON.stringify(view));}
        else {reading++;assert.ok(Math.abs(view.zoom-.8)<.005,JSON.stringify(view));assert.ok(view.left>=view.area.left-1,JSON.stringify(view));}
        const current=await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().nodes.map(node=>({id:node.id,position:node.position})));
        if(positions)assert.deepEqual(current,positions);else positions=current;
        await page.screenshot({path:path.resolve('.cache',`designv22g-${input.board}-${size.width}.png`)});
        console.log(`PASS ${input.board} ${size.width}x${size.height}: ${view.readable?'whole session fits':'reading size at left edge'}; zoom=${view.zoom}; topCut=0`);
        await nav.getByRole('button',{name:'Home',exact:true}).click();
      }
      if(input.board==='canvas_open')assert.ok(fitted>0&&reading>0,'Opening proof must exercise both readable fit and reading-size fallback');
      else assert.equal(reading,4);
      await page.setViewportSize({width:1009,height:940});
      await page.getByRole('button',{name:'Open its Canvas',exact:true}).click();
      await page.getByRole('button',{name:'More canvas actions',exact:true}).click();
      await page.getByRole('menuitem',{name:'Thread',exact:true}).click();
      await page.getByRole('button',{name:'Open Thread',exact:true}).click();await page.waitForTimeout(250);
      let session=await page.locator('.react-flow__node[data-id="start"]').boundingBox();
      const thread=await page.locator('[data-thread-peek]').boundingBox();
      assert.ok(session.x>=100&&session.x+session.width<thread.x&&session.y>=89,JSON.stringify({session,thread}));
      await page.getByRole('button',{name:'Close thread',exact:true}).click();
      await page.getByRole('button',{name:'Open Inspector',exact:true}).click();await page.waitForTimeout(250);
      session=await page.locator('.react-flow__node[data-id="start"]').boundingBox();
      const inspector=await page.locator('.v22g-inspector-peek').boundingBox();
      assert.ok(session.x>=100&&session.x+session.width<inspector.x&&session.y>=89,JSON.stringify({session,inspector}));
      await page.getByRole('button',{name:'Close Inspector',exact:true}).click();
      console.log(`PASS ${input.board}: Thread and Inspector peek keep the session node readable`);
      await nav.getByRole('button',{name:'Home',exact:true}).click();
      await page.getByRole('button',{name:'Open its Canvas',exact:true}).click();await page.waitForTimeout(250);
      const view=await measure(),before=await page.evaluate(()=>JSON.stringify(window.ArchHubAPI.getSnapshot().graph.viewport));
      await inputSession.send('Input.dispatchMouseEvent',{type:'mouseWheel',x:view.area.right-20,y:view.area.bottom-160,deltaX:0,deltaY:-140});
      await page.waitForFunction(before=>JSON.stringify(window.ArchHubAPI.getSnapshot().graph.viewport)!==before,before);
      await page.evaluate(()=>window.ArchHubAPI.saveSession());
      const manual=await measure();
      await page.setViewportSize({width:1009,height:940});await page.waitForTimeout(250);
      const kept=await measure();
      for(const key of ['zoom','x','y'])assert.ok(Math.abs(kept[key]-manual[key])<.1,JSON.stringify({manual,kept}));
      assert.deepEqual(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().nodes.map(node=>({id:node.id,position:node.position}))),positions);
      if(input.unboundPath){
        await page.evaluate(file=>window.ArchHubAPI.openSession(file),input.unboundPath);
        await nav.getByRole('button',{name:'Canvas',exact:true}).click();
        for(const size of [{width:900,height:700},{width:1009,height:940},{width:1366,height:768},{width:1864,height:949}]){
          await page.setViewportSize(size);await page.waitForTimeout(250);
          const standalone=await measure();
          assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().title),'Standalone opening check');
          assert.equal(standalone.nodes.length,4);
          assert.ok(Math.abs(standalone.zoom-.8)<.005&&standalone.left>=standalone.area.left-1&&standalone.top>=standalone.area.top-1,JSON.stringify(standalone));
          console.log(`PASS standalone Canvas ${size.width}x${size.height}: reading size at left edge; topCut=0`);
        }
      }
      assert.deepEqual(errors,[]);
      console.log(`PASS ${input.board}: resize honors manual zoom/pan; node positions unchanged`);
      return;
    }
    if(input.board==='zero_home'){
      await page.getByRole('heading',{name:'What do you need?',exact:true}).waitFor();
      assert.equal(await page.locator('[data-resume-step]').count(),0);
      const starter=page.getByRole('button',{name:'Review a drawing set',exact:true});
      await starter.click();
      const inputBox=page.getByRole('textbox',{name:'Message',exact:true});
      assert.equal(await inputBox.inputValue(),'Review a drawing set');
      assert.equal((await page.getByRole('button',{name:'Composer scope',exact:true}).innerText()).trim(),'New session');
      await inputBox.press('Enter');
      await page.getByRole('tab',{name:'Review a drawing set',exact:true}).waitFor();
      const saved=await page.evaluate(()=>({path:window.ArchHubAPI.getSessionPath(),document:window.ArchHubAPI.getSessionDocument()}));
      assert.ok(fs.existsSync(saved.path));
      assert.equal(saved.document.title,'Review a drawing set');
      assert.equal(saved.document.nodes.some(node=>node.result),false);
      assert.equal(await page.locator('.react-flow').count(),1);
      assert.deepEqual(errors,[]);
      console.log('PASS zero sessions: starter fills composer; Enter creates one real session file and opens Canvas without Run');
      return;
    }
    if (input.board === 'resume') {
      await page.getByRole('navigation',{name:'Main navigation'}).waitFor();
      await page.getByRole('heading',{name:'Sessions',exact:true}).waitFor();
      assert.equal(await page.getByRole('heading',{name:'Sessions',exact:true}).count(),1);
      await page.locator('.dx-task').filter({hasText:'Drawing set review'}).first().click();
      await page.getByRole('region',{name:'Resumed session',exact:true}).getByRole('heading',{name:'Drawing set review',exact:true}).waitFor();
      assert.equal(await page.locator('[data-resume-step]').count(),3);
      assert.equal(await page.locator('[data-resume-step][data-state=done]').count(),2);
      await page.getByRole('button',{name:'Pin Drawing set review',exact:true}).click();
      await page.getByRole('button',{name:'Unpin Drawing set review',exact:true}).waitFor();
      for(const size of [{width:900,height:700},{width:1009,height:940},{width:1366,height:768},{width:1864,height:949}]){
        await page.setViewportSize(size);await page.waitForTimeout(150);
        const result=await page.locator('[aria-label="Resumed session"]').evaluate(el=>({scroll:el.scrollHeight>el.clientHeight+1,steps:[...el.querySelectorAll('[data-resume-step]')].map(node=>node.getBoundingClientRect().toJSON()),composer:document.querySelector('.global-composer').getBoundingClientRect().toJSON(),bottom:document.querySelector('.screen-with-composer').getBoundingClientRect().bottom}));
        await assertReadable(size.width+' Resume');
        assert.equal(result.bottom,size.height);
        for(const box of result.steps)assert.ok(box.left>=64&&box.right<=size.width&&box.top>=48&&box.bottom<result.composer.top,JSON.stringify(result));
        await page.screenshot({path:path.resolve('.cache',`designv22g-resume-${size.width}.png`)});
        console.log(`PASS Resume ${size.width}x${size.height}: readable steps, floating composer, no bottom band`);
      }
      const sash=await page.getByRole('separator',{name:'Resize the session list',exact:true}).boundingBox();
      await pointer('mouseMoved',sash.x+sash.width/2,sash.y+sash.height/2);await pointer('mousePressed',sash.x+sash.width/2,sash.y+sash.height/2,true);for(let step=1;step<=8;step++)await pointer('mouseMoved',sash.x+sash.width/2+60*step/8,sash.y+sash.height/2,true);await pointer('mouseReleased',sash.x+sash.width/2+60,sash.y+sash.height/2);
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().homeLayout.width>=354&&window.ArchHubAPI.getSnapshot().homeLayout.width<=366);
      const keptWidth=await page.evaluate(()=>window.ArchHubAPI.getSnapshot().homeLayout.width);
      await page.getByRole('button',{name:'Fold the list to avatars',exact:true}).click();
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().homeLayout.collapsed);
      await page.getByRole('button',{name:'Open the list',exact:true}).click();
      await page.waitForFunction(()=>!window.ArchHubAPI.getSnapshot().homeLayout.collapsed);
      await page.getByRole('button',{name:'Hide Sheet index check from Home',exact:true}).click();
      assert.equal(await page.getByRole('button',{name:'Hide Sheet index check from Home',exact:true}).count(),0);
      await page.getByRole('button',{name:'Undo Home change',exact:true}).click();
      await page.getByRole('button',{name:'Hide Sheet index check from Home',exact:true}).waitFor();
      await page.getByRole('button',{name:'Reset Home',exact:true}).click();
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().homeLayout.width===300);
      await page.getByRole('button',{name:'Undo Home change',exact:true}).click();
      await page.waitForFunction(width=>window.ArchHubAPI.getSnapshot().homeLayout.width===width,keptWidth);
      console.log('PASS Resume: resize, fold, hide/restore and reset/undo use the homeLayout owner');
      await page.getByRole('button',{name:'Open its Canvas',exact:true}).click();
      await page.evaluate(()=>window.ArchHubAPI.addNode('g_approval_gate',{x:500,y:200}));
      await page.locator('[data-design="toolbar.run"]').click();
      await page.locator('[data-design="approval.panel"]').waitFor();
      await page.locator('body').press('Escape');
      await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Home',exact:true}).click();
      await page.getByRole('region',{name:'Resumed session',exact:true}).getByRole('button',{name:'Ask why',exact:true}).click();
      await page.locator('[data-design="thread.msg"]').waitFor();
      assert.match(await page.locator('[data-design="thread.msg"]').inputValue(),/^Why does .* need approval\?$/);
      await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Home',exact:true}).click();
      await page.getByRole('region',{name:'Resumed session',exact:true}).getByRole('button',{name:'Reject',exact:true}).click();
      await page.waitForFunction(()=>!window.ArchHubAPI.getSnapshot().approvals.some(card=>card.status==='pending'));
      console.log('PASS Resume: existing task pin owner and real gate Reject/Ask why path');
      await page.evaluate(async()=>{const task=await window.ArchHubAPI.createTask('Home approval proof');window.dispatchEvent(new CustomEvent('archhub:open-task',{detail:{task_id:task.taskId}}));});
      await page.getByRole('tab',{name:'Home approval proof',exact:true}).waitFor();
      await page.evaluate(()=>window.ArchHubAPI.addNode('g_approval_gate',{x:500,y:200}));
      await page.locator('[data-design="toolbar.run"]').click();
      await page.locator('[data-design="approval.panel"]').waitFor();
      await page.locator('body').press('Escape');
      await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Home',exact:true}).click();
      await page.locator('.dx-task').filter({hasText:'Home approval proof'}).click();
      assert.match(await page.locator('.resume-row').first().innerText(),/Home approval proof/);
      await page.getByRole('region',{name:'Resumed session',exact:true}).getByRole('button',{name:'Approve',exact:true}).click();
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().graph.nodes.some(node=>node.type==='approval.gate'&&node.status==='Done'));
      console.log('PASS Resume: waiting session first; Approve resumes the real gate and re-reads its file result');
      await page.locator('.dx-task').filter({hasText:'Drawing set review'}).click();
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().homeLayout.resume===window.ArchHubAPI.getSnapshot().tasks.find(task=>task.title==='Drawing set review').id);
      await page.reload();
      await page.getByRole('region',{name:'Resumed session',exact:true}).getByRole('heading',{name:'Drawing set review',exact:true}).waitFor();
      assert.equal(await page.getByRole('button',{name:'Unpin Drawing set review',exact:true}).isVisible(),true);
      assert.deepEqual(errors,[]);
      return;
    }
    if (input.board === 'fluid_shell') {
      const nav = page.getByRole('navigation', {name:'Main navigation'});
      await nav.waitFor();
      assert.equal(await nav.getByRole('button', {name:'Workshop',exact:true}).count(), 0);
      assert.equal(await nav.getByRole('button', {name:'Automations',exact:true}).count(), 0);
      for (const size of [{width:900,height:700},{width:1009,height:940},{width:1366,height:768},{width:1864,height:949}]) {
        await page.setViewportSize(size);
        for (const route of ['Home','Canvas','Docs','Settings']) {
          await nav.getByRole('button', {name:route,exact:true}).click();
          await page.waitForTimeout(200);
          const result = await page.evaluate(() => {
            const visible = el => {
              const r=el.getBoundingClientRect(),s=window.getComputedStyle(el);
              if(r.width<=0||r.height<=0||s.visibility==='hidden'||s.display==='none'||el.closest('[hidden]'))return false;
              for(let parent=el.parentElement;parent;parent=parent.parentElement){
                const style=window.getComputedStyle(parent),box=parent.getBoundingClientRect();
                if(/auto|scroll|hidden|clip/.test(style.overflowY)&&(r.bottom<=box.top||r.top>=box.bottom))return false;
                if(/auto|scroll|hidden|clip/.test(style.overflowX)&&(r.right<=box.left||r.left>=box.right))return false;
              }
              return true;
            };
            const controls = [...document.querySelectorAll('button,input,select,textarea')].filter(visible).filter(el=>!el.closest('.react-flow__viewport,[role=listbox],.context-menu'));
            const cut = controls.filter(el=>{
              const r=el.getBoundingClientRect();
              if(r.left<-.5||r.right>window.innerWidth+.5)return true;
              for(let parent=el.parentElement;parent;parent=parent.parentElement)if(/auto|scroll/.test(window.getComputedStyle(parent).overflowY)&&parent.scrollHeight>parent.clientHeight)return false;
              return r.top<-.5||r.bottom>window.innerHeight+.5;
            }).map(el=>({label:el.getAttribute('aria-label')||el.textContent,box:el.getBoundingClientRect().toJSON()}));
            const strips = [...document.querySelectorAll('body *')].filter(visible).filter(el=>{
              const r=el.getBoundingClientRect(),s=window.getComputedStyle(el);
              return r.width>window.innerWidth*.6&&r.height>1&&r.height<=160&&r.bottom>=window.innerHeight-1&&s.backgroundColor!=='rgba(0, 0, 0, 0)'&&s.backgroundColor!=='transparent';
            }).map(el=>el.className);
            const composer=document.querySelector('.global-composer,.v22g-composer-dock');
            return {cut,strips,composer:composer&&window.getComputedStyle(composer).position,footer:!!document.querySelector('.app-window>footer'),bottom:document.querySelector('.screen-with-composer').getBoundingClientRect().bottom};
          });
          await assertReadable(size.width+' '+route);
          assert.deepEqual(result.cut, [], `${size.width} ${route}: cut ${JSON.stringify(result.cut)}`);
          assert.deepEqual(result.strips, [], `${size.width} ${route}: opaque strip ${JSON.stringify(result.strips)}`);
          assert.equal(result.footer,false);
          assert.equal(result.composer,'fixed', `${route} composer must float`);
          assert.equal(result.bottom,size.height);
          if(route==='Canvas')await page.screenshot({path:path.resolve('.cache',`designv22g-shell-${size.width}.png`)});
          console.log(`PASS fluid shell ${size.width}x${size.height} ${route}: cut=0 opaqueStrip=0 floatingComposer=true`);
        }
      }
      await page.setViewportSize({width:1009,height:940});
      await nav.getByRole('button',{name:'Canvas',exact:true}).click();
      await page.locator('[data-design="canvas.stage"]').waitFor();
      await page.getByRole('button',{name:'More canvas actions',exact:true}).click();
      await page.getByRole('menuitem',{name:'Thread',exact:true}).click();
      await page.getByRole('button',{name:'Open Thread',exact:true}).click();
      await page.getByRole('button',{name:'Close thread',exact:true}).waitFor();
      assert.equal(await page.locator('textarea[aria-label="Message"]').count(),1);
      assert.equal(await page.locator('.v22g-composer-dock').evaluate(el=>window.getComputedStyle(el).position),'fixed');
      await page.getByRole('button',{name:'Open Inspector',exact:true}).click();
      await page.locator('.v22g-inspector-peek').waitFor();
      assert.equal(await page.locator('.v22g-inspector-peek').evaluate(el=>el.getBoundingClientRect().right<=window.innerWidth),true);
      await page.getByRole('button',{name:'Close Inspector',exact:true}).click();
      await page.getByRole('button',{name:'Close thread',exact:true}).click();
      console.log('PASS fluid shell: narrow Thread and Inspector peek over Canvas; one floating composer');
      for(const title of ['Drawing set review','Sheet index check','Export issue package','Update drawing references','Model view audit']){
        await nav.getByRole('button',{name:'Home',exact:true}).click();
        await page.getByRole('button',{name:'Open the list',exact:true}).click();
        await page.locator('.dx-task').filter({hasText:title}).first().dblclick();
        await page.getByRole('tab',{name:title,exact:true}).dblclick();
      }
      const overflow=page.locator('.v22g-tab-overflow');
      await overflow.locator('summary').click();
      const hiddenTab=overflow.getByRole('menuitem').first(),title=await hiddenTab.innerText();
      await hiddenTab.click();
      await page.getByRole('tab',{name:title,exact:true,selected:true}).waitFor();
      assert.equal(await page.locator('[data-design="tab.add"]').isVisible(),true);
      assert.equal(await page.locator('[data-design="tab.active"]').evaluate(el=>{const r=el.getBoundingClientRect();return r.left>=64&&r.right<=window.innerWidth;}),true);
      console.log('PASS fluid shell: tabs fold into n more; active tab and + stay visible; hidden tab opens');
      await page.setViewportSize({width:300,height:700});
      const floor=await page.locator('.v22g-composer-dock').boundingBox();
      assert.ok(floor.width>=320);
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth>=900));
      console.log('PASS below 900px: shell scrolls at its floor; composer width >= 320px');
      assert.deepEqual(errors, []);
      return;
    }
    await page.setViewportSize({width:1864,height:949});
    const nav=page.getByRole('navigation',{name:'Main navigation'});
    await nav.waitFor();
    await page.locator('.dx-task').filter({hasText:'Drawing set review'}).first().click();
    await page.getByRole('region',{name:'Resumed session'}).waitFor();
    assert.equal(await page.getByRole('complementary',{name:'Properties'}).count(),0);
    if(input.board==='canvas'||input.board==='canvas_fit')assert.equal(await page.locator('[data-resume-step]').count(),input.board==='canvas'?4:2);
    else assert.equal(await page.locator('[data-resume-step][data-state=done]').count(),2);
    await page.evaluate(()=>document.fonts.ready);
    assert.equal(await page.evaluate(()=>[...document.fonts].some(face=>face.family==='Inter'&&face.status==='loaded')),true);
    assert.equal(await page.evaluate(()=>window.devicePixelRatio),1);
    assert.equal(await page.evaluate(()=>localStorage.getItem('archhub.home.layout.v1')),null);
    await page.getByRole('button',{name:'Open its Canvas',exact:true}).click();
    await page.locator('[data-design="canvas.stage"]').waitFor();
    let preview=page.getByRole('complementary',{name:'Properties'});
    await preview.waitFor();
    const cleanSession=await page.evaluate(()=>({id:window.ArchHubAPI.getSnapshot().graph.id,path:window.ArchHubAPI.getSessionPath()}));
    assert.equal(await page.locator('.app-rail').evaluate(el=>el.getBoundingClientRect().width),64);
    assert.equal(await page.locator('[data-screen=canvas]').count(),1);
    if(input.board==='workshop'){
      await page.getByRole('button',{name:'Thread',exact:true}).click();
      await page.locator('[data-design="thread.message"]').filter({hasText:'Review is complete.'}).waitFor();
      assert.equal(await page.locator('textarea[aria-label="Message"]').count(),1);
      assert.equal(await page.locator('.react-flow').count(),1);
      await page.getByRole('button',{name:'Open Inspector',exact:true}).click();
      await preview.waitFor();
    }
    if(input.board==='canvas_fit'){
      await page.getByRole('button',{name:'Fit',exact:true}).click();
      const area=await page.getByLabel('Workflow canvas',{exact:true}).boundingBox();
      for(const node of await page.locator('.react-flow__node').all()){
        const box=await node.boundingBox();assert.ok(box.x>=area.x-1&&box.y>=area.y-1&&box.x+box.width<=area.x+area.width+1&&box.y+box.height<=area.y+area.height+1);
      }
      const before=await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.viewport);
      await inputSession.send('Input.dispatchMouseEvent',{type:'mouseWheel',x:area.x+area.width-40,y:area.y+100,deltaX:0,deltaY:-140});
      await page.waitForFunction(before=>window.ArchHubAPI.getSnapshot().graph.viewport?.zoom!==before.zoom,before);
      await page.evaluate(()=>window.ArchHubAPI.saveSession());
      const saved=await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.viewport);
      await nav.getByRole('button',{name:'Home',exact:true}).click();await page.getByRole('button',{name:'Open its Canvas',exact:true}).click();
      assert.deepEqual(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.viewport),saved);
      await page.evaluate(async()=>{window.ArchHubAPI.setSessionViewport({x:0,y:0,zoom:1});await window.ArchHubAPI.saveSession();});
      const file=await page.evaluate(()=>window.ArchHubAPI.getSessionPath());
      assert.deepEqual(JSON.parse(fs.readFileSync(file,'utf8')).viewport,{x:0,y:0,zoom:1});
      await page.reload();
      await page.getByRole('button',{name:'Open its Canvas',exact:true}).click();
      await page.locator('.react-flow__viewport').waitFor();await page.waitForTimeout(250);
      assert.deepEqual(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().viewport),{x:0,y:0,zoom:1});
      const restored=await page.locator('.react-flow__viewport').evaluate(el=>{const m=new window.DOMMatrix(window.getComputedStyle(el).transform);return {x:m.e,y:m.f,zoom:m.a};});
      assert.deepEqual(restored,{x:0,y:0,zoom:1},'The rendered viewport must restore the saved origin at 100%');
      console.log('PASS saved viewport {x:0,y:0,zoom:1}: file readback and reopened rendered transform unchanged');
      assert.deepEqual(errors,[]);console.log('PASS canvas_fit: real nodes fit; wheel viewport saves and reopens unchanged');return;
    }
    if(input.board==='canvas'){
      await page.getByRole('button',{name:'Fit',exact:true}).click();
      const node=page.locator('.react-flow__node[data-id="slice"]');
      await node.locator('[data-node-card-title]').click();
      const inspector=page.locator('[data-node-inspector="slice"]');await inspector.waitFor();
      assert.equal(await node.locator('[data-ds-node]').evaluate(el=>el.offsetWidth),268);
      assert.equal(await node.locator('[data-ds-node]').evaluate(el=>window.getComputedStyle(el).backgroundColor),'rgb(21, 21, 26)');
      const stable=await preview.boundingBox(),toolbar=await page.locator('.v22g-strip').boundingBox();
      for(let index=0;index<3;index++){
        await node.locator('[data-node-card-title]').click();
        const point=await page.locator('[data-graph-wire="first"]').evaluate(path=>{const p=path.getPointAtLength(path.getTotalLength()/2),q=new window.DOMPoint(p.x,p.y).matrixTransform(path.getScreenCTM());return {x:q.x,y:q.y};});
        await pointer('mousePressed',point.x,point.y,true);await pointer('mouseReleased',point.x,point.y);await page.locator('[data-wire-inspection]').waitFor({timeout:5000});
        assert.deepEqual(await preview.boundingBox(),stable);assert.deepEqual(await page.locator('.v22g-strip').boundingBox(),toolbar);
      }
      await node.locator('[data-node-card-title]').click();
      await inspector.getByRole('textbox',{name:'Node label',exact:true}).fill('Review first sheets');await inspector.getByRole('textbox',{name:'Node label',exact:true}).press('Tab');
      await inspector.getByLabel('Node icon',{exact:true}).selectOption('docs');
      await assert.rejects(()=>page.evaluate(()=>window.ArchHubAPI.setNodePresentation('slice',{color:'red'})),/six-digit/);
      await assert.rejects(()=>page.evaluate(()=>window.ArchHubAPI.setNodePresentation('slice',[])),/six-digit/);
      await inspector.getByLabel('Node colour',{exact:true}).fill('#743b27');
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().graph.nodes.find(node=>node.id==='slice').color==='#743b27');
      assert.equal(await inspector.locator('[data-linked-source]').count(),1);
      await node.getByRole('button',{name:'Parameters',exact:true}).click();
      assert.ok(await node.locator('[data-parameter="count"] input[type=number]').count()>0);
      assert.equal(await node.locator('[data-parameter="items"] input').count(),0);
      const count=inspector.getByRole('spinbutton',{name:'Review first sheets count',exact:true});
      assert.ok((await count.boundingBox()).width>100);await count.fill('4');
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().graph.nodes.find(node=>node.id==='count').output?.count===4);
      for(const [label,value] of [['Undo · Ctrl Z','3'],['Redo · Ctrl Shift Z','4']]){await page.getByRole('button',{name:'More canvas actions',exact:true}).click();await page.getByRole('menuitem',{name:label,exact:true}).click();await page.waitForFunction(value=>String(window.ArchHubAPI.getSnapshot().graph.nodes.find(node=>node.id==='slice').params.count)===value,value);}
      for(const [color,ink] of [['#ffffff','rgb(0, 0, 0)'],['#000000','rgb(255, 255, 255)']]){await inspector.getByLabel('Node colour',{exact:true}).fill(color);await page.waitForFunction(({color,ink})=>window.ArchHubAPI.getSnapshot().graph.nodes.find(node=>node.id==='slice').color===color&&window.getComputedStyle(document.querySelector('[data-graph-node="slice"] .node-header')).color===ink,{color,ink});}
      await inspector.getByLabel('Node colour',{exact:true}).fill('#743b27');
      await page.locator('[data-graph-node="pdf"]').getByRole('button',{name:'Parameters',exact:true}).click();
      await page.locator('[data-graph-node="pdf"] [data-parameter="folder"] input').fill('issued');
      await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().graph.nodes.find(node=>node.id==='pdf').status==='Out of date');
      for(const [theme,color] of [['Light','rgb(251, 249, 244)'],['Dark','rgb(21, 21, 26)']]){await page.evaluate(theme=>window.ArchHubAPI.setSetting('Appearance.Theme',theme),theme);await page.waitForFunction(color=>window.getComputedStyle(document.querySelector('[data-graph-node="count"] [data-ds-node]')).backgroundColor===color,color);}
      await page.getByRole('button',{name:'Library',exact:true}).click();
      await page.getByRole('complementary',{name:'Library shelf'}).waitFor();
      await page.getByRole('button',{name:'Close Library',exact:true}).click();
      await page.getByRole('complementary',{name:'Library shelf'}).waitFor({state:'hidden'});
      await page.getByRole('tab',{name:'Task',exact:true}).click();
    }
    await page.getByRole('tab',{name:'Task',exact:true}).click();
    const progress=preview.locator('.dx-plan-summary');
    assert.equal(await progress.locator('li').count(),3);assert.equal(await progress.locator('li[data-step=done]').count(),2);assert.equal(await progress.getByRole('textbox').count(),0);
    const sash=await page.getByRole('separator',{name:'Resize the Properties pane',exact:true}).boundingBox();
    await pointer('mouseMoved',sash.x+sash.width/2,sash.y+sash.height/2);await pointer('mousePressed',sash.x+sash.width/2,sash.y+sash.height/2,true);for(let step=1;step<=8;step++)await pointer('mouseMoved',sash.x+sash.width/2-80*step/8,sash.y+sash.height/2,true);await pointer('mouseReleased',sash.x+sash.width/2-80,sash.y+sash.height/2);
    await page.waitForFunction(()=>Math.abs(window.ArchHubAPI.getSnapshot().settings.find(row=>row.id==='Appearance.Inspector width').value-400)<=8);
    for(const [label,value] of [['Scope','Review the current issue'],['Rules','Review every sheet before export'],['References','Current drawing index'],['Folders','Dated issue folder renamed']]){
      const field=preview.locator('details').filter({has:page.locator('summary>span:first-child').filter({hasText:new RegExp('^'+label+'$')})});
      await field.locator('summary').click();await field.getByRole('textbox').fill(value);await key('Tab',9);
      await page.waitForFunction(({label,value})=>{const task=window.ArchHubAPI.getSnapshot().tasks.find(task=>task.title==='Drawing set review'),key={Scope:'scope',Rules:'rules',References:'references',Folders:'folders'}[label];return task&&JSON.stringify(task[key]).includes(value);},{label,value});await field.locator('summary').click();
    }
    await assertReadable(input.board);
    await page.evaluate(()=>window.ArchHubAPI.saveSession());
    const savedViewport=input.board==='canvas'?await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.viewport):null;
    assert.deepEqual(await page.evaluate(()=>({id:window.ArchHubAPI.getSnapshot().graph.id,path:window.ArchHubAPI.getSessionPath()})),cleanSession);
    if(input.board==='settings'){
      const look=async()=>{await nav.getByRole('button',{name:'Settings',exact:true}).click();await page.getByRole('navigation',{name:'Settings categories'}).getByRole('button',{name:'Appearance',exact:true}).click();await page.getByRole('combobox',{name:'Theme',exact:true}).waitFor();await page.getByRole('button',{name:'Show advanced',exact:true}).click();};
      await look();await page.getByRole('spinbutton',{name:'Row spacing',exact:true}).fill('8');await page.getByRole('spinbutton',{name:'Node radius',exact:true}).fill('12');
      await page.getByRole('spinbutton',{name:'Text scale',exact:true}).fill('150');await page.waitForFunction(()=>window.getComputedStyle(document.querySelector('.settings-sheet h1')).fontSize==='42px');await page.getByRole('spinbutton',{name:'Text scale',exact:true}).fill('100');
      for(const size of [{width:900,height:700},{width:1009,height:940},{width:1366,height:768},{width:1864,height:949}]){await page.setViewportSize(size);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),size.width);assert.equal(await page.locator('.sheet-content').evaluate(el=>el.scrollWidth>el.clientWidth),false);}
      for(const theme of ['Light','Dark']){await page.getByRole('combobox',{name:'Theme',exact:true}).selectOption(theme);await page.waitForFunction(theme=>document.documentElement.dataset.theme===theme,theme);}
      await page.reload();await look();assert.equal(await page.getByRole('spinbutton',{name:'Row spacing',exact:true}).inputValue(),'8');assert.equal(await page.getByRole('spinbutton',{name:'Node radius',exact:true}).inputValue(),'12');
      await page.getByRole('button',{name:'Changed only',exact:true}).click();assert.equal(await page.getByRole('combobox',{name:'Theme',exact:true}).count(),0);await page.getByRole('button',{name:'Changed only',exact:true}).click();await page.getByRole('button',{name:'Reset Appearance',exact:true}).click();await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().settings.find(row=>row.id==='Appearance.Row spacing').value===4);
    }
    await nav.getByRole('button',{name:'Home',exact:true}).click();
    await page.setViewportSize({width:1864,height:949});
    await page.getByRole('region',{name:'Resumed session'}).waitFor();await page.getByRole('button',{name:'Open its Canvas',exact:true}).click();
    if(input.board==='workshop')await page.getByRole('button',{name:'Open Inspector',exact:true}).click();
    await preview.getByText('Review the current issue',{exact:true}).waitFor();
    assert.ok(Math.abs((await preview.boundingBox()).width-(input.board==='settings'?320:400))<=8);
    if(input.board==='canvas'){
      assert.deepEqual(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.viewport),savedViewport);
      const saved=await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.nodes.find(node=>node.id==='slice'));
      assert.equal(saved.title,'Review first sheets');assert.equal(saved.color,'#743b27');assert.equal(saved.icon,'docs');
    }
    if(input.board==='settings'){
      const task=await page.evaluate(()=>window.ArchHubAPI.getSnapshot().tasks.find(task=>task.title==='Sheet index check'));
      const opens=[];page.on('request',request=>{try{const body=request.postDataJSON();if(body?.function==='openTaskGraph')opens.push(body.args[0]);}catch{}});
      await page.evaluate(id=>window.dispatchEvent(new CustomEvent('archhub:open-task',{detail:{task_id:id}})),task.id);await page.getByRole('tab',{name:'Sheet index check',exact:true}).waitFor();assert.deepEqual(opens,[task.id]);
      const id=await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.id);
      await page.evaluate(()=>window.dispatchEvent(new CustomEvent('archhub:open-task',{detail:{task_id:'missing-task'}})));await page.getByRole('alert').filter({hasText:/task/i}).waitFor();assert.deepEqual(opens,[task.id,'missing-task']);assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.id),id);
      await nav.getByRole('button',{name:'Settings',exact:true}).click();await page.getByRole('button',{name:'Back to task',exact:true}).click();await page.getByRole('tab',{name:'Sheet index check',exact:true}).waitFor();assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.id),id);
      await nav.getByRole('button',{name:'Docs',exact:true}).click();await nav.getByRole('button',{name:'Settings',exact:true}).click();await page.getByRole('button',{name:'Back to task',exact:true}).click();assert.equal(await nav.getByRole('button',{name:'Docs',exact:true}).getAttribute('aria-current'),'page');
    }
    await page.close();page=await context.newPage();await page.setViewportSize({width:1864,height:949});page.on('pageerror',error=>errors.push(error.message));await page.goto(input.url);
    await page.getByRole('region',{name:'Resumed session'}).waitFor();await page.getByRole('button',{name:'Open its Canvas',exact:true}).click();
    if(await page.getByRole('button',{name:'Open Inspector',exact:true}).isVisible())await page.getByRole('button',{name:'Open Inspector',exact:true}).click();
    await page.getByRole('complementary',{name:'Properties'}).getByText('Review the current issue',{exact:true}).waitFor();
    if(input.board==='canvas'){
      assert.deepEqual(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.viewport),savedViewport);
      await page.waitForFunction(saved=>{const element=document.querySelector('.react-flow__viewport');if(!element)return false;const matrix=new window.DOMMatrix(window.getComputedStyle(element).transform);return Math.abs(matrix.e-saved.x)<.001&&Math.abs(matrix.f-saved.y)<.001&&Math.abs(matrix.a-saved.zoom)<.001;},savedViewport);
    }
    assert.deepEqual(errors,[]);
    console.log('PASS '+input.board+': current shell, real fields, styles and Settings; file and browser reopen preserve owner state');
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
