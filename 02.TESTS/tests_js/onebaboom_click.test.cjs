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
    ARCHHUB_TEST_STATE_DIR:path.join(profile,'state'),ARCHHUB_TEST_SECRET_STORE:'memory'};
  const python=process.env.ARCHHUB_COURT_PYTHON ||
    path.join(process.env.LOCALAPPDATA,'ArchHub','.venv','Scripts','python.exe');
  const code=[
    'import json, os, sys',
    'from nodelang.nograph_server import NoGraphServer',
    'server=NoGraphServer(os.environ["ARCHHUB_TEST_STATE_DIR"], port=0).start()',
    'print(json.dumps({"url":server.public_url,"bootstrap":server.browser_bootstrap_token}),flush=True)',
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
  // One joined agent, so the To list has a recipient that is not BABOOM.
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
          if(!views.has(current))views.set(current,{...current,liveAgents:[{agent:'Claude Code / drawings / session-abcdef12',
            name:'Drawing reviewer',handle:'drawing-reviewer',app:'claude',status:'working',task:'Reviews the drawing set',session:'court-1'}]});
          return views.get(current);
        }};
      },
    });
  });
  await page.goto(server.url+'/studio?bootstrap='+server.bootstrap,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.querySelector('.boot-evidence:not([hidden])')||
    !document.getElementById('studio-boot')&&document.querySelector('[data-home-page]'));
  assert.deepEqual(await page.locator('.boot-evidence:not([hidden])').allTextContents(),[]);
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
  assert.equal(await recipient.textContent(),'@BABOOM','the opening click points the composer at BABOOM');
  assert.equal(await page.evaluate(()=>document.activeElement.closest('[data-design="composer.surface"]')!==null&&
    document.activeElement.tagName),'TEXTAREA','with the caret in it');
  assert.equal(await panel.locator('textarea,input').count(),0,'his panel has no input of its own');

  await pick('Drawing reviewer');                  // he goes back to the other agent, the panel still open
  await click();                                   // closes his panel
  await panel.waitFor({state:'detached'});
  assert.equal(await recipient.textContent(),'@Drawing reviewer','the closing click leaves the recipient alone');
  assert.deepEqual(problems,[]);
});
