const {test} = require('node:test');
const assert = require('node:assert/strict');

test('BABOOM5 native HTML mounts the actual shared Approve card and awaits its channel receipt', async()=>{
  const {execFileSync}=require('node:child_process');
  const {fileURLToPath}=require('node:url');
  const fs=require('node:fs');
  const {JSDOM}=await import('jsdom');
  const html=execFileSync(require('node:path').resolve(__dirname,'../../.venv/Scripts/python.exe'),
    ['-c','from nodelang.baboom_native_companion import baboom_approval_html; print(baboom_approval_html({"title":"Remember","summary":"Remember blue?","state":"needs-user","id":"reviewed"}, "binding-court"))'],{encoding:'utf8',cwd:require('node:path').resolve(__dirname,'../..'),env:{...process.env,PYTHONPATH:require('node:path').resolve(__dirname,'../../01.APP')}});
  const dom=new JSDOM(html,{runScripts:'outside-only',pretendToBeVisual:true});
  const win=dom.window, calls=[], listeners=new Set();
  win.structuredClone=globalThis.structuredClone;
  win.qt={webChannelTransport:{}};
  const bridge={settled:{connect:fn=>listeners.add(fn),disconnect:fn=>listeners.delete(fn)},
    decide:(binding,choice)=>calls.push({binding,choice})};
  win.QWebChannel=function(_,callback){callback({objects:{baboom:bridge}});};
  try {
    for(const script of win.document.querySelectorAll('script')) {
      if(script.src.startsWith('qrc:')) continue;
      win.eval(script.src ? fs.readFileSync(fileURLToPath(script.src),'utf8') : script.textContent);
    }
    for(let i=0;i<50&&!win.document.querySelector('[data-approval="reviewed"]');i++)await new Promise(resolve=>setTimeout(resolve,10));
    const card=win.document.querySelector('[data-approval="reviewed"]');
    const approve=card && [...card.querySelectorAll('button')].find(button=>button.textContent==='Approve once');
    assert.ok(approve,'actual shared card is mounted from production HTML');
    assert.equal(approve.textContent,'Approve once');
    assert.match(card.textContent,/Remember blue\?/);
    approve.click();approve.click();
    await new Promise(resolve=>setTimeout(resolve,20));
    assert.deepEqual(calls,[{binding:'binding-court',choice:'approve'}]);
    assert.equal(approve.disabled,true,'awaits real receipt');
    for(const listener of listeners)listener('binding-court','');
    await new Promise(resolve=>setTimeout(resolve,20));
    assert.equal(approve.disabled,true,'single use after receipt');
  } finally {dom.window.close();}
});
