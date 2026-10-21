const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..', '..');
const read = name => fs.readFileSync(path.join(root,name),'utf8');
async function main() {
  const seedText=read('01.APP/nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
  const theme=Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m=>[m[1],m[2]]));
  const session={app:'codex',runtime:'codex',session_id:'app:agent-session:runtime:isolated-court-august7',title:'codex Agent Session',issued_at:1792288800,connected:true,selectable:true};
  const state={ok:true,boot:'match',projection:'match',key_pinned:true,revision:1,
    built_in:{id:'archhub',path:'C:\\Isolated court\\ArchHub'},promise:'Removing a workspace only stops ArchHub from governing it. Your files are never deleted.',
    roots:[{root_id:'bbc4-court',path:'D:\\Isolated court\\August 7 sheets',privacy:'private',writers:['codex'],state:'registered'}],
    private_grant_defaults:{operations:['edit_file','apply_patch','write_file','create'],expires_after_seconds:2592000},
    private_grants:[],private_grant_sessions:{status:'ok',sessions:[session]}};
  const calls=[];
  const hostStyle=read('01.APP/nodelang/studio/studio.html').match(/<style>([\s\S]*?)<\/style>/)[1];
  const faceBlock=read('01.APP/nodelang/site_export.py').match(/^FONT_FACES = \(([\s\S]*?)^\)/m)[1];
  const faces=[...faceBlock.matchAll(/\("([^"]+)", "([^"]+)", "([^"]+)", "([^"]+)"\)/g)];
  const fontCss=faces.map(([,name,family,style,weight])=>`@font-face{font-family:"${family}";font-style:${style};font-weight:${weight};font-display:swap;src:url(/assets/fonts/${name}) format("woff2")}`).join('\n');
  const server=http.createServer((req,res)=>{
    if(req.url==='/assets/fonts.css'){res.writeHead(200,{'Content-Type':'text/css'});return res.end(fontCss);}
    const face=faces.find(row=>req.url==='/assets/fonts/'+row[1]);
    if(face){res.writeHead(200,{'Content-Type':'font/woff2'});return res.end(fs.readFileSync(path.join(root,'01.APP/nodelang/data/website/fonts',face[1])));}
    res.writeHead(200,{'Content-Type':'text/html'});return res.end(`<!doctype html><html><head><style>${hostStyle}</style><link rel="stylesheet" href="/assets/fonts.css"></head><body><div id="root"></div></body></html>`);
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  let browser;
  try {
    browser=await chromium.launch({headless:true});
    const context=await browser.newContext({viewport:{width:1500,height:1100},colorScheme:'dark'});
    const page=await context.newPage();
    await page.route('**/api/universal/**',async route=>{
      const req=route.request();let answer;
      if(req.url().includes('/workspace-roots')) {
        const body=req.postDataJSON();calls.push(body);
        if(body.action==='grant-private-root') {
          state.private_grants=[{root_id:body.id,runtime:body.runtime,session_id:body.session_id,operations:state.private_grant_defaults.operations,expires_at:1794880800}];
          state.last_private_grant_event={action:body.action,message:'unverifiable document set aside as private-root-grants.unverifiable-isolated-court.json'};
        } else if(body.action==='revoke-private-root') {state.private_grants=[];state.last_private_grant_event={action:body.action,message:'Agent access revoked.'};}
        answer=state;
      } else answer={ok:true,connectors:[],operations:[],groups:[]};
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(answer)});
    });
    await page.route('**/tools',r=>r.fulfill({json:{tools:[]}}));
    await page.route('**/waiting',r=>r.fulfill({json:{items:[]}}));
    await page.goto('http://127.0.0.1:'+server.address().port);
    await page.evaluate(theme=>{window.ARCHHUB_THEME=theme;window.ARCHHUB_LIVE={hosts:[],connectors:[],skills:[],memory:[],graph:{nodes:[],wires:[]}};window.__archhubSession={token:'isolated-court',csrf:'isolated-court'};},theme);
    for(const name of ['vendor/react.js','vendor/react-dom.js'])await page.addScriptTag({path:path.join(root,'01.APP/nodelang/studio',name)});
    const manifest=JSON.parse(read('01.APP/nodelang/studio/compiled/manifest.json'));
    for(const file of manifest.files)if(file.source!=='mount.jsx')await page.addScriptTag({path:path.join(root,'01.APP/nodelang/studio/compiled',file.output)});
    await page.evaluate('ReactDOM.createRoot(document.getElementById("root")).render(React.createElement(StudioLM))');
    await page.evaluate(()=>document.fonts.ready);
    await page.locator('[title="Settings"]').click();
    await page.locator('[data-settings54-group-title]').filter({hasText:/^Permissions$/}).click();
    await page.locator('[data-settings54-capability-nav] button').filter({hasText:/^Workspaces$/}).click();
    await page.getByRole('button',{name:'Grant agent access',exact:true}).click();
    await page.locator('[data-private-session]').waitFor();
    await page.screenshot({path:path.join(root,'05.EVIDENCE/privgrant/picker.png'),fullPage:true});
    await page.locator('[data-private-session]').click();
    await page.getByRole('dialog',{name:'Confirm agent access'}).waitFor();
    const preview=await page.getByRole('dialog',{name:'Confirm agent access'}).boundingBox();
    assert.ok(preview && preview.y>=0 && preview.y+preview.height<=1100,'entire consent preview must fit the isolated Studio viewport');
    await page.screenshot({path:path.join(root,'05.EVIDENCE/privgrant/confirmation.png'),fullPage:true});
    await page.getByRole('button',{name:'Confirm grant',exact:true}).click();
    await page.locator('[data-private-grant]').waitFor();
    await page.screenshot({path:path.join(root,'05.EVIDENCE/privgrant/granted.png'),fullPage:true});
    assert.deepEqual(calls.find(c=>c.action==='grant-private-root'),{action:'grant-private-root',id:'bbc4-court',runtime:'codex',session_id:session.session_id});
    await page.getByRole('button',{name:'Revoke',exact:true}).click();
    await page.locator('[data-private-grant]').waitFor({state:'detached'});
    assert.deepEqual(calls.find(c=>c.action==='revoke-private-root'),{action:'revoke-private-root',id:'bbc4-court',runtime:'codex',session_id:session.session_id});
    await page.screenshot({path:path.join(root,'05.EVIDENCE/privgrant/revoked.png'),fullPage:true});
    fs.writeFileSync(path.join(root,'05.EVIDENCE/privgrant/screenshot-requests.json'),JSON.stringify(calls,null,2));
    console.log('PRIVGRANT screenshots: picker, confirmation, granted, revoked; isolated browser profile; exact grant/revoke payloads.');
    await context.close();
  } finally {if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
