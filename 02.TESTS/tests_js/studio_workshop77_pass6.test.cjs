const {test}=require('node:test');
const assert=require('node:assert/strict');

const {plateFixture}=require('./workshop77_plate_fixture.cjs');
const {renderModels}=require('./workshop77_render_models.cjs');

test('PASS6 render fixture reads free entries through the real catalogue; synthetic court ids stay intact',()=>{
  const models=Array.from({length:3},(_,i)=>({route:`provider/model-${i}:free`,name:`Catalogue entry ${i}`,cost:'free'}));let called=false;
  const rows=renderModels((exe,args,options)=>{called=true;assert.match(args[1],/from nodelang.model_catalogue import openrouter_models/);assert.match(args[1],/opener=urllib.request.urlopen/);assert.equal(options.cwd, require('node:path').resolve(__dirname, '..', '..'));return {status:0,stdout:JSON.stringify(models)};});
  assert.ok(called);const f=plateFixture({models:rows});
  assert.deepEqual(f.state.workshop.participants.filter(a=>a.is_agent).map(a=>a.model),models.map(a=>a.route));
  assert.deepEqual(f.state.workshopPresentation.models.groups[0].items.map(a=>a.name),models.map(a=>a.name));
  assert.equal(plateFixture().state.workshop.participants[1].model,'registry-a');
  assert.throws(()=>renderModels(()=>({status:1})),/catalogue unavailable/);
  assert.throws(()=>renderModels(()=>({status:0,stdout:'[]'})),/three free/);
});
