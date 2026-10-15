const test=require('node:test');
const assert=require('node:assert/strict');
const {mountStudio}=require('./studio_home3_helpers.cjs');
test('082 Home shows a truthful empty finishing state and exactly one bottom composer',async()=>{
 const ui=await mountStudio();try{
 await ui.settle();await ui.settle();
 assert.ok(ui.doc.querySelector('[data-home-design="082"]'),'082 replaces prior Home');
 assert.match(ui.doc.querySelector('[data-home-heading]').textContent,/No tasks in flight/);
 assert.match(ui.doc.body.textContent,/Start something/);
 assert.equal(ui.doc.querySelectorAll('textarea[aria-label="Start a new session"]').length,1);
 assert.equal(ui.doc.querySelector('[data-home-composer]').style.marginTop,'auto');
 assert.equal(ui.doc.querySelector('[data-home-programs]'),null);
 assert.equal(ui.doc.querySelector('[data-home-agents]'),null);
 assert.match(ui.doc.querySelector('[data-home-templates]').textContent,/No saved composite templates/);
 }finally{ui.close();}
});

const workflow=(root,state='running',extra={})=>({root,title:'Stored '+root,state,approval:{current:true},...extra});
const snapshot=(workflows)=>({workshop:{root:'room-a',graph_id:'graph-a',scope_root:'scope-a',can_send:true,messages:[],participants:[],workflows}});
test('finishing count comes from distinct Workshop work, and results are terminal only',async()=>{
 const ui=await mountStudio({snapshot:snapshot([workflow('first'),workflow('second'),workflow('done','done',{result_summary:'Actual proof ready',completed_at:'2026-10-15T10:00:00Z'})])});
 try{await ui.settle();assert.match(ui.doc.querySelector('[data-home-heading]').textContent,/finishing 2 things/);
 assert.deepEqual([...ui.doc.querySelectorAll('[data-home-result]')].map(el=>el.dataset.homeResult),['done']);
 assert.match(ui.doc.querySelector('[data-home-result]').textContent,/Actual proof ready/);
 }finally{ui.close();}
});
test('templates are ordered by real run count and Start invokes the existing group owner once',async()=>{
 const templates=[{id:'low',title:'Stored low',run_count:2,child_count:2,children:[{title:'Read'},{title:'Write'}]},
 {id:'high',title:'Stored high',run_count:19,child_count:3,children:[{title:'Read'},{title:'Check'},{title:'Publish'}]}];
 let release;const pending=new Promise(resolve=>release=resolve);const calls=[];
 const ui=await mountStudio({templates,owner:{startHomeTemplate:async id=>{calls.push(id);await pending;return {ok:true,root:'group',children:['a','b','c']};}}});
 try{await ui.settle();await ui.settle();assert.deepEqual([...ui.doc.querySelectorAll('[data-home-template]')].map(el=>el.dataset.homeTemplate),['high','low']);
 ui.win.ReactDOM.flushSync(()=>{ui.doc.querySelector('[data-template-start="high"]').click();ui.doc.querySelector('[data-template-start="high"]').click();});
 assert.deepEqual(calls,['high']); release();await ui.settle();
 }finally{release();ui.close();}
});
const packageFlow=()=>workflow('package','review',{approval:{current:false},digest:'d'.repeat(64),package:{available:true,destination:'03.PUBLISHED/Reviewed set',sheets:[
 {id:'sheet-1',name:'Stored sheet.pdf',path:'/fixture/Stored sheet.pdf',thumbnail_url:'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='}]}});
