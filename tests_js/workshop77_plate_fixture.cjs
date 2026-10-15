/* Plate-shaped fake authority data only. Never imported by application code. */
function plateFixture({models}={}){
  const now=Date.now()/1000,root='room-a',work='work:doors301';
  const authorization={subject:'owner-a',session:'view-a'};
  const participants=[{root:'owner-a',label:'Account owner',is_agent:false,attached:true},
    {root:'agent-a',label:'Claude Code',runtime:'claude',is_agent:true,attached:true,connected:true,model:'registry-a'},
    {root:'agent-b',label:'Codex',runtime:'codex',is_agent:true,attached:true,connected:true,model:'registry-b',state:'working'},
    {root:'agent-c',label:'OpenCode',runtime:'opencode',is_agent:true,attached:true,connected:true,model:'registry-c:free',state:'working'}];
  const node={id:root,cat:'workshop',title:'Tag doors on Level 3',x:880,y:120,w:300,members:['agent-a','agent-b'],
    ins:[{id:'doors-in',label:'doors',t:'doors',list:true,connectable:true}],
    outs:[{id:'tags-out',label:'tags',t:'doors',list:true,connectable:true},{id:'schedule-out',label:'schedule',t:'file',connectable:true}]};
  const taskNodes=[{id:work,title:node.title,status:'awaiting_approval'},
    {id:'work:mail0001',title:'Send door schedule to Sara',status:'awaiting_approval'},
    {id:'work:walls001',title:'Wall schedule',status:'running',progress:70,status_line:'Reading walls · 148 of 212'},
    {id:'work:views001',title:'Rename views on Level 4',status:'running',progress:15,status_line:'Planning · 3 steps'},
    {id:'work:audit001',title:'Model audit',status:'done'},
    {id:'work:fire0001',title:'Fire ratings list',status:'done'},
    {id:'work:read0001',title:'Read doors on Level 3',status:'done',duration:'0.8 s',result_summary:'46 doors'},
    {id:'work:find0001',title:'Find untagged doors',status:'done',duration:'0.1 s',result_summary:'12 found'},
    {id:'work:place001',title:'Place 12 tags',status:'awaiting_approval',duration:'—',result_summary:'needs you'},
    {id:'work:refresh1',title:'Refresh door schedule',status:'planned'}];
  const rows=Array.from({length:12},(_,i)=>({id:'door-'+i,label:['D-301','D-307','D-312','D-318'][i]||'D-'+(320+i),now:'—',after:'L3-'+String(i+1).padStart(2,'0')}));
  const messages=[{root:'ask-a',sender_root:'owner-a',work_root:work,body:'Tag the untagged doors on Level 3 with prefix L3-.',created_at:now-240},
    {root:'reply-a',sender_root:'agent-a',work_root:work,body:"Level 3 has 46 doors; 12 have no tag. I'll tag them L3-01 to L3-12, then refresh the schedule.",elapsed:'38 s',cost_label:'free',created_at:now-202},
    {root:'review-a',sender_root:'agent-b',work_root:work,body:'Checked all 12 tags: unique, prefix correct, no tag on a door that already has one.',elapsed:'9 s',cost_label:'free',created_at:now-193},
    {root:'mail-event',sender_root:'agent-b',body:'Submitted Work work:mail0001 for review.',category:'lifecycle',created_at:now},
    {root:'walls-event',sender_root:'agent-b',body:'Started Work work:walls001.',category:'lifecycle',created_at:now},
    {root:'views-event',sender_root:'agent-c',body:'Started Work work:views001.',category:'lifecycle',created_at:now},
    {root:'audit-event',sender_root:'agent-a',body:'Completed Work work:audit001.',category:'lifecycle',created_at:now},
    {root:'fire-event',sender_root:'agent-b',body:'Completed Work work:fire0001.',category:'lifecycle',created_at:now}];
  const state={account:{name:'Alex Farid',initials:'AF',colour:'linear-gradient(135deg,#e8c39e,#b98a62)'},
    canvas:{graph_id:'graph-a',root:'scope-a',revision:4,authorization},workshops:[{root,label:node.title}],
    workshop:{root,ok:true,can_send:true,self:'owner-a',participants,messages,
      assignments:[{work,agent_session:'agent-a'},{work:'work:mail0001',agent_session:'agent-b'},{work:'work:walls001',agent_session:'agent-b'},
        {work:'work:views001',agent_session:'agent-c'},{work:'work:audit001',agent_session:'agent-a'},{work:'work:fire0001',agent_session:'agent-b'}],
      reviews:[{workflow:work,judged_by:'agent-b',review_message:'review-a'}],
      workflows:[{root:work,title:node.title,proposed_by:'agent-a',source_message:'reply-a',state:'needs-user',elapsed:'4 min',digest:'c'.repeat(64),approval:{current:true},
        nodes:taskNodes.slice(6).map(n=>({root:n.id,title:n.title,duration:n.duration,result:n.result_summary}))}]},
    nativeWork:{root,scope:'scope-a',owner:'owner-a',view:'view-a',work,mode:'agent',state:'awaiting_approval',approved:false,
      input_digest:'a'.repeat(64),review_expires_at:now+600,result_count:12,output_label:'tags',change_unit:'doors',item_label:'Door',
      title:'Place 12 door tags',summary:'Tag only the 12 untagged doors.',changes:rows,host:'Revit 2025',document:'Nile_Tower.rvt',scope_label:'Level 3 plan',
      writes_to_model:true,undo_available:true,unchanged_scope:true},
    workshopPresentation:{root,subject:'owner-a',graph_id:'graph-a',layout:1,models:{groups:[{items:[
      {id:'registry-a',name:'Registry model A',free:true},{id:'registry-b',name:'Registry model B',free:true},{id:'registry-c:free',name:'Registry model C free',free:true}]}]}},
    hosts:[{name:'Revit 2025',file:'Nile_Tower.rvt',state:'connected'}],
    topology:{canvas:{application_root:'graph-a',scope:{current:'scope-a',label:node.title},authorization,project_label:'Nile Tower'},
      graph:{nodes:[node,{id:'agent-a',title:'Claude Code',group:root},{id:'agent-b',title:'Codex',group:root},...taskNodes],wires:[]}}};
  if(models){
    if(models.length<participants.filter(p=>p.is_agent).length)throw new Error('Render needs three real free catalogue entries');
    participants.filter(p=>p.is_agent).forEach((agent,index)=>{agent.model=models[index].route;agent.free_only=true;});
    state.workshopPresentation.models={groups:[{items:models.map(row=>({...row,id:row.route,free:true}))}]};
  }
  return {state,node,work,rows};
}
module.exports={plateFixture};
