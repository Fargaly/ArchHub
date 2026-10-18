/* Independent mounted production controller: archive Older stays an opaque read. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createHash} = require('node:crypto');
const context = vm.createContext({URLSearchParams, TextEncoder});
vm.runInContext(fs.readFileSync(path.join(__dirname,
  '../nodelang/studio/studio-existing-workshop.js'), 'utf8'), context);
const plain = value => JSON.parse(JSON.stringify(value));
const position = offset => 'a1:' + offset + ':7:' + createHash('sha256')
  .update(JSON.stringify(['a1', ['graph-a', 'instance-a', 'workshop-a', 'scope-a', 'owner-a', 'view-a', true], offset, 7]))
  .digest('hex');
const page = (change={}) => ({ok:true, graph_id:'graph-a', root:'workshop-a', scope_root:'scope-a',
  revision:4, owner:'owner-a', view:'view-a', self:'owner-a', can_send:true, can_join:false,
  participants:[{root:'owner-a', label:'Owner', attached:true}], storage:'conversation-content',
  feed:'all', content_cursor:'c1:ordinary-position', page_before:null, total:1,
  has_older:true, next_before:position(0), messages:[{root:'original-message', sequence:1,
    sender_root:'owner-a', body:'Recent original message', state:'sent', category:'note'}], ...change});

test('Older follows the returned a1 token into a bounded read-only aggregate and Latest recovers', async()=>{
  const gets=[], posts=[], retained=new Map();
  const archived = offset => page({can_send:false, can_manage_history:false,
    page_before:position(offset), content_cursor:'c1:archive-position', total:1,
    has_older:offset===0, next_before:offset===0?position(16384):null,
    messages:[{root:'trace-archive:independent-session', message_id:'trace-archive:independent-session',
      sequence:1, sender_root:'Conversation archive', recipient_root:'Local archive', recipient_roots:[],
      body:'Archived conversation (read only)\n\n' + (offset===0?'Unique cold testimony':'Second cold chunk'),
      state:'archived', category:'archive', archive_projection:true}]});
  const api = context.ArchHubExistingWorkshop.create({
    pendingStorage:{getItem:key=>retained.get(key)||null, setItem:(key,value)=>retained.set(key,value)},
    uuid:()=> 'independent-message', hash:async value=>createHash('sha256').update(value).digest('hex'),
    get:async url=>{
      gets.push(url);
      const query=new URL(url,'http://independent.test').searchParams;
      if(!query.has('before')) return page();
      assert.equal(query.get('root'),'workshop-a'); assert.equal(query.get('scope'),'scope-a');
      const token=query.get('before');
      assert.ok([position(0),position(16384)].includes(token),token);
      return archived(token===position(0)?0:16384);
    },
    post:async(url,body)=>{posts.push({url,body}); throw new Error('Archive navigation cannot post.');}});
  api.setCanvas({graph_id:'graph-a',root:'scope-a',revision:4,
    workshops:[{root:'workshop-a',label:'Workshop',send_category:'note'}]});
  await api.refreshWorkshop('workshop-a');
  assert.equal(api.getSnapshot().workshop.messages[0].root,'original-message');
  await api.loadOlderWorkshop('workshop-a');
  let shown=plain(api.getSnapshot().workshop);
  assert.equal(new URL(gets[1],'http://independent.test').searchParams.get('before'),position(0));
  assert.equal(shown.page_before,position(0)); assert.equal(shown.can_send,false);
  assert.equal(shown.can_manage_history,false); assert.equal(shown.messages.length,1);
  assert.equal(shown.messages[0].archive_projection,true);
  assert.equal(shown.messages[0].body,'Archived conversation (read only)\n\nUnique cold testimony');
  assert.equal(shown.messages.some(row=>row.root==='original-message'),false);
  await assert.rejects(api.sendWorkshopMessage('workshop-a',
    {target:'',message:'Must not post from the archive'}),/Refresh.*before sending/);
  assert.equal(posts.length,0);
  await api.loadOlderWorkshop('workshop-a');
  shown=plain(api.getSnapshot().workshop);
  assert.equal(new URL(gets[2],'http://independent.test').searchParams.get('before'),position(16384));
  assert.equal(shown.messages.length,1); assert.ok(shown.messages[0].body.endsWith('Second cold chunk'));
  assert.equal(shown.has_older,false); assert.equal(shown.next_before,null);
  await api.showLatestWorkshop('workshop-a');
  assert.equal(api.getSnapshot().workshop.messages[0].root,'original-message');
  assert.equal(api.getSnapshot().workshop.can_send,true);
  assert.equal(new URL(gets[3],'http://independent.test').searchParams.has('before'),false);
  assert.equal(posts.length,0); assert.equal(retained.size,0);
});

test('Older follows opaque a2 positions across sessions without merging sequence-one aggregates', async()=>{
  const sessions=['app:agent-session:reader-agent','app:baboom-session:reader-baboom'];
  const identity=['graph-a','instance-a','workshop-a','scope-a','owner-a','view-a',true];
  const tokenFor=session=>{
    const encoded=Buffer.from(session,'utf8').toString('base64url');
    const signature=createHash('sha256').update(JSON.stringify(['a2',identity,encoded,0,3])).digest('hex');
    return `a2:${encoded}:0:3:${signature}`;
  };
  const tokens=sessions.map(tokenFor), gets=[], posts=[];
  const api=context.ArchHubExistingWorkshop.create({
    pendingStorage:{getItem:()=>null,setItem:()=>assert.fail('archive text must not be persisted')},
    uuid:()=> 'nonroom-review', hash:async value=>createHash('sha256').update(value).digest('hex'),
    get:async url=>{
      gets.push(url);
      const query=new URL(url,'http://independent.test').searchParams;
      if(!query.has('before')) return page({next_before:tokens[0]});
      const index=tokens.indexOf(query.get('before'));
      assert.ok(index>=0,'the exact returned a2 position must be passed unchanged');
      return page({can_send:false,can_manage_history:false,page_before:tokens[index],
        content_cursor:'same-bounded-archive-cursor',has_older:index===0,
        next_before:index===0?tokens[1]:null,messages:[{
          root:'trace-archive:'+index,message_id:'trace-archive:'+index,sequence:1,
          sender_root:'Conversation archive',recipient_root:'Local archive',recipient_roots:[],
          body:`Archived session ${sessions[index]} (read only)\n\nUnique session text ${index}`,
          category:'archive',state:'archived',archive_projection:true}]});
    },
    post:async(url,body)=>{posts.push({url,body});assert.fail('a2 navigation cannot post');}});
  api.setCanvas({graph_id:'graph-a',root:'scope-a',revision:4,
    workshops:[{root:'workshop-a',label:'Workshop',send_category:'note'}]});
  await api.refreshWorkshop('workshop-a');
  await api.loadOlderWorkshop('workshop-a');
  assert.equal(new URL(gets[1],'http://independent.test').searchParams.get('before'),tokens[0]);
  assert.equal(api.getSnapshot().workshop.messages[0].root,'trace-archive:0');
  await api.loadOlderWorkshop('workshop-a');
  const shown=plain(api.getSnapshot().workshop);
  assert.equal(new URL(gets[2],'http://independent.test').searchParams.get('before'),tokens[1]);
  assert.equal(shown.page_before,tokens[1]); assert.equal(shown.messages.length,1);
  assert.equal(shown.messages[0].root,'trace-archive:1');
  assert.ok(shown.messages[0].body.includes(sessions[1]));
  assert.equal(shown.messages[0].body.includes('Unique session text 0'),false);
  assert.equal(shown.can_send,false); assert.equal(shown.can_manage_history,false);
  assert.equal(shown.has_older,false); assert.equal(shown.next_before,null);
  await assert.rejects(api.sendWorkshopMessage('workshop-a',
    {target:'',message:'No send from another session archive'}),/Refresh.*before sending/);
  await api.showLatestWorkshop('workshop-a');
  assert.equal(api.getSnapshot().workshop.messages[0].root,'original-message');
  assert.equal(posts.length,0);
});
