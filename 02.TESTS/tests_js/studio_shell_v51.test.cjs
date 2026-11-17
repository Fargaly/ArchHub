const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require('playwright');

test('BABOOM opens from the tray and its panel and Home avatars stay in bounds', {timeout:120000}, async t=>{
  const root=path.resolve(__dirname,'../..'), app=path.join(root,'01.APP');
  const output=process.env.ARCHHUB_SHELL_EVIDENCE;
  const cache=path.join(root,'.cache');
  fs.mkdirSync(cache,{recursive:true});
  const profile=fs.mkdtempSync(path.join(cache,'baboom-shell-'));
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
  const page=await browser.newPage({viewport:{width:900,height:900}});
    page.setDefaultTimeout(12000);
    page.on('pageerror',error=>problems.push(error.message));
    await page.route('**/*',route=>new URL(route.request().url()).origin===server.url?
      route.continue():route.abort());
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
            if(!views.has(current))views.set(current,{...current,tasks:[...current.tasks,{
              id:'shell-review',status:'WIP',title:'Review drawing changes',messages:[],
              owner:'Studio Architect',updated_at:new Date().toISOString(),
              members:['Studio Architect','Site Observer','Envelope Planner','Safety Officer'].map(name=>({name})),
            }]});
            return views.get(current);
          }};
        },
      });
    });
  await page.goto(server.url+'/studio?bootstrap='+server.bootstrap,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.querySelector('.boot-evidence:not([hidden])')||
    !document.getElementById('studio-boot')&&document.querySelector('[data-home-page]'));
  const bootFailure=await page.locator('.boot-evidence:not([hidden])').allTextContents();
  assert.deepEqual(bootFailure,[]);
  for(const width of [900,1009,1440,1920]){
      await page.setViewportSize({width,height:900});
      const rail=page.getByRole('navigation',{name:'Main navigation'});
      const railPet=rail.getByRole('button',{name:'BABOOM',exact:true});
      const session=page.locator('.resume-row').filter({hasText:'Review drawing changes'});
      const peek=page.getByRole('button',{name:'Open the list',exact:true});
      if(await peek.isVisible())await peek.click();
      await session.locator('.resume-members').waitFor({state:'visible'});
      const row=await session.evaluate(element=>{
        const box=element.getBoundingClientRect();
        const pane=element.closest('.resume-session-scroll').getBoundingClientRect();
        const chips=[...element.querySelectorAll('.resume-members>*')].map(chip=>chip.getBoundingClientRect());
        const controls=[...element.querySelectorAll('.resume-pin,.resume-hide')].map(button=>button.getBoundingClientRect());
        return {count:chips.length,clipped:chips.some(chip=>chip.left<Math.max(box.left,pane.left)-1||
          chip.right>Math.min(box.right,pane.right)+1||chip.bottom>box.bottom+1),
          overlap:chips.some((chip,index)=>controls.concat(chips.slice(index+1)).some(button=>chip.left<button.right&&chip.right>button.left&&
            chip.top<button.bottom&&chip.bottom>button.top))};
      });
      if(output)await page.screenshot({path:path.join(output,width+'-companion-closed.png')});
      if(row.count!==3||row.clipped||row.overlap)problems.push(width+' px session avatars '+JSON.stringify(row));
      if(await railPet.count()){
        problems.push(width+' px: BABOOM occupies a navigation tile');
        await railPet.click();
      }else{
        await page.getByRole('button',{name:'Tray menu',exact:true}).click();
        await page.getByText('BABOOM',{exact:true}).last().click();
      }
      const bubble=page.locator('[aria-label="BABOOM companion"]');
      await bubble.waitFor();
      if(output)await page.screenshot({path:path.join(output,width+'-companion-open.png')});
      const geometry=await bubble.evaluate(element=>{
        const outer=element.getBoundingClientRect();
        const buttons=[...element.querySelectorAll('header button,.pbacts button,button[type=submit],.button-reset')];
        const outside=(box,container)=>box.left<container.left-1||box.right>container.right+1;
        return {horizontalOverflow:element.scrollWidth>element.clientWidth+1,
          viewportOverflow:outer.left<0||outer.right>window.innerWidth||outer.top<0||outer.bottom>window.innerHeight,
          clipped:buttons.filter(button=>{
            const label=document.createRange();
            label.selectNodeContents(button);
            const own=button.getBoundingClientRect();
            return outside(own,outer)||outside(label.getBoundingClientRect(),own);
          }).map(button=>button.getAttribute('aria-label')||button.textContent.trim())};
      });
      if(geometry.horizontalOverflow||geometry.viewportOverflow||geometry.clipped.length)
        problems.push(width+' px BABOOM '+JSON.stringify(geometry));
      await bubble.getByRole('button',{name:'Close BABOOM',exact:true}).click();
      await bubble.waitFor({state:'detached'});
  }
  assert.deepEqual(problems,[]);
});
