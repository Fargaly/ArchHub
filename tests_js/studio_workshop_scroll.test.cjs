const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(process.env.ARCHHUB_WORKSPACE_TEST_PATH ||
  path.join(__dirname, '../nodelang/studio/studio-workshop.jsx'), 'utf8');
const start = source.indexOf('const createWorkshopMessageScroll =');
const end = source.indexOf('// The conversation panel is a live lens', start);
assert.ok(start > 0 && end > start);
const context = vm.createContext({});
vm.runInContext(source.slice(start,end) + '\nglobalThis.create = createWorkshopMessageScroll;',context);

// Actual controller with explicit layout geometry; no browser layout claim.
function fixture() {
  let messages = [], position = 0;
  const events = [];
  const viewport = {clientHeight:200, clientTop:0,
    get scrollHeight() {return messages.reduce((sum,row)=>sum+row.height,0);},
    get scrollTop() {return position;},
    set scrollTop(value) {position=Math.max(0,Math.min(value,this.scrollHeight-this.clientHeight));},
    getBoundingClientRect:()=>({top:20}),
    querySelectorAll:()=>{
      let offset=0;
      return messages.map(row=>{
        const rowTop=offset; offset+=row.height;
        return {getAttribute:()=>row.root,getBoundingClientRect:()=>({
          top:20+rowTop-position,bottom:20+rowTop+row.height-position})};
      });
    },
  };
  const control=context.create(value=>events.push(value));
  return {viewport,control,events,
    rows:(ids,height=100)=>{messages=ids.map(root=>({root,height}));},
    resize:(root,height)=>{messages.find(row=>row.root===root).height=height;},
    userScroll:value=>{viewport.scrollTop=value;control.scroll(viewport);},
    offset:root=>viewport.querySelectorAll().find(row=>row.getAttribute()===root).getBoundingClientRect().top-20,
  };
}

test('latest waits for success then follows bottom; reading up preserves the same row through bounded tail replacement',()=>{
  const f=fixture();f.rows(['a','b','c','d','e']);
  f.control.update(f.viewport,'room/view/latest',false,false);
  assert.equal(f.viewport.scrollTop,0);
  f.control.update(f.viewport,'room/view/latest',true,false);
  assert.equal(f.viewport.scrollTop,300);
  f.rows(['b','c','d','e','f']);f.control.update(f.viewport,'room/view/latest',true,false);
  assert.equal(f.viewport.scrollTop,300);
  f.userScroll(125);assert.equal(f.offset('c'),-25);
  f.rows(['c','d','e','f','g']);f.control.update(f.viewport,'room/view/latest',true,false);
  assert.equal(f.viewport.scrollTop,25);assert.equal(f.offset('c'),-25);
  f.control.scroll(f.viewport); // The programmatic scroll event cannot change intent.
  f.rows(['c','d','e','f','g','h']);f.control.update(f.viewport,'room/view/latest',true,false);
  assert.equal(f.viewport.scrollTop,25);
  assert.deepEqual(f.events,[true]);
  f.control.jump(f.viewport);assert.equal(f.viewport.scrollTop,400);
  assert.deepEqual(f.events,[true,false]);
});

test('font and viewport reflow preserve reader anchor; explicit older pages start at top and never follow',()=>{
  const f=fixture();f.rows(['a','b','c','d','e']);
  f.control.update(f.viewport,'latest',true,false);f.userScroll(125);
  f.resize('a',180);f.control.reflow(f.viewport);
  assert.equal(f.offset('b'),-25);assert.equal(f.viewport.scrollTop,205);
  f.viewport.clientHeight=250;f.control.reflow(f.viewport);assert.equal(f.offset('b'),-25);
  f.rows(['old-a','old-b','old-c','old-d']);f.control.update(f.viewport,'older-token',true,true);
  assert.equal(f.viewport.scrollTop,0);
  f.userScroll(150);f.rows(['old-a','old-b','old-c','old-d','old-e']);
  f.control.update(f.viewport,'older-token',true,true);assert.equal(f.viewport.scrollTop,150);
  f.control.jump(f.viewport);assert.equal(f.viewport.scrollTop,150);
  f.rows(['new-a','new-b','new-c','new-d']);f.control.update(f.viewport,'latest',true,false);
  assert.equal(f.viewport.scrollTop,150);
});

test('evicted anchors clamp without acquiring follow intent; error gaps and owner/room reset stay distinct',()=>{
  const f=fixture();f.rows(['a','b','c','d','e']);
  f.control.update(f.viewport,'owner-a/room-a/latest',true,false);f.userScroll(125);
  f.rows(['x','y','z']);f.control.update(f.viewport,'owner-a/room-a/latest',true,false);
  assert.equal(f.viewport.scrollTop,100);f.control.scroll(f.viewport);
  f.rows(['x','y','z','next']);f.control.update(f.viewport,'owner-a/room-a/latest',true,false);
  assert.equal(f.viewport.scrollTop,100);assert.deepEqual(f.events,[true]);
  f.rows([]);f.control.update(f.viewport,'error-without-identity',false,false);
  f.rows(['x','y','z','next']);f.control.update(f.viewport,'owner-a/room-a/latest',true,false);
  assert.equal(f.viewport.scrollTop,100);
  f.control.update(f.viewport,'owner-b/room-a/latest',true,false);
  assert.equal(f.viewport.scrollTop,200);assert.deepEqual(f.events,[true,false]);
});
