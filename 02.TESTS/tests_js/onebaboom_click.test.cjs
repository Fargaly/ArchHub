// ONEBABOOM: a click on BABOOM that opens his panel points the one composer at him; the click that closes it
// leaves the recipient alone, so a thread talking to another agent keeps talking to it.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require('playwright');

test('the click that opens BABOOM points the composer at him; the click that closes it changes nothing', {timeout:120000}, async t=>{
  const root=path.resolve(__dirname,'../..'), app=path.join(root,'01.APP');
  const cache=path.join(root,'.cache');
  fs.mkdirSync(cache,{recursive:true});
  const profile=fs.mkdtempSync(path.join(cache,'onebaboom-click-'));
  const env={...process.env,HOME:profile,USERPROFILE:profile,LOCALAPPDATA:path.join(profile,'LOCAL'),
    APPDATA:path.join(profile,'ROAMING'),TEMP:profile,TMP:profile,ARCHHUB_HOME:profile,
    ARCHHUB_TEST_STATE_DIR:path.join(profile,'state'),WORKSHOP_STATE_DIR:path.join(profile,'workshop'),ARCHHUB_TEST_SECRET_STORE:'memory'};
  const python=process.env.ARCHHUB_COURT_PYTHON ||
    path.join(process.env.LOCALAPPDATA,'ArchHub','.venv','Scripts','python.exe');
  const code=[
    'import json, os, sys',
    'from nodelang.nograph_server import NoGraphServer',
    'from nodelang.window_commands import COMPANION_BRIDGE',
    'server=NoGraphServer(os.environ["ARCHHUB_TEST_STATE_DIR"], port=0).start()',
    'print(json.dumps({"url":server.public_url,"bootstrap":server.browser_bootstrap_token,"companionBridge":COMPANION_BRIDGE}),flush=True)',
    'try: sys.stdin.read()',
    'finally: server.close()',
  ].join('\n');
  const owner=spawn(python,['-B','-c',code],{cwd:app,env,windowsHide:true});
  const exited=new Promise(resolve=>owner.once('close',resolve));
  let browser;
  t.after(async()=>{
    await browser?.close();
    owner.stdin.end();
    await exited;
  });
  const server=await new Promise((resolve,reject)=>{
    let output='',errors='';
    owner.stderr.on('data',data=>{errors+=data;});
    owner.stdout.on('data',data=>{
      output+=data;
      if(output.includes('\n')){
        try{resolve(JSON.parse(output.split('\n')[0]));}catch(error){reject(error);}
      }
    });
    owner.once('close',code=>reject(Error('Studio owner exited '+code+': '+errors)));
    owner.once('error',reject);
  });
  const chrome=process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
  browser=await chromium.launch({headless:true,...(chrome?{executablePath:chrome}:{})});
  const problems=[];
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  page.setDefaultTimeout(12000);
  page.on('pageerror',error=>problems.push(error.message));
  await page.route('**/*',route=>new URL(route.request().url()).origin===server.url?
    route.continue():route.abort());
  // Supply a recipient without contacting a live external agent.
  await page.addInitScript(()=>{
    let api;
    Object.defineProperty(window,'ArchHubAPI',{
      configurable:true,
      get:()=>api,
      set:value=>{
        const snapshot=value.getSnapshot;
        const views=new WeakMap();
        api={...value,getSnapshot:()=>{
          const current=snapshot();
          if(!views.has(current)){
            views.set(current,{...current,liveAgents:[{agent:'Claude Code / drawings / session-abcdef12',
              name:'Drawing reviewer',handle:'drawing-reviewer',app:'claude',status:'working',task:'Reviews the drawing set',session:'court-1'}]});
          }
          return views.get(current);
        }};
      },
    });
  });
  await page.goto(server.url+'/studio?bootstrap='+server.bootstrap,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.querySelector('.boot-evidence:not([hidden])')||
    !document.getElementById('studio-boot')&&document.querySelector('[data-home-page]'));
  assert.deepEqual(await page.locator('.boot-evidence:not([hidden])').allTextContents(),[]);
  // Run the desktop's own bridge in Studio. Only the receiving Qt object is replaced here.
  await page.addScriptTag({content:`{const channel={objects:{desktopWindow:{companionHome(){},
    companionSees(needs,listening){window.companionReceipt={needs,listening};}}}};${server.companionBridge}}`});
  const badge=needs=>page.waitForFunction(count=>window.companionReceipt?.needs===count,needs);
  await badge(0);
  const composer=page.locator('[data-design="composer.surface"]').first();
  const recipient=composer.locator('.recipient-name');
  const panel=page.locator('[aria-label="BABOOM companion"]');
  // What the native companion's click reaches the page as (nograph_launcher.ask_baboom).
  const click=()=>page.evaluate(()=>window.dispatchEvent(new CustomEvent('archhub:ask-baboom')));
  const pick=async name=>{
    await composer.locator('.ws-to>.ws-link').click();
    await composer.getByRole('option',{name}).click();
  };
  await pick('Drawing reviewer');
  assert.equal(await recipient.textContent(),'@Drawing reviewer');

  await click();                                   // opens his panel
  await panel.waitFor();
  await page.waitForFunction(()=>window.companionReceipt.listening===true);
  assert.equal(await recipient.textContent(),'@BABOOM','the opening click points the composer at BABOOM');
  assert.equal(await page.evaluate(()=>document.activeElement.closest('[data-design="composer.surface"]')!==null&&
    document.activeElement.tagName),'TEXTAREA','with the caret in it');
  assert.equal(await panel.locator('textarea,input').count(),0,'his panel has no input of its own');
  // His panel as the design prototype measures it: 380 wide, radius 10; the header is his sprite at .4 (32 x 35),
  // his name 14 bold, his role 12 and a 30 px close; then the greeting, English and Arabic.
  const look=await panel.evaluate(async element=>{
    const box=e=>e.getBoundingClientRect(),style=e=>window.getComputedStyle(e);
    const head=element.querySelector('.bbm-ph'),sprite=head.querySelector('.bbm-mini'),name=head.querySelector('b'),
      role=head.querySelector('b+span'),close=head.querySelector('[aria-label="Close BABOOM"]');
    const atlas=await fetch('/assets/baboom/spritesheet.png');
    return {width:box(element).width,radius:style(element).borderTopLeftRadius,
      sprite:[box(sprite).width,box(sprite).height,style(sprite).backgroundImage.includes('/assets/baboom/spritesheet.png')],
      atlas:[atlas.status,atlas.headers.get('content-type')],
      name:[name.textContent,style(name).fontSize,style(name).fontWeight],role:[role.textContent,style(role).fontSize],
      close:[box(close).width,box(close).height],
      greeting:[...element.querySelectorAll('.pet-messages>p')].slice(0,2).map(p=>[p.textContent,p.lang,p.dir])};
  });
  assert.deepEqual(look,{width:380,radius:'10px',sprite:[32,35,true],atlas:[200,'image/png'],
    name:['BABOOM','14px','700'],role:['Your ArchHub assistant','12px'],close:[30,30],
    greeting:[['Welcome. Ask me about your work or the standard, or tell me what to do. Type below; I answer here.','',''],
      ['أهلاً. اسألني عن شغلك أو الستاندرد، أو قولّي أعمل إيه. اكتب تحت وأنا أرد هنا.','ar','rtl']]});

  await pick('Drawing reviewer');                  // he goes back to the other agent, the panel still open
  await click();                                   // closes his panel
  await panel.waitFor({state:'detached'});
  await page.waitForFunction(()=>window.companionReceipt.listening===false);
  assert.equal(await recipient.textContent(),'@Drawing reviewer','the closing click leaves the recipient alone');

  // A line of his menu that the user finishes in his own words (nograph_launcher.ask_baboom with words): his panel
  // opens, the composer points at him and starts with those words; a second such line keeps the panel open.
  const line=text=>page.evaluate(text=>window.dispatchEvent(new CustomEvent('archhub:ask-baboom',{detail:{text}})),text);
  const starts=text=>page.waitForFunction(text=>document.activeElement.tagName==='TEXTAREA'&&
    document.activeElement.closest('[data-design="composer.surface"]')!==null&&document.activeElement.value===text,text);
  await line('remember: ');
  await panel.waitFor();
  await starts('remember: ');
  assert.equal(await recipient.textContent(),'@BABOOM');
  await line('tell codex: ');
  await starts('tell codex: ');
  assert.equal(await panel.count(),1,'words to start from never close his panel');
  await panel.getByRole('button',{name:'Close BABOOM'}).click();
  // Seed replies in the two actual session files, without calling a model.
  let selectedId;
  for(const title of ['Door review','Level review']){
    selectedId=await page.evaluate(async title=>{
      const api=window.ArchHubAPI;
      const {taskId}=await api.createTask(title);
      const text=title+' reply';
      const saved=await api.setTaskSession(taskId,{messages:[{id:taskId+'-reply',who:'BABOOM',text}]});
      if(!saved.messages?.some(message=>message.text===text))throw Error('Reply was not saved to the test session');
      return taskId;
    },title);
    await page.locator('.dx-task').filter({hasText:title}).click();
    await page.waitForFunction(id=>window.UI.homeShown()===id,selectedId);
    if(title==='Door review')await click();
    await panel.getByText(title+' reply',{exact:true}).waitFor();
    const other=title==='Door review'?'Level review':'Door review';
    assert.equal(await panel.getByText(other+' reply',{exact:true}).count(),0);
  }
  const scope=composer.locator('[data-design="composer.to"]');
  await scope.click();
  await composer.getByRole('button',{name:'Composer scope: New session. Change'}).waitFor();
  assert.equal(await page.evaluate(()=>window.UI.homeShown()),selectedId,'the rail still targets the selected Canvas');
  assert.equal(await panel.getByText('Level review reply',{exact:true}).count(),0,'New session must clear the last conversation');
  await scope.click();
  await panel.getByText('Level review reply',{exact:true}).waitFor();
  await panel.getByRole('button',{name:'Close BABOOM'}).click();
  // The badge follows task changes even while Home is unmounted and its list cannot trigger a repaint.
  await page.locator('.app-rail button[aria-label="Settings"]').click();
  await page.locator('.settings-sheet').waitFor();
  const review=await page.evaluate(async()=>{
    const api=window.ArchHubAPI;
    const task=(await api.createTask('Review the drawing set')).taskId;
    await api.openTaskGraph(task);
    const gate=api.getSnapshot().libraryPorts.find(item=>item.engine==='approval.gate'&&!item.noEngine);
    if(!gate)throw Error('The approval gate is missing from the Canvas library');
    const node=await api.addNode(gate.id,{x:300,y:0});
    const run=await api.runNode(node.id);
    const card=api.getSnapshot().approvals.find(row=>row.id===run.approvalId&&row.status==='pending');
    if(!card||!(card.taskId===task||card.taskIds?.includes(task)))throw Error('The pending approval did not belong to the test task');
    return card.id;
  });
  assert.equal(await page.locator('.settings-sheet:visible').count(),1);
  await badge(1);
  const settled=await page.evaluate(id=>window.ArchHubAPI.decline(id),review);
  assert.equal(settled.status,'declined');
  await badge(0);
  assert.deepEqual(problems,[]);
});
