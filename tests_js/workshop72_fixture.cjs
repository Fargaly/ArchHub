const plain = value => JSON.parse(JSON.stringify(value));
function fixture() {
  const root = 'room-a', work = 'work:labels001', now = Date.now() / 1000;
  const participants = [{root:'owner-a',label:'Owner',is_agent:false,attached:true},
    {root:'agent-a',label:'Claude Code',runtime:'claude',is_agent:true,attached:true,connection_status:'connected',
      connection_basis:'authenticated-request',observed_at:now-1,expires_at:now+600},
    {root:'agent-b',label:'Codex',runtime:'codex',is_agent:true,attached:true,connected:true}];
  const messages = [{root:'ask-a',sender_root:'owner-a',body:'Label the selected elements.',created_at:'2026-10-14T09:00:00Z'},
    {root:'reply-a',sender_root:'agent-a',body:`Claimed Work ${work}. Read the selection.`,agent_text:'Read the selection.',created_at:now}];
  const node = {id:root,cat:'workshop',title:'Label selected elements',x:40,y:40,members:['agent-a','agent-b'],
    ins:[{id:'elements-in',label:'elements',t:'object',multiple:true,connectable:true}],
    outs:[{id:'labels-out',label:'labels',t:'text',multiple:true,connectable:true}]};
  const authorization = {subject:'owner-a',session:'view-a'};
  const state = {canvas:{graph_id:'graph-a',root:'scope-a',revision:4,authorization},
    workshops:[{root,label:node.title}],workshop:{root,ok:true,self:'owner-a',can_send:true,participants,messages,
      assignments:[{work,agent_session:'agent-a'}], reviews:[{workflow:'flow-a',judged_by:'agent-b'}],
      workflows:[{root:'flow-a',title:'Selection labelling',proposed_by:'agent-a',digest:'c'.repeat(64),
        nodes:[{root:'work:read0001',title:'Read selection'},{root:work,title:'Apply labels'},{root:'work:check001',title:'Verify labels'}],
        approval:{current:true}}]},
    nativeWork:{root,scope:'scope-a',owner:'owner-a',view:'view-a',work,mode:'agent',state:'awaiting_approval',approved:false,input_digest:'a'.repeat(64),
      review_expires_at:now+600,result_count:7,output_label:'labels'},
    topology:{canvas:{application_root:'graph-a',scope:{current:'scope-a'},authorization},
      graph:{nodes:[node,{id:'agent-a',title:'Claude Code',group:root},{id:'agent-b',title:'Codex',group:root},
      {id:work,title:node.title,status:'awaiting_approval'},
      {id:'work:read0001',title:'Read selection',status:'done'},{id:'work:check001',title:'Verify labels',status:'planned'}],wires:[]}}};
  const calls = [];
  const spy = name => async (...args) => {calls.push([name,...plain(args)]);};
  const authority = {getSnapshot:() => state,subscribe:() => () => {},refreshWorkshop:spy('refreshWorkshop'),
    beginWorkshopTask:async()=>{calls.push(['beginWorkshopTask',root]);state.workshopTaskDraft={root,graph_id:'graph-a',scope_root:'scope-a',subject:'owner-a',request:'fixture-task'};},
    cancelWorkshopTask:async()=>{state.workshopTaskDraft=null;},
    createWorkshopTask:async(r,details)=>{calls.push(['createWorkshopTask',r,details]);state.workshopTaskDraft=null;
      state.topology.canvas.hidden_work=[...(state.topology.canvas.hidden_work || []),{id:'work:newtask01',engine:'work',title:details.message,status:'planned'}];
      state.workshop.messages.push({root:'new-task-message',sender_root:'owner-a',body:details.message,reference_roots:['work:newtask01'],created_at:Date.now()/1000});
      return {created_root:'work:newtask01'};},
    refreshNativeWork:spy('refreshNativeWork'),nativeAgents:async () => ({contacts:[]}),
    approveNativeWork:spy('approveNativeWork'),nativeWorkAction:spy('nativeWorkAction'),
    refreshTopologyCanvas:spy('refreshTopologyCanvas'),workshopWorkflow:spy('workshopWorkflow'),
    sendWorkshopMessage:spy('sendWorkshopMessage'),selectTopology:spy('selectTopology')};
  return {state,node,authority,calls,work};
}

module.exports = {fixture};