test('one set-approve shows actual supplied sheet thumbnails and issues through approve then execute',async()=>{
 const calls=[];const ui=await mountStudio({snapshot:snapshot([packageFlow()]),owner:{workshopWorkflow:async(root,action,fields)=>{calls.push({root,action,fields});return {ok:true,pending:{},publication:action==='workflow-execute'?{receipt:'receipt',destination:packageFlow().package.destination,files:['Stored sheet.pdf']}:undefined};}}});
 try{await ui.settle();const card=ui.doc.querySelector('[data-approval-variant="set-approve"]');assert.ok(card);
 assert.equal(ui.doc.querySelectorAll('[data-home-results] [data-approval-component]').length,1);
 assert.equal(card.querySelector('img').alt,'Stored sheet.pdf');
 assert.equal(card.querySelector('img').style.width,'100%');
 ui.win.ReactDOM.flushSync(()=>card.querySelector('[data-approval-open-sheets]').click());
 assert.equal(card.querySelector('[role="tab"]').textContent,'PDF sheets');
 assert.match(card.querySelector('[role="tabpanel"]').textContent,/Stored sheet.pdf/);
 ui.win.ReactDOM.flushSync(()=>{card.querySelector('[data-workshop-primary="approve"]').click();card.querySelector('[data-workshop-primary="approve"]').click();});
 await ui.settle();await ui.settle();assert.deepEqual(calls.map(row=>row.action),['workflow-approve','workflow-execute']);
 assert.equal(calls[0].fields.digest,'d'.repeat(64));
 assert.equal(card.querySelector('[data-workshop-primary="approve"]').disabled,true);
 }finally{ui.close();}
});
test('accepted approval is never replayed after publication refusal',async()=>{
 const calls=[];const ui=await mountStudio({snapshot:snapshot([packageFlow()]),owner:{workshopWorkflow:async(root,action)=>{calls.push(action);if(action==='workflow-execute')throw Error('transport unavailable');return {ok:true};}}});
 try{await ui.settle();const button=ui.doc.querySelector('[data-home-results] [data-workshop-primary="approve"]');
 ui.win.ReactDOM.flushSync(()=>button.click());await ui.settle();await ui.settle();
 assert.match(ui.doc.querySelector('[data-home-results] [role="alert"]').textContent,/Approval recorded.*transport unavailable/);
 ui.win.ReactDOM.flushSync(()=>button.click());await ui.settle();assert.deepEqual(calls,['workflow-approve','workflow-execute']);
 assert.equal(button.textContent,'Approval recorded');
 }finally{ui.close();}
});
test('rail DOM keeps the same eight destinations across Home and every screen',async()=>{
 const ui=await mountStudio();try{await ui.settle();const rail=ui.doc.querySelector('[data-app-rail]');
 const shape=()=>[...rail.querySelectorAll('[data-rail-panel]')].map(el=>[el.tagName,el.getAttribute('aria-label'),el.dataset.railPanel]);
 const baseline=shape();assert.deepEqual(baseline.map(row=>row[2]),['Home','Chats','Workshop','Canvas','Library','Docs','Settings','Account']);
 for(const name of ['Chats','Workshop','Canvas','Library','Docs','Settings','Account','Home']){
 const el=rail.querySelector('[data-rail-panel="'+name+'"]');ui.win.ReactDOM.flushSync(()=>el.click());await ui.settle();
 assert.equal(ui.doc.querySelectorAll('[data-app-rail]').length,1,name+' has one rail');
 assert.equal(ui.doc.querySelector('[data-app-rail]'),rail,name+' preserves same DOM element');assert.deepEqual(shape(),baseline,name+' preserves all destination DOM');
 }
 }finally{ui.close();}
});
test('grep court: Home rows originate in store projections, with no plate or constant data imports',()=>{
 const {read}=require('./studio_home3_helpers.cjs');const source=read('nodelang/studio/studio-lm.jsx');
 const home=source.slice(source.indexOf('const homeMissionProjection'),source.indexOf('const Chip ='));
 for(const forbidden of ['_SEED_','Submittal 07','Tower B','ran 33','Mona','Programs grid','BABOOM panel'])assert.equal(home.includes(forbidden),false,forbidden);
 assert.match(home,/window\.ARCHHUB_WORKSHOP_MODEL/);assert.match(home,/owner\.readHomeTemplates\(\)/);assert.match(home,/mission\.results/);assert.match(home,/mission\.inFlight/);
});

test('Ctrl+K exposes the same visible template Start control',async()=>{
 const ui=await mountStudio({templates:[{id:'saved',title:'Persisted job',run_count:4,child_count:1,children:[{title:'Read'}]}]});
 try{await ui.settle();await ui.settle();
 ui.win.ReactDOM.flushSync(()=>ui.win.dispatchEvent(new ui.win.KeyboardEvent('keydown',{key:'k',ctrlKey:true,bubbles:true})));
 await ui.settle();const command=[...ui.doc.querySelectorAll('button')].find(el=>el.textContent.includes('Start · Persisted job'));
 assert.ok(command,'palette has saved template');ui.win.ReactDOM.flushSync(()=>command.click());await ui.settle();
 assert.deepEqual(ui.ownerCalls.filter(row=>row[0]==='startHomeTemplate'),[['startHomeTemplate','saved']]);
 }finally{ui.close();}
});

test('approval receipt stays visible when the actual store removes its needs-user card before execution settles',async()=>{
 let ui;const calls=[];
 ui=await mountStudio({snapshot:snapshot([packageFlow()]),owner:{workshopWorkflow:async(root,action)=>{
 calls.push(action);if(action==='workflow-approve'){ui.update(state=>{state.workshop={...state.workshop,workflows:[{...packageFlow(),approval:{current:true}}]};});return {ok:true};}
 await new Promise(resolve=>setTimeout(resolve,20));throw Error('writer unavailable');
 }}});
 try{await ui.settle();ui.win.ReactDOM.flushSync(()=>ui.doc.querySelector('[data-home-results] [data-workshop-primary="approve"]').click());
 await ui.settle();await ui.settle();assert.match(ui.doc.querySelector('[data-home-results] [role="alert"]')?.textContent || '',/Approval recorded.*writer unavailable/);
 assert.deepEqual(calls,['workflow-approve','workflow-execute']);assert.match(ui.doc.querySelector('[data-home-decision-receipt]').textContent,/Approval recorded/);
 }finally{ui.close();}
});

test('after issuance removes the first card the next real approval is reachable',async()=>{
 let ui;const second={...packageFlow(),root:'next-package',title:'Next stored package'};
 ui=await mountStudio({snapshot:snapshot([packageFlow(),second]),owner:{workshopWorkflow:async(root,action)=>{
 if(action==='workflow-approve')ui.update(state=>{state.workshop={...state.workshop,workflows:[{...packageFlow(),approval:{current:true}},second]};});
 return {ok:true,pending:{},publication:action==='workflow-execute'?{receipt:'receipt',destination:packageFlow().package.destination,files:['Stored sheet.pdf']}:undefined};
 }}});
 try{await ui.settle();ui.win.ReactDOM.flushSync(()=>ui.doc.querySelector('[data-home-results] [data-workshop-primary="approve"]').click());
 await ui.settle();await ui.settle();assert.equal(ui.doc.querySelector('[data-home-results] [data-workshop-approval-card]').dataset.workshopApprovalCard,'next-package');
 assert.equal(ui.doc.querySelector('[data-home-results] [data-workshop-primary="approve"]').disabled,false);
 assert.match(ui.doc.querySelector('[data-home-decision-receipt]').textContent,/Package issued/);
 }finally{ui.close();}
});
