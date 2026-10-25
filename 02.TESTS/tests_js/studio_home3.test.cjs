const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const studio=path.resolve(__dirname,'../../01.APP/nodelang/studio');
const read=name=>fs.readFileSync(path.join(studio,name),'utf8');

test('grep court: Home rows originate in store projections, with no plate or constant data imports',()=>{
 const home=read('ds_home2.jsx');
 for(const forbidden of ['_SEED_','Submittal 07','Tower B','ran 33','Mona','Programs grid','BABOOM panel'])assert.equal(home.includes(forbidden),false,forbidden);

});
