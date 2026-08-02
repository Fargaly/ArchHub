import { JSDOM } from 'jsdom';
import { performance } from 'node:perf_hooks';

const input = JSON.parse(await new Promise((resolve, reject) => {
  let body = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', chunk => { body += chunk; });
  process.stdin.on('end', () => resolve(body));
  process.stdin.on('error', reject);
}));

const requests = [];
let gestureResponseDelivered = 0;
let rejectedGestureCount = 0;
let staleGestureCount = 0;
let propertyResponseDelivered = 0;
let interfaceValueResponseDelivered = 0;
let collectionValueResponseDelivered = 0;
let topologyResponseDelivered = 0;
let expiredInteractionCount = 0;
let historyResponseIndex = 0;
let relationComposerRequestCount = 0;
let librarySearchRequestCount = 0;
let projection = structuredClone(input.projection);
const relationComposerResponses=(input.relationComposerResponses || []).map(
  item => structuredClone(item));
const initialScope = structuredClone(projection.scope);

const relationPointFacts=[
  ['x','canvas-point-x',true,0,1000000],
  ['y','canvas-point-y',true,0,1000000],
  ['pan_x','canvas-viewport-pan-x',false,-10000000,10000000],
  ['pan_y','canvas-viewport-pan-y',false,-10000000,10000000],
  ['zoom','canvas-viewport-zoom',false,0.1,4],
].map(([key,source,required,minimum,maximum]) => ({
  input:`court:event-fact:${key}`,source,value_kind:'number',required,
  minimum,maximum,
}));

function relationComposerControlOperation(candidate,control) {
  const definition=candidate.selected_definition;
  const composer=definition?.composer;
  if (!composer) return null;
  if (control === composer.position_control) return 'position';
  if (control === composer.create_control) return 'create';
  for (const role of composer.roles || []) {
    if (control === role.add_control) return 'add';
    for (const entry of role.entries || []) {
      if (control === entry.remove_control) return 'remove';
      if (control === entry.select_control) return 'select';
    }
  }
  return null;
}

function syncRelationComposerInteractions(candidate) {
  const definition=candidate.selected_definition;
  const composer=definition?.composer;
  if (!composer) return;
  const bindings=[];
  const add=(control,operation,event,eventFacts=[]) => {
    bindings.push({
      control,
      interaction:`court:interaction:relation-composer:${operation}:${control}`,
      event,
      inputs:[`court:relation-composer-operation:${operation}`,definition.id],
      event_facts:eventFacts,
    });
  };
  add(composer.position_control,'position','court:event:place',relationPointFacts);
  for (const role of composer.roles || []) {
    if (role.can_add) add(role.add_control,'add','court:event:activate');
    for (const entry of role.entries || []) {
      if (!entry.remove_disabled) {
        add(entry.remove_control,'remove','court:event:activate');
      }
      add(entry.select_control,'select','court:event:change',[{
        input:'court:event-fact:participant-index',
        source:'relation-participant-index',value_kind:'number',required:true,
        minimum:0,maximum:1000000,
      }]);
    }
  }
  if (composer.complete && typeof composer.draft === 'string') {
    add(composer.create_control,'create','court:event:activate');
  }
  candidate.interaction_projection={
    revision:candidate.revision,
    lifecycle:'wip',
    bindings,
  };
}
function syncTopologyInteractions(candidate) {
  const bindings=[];
  const candidateFact={
    input:'court:event-fact:topology-candidate-index',
    source:'topology-candidate-index',value_kind:'number',required:true,
    minimum:0,maximum:1000000,
  };
  for (const node of candidate.nodes || []) {
    for (const port of node.ports || []) {
      if (typeof port.connect_control !== 'string') continue;
      bindings.push({
        control:port.connect_control,
        interaction:`court:interaction:topology:connect:${port.id}`,
        event:'court:event:pointer-up',projection_mode:'topology-delta-v1',
        inputs:['court:topology:connect',node.id,port.id,candidateFact.input],
        event_facts:[candidateFact],
      });
    }
  }
  for (const wire of (candidate.wires || []).filter(
    item => !item.nary && item.selected)) {
    bindings.push({
      control:wire.disconnect_control,
      interaction:`court:interaction:topology:disconnect:${wire.id}`,
      event:'court:event:activate',projection_mode:'topology-delta-v1',
      inputs:['court:topology:disconnect',wire.id],event_facts:[],
    });
    for (const side of ['source','target']) {
      const control=wire[side+'_rewire_control'];
      if (typeof control !== 'string') continue;
      bindings.push({
        control,
        interaction:`court:interaction:topology:rewire:${wire.id}:${side}`,
        event:'court:event:change',projection_mode:'topology-delta-v1',
        inputs:[
          'court:topology:rewire',wire.id,wire[side+'_incidence'],
          candidateFact.input,
        ],
        event_facts:[candidateFact],
      });
    }
  }
  candidate.interaction_projection={
    revision:candidate.revision,lifecycle:'wip',bindings,
  };
}
function historyControlOperation(candidate,controlRoot) {
  const controls=candidate.configuration?.design_system?.control_catalog?.controls || [];
  const control=controls.find(item => (
    item.owner === controlRoot
    && ['undo','redo'].includes(item.activation?.arguments?.operation)));
  return control?.activation?.arguments?.operation || null;
}
function syncHistoryInteractions(candidate) {
  const controls=(
    candidate.configuration?.design_system?.control_catalog?.controls || []
  ).filter(item => (
    item.zone === 'canvas-toolbar'
    && item.applicable
    && ['undo','redo'].includes(item.activation?.arguments?.operation)));
  candidate.interaction_projection={
    revision:candidate.revision,
    lifecycle:'wip',
    bindings:controls.map(control => ({
      control:control.owner,
      interaction:`court:interaction:history:${control.activation.arguments.operation}`,
      event:'court:event:activate',
      projection_mode:'topology-delta-v1',
      inputs:[control.activation.binding],
      event_facts:[],
    })),
  };
}
function syncPresentationInteractions(candidate) {
  const bindings=[];
  for (const property of (candidate.properties || []).filter(
    item => item.presentation_editable)) {
    bindings.push({
      control:property.presentation_control,
      interaction:`court:interaction:appearance:preview:${property.relation}`,
      event:'court:event:change',projection_mode:'interaction-delta-v1',
      inputs:[
        'court:appearance:preview',property.relation,property.value_root,
        property.presentation_event_fact_input,
      ],
      event_facts:[{
        input:property.presentation_event_fact_input,
        source:'submitted',value_kind:'text',required:false,
        maximum_bytes:65536,
      }],
    });
    if (property.presentation_reset) bindings.push({
      control:property.presentation_reset_control,
      interaction:`court:interaction:appearance:reset:${property.relation}`,
      event:'court:event:activate',projection_mode:'interaction-delta-v1',
      inputs:['court:appearance:reset',property.relation,property.value_root],
      event_facts:[],
    });
  }
  for (const field of candidate.configuration?.theme_fields || []) {
    bindings.push({
      control:field.control,
      interaction:`court:interaction:theme-preview:${field.key}`,
      event:'court:event:change',projection_mode:'interaction-delta-v1',
      inputs:[
        'court:appearance:theme-preview',
        candidate.configuration.personal_asset,
        field.token_root,
        field.event_fact_input,
      ],
      event_facts:[{
        input:field.event_fact_input,
        source:'submitted',value_kind:'text',required:false,
        maximum_bytes:65536,
      }],
    });
  }
  for (const revision of candidate.configuration?.history || []) {
    if (revision.current || typeof revision.restore_control !== 'string') continue;
    bindings.push({
      control:revision.restore_control,
      interaction:`court:interaction:theme-restore:${revision.revision}`,
      event:'court:event:activate',projection_mode:'interaction-delta-v1',
      inputs:[
        'court:appearance:theme-restore',
        candidate.configuration.personal_asset,
        revision.revision,
      ],
      event_facts:[],
    });
  }
  candidate.interaction_projection={
    revision:candidate.revision,lifecycle:'wip',bindings,
  };
}
function retargetCardDescriptor(template,id,label) {
  const sourcePrefix=`canvas:node:${template.id}`;
  const targetPrefix=`canvas:node:${id}`;
  const rewrite=descriptor => {
    const rewritten={
      ...structuredClone(descriptor),
      key:descriptor.key.replace(sourcePrefix,targetPrefix),
      children:(descriptor.children || []).map(rewrite),
    };
    if (rewritten.key.endsWith(':title')) rewritten.text=label;
    if (rewritten.key === targetPrefix) {
      rewritten.attributes={
        ...(rewritten.attributes || {}),
        'aria-label':`${label}. 0 relations`,
      };
    }
    return rewritten;
  };
  return (template.card_descriptor || []).map(rewrite);
}
if (input.viewport) projection.viewport = structuredClone(input.viewport);
if (input.syntheticCount) {
  const template = projection.nodes[0];
  projection.nodes = Array.from({length: input.syntheticCount}, (_, index) => {
    const id=`court:node:${index}`;
    const label=`Court node ${index + 1}`;
    const densePorts=[
      {
        id:`court:interface:${index}:input`,name:'Input',side:'target',
        mode:'connection',connectable:true,read_only:false,
      },
      {
        id:`court:interface:${index}:output`,name:'Output',side:'source',
        mode:'connection',connectable:true,read_only:false,
      },
    ];
    const rawPorts=[
      'performance_lens_250','performance_wire_preview_250',
    ].includes(input.scenario) ? densePorts : [];
    if (input.scenario === 'performance_wire_preview_250' && index === 0) {
      rawPorts[1].connect_control='court:control:wire-preview';
      rawPorts[1].connect_choices=Array.from(
        {length:input.syntheticCount},(_unused,targetIndex) => ({
          id:`court:interface:${targetIndex}:input`,
          owner:`court:node:${targetIndex}`,
        })
      );
    }
    const ports=rawPorts.map(port => ({
      ...port,
      descriptor:[{
        key:`canvas:interface:${port.id}`,
        tag:'button',
        class:`node-port ${port.side === 'target'
          ? 'node-port-in' : 'node-port-out'}`,
        text:port.name,
        attributes:{
          type:'button',title:port.name,
          'aria-label':`${port.side === 'target' ? 'Input' : 'Output'}: ${port.name}`,
          'aria-pressed':false,
          'data-universal-interface':port.id,
          'data-interface-label':port.name,
          'data-interface-mode':port.mode,
          'data-context':false,
          'data-selected':false,
          [port.side === 'target'
            ? 'data-universal-input' : 'data-universal-output']:id,
        },
        children:[],
      }],
    }));
    return {
      ...structuredClone(template),
      id,label,
      x:60+(index%25)*244,
      y:92+Math.floor(index/25)*174,
      selected:index===0,
      openable:false,
      ports,
      card_descriptor:retargetCardDescriptor(template,id,label),
    };
  });
  const wireCount = input.syntheticWireCount || input.syntheticCount * 2;
  projection.wires = Array.from({length: wireCount}, (_, index) => ({
    id: `court:relation:${index}`,
    source: `court:node:${index % input.syntheticCount}`,
    target: `court:node:${(index * 7 + 1) % input.syntheticCount}`,
    source_interface: null,
    target_interface: null,
    selected: false,
    authority_roots: [],
    color: '#5fb3b3',
    width: 1.35,
    dash: '',
    context: false,
  }));
  projection.selection = [projection.nodes[0].id];
  projection.selected = projection.nodes[0].id;
  projection.selected_title = projection.nodes[0].label;
  projection.canvas_signature=(
    `court:canvas:${input.scenario}:${projection.nodes.length}:`
    + projection.wires.length
  );
}
const nodeIds = projection.nodes.slice(0, 3).map(node => node.id);
const expectedUniqueNodeCount = projection.nodes.length;

if (input.scenario === 'relation_composer') {
  const definition=projection.selected_definition;
  if (!definition?.composer) {
    throw new Error('no graph-authored relation composer projected');
  }
  syncRelationComposerInteractions(projection);
}
if ([
  'property_identity','floor_atom_identity','topology_reconcile',
  'performance_property_250',
].includes(input.scenario)) {
  const editable=projection.properties.filter(property => property.editable);
  if (!editable.length || editable.some(property => (
    typeof property.control !== 'string'
    || typeof property.event_fact_input !== 'string'
  ))) {
    throw new Error('Property interaction fixture is incomplete');
  }
  projection.interaction_projection={
    revision:projection.revision,
    lifecycle:'wip',
    bindings:editable.map((property,index) => ({
      control:property.control,
      interaction:`court:interaction:property:${index}`,
      event:'court:event:change',
      inputs:property.batch ? [
        property.operation,property.control,property.event_fact_input,
      ] : [property.relation,property.value_root,property.event_fact_input],
      event_facts:[{
        input:property.event_fact_input,
        source:'submitted',
        value_kind:'text',
        required:false,
        maximum_bytes:65536,
      }],
    })),
  };
}
if (input.scenario === 'interface_value_identity') {
  const editable=projection.selected_interfaces.filter(item => (
    item.editable && item.mode === 'connection'));
  if (!editable.length || editable.some(item => (
    typeof item.control !== 'string'
    || typeof item.event_fact_input !== 'string'
  ))) {
    throw new Error('Interface-value interaction fixture is incomplete');
  }
  projection.interaction_projection={
    revision:projection.revision,
    lifecycle:'wip',
    bindings:editable.map((item,index) => ({
      control:item.control,
      interaction:`court:interaction:interface-value:${index}`,
      event:'court:event:change',
      inputs:[item.owner,item.id,item.target,item.event_fact_input],
      event_facts:[{
        input:item.event_fact_input,
        source:'submitted',
        value_kind:'text',
        required:false,
        maximum_bytes:65536,
      }],
    })),
  };
}
if (input.scenario === 'collection_item_identity') {
  const editable=projection.selected_interfaces.flatMap(item => (
    item.editable && item.mode === 'collection' ? item.items.map(member => ({
      owner:item.owner,interface:item.id,...member,
    })) : []));
  if (!editable.length || editable.some(item => (
    typeof item.control !== 'string'
    || typeof item.event_fact_input !== 'string'
    || typeof item.value_root !== 'string'
  ))) {
    throw new Error('Collection-item interaction fixture is incomplete');
  }
  projection.interaction_projection={
    revision:projection.revision,
    lifecycle:'wip',
    bindings:editable.map((item,index) => ({
      control:item.control,
      interaction:`court:interaction:collection-value:${index}`,
      event:'court:event:change',
      inputs:[
        item.owner,item.interface,item.incidence,item.value_root,
        item.event_fact_input,
      ],
      event_facts:[{
        input:item.event_fact_input,
        source:'submitted',
        value_kind:'text',
        required:false,
        maximum_bytes:65536,
      }],
    })),
  };
}
if (input.scenario === 'collection_actions_identity') {
  const collection=projection.selected_interfaces.find(item => (
    item.editable && item.mode === 'collection'));
  if (!collection || typeof collection.append_control !== 'string'
      || typeof collection.append_event_fact_input !== 'string') {
    throw new Error('Collection action fixture is incomplete');
  }
  const bindings=[{
    control:collection.append_control,
    interaction:'court:interaction:relation-members:append',
    event:'court:event:activate',
    projection_mode:'topology-delta-v1',
    inputs:[
      collection.owner,collection.id,collection.target,
      'court:operation:append',collection.append_event_fact_input,
    ],
    event_facts:[{
      input:collection.append_event_fact_input,
      source:'submitted',value_kind:'text',required:false,
      maximum_bytes:65536,
    }],
  }];
  for (const member of collection.items) {
    for (const [field,operation] of [
      ['up_control','move-up'],['down_control','move-down'],
      ['remove_control','remove'],
    ]) bindings.push({
      control:member[field],
      interaction:`court:interaction:relation-members:${operation}:${member.incidence}`,
      event:'court:event:activate',
      projection_mode:'topology-delta-v1',
      inputs:[
        collection.owner,collection.id,collection.target,member.incidence,
        `court:operation:${operation}`,
      ],
      event_facts:[],
    });
  }
  projection.interaction_projection={
    revision:projection.revision,lifecycle:'wip',bindings,
  };
}
if ([
  'relation_role_edit','relation_role_wire_edit','relation_role_wire_append',
].includes(input.scenario)) {
  const bindings=[];
  for (const interfaceItem of projection.selected_interfaces.filter(
    item => item.editable && item.mode === 'relation-role')) {
    const participantFact={
      input:interfaceItem.append_event_fact_input,
      source:'relation-participant-index',value_kind:'number',required:true,
      minimum:0,maximum:Math.max(0,interfaceItem.choices.length-1),
    };
    bindings.push({
      control:interfaceItem.append_control,
      interaction:`court:interaction:relation-members:append:${interfaceItem.id}`,
      event:'court:event:activate',
      projection_mode:'topology-delta-v1',
      inputs:[
        interfaceItem.owner,interfaceItem.id,interfaceItem.target,
        'court:operation:append',interfaceItem.append_event_fact_input,
      ],
      event_facts:[participantFact],
    });
    for (const member of interfaceItem.items) {
      bindings.push({
        control:member.replace_control,
        interaction:`court:interaction:relation-members:replace:${member.incidence}`,
        event:'court:event:change',
        projection_mode:'topology-delta-v1',
        inputs:[
          interfaceItem.owner,interfaceItem.id,interfaceItem.target,
          member.incidence,'court:operation:replace',
          member.replace_event_fact_input,
        ],
        event_facts:[{
          ...participantFact,input:member.replace_event_fact_input,
        }],
      });
      bindings.push({
        control:member.remove_control,
        interaction:`court:interaction:relation-members:remove:${member.incidence}`,
        event:'court:event:activate',
        projection_mode:'topology-delta-v1',
        inputs:[
          interfaceItem.owner,interfaceItem.id,interfaceItem.target,
          member.incidence,'court:operation:remove',
        ],
        event_facts:[],
      });
    }
  }
  projection.interaction_projection={
    revision:projection.revision,lifecycle:'wip',bindings,
  };
}
const relationCreateControl=(
  projection.selected_definition?.composer?.create_control || null);

function applyFixtureSelection(roots, focus = roots.at(-1) || projection.selected) {
  projection.selection = [...roots];
  projection.selected = focus;
  projection.selected_title = projection.nodes.find(node => node.id === focus)?.label
    || projection.selected_title;
  projection.nodes = projection.nodes.map(node => ({
    ...node,
    selected: roots.includes(node.id),
  }));
}

if (input.scenario === 'shift_remove') applyFixtureSelection(nodeIds.slice(0, 2), nodeIds[1]);
if (input.scenario === 'ctrl_retains') applyFixtureSelection([nodeIds[0]], nodeIds[0]);
if (input.scenario === 'modifier_marquee') {
  applyFixtureSelection([nodeIds[0]], nodeIds[0]);
}
if (['marquee', 'marquee_viewport', 'crossing'].includes(input.scenario)) {
  applyFixtureSelection([], projection.selected);
}
if (['cancel', 'escape_cancel'].includes(input.scenario)) {
  applyFixtureSelection([nodeIds[0]], nodeIds[0]);
}
if (['rejected_gesture','rejected_then_success'].includes(input.scenario)) {
  applyFixtureSelection([nodeIds[0]], nodeIds[0]);
}
if (input.scenario === 'keyboard_select') applyFixtureSelection([], projection.selected);
if (input.scenario === 'wire_delete') {
  const wire=projection.wires.find(item => !item.nary);
  if (!wire) throw new Error('no detachable binary wire projected');
  projection.selection=[];
  projection.selected=wire.id;
  projection.selected_title='Selected connection';
  projection.selected_relation={id:wire.id};
  projection.wires=projection.wires.map(item => ({
    ...item,selected:item.id === wire.id,
  }));
}
if ([
  'wire_rejected','wire_delete','wire_endpoint_rewire','relation_rewire',
].includes(input.scenario)) syncTopologyInteractions(projection);
if (input.scenario === 'history_keyboard') syncHistoryInteractions(projection);
if ([
  'presentation_color','presentation_reset','theme_preview','theme_restore',
].includes(input.scenario)) {
  syncPresentationInteractions(projection);
}
if (['tabs', 'tabs_after_mutation', 'tabs_expired_lease'].includes(input.scenario)) {
  const panels=projection.inspector.presentation.panels;
  projection.interaction_projection={
    revision:projection.revision,
    lifecycle:'wip',
    bindings:panels.map((panel,index) => ({
      control:panel.id,
      interaction:`court:interaction:${index}`,
      event:'court:event:activate',
      projection_mode:'interaction-delta-v1',
      inputs:[panel.id],
      event_facts:[],
    })),
  };
}
if (['property_create', 'interface_create'].includes(input.scenario)) {
  const form=input.scenario === 'property_create'
    ? projection.authoring.property_form
    : projection.authoring.interface_form;
  const keys=input.scenario === 'property_create'
    ? ['label','value']
    : ['name','presentation','contract'];
  projection.interaction_projection={
    revision:projection.revision,
    lifecycle:'wip',
    bindings:[{
      control:form.control,
      interaction:`court:interaction:${form.root}`,
      event:'court:event:submit',
      event_facts:keys.map(key => ({
        input:form.inputs[key],
        source:'submitted',
        value_kind:key === 'presentation' || key === 'contract' ? 'root' : 'text',
        required:key !== 'value',
        maximum_bytes:key === 'value' ? 65536
          : key === 'presentation' || key === 'contract' ? 0 : 512,
      })),
    }],
  };
}
if ([
  'scope_navigation', 'scope_keyboard', 'scope_reconciliation_change'
].includes(input.scenario)) {
  projection.interaction_projection={
    revision:projection.revision,
    lifecycle:'wip',
    bindings:projection.nodes.filter(node => node.openable).map((node,index) => ({
      control:node.id,
      interaction:`court:interaction:scope:${index}`,
      event:'court:event:activate',
      inputs:[projection.scope.current,node.id],
      event_facts:[],
    })),
  };
}
if (['build_lens', 'performance_lens_250'].includes(input.scenario)) {
  const active=projection.inspector.active;
  const build=projection.inspector.lenses.find(lens => lens.name === 'build');
  if (!build || typeof active !== 'string') {
    throw new Error('Build lens interaction fixture is incomplete');
  }
  projection.interaction_projection={
    revision:projection.revision,
    lifecycle:'wip',
    bindings:[{
      control:build.id,
      interaction:'court:interaction:lens:build',
      event:'court:event:activate',
      inputs:[active,build.id],
      event_facts:[],
    }],
  };
}
if (input.scenario === 'group_control') {
  const group=projection.configuration.design_system.control_catalog.controls
    .find(control => control.owner === 'app:control:canvas:group');
  if (!group?.applicable || !group.activation?.binding) {
    throw new Error('Group interaction fixture is incomplete');
  }
  projection.interaction_projection={
    revision:projection.revision,
    lifecycle:'wip',
    bindings:[{
      control:group.owner,
      interaction:'court:interaction:composition:group',
      event:'court:event:activate',
      inputs:[group.activation.binding],
      event_facts:[],
    }],
  };
}
if ([
  'library_place','library_place_rejected','topology_delta_reconcile',
  'performance_topology_250','primitive_drag','library_search_keyboard',
].includes(input.scenario)) {
  const control=input.scenario === 'primitive_drag'
    ? projection.primitive
    : input.scenario === 'library_search_keyboard'
      ? projection.catalog.find(item => (
          !item.composition_contract
          && item.name.toLocaleLowerCase() === String(input.query || '')
            .trim().toLocaleLowerCase()
        ))
      : projection.catalog.find(item => !item.composition_contract);
  if (!control?.id) throw new Error('Placement interaction fixture is incomplete');
  const facts=[
    ['x','canvas-point-x',true,0,1000000],
    ['y','canvas-point-y',true,0,1000000],
    ['pan_x','canvas-viewport-pan-x',false,-10000000,10000000],
    ['pan_y','canvas-viewport-pan-y',false,-10000000,10000000],
    ['zoom','canvas-viewport-zoom',false,0.1,4],
  ].map(([key,source,required,minimum,maximum]) => ({
    input:`court:event-fact:${key}`,source,value_kind:'number',required,
    minimum,maximum,
  }));
  projection.interaction_projection={
    revision:projection.revision,
    lifecycle:'wip',
    bindings:[{
      control:control.id,
      interaction:'court:interaction:instantiate',
      event:'court:event:place',
      inputs:[control.id,...facts.map(fact => fact.input)],
      event_facts:facts,
    }],
  };
}
const initialInteractionProjection=structuredClone(
  projection.interaction_projection);
const initialTopologyOperationByControl=new Map(
  (initialInteractionProjection?.bindings || []).filter(binding => (
    String(binding.inputs?.[0] || '').startsWith('court:topology:')
  )).map(binding => [binding.control,binding.inputs[0]]));
const initialHistoryOperationByControl=new Map(
  [input.projection,...(input.historyProjectionResponses || [])].flatMap(
    candidate => (
      candidate.configuration?.design_system?.control_catalog?.controls || []
    ).map(control => [
      control.owner,control.activation?.arguments?.operation,
    ])).filter(([_control,operation]) => ['undo','redo'].includes(operation)));
const initialInspectorLensRoots=new Set(
  projection.inspector.lenses.map(lens => lens.id));

function response(payload, onRead = null) {
  return {
    ok: true,
    async json() {
      if (onRead) onRead();
      return structuredClone(payload);
    },
  };
}

function syncPresentationDescriptor(property) {
  const components=(projection.inspector?.presentation?.panels || [])
    .flatMap(panel => panel.components || []);
  const visit=spec => {
    if (spec.key === `presentation-row:${property.relation}`) {
      const inputSpec=(spec.children || []).find(
        child => child.attributes?.['data-universal-control']
          === property.presentation_control);
      if (inputSpec) {
        inputSpec.value=property.value;
      }
      const sourceSpec=(spec.children || []).find(
        child => child.class === 'presentation-source');
      if (sourceSpec) {
        sourceSpec.text=`${property.presentation_source_mode.toUpperCase()} / `
          + property.presentation_source;
      }
      spec.children=(spec.children || []).filter(
        child => child.class !== 'presentation-reset');
      if (property.presentation_reset) {
        spec.children.push({
          key:`${spec.key}:reset`,
          tag:'button',
          class:'presentation-reset',
          attributes:{
            type:'button',
            'data-universal-control':property.presentation_reset_control,
          },
          children:[],
          text:'RESET',
        });
      }
      return;
    }
    (spec.children || []).forEach(visit);
  };
  components.forEach(component => (component.descriptor || []).forEach(visit));
}

function syncEditablePropertyDescriptor(property) {
  const components=(projection.inspector?.presentation?.panels || [])
    .flatMap(panel => panel.components || []);
  const visit=spec => {
    if (
      spec.attributes?.['data-universal-event-fact-input']
      === property.event_fact_input
      && spec.attributes?.['data-universal-control'] === property.control
    ) {
      spec.value=property.value;
    }
    (spec.children || []).forEach(visit);
  };
  components.forEach(component => (component.descriptor || []).forEach(visit));
}

function syncInspectorDescriptors(candidate) {
  const panels=candidate.inspector?.presentation?.panels || [];
  const activePanels=new Map(panels.map(panel => [panel.id,Boolean(panel.active)]));
  const lenses=new Map((candidate.inspector?.lenses || []).map(
    lens => [lens.id,Boolean(lens.active)]));
  const visit=spec => {
    const attributes=spec.attributes || {};
    const panel=attributes['data-universal-properties-panel'];
    if (panel && activePanels.has(panel)) {
      const active=activePanels.get(panel);
      attributes['aria-selected']=active;
      attributes['data-active']=active;
      attributes.tabindex=active ? '0' : '-1';
    }
    const lens=attributes['data-universal-inspector-lens'];
    if (lens && lenses.has(lens)) {
      const active=lenses.get(lens);
      attributes['aria-pressed']=active;
      attributes['data-active']=active;
    }
    const tabPanel=attributes['data-inspector-tabpanel'];
    if (tabPanel && activePanels.has(tabPanel)) {
      attributes.hidden=!activePanels.get(tabPanel);
    }
    if (spec.key === 'inspector:root') {
      attributes['data-inspected-node']=candidate.selected || '';
    }
    (spec.children || []).forEach(visit);
  };
  (candidate.inspector?.controls_descriptor || []).forEach(visit);
  (candidate.inspector?.shell_descriptor || []).forEach(visit);
}

function syncToolbarDescriptor(candidate) {
  const catalog=structuredClone(
    input.controlStateAfter
      || candidate.configuration.design_system.control_catalog);
  if (!input.controlStateAfter) {
    catalog.controls=catalog.controls.map(control => {
      const capability=control.activation?.capability;
      const operation=control.activation?.arguments?.operation;
      let applicable=control.applicable;
      if (capability === 'app:device-capability:scope') {
        applicable=Boolean(candidate.scope?.parent);
      } else if (capability === 'app:device-capability:composition') {
        applicable=operation === 'group'
          ? candidate.selection.length >= 2
          : Boolean(candidate.nodes.find(node => (
              node.id === candidate.selected && node.composition)));
      } else if (capability === 'app:device-capability:history') {
        applicable=operation === 'undo'
          ? Boolean(candidate.action_history?.can_undo)
          : Boolean(candidate.action_history?.can_redo);
      }
      return {...control,applicable};
    });
  }
  candidate.configuration.design_system.control_catalog=catalog;
  const controls=catalog.controls.filter(control => (
    control.zone === 'canvas-toolbar' && control.applicable
  )).sort((left,right) => left.order-right.order);
  const button=control => {
    const attributes={
      type:'button',
      'data-universal-control':control.owner,
      'data-control-binding':control.activation.binding,
      'data-control-capability':control.activation.capability,
      'data-control-icon':control.icon,
      title:control.title,
      'aria-label':control.title,
    };
    const args=control.activation.arguments || {};
    if (control.activation.capability === 'app:device-capability:viewport') {
      attributes['data-universal-zoom']=args.operation === 'fit'
        ? 'fit' : Number(args.amount) > 0 ? 'in' : 'out';
    }
    if (control.activation.capability === 'app:device-capability:history') {
      attributes['data-universal-history']=args.operation;
    }
    return {
      key:`toolbar:control:${control.owner}`,tag:'button',
      class:'header-action icon-only',attributes,children:[],
    };
  };
  const trail=(candidate.scope?.trail || []).map((item,index) => {
    const key=`toolbar:scope:item:${item.root}`;
    const children=[];
    if (index) {
      children.push({
        key:`${key}:divider`,tag:'span',class:'canvas-scope-divider',
        attributes:{},children:[],text:'/',
      });
    }
    if (item.current) {
      children.push({
        key:`${key}:current`,tag:'span',class:'canvas-scope-current',
        attributes:{},children:[],text:item.label,
      });
    } else {
      children.push({
        key:`${key}:crumb`,tag:'button',class:'canvas-scope-button',
        attributes:{type:'button','data-universal-scope':item.root},
        children:[],text:item.label,
      });
    }
    return {
      key,tag:'span',class:'canvas-scope-item',attributes:{},children,
    };
  });
  const scopeControls=controls.filter(control => (
    control.activation.capability === 'app:device-capability:scope'
  ));
  const otherControls=controls.filter(control => !scopeControls.includes(control));
  const selection=() => ({
    key:'toolbar:selection',tag:'span',class:'canvas-selection-value',
    attributes:{'data-universal-toolbar-selection-value':'True'},children:[],
    text:`${candidate.selection.length} selected`,
  });
  const zoom=() => ({
    key:'toolbar:zoom:value',tag:'span',class:'universal-zoom-value',
    attributes:{'data-universal-toolbar-zoom-value':'True'},children:[],
    text:`${Math.round(Number(candidate.viewport.zoom)*100)}%`,
  });
  const toolbarItems=[];
  let selectionPlaced=false;
  otherControls.forEach(control => {
    const capability=control.activation.capability;
    const args=control.activation.arguments || {};
    if (
      capability === 'app:device-capability:composition'
      && !selectionPlaced
    ) {
      toolbarItems.push(selection());
      selectionPlaced=true;
    }
    toolbarItems.push(button(control));
    if (
      capability === 'app:device-capability:viewport'
      && args.operation === 'delta' && Number(args.amount) < 0
    ) toolbarItems.push(zoom());
  });
  if (!selectionPlaced) toolbarItems.push(selection());
  candidate.toolbar_descriptor=[{
    key:'toolbar:surface',tag:'div',class:'canvas-toolbar-surface',
    attributes:{},children:[
      {
        key:'toolbar:scope',tag:'div',class:'canvas-scope-trail',
        attributes:{'data-universal-toolbar-scope':'True'},
        children:[...scopeControls.map(button),...trail],
      },
      ...toolbarItems,
    ],
  }];
}

function syncCanvasHeadingDescriptor(candidate) {
  candidate.canvas_heading_descriptor=[{
    key:'canvas:heading',tag:'div',class:'canvas-heading',
    attributes:{'data-universal-canvas-heading':candidate.scope.current},
    children:[],text:candidate.scope.current_label,
  }];
}

let servedNodeStates=new Map(projection.nodes.map(node => [node.id,{
  id:node.id,selected:node.selected,x:node.x,y:node.y,
}]));
let servedWireStates=new Map(projection.wires.map(wire => [
  `${wire.id}:${wire.segment}`,
  {id:wire.id,segment:wire.segment,selected:wire.selected,context:wire.context},
]));

function fixtureInteractionDelta(candidate, baseRevision) {
  syncToolbarDescriptor(candidate);
  syncCanvasHeadingDescriptor(candidate);
  const nextNodeStates=new Map(candidate.nodes.map(node => [node.id,{
    id:node.id,selected:node.selected,x:node.x,y:node.y,
  }]));
  const nextWireStates=new Map(candidate.wires.map(wire => [
    `${wire.id}:${wire.segment}`,
    {id:wire.id,segment:wire.segment,selected:wire.selected,context:wire.context},
  ]));
  const nodeStates=[...nextNodeStates].filter(([root,state]) => {
    const before=servedNodeStates.get(root);
    return !before || before.selected !== state.selected
      || before.x !== state.x || before.y !== state.y;
  }).map(([_root,state]) => state);
  const wireStates=[...nextWireStates].filter(([root,state]) => {
    const before=servedWireStates.get(root);
    return !before || before.selected !== state.selected
      || before.context !== state.context;
  }).map(([_root,state]) => state);
  servedNodeStates=nextNodeStates;
  servedWireStates=nextWireStates;
  const fields=[
    'revision','selected','selection','selected_title','focus','obligations',
    'authorization','catalog','scope','authoring','inspector','properties',
    'selected_relation',
    'selected_interface','selected_interfaces','viewport',
    'selected_definition','selected_assembly','physical',
    'interaction_projection','toolbar_descriptor','canvas_heading_descriptor',
    'canvas_signature',
  ];
  const delta={
    ok:true,
    touched:candidate.revision,
    projection_mode:'interaction-delta-v1',
    base_revision:baseRevision,
    connection_count:candidate.connections.length,
    node_count:candidate.nodes.length,
    wire_count:candidate.wires.length,
    node_states:nodeStates,
    wire_states:wireStates,
    control_state:input.controlStateAfter
      || candidate.configuration.design_system.control_catalog,
    configuration_state:Object.fromEntries(Object.entries(
      candidate.configuration).filter(([key]) => key !== 'design_system')),
  };
  fields.forEach(field => { delta[field]=candidate[field]; });
  return delta;
}

function fixtureTopologyDelta(candidate, baseRevision, topologyPatch=null) {
  const delta=fixtureInteractionDelta(candidate,baseRevision);
  delta.projection_mode='topology-delta-v1';
  if (topologyPatch) {
    delta.topology_patch={
      node_order:candidate.nodes.map(node => node.id),
      wire_order:candidate.wires.map(wire => `${wire.id}:${wire.segment}`),
      remove_nodes:topologyPatch.remove_nodes || [],
      remove_wires:topologyPatch.remove_wires || [],
      upsert_nodes:topologyPatch.upsert_nodes || [],
      upsert_wires:topologyPatch.upsert_wires || [],
    };
  } else {
    delta.topology_recovery=true;
    // response().json() performs the one browser-side materialization that
    // represents parsing the server response; cloning here would count it twice.
    delta.nodes=candidate.nodes;
    delta.wires=candidate.wires;
  }
  delete delta.node_states;
  delete delta.wire_states;
  return delta;
}

const initialRenderStarted = performance.now();
const runtimeErrors = [];
const dom = new JSDOM(input.html, {
  url: 'http://127.0.0.1:8501/',
  runScripts: 'dangerously',
  pretendToBeVisual: true,
  beforeParse(window) {
    window.console.error = (...values) => {
      runtimeErrors.push(values.map(value => String(value?.message || value)).join(' '));
    };
    class PointerEvent extends window.MouseEvent {
      constructor(type, init = {}) {
        super(type, init);
        Object.defineProperty(this, 'pointerId', { value: init.pointerId ?? 1 });
        Object.defineProperty(this, 'isPrimary', { value: init.isPrimary ?? true });
      }
    }
    window.PointerEvent = PointerEvent;
    window.requestAnimationFrame = callback => window.setTimeout(
      () => callback(window.performance.now()), 0);
    window.cancelAnimationFrame = handle => window.clearTimeout(handle);
    window.Element.prototype.setPointerCapture = function setPointerCapture() {};
    window.Element.prototype.releasePointerCapture = function releasePointerCapture() {};
    window.document.elementFromPoint = () => null;
    window.fetch = async (path, options = {}) => {
      const route = String(path);
      const payload = options.body ? JSON.parse(options.body) : {};
      requests.push({ route, payload });
      if (route.endsWith('/canvas')) return response({ ok: true, ...projection });
      if (route.endsWith('/gesture')) {
        if (
          ['rapid_queued_gestures','queued_governed_mutations'].includes(
            input.scenario)
          && payload.projection_revision !== projection.revision
        ) {
          staleGestureCount += 1;
          return {
            ok: false,
            async json() {
              return {ok: false, error: 'interaction delta projection is stale'};
            },
          };
        }
        if (
          input.scenario === 'rejected_gesture'
          || (
            input.scenario === 'rejected_then_success'
            && rejectedGestureCount++ === 0
          )
        ) {
          return {
            ok: false,
            async json() {
              return {ok: false, error: 'Selection denied by authority'};
            },
          };
        }
        const baseRevision=projection.revision;
        if (payload.roots) applyFixtureSelection(payload.roots, payload.focus);
        if (payload.viewport) projection.viewport={...payload.viewport};
        if (payload.roots || payload.viewport) {
          projection.canvas_signature=(
            `${projection.canvas_signature}:gesture:${projection.revision+1}`
          );
        }
        if (input.scenario === 'delta_authority_catalog_merge') {
          projection.authorization={
            ...projection.authorization,
            assigned_canvas_roots:987,
          };
          projection.catalog=projection.catalog.map((item,index) => (
            index === 0 ? {...item,label:'Updated canonical definition'} : item
          ));
        }
        if (input.scenario === 'tabs_after_mutation') {
          await new Promise(resolve => window.setTimeout(resolve, 50));
          projection.revision += 1;
          projection.interaction_projection={
            ...projection.interaction_projection,
            revision:projection.revision,
          };
        }
        if (input.deltaResponses) projection.revision += 1;
        return response(
          input.deltaResponses
            ? fixtureInteractionDelta(projection,baseRevision)
            : { ok: true, ...projection },
          () => { gestureResponseDelivered += 1; },
        );
      }
      if (route.endsWith('/interaction')) {
        if (
          input.scenario === 'tabs_expired_lease'
          && expiredInteractionCount++ === 0
        ) {
          return {
            ok:false,
            status:409,
            async json() {
              return {
                ok:false,
                error:'projection lease expired',
                code:'projection_lease_expired',
                retryable:true,
              };
            },
          };
        }
        const binding=projection.interaction_projection?.bindings.find(
          item => item.interaction === payload.interaction &&
            item.control === payload.control && item.event === payload.event
        );
        if (!binding || payload.revision !== projection.interaction_projection.revision) {
          return {
            ok:false,
            async json() { return {ok:false,error:'Interaction lease rejected'}; },
          };
        }
        const historyOperation=historyControlOperation(
          projection,binding.control);
        if (
          input.scenario === 'history_keyboard'
          && historyOperation
          && input.historyProjectionResponses
        ) {
          const baseRevision=projection.revision;
          const next=input.historyProjectionResponses[historyResponseIndex];
          if (!next) throw new Error('history projection response is missing');
          historyResponseIndex+=1;
          projection=structuredClone(next);
          syncHistoryInteractions(projection);
          return response(
            fixtureTopologyDelta(projection,baseRevision),
            () => { topologyResponseDelivered+=1; },
          );
        }
        if (input.scenario === 'relation_composer') {
          const operation=relationComposerControlOperation(
            projection,binding.control);
          if (operation) {
            const baseRevision=projection.revision;
            if (operation === 'create') {
              projection.revision+=1;
              syncRelationComposerInteractions(projection);
              return response(fixtureTopologyDelta(projection,baseRevision));
            }
            relationComposerRequestCount+=1;
            const next=relationComposerResponses.shift();
            if (!next) {
              throw new Error('relation composer fixture response exhausted');
            }
            projection=structuredClone(next);
            syncRelationComposerInteractions(projection);
            return response(fixtureInteractionDelta(projection,baseRevision));
          }
        }
        const connectPort=projection.nodes.flatMap(node => (
          (node.ports || []).map(port => ({node,port}))
        )).find(item => item.port.connect_control === binding.control);
        if (connectPort && input.scenario === 'wire_rejected') {
          return {
            ok:false,
            async json() {
              return {ok:false,error:'Connection contract rejected this wire'};
            },
          };
        }
        const disconnectWire=projection.wires.find(wire => (
          wire.disconnect_control === binding.control));
        if (disconnectWire && input.scenario === 'wire_delete') {
          const baseRevision=projection.revision;
          projection.wires=projection.wires.filter(
            wire => wire.id !== disconnectWire.id);
          projection.selected=disconnectWire.source;
          projection.selected_title=projection.nodes.find(
            node => node.id === disconnectWire.source)?.label || 'Source';
          projection.selected_relation=null;
          projection.revision+=1;
          syncTopologyInteractions(projection);
          return response(
            fixtureTopologyDelta(projection,baseRevision),
            () => { topologyResponseDelivered += 1; },
          );
        }
        const rewireMatch=projection.wires.flatMap(wire => (
          ['source','target'].map(side => ({wire,side}))
        )).find(item => (
          item.wire[item.side+'_rewire_control'] === binding.control));
        if (rewireMatch && [
          'wire_endpoint_rewire','relation_rewire',
        ].includes(input.scenario)) {
          const fact=payload.event_facts?.find(item => (
            item.input === 'court:event-fact:topology-candidate-index'));
          const choices=rewireMatch.wire[
            rewireMatch.side+'_rewire_choices'] || [];
          const choice=Number.isSafeInteger(fact?.value)
            ? choices[fact.value] : null;
          if (!choice) throw new Error('topology rewire choice is missing');
          const baseRevision=projection.revision;
          rewireMatch.wire[rewireMatch.side+'_interface']=choice.id;
          rewireMatch.wire[rewireMatch.side]=choice.owner;
          const endpoint=projection.selected_relation?.[rewireMatch.side];
          if (endpoint) {
            endpoint.participant_interface=choice.id;
            endpoint.participant_owner=choice.owner;
            endpoint.participant=choice.id;
          }
          projection.revision+=1;
          syncTopologyInteractions(projection);
          return response(
            fixtureTopologyDelta(projection,baseRevision),
            () => { topologyResponseDelivered += 1; },
          );
        }
        const placementScenario=[
          'library_place','library_place_rejected','topology_delta_reconcile',
          'performance_topology_250','primitive_drag',
        ].includes(input.scenario) && (
          projection.primitive?.id === binding.control
          || projection.catalog.some(
            item => item.id === binding.control && !item.composition_contract)
        );
        if (placementScenario && input.scenario === 'library_place_rejected') {
          return {
            ok:false,
            async json() {
              return {ok:false,error:'Governed placement was rejected'};
            },
          };
        }
        if (
          placementScenario
          && (
            input.scenario === 'topology_delta_reconcile'
            || input.scenario === 'performance_topology_250'
          )
        ) {
          const baseRevision=projection.revision;
          const previouslySelected=new Set(projection.nodes.filter(
            node => node.selected).map(node => node.id));
          const entered={
            ...structuredClone(projection.nodes[0]),
            id:'court:node:entered',
            label:'Entered court node',
            x:980,
            y:620,
            selected:true,
            ports:[],
          };
          entered.card_descriptor=retargetCardDescriptor(
            projection.nodes[0],entered.id,entered.label);
          projection.nodes=projection.nodes.map(node => ({
            ...node,selected:false,
          })).concat(entered);
          const wireTemplate=projection.wires[0] || {
            color:'#5fb3b3',width:1.35,dash:'',directed:false,context:false,
          };
          const enteredWire={
            ...structuredClone(wireTemplate),
            id:'court:relation:entered',
            segment:'court:relation:entered:segment',
            source:projection.nodes[0].id,
            target:entered.id,
            source_interface:null,
            target_interface:null,
            source_incidence:null,
            target_incidence:null,
            selected:false,
          };
          projection.wires=projection.wires.concat(enteredWire);
          projection.selected=entered.id;
          projection.selection=[entered.id];
          projection.selected_title=entered.label;
          projection.revision+=1;
          return response(
            fixtureTopologyDelta(projection,baseRevision,{
              upsert_nodes:projection.nodes.filter(node => (
                node.id === entered.id || previouslySelected.has(node.id)
              )),
              upsert_wires:[enteredWire],
            }),
            () => { topologyResponseDelivered += 1; },
          );
        }
        if (
          (input.scenario === 'build_lens'
            || input.scenario === 'performance_lens_250')
          && Array.isArray(binding.inputs)
          && binding.inputs.length === 2
          && binding.inputs[0] === projection.inspector.active
        ) {
          const baseRevision=projection.revision;
          const target=binding.inputs[1];
          projection.inspector.active=target;
          projection.inspector.lenses=projection.inspector.lenses.map(lens => ({
            ...lens,
            active:lens.id === target,
          }));
          projection.revision+=1;
          projection.interaction_projection={
            revision:projection.revision,
            lifecycle:'wip',
            bindings:[],
          };
          projection.canvas_signature=(
            `${projection.canvas_signature}:lens:${target}`
          );
          syncInspectorDescriptors(projection);
          return response(fixtureInteractionDelta(projection,baseRevision));
        }
        if (
          input.scenario === 'group_control'
          && payload.control === 'app:control:canvas:group'
          && binding.inputs?.[0] === 'app:control-binding:canvas:group'
        ) {
          const baseRevision=projection.revision;
          projection.revision+=1;
          projection.interaction_projection={
            revision:projection.revision,
            lifecycle:'wip',
            bindings:[],
          };
          return response(fixtureTopologyDelta(projection,baseRevision));
        }
        if (
          (input.scenario === 'scope_navigation'
            || input.scenario === 'scope_keyboard'
            || input.scenario === 'scope_reconciliation_change')
          && Array.isArray(binding.inputs)
          && binding.inputs.length === 2
          && binding.inputs[0] === projection.scope.current
        ) {
          const baseRevision=projection.revision;
          const target=binding.inputs[1];
          if (target === initialScope.current) {
            projection.scope=structuredClone(initialScope);
            projection.interaction_projection={
              ...structuredClone(initialInteractionProjection),
              revision:baseRevision+1,
            };
          } else {
            const targetNode=projection.nodes.find(node => node.id === target);
            projection.scope={
              current:target,
              current_label:targetNode?.label || 'Nested scope',
              parent:initialScope.current,
              trail:[
                {...initialScope.trail[0],current:false},
                {root:target,label:targetNode?.label || 'Nested scope',current:true},
              ],
            };
            const retained=(projection.interaction_projection.bindings || [])
              .filter(item => !Array.isArray(item.inputs)
                || item.inputs.length !== 2);
            projection.interaction_projection={
              ...projection.interaction_projection,
              revision:baseRevision+1,
              bindings:[...retained,{
                control:initialScope.current,
                interaction:'court:interaction:scope:return',
                event:'court:event:activate',
                inputs:[target,initialScope.current],
                event_facts:[],
              }],
            };
          }
          projection.revision=baseRevision+1;
          projection.canvas_signature=(
            `${projection.canvas_signature}:scope:${projection.scope.current}`
          );
          syncToolbarDescriptor(projection);
          syncCanvasHeadingDescriptor(projection);
          return response(fixtureTopologyDelta(projection,baseRevision));
        }
        const editableProperty=projection.properties.find(property => (
          property.editable && property.control === binding.control
          && (
            property.batch ? (
              binding.inputs?.[0] === property.operation
              && binding.inputs?.[1] === property.control
            ) : (
              binding.inputs?.[0] === property.relation
              && binding.inputs?.[1] === property.value_root
            )
          )
          && binding.inputs?.[2] === property.event_fact_input
        ));
        const themeField=(projection.configuration?.theme_fields || []).find(
          field => field.control === binding.control);
        if (themeField) {
          const fact=payload.event_facts?.find(item => (
            item.input === themeField.event_fact_input));
          if (!fact || typeof fact.value !== 'string') {
            throw new Error('Theme submitted Event Fact is missing');
          }
          const baseRevision=projection.revision;
          projection.revision+=1;
          projection.configuration.theme={
            ...projection.configuration.theme,[themeField.key]:fact.value,
          };
          projection.configuration.theme_fields=(
            projection.configuration.theme_fields.map(field => (
              field.key === themeField.key ? {...field,value:fact.value} : field
            ))
          );
          syncPresentationInteractions(projection);
          return response(fixtureInteractionDelta(projection,baseRevision));
        }
        const themeRestore=(projection.configuration?.history || []).find(
          item => item.restore_control === binding.control);
        if (themeRestore) {
          const baseRevision=projection.revision;
          projection.revision+=1;
          projection.configuration.history=(
            projection.configuration.history.map(item => ({
              ...item,current:item.revision === themeRestore.revision,
              restore_control:item.revision === themeRestore.revision
                ? null : (item.restore_control
                  || `court:theme:restore:${item.revision}`),
            }))
          );
          syncPresentationInteractions(projection);
          return response(fixtureInteractionDelta(projection,baseRevision));
        }
        const appearanceProperty=projection.properties.find(property => (
          property.presentation_editable
          && (
            property.presentation_control === binding.control
            || property.presentation_reset_control === binding.control
          )
        ));
        if (appearanceProperty) {
          const preview=(
            appearanceProperty.presentation_control === binding.control);
          let color=appearanceProperty.value;
          if (preview) {
            const fact=payload.event_facts?.find(item => (
              item.input === appearanceProperty.presentation_event_fact_input));
            if (!fact || typeof fact.value !== 'string') {
              throw new Error('Presentation submitted Event Fact is missing');
            }
            color=fact.value;
          }
          const baseRevision=projection.revision;
          projection.revision+=1;
          projection.properties=projection.properties.map(property => (
            property.relation === appearanceProperty.relation
              ? preview ? {
                  ...property,
                  value:color,
                  presentation_revision:'court:presentation:revision',
                  presentation_source_mode:'personal-wip',
                  presentation_source:'Personal appearance draft',
                  presentation_reset:true,
                  presentation_reset_control:(
                    property.presentation_reset_control
                    || `court:appearance:reset:${property.relation}`
                  ),
                } : {
                  ...property,
                  presentation_revision:'court:presentation:reset',
                  presentation_source_mode:'inherited',
                  presentation_source:'Inherited node appearance',
                  presentation_reset:false,
                  presentation_reset_control:null,
                }
              : property
          ));
          if (preview) projection.nodes=projection.nodes.map(node => (
            node.id === appearanceProperty.owner ? {...node,color} : node
          ));
          const changed=projection.properties.find(property => (
            property.relation === appearanceProperty.relation));
          if (changed) syncPresentationDescriptor(changed);
          syncPresentationInteractions(projection);
          return response(fixtureInteractionDelta(projection,baseRevision));
        }
        if (editableProperty) {
          const fact=payload.event_facts?.find(item => (
            item.input === editableProperty.event_fact_input));
          if (!fact || typeof fact.value !== 'string') {
            throw new Error('Property submitted Event Fact is missing');
          }
          const baseRevision=projection.revision;
          projection.properties=projection.properties.map(property => (
            property.relation === editableProperty.relation
              ? {...property,value:fact.value,mixed:false}
              : property
          ));
          const changed=projection.properties.find(property => (
            property.relation === editableProperty.relation));
          if (changed) syncEditablePropertyDescriptor(changed);
          if (input.scenario === 'topology_reconcile') {
            const exited=projection.nodes.at(-1);
            const entered={
              ...structuredClone(projection.nodes[0]),
              id:'court:node:entered',
              label:'Entered court node',
              x:980,
              y:620,
              selected:false,
              ports:[],
            };
            entered.card_descriptor=retargetCardDescriptor(
              projection.nodes[0],entered.id,entered.label);
            projection.nodes=[...projection.nodes.slice(0,-1),entered];
            const retainedWires=projection.wires.slice(0,-1);
            const wireTemplate=projection.wires[0] || {
              color:'#5fb3b3',width:1.35,dash:'',directed:false,context:false,
            };
            projection.wires=[...retainedWires,{
              ...structuredClone(wireTemplate),
              id:'court:relation:entered',
              segment:'court:relation:entered:segment',
              source:projection.nodes[0].id,
              target:entered.id,
              source_interface:null,
              target_interface:null,
              source_incidence:null,
              target_incidence:null,
              selected:false,
            }];
            projection.selection=projection.selection.filter(
              root => root !== exited.id);
            projection.canvas_signature=(
              `${projection.canvas_signature}:topology-reconcile`
            );
          }
          projection.interaction_projection={
            ...projection.interaction_projection,
            revision:projection.interaction_projection.revision+1,
          };
          projection.revision=projection.interaction_projection.revision;
          return response(
            input.scenario === 'topology_reconcile'
              ? {ok:true,...projection}
              : fixtureInteractionDelta(projection,baseRevision),
            () => { propertyResponseDelivered += 1; },
          );
        }
        const editableInterface=projection.selected_interfaces.find(item => (
          item.editable && item.mode === 'connection'
          && item.control === binding.control
          && binding.inputs?.[0] === item.owner
          && binding.inputs?.[1] === item.id
          && binding.inputs?.[2] === item.target
          && binding.inputs?.[3] === item.event_fact_input
        ));
        if (editableInterface) {
          const fact=payload.event_facts?.find(item => (
            item.input === editableInterface.event_fact_input));
          if (!fact || typeof fact.value !== 'string') {
            throw new Error('Interface submitted Event Fact is missing');
          }
          projection.selected_interfaces=projection.selected_interfaces.map(
            item => item.id === editableInterface.id
              ? {...item,value:fact.value}
              : item
          );
          const changed=projection.selected_interfaces.find(
            item => item.id === editableInterface.id);
          if (changed) syncEditablePropertyDescriptor(changed);
          projection.interaction_projection={
            ...projection.interaction_projection,
            revision:projection.interaction_projection.revision+1,
          };
          projection.revision=projection.interaction_projection.revision;
          return response(
            {ok:true,...projection},
            () => { interfaceValueResponseDelivered += 1; },
          );
        }
        const editableCollectionItem=projection.selected_interfaces.flatMap(
          item => item.editable && item.mode === 'collection'
            ? item.items.map(member => ({
              owner:item.owner,interface:item.id,...member,
            })) : []
        ).find(item => (
          item.control === binding.control
          && binding.inputs?.[0] === item.owner
          && binding.inputs?.[1] === item.interface
          && binding.inputs?.[2] === item.incidence
          && binding.inputs?.[3] === item.value_root
          && binding.inputs?.[4] === item.event_fact_input
        ));
        if (editableCollectionItem) {
          const fact=payload.event_facts?.find(item => (
            item.input === editableCollectionItem.event_fact_input));
          if (!fact || typeof fact.value !== 'string') {
            throw new Error('Collection submitted Event Fact is missing');
          }
          projection.selected_interfaces=projection.selected_interfaces.map(
            item => item.id === editableCollectionItem.interface
              ? {...item,items:item.items.map(member => (
                member.incidence === editableCollectionItem.incidence
                  ? {...member,value:fact.value}
                  : member
              ))}
              : item
          );
          projection.interaction_projection={
            ...projection.interaction_projection,
            revision:projection.interaction_projection.revision+1,
          };
          projection.revision=projection.interaction_projection.revision;
          return response(
            {ok:true,...projection},
            () => { collectionValueResponseDelivered += 1; },
          );
        }
        if (binding.event_facts?.length) {
          projection.interaction_projection={
            ...projection.interaction_projection,
            revision:projection.interaction_projection.revision+1,
          };
          projection.revision=projection.interaction_projection.revision;
          return response({ok:true,...projection});
        }
        projection.inspector.presentation.active=payload.control;
        projection.inspector.presentation.panels=(
          projection.inspector.presentation.panels.map(panel => ({
            ...panel,
            active:panel.id === payload.control,
          }))
        );
        projection.interaction_projection={
          ...projection.interaction_projection,
          revision:projection.interaction_projection.revision+1,
        };
        syncInspectorDescriptors(projection);
        return response({ok:true,...projection});
      }
      if (
        route.endsWith('/instantiate')
        && input.scenario === 'library_place_rejected'
      ) {
        return {
          ok:false,
          async json() {
            return {ok:false,error:'Governed placement was rejected'};
          },
        };
      }
      if (
        route.endsWith('/instantiate')
        && (
          input.scenario === 'topology_delta_reconcile'
          || input.scenario === 'performance_topology_250'
        )
      ) {
        const baseRevision=projection.revision;
        const previouslySelected=new Set(projection.nodes.filter(
          node => node.selected).map(node => node.id));
        const entered={
          ...structuredClone(projection.nodes[0]),
          id:'court:node:entered',
          label:'Entered court node',
          x:980,
          y:620,
          selected:true,
          ports:[],
        };
        entered.card_descriptor=retargetCardDescriptor(
          projection.nodes[0],entered.id,entered.label);
        projection.nodes=projection.nodes.map(node => ({
          ...node,selected:false,
        })).concat(entered);
        const wireTemplate=projection.wires[0] || {
          color:'#5fb3b3',width:1.35,dash:'',directed:false,context:false,
        };
        const enteredWire={
          ...structuredClone(wireTemplate),
          id:'court:relation:entered',
          segment:'court:relation:entered:segment',
          source:projection.nodes[0].id,
          target:entered.id,
          source_interface:null,
          target_interface:null,
          source_incidence:null,
          target_incidence:null,
          selected:false,
        };
        projection.wires=projection.wires.concat(enteredWire);
        projection.selected=entered.id;
        projection.selection=[entered.id];
        projection.selected_title=entered.label;
        projection.revision+=1;
        return response(
          fixtureTopologyDelta(projection,baseRevision,{
            upsert_nodes:projection.nodes.filter(node => (
              node.id === entered.id || previouslySelected.has(node.id)
            )),
            upsert_wires:[enteredWire],
          }),
          () => { topologyResponseDelivered += 1; },
        );
      }
      return response({ ok: true, ...projection });
    };
  },
});

const { window } = dom;
const { document } = window;

async function settle(rounds = 8) {
  for (let index = 0; index < rounds; index += 1) {
    await new Promise(resolve => window.setTimeout(resolve, 5));
  }
}

async function waitUntil(predicate, timeoutMs = 3000) {
  const started = performance.now();
  while (!predicate()) {
    if (performance.now() - started > timeoutMs) {
      throw new Error('rendered-DOM condition timed out');
    }
    await new Promise(resolve => window.setTimeout(resolve, 1));
  }
}

function rect(left, top, width, height) {
  return {
    x: left, y: top, left, top, width, height,
    right: left + width, bottom: top + height,
    toJSON() { return this; },
  };
}

function installGeometry() {
  const canvas = document.querySelector('.canvas');
  const stage = document.querySelector('.canvas-stage');
  const selectionBox = document.querySelector('.selection-box');
  const overlayBounds = rect(25, 10, 1200, 760);
  canvas.getBoundingClientRect = () => rect(100, 50, 800, 600);
  stage.getBoundingClientRect = () => rect(100, 50, 1320, 760);
  Object.defineProperty(selectionBox, 'offsetParent', {
    configurable: true,
    value: {getBoundingClientRect: () => overlayBounds},
  });
  const viewport = projection.viewport;
  const bounds = [];
  [...document.querySelectorAll('.graph-node[data-graph-node]')].forEach((card, index) => {
    const node = projection.nodes.find(item => item.id === card.dataset.graphNode);
    const cardBounds = input.scenario === 'marquee_viewport'
      ? rect(
          100 + viewport.pan_x + Number(node.x) * viewport.zoom,
          50 + viewport.pan_y + Number(node.y) * viewport.zoom,
          120 * viewport.zoom,
          80 * viewport.zoom,
        )
      : rect(150 + index * 180, 110, 120, 80);
    bounds.push(cardBounds);
    card.getBoundingClientRect = () => cardBounds;
    card.getClientRects = () => [cardBounds];
  });
  return { canvas, bounds, overlayBounds };
}

function pointer(target, type, init = {}) {
  target.dispatchEvent(new window.PointerEvent(type, {
    bubbles: true,
    cancelable: true,
    button: 0,
    buttons: type === 'pointerup' ? 0 : 1,
    pointerId: 7,
    clientX: 170,
    clientY: 130,
    ...init,
  }));
}

function wheel(target, init = {}) {
  const event = new window.Event('wheel', {bubbles:true,cancelable:true});
  for (const [key,value] of Object.entries({
    deltaY:120,
    deltaMode:0,
    clientX:500,
    clientY:320,
    ...init,
  })) Object.defineProperty(event,key,{value});
  target.dispatchEvent(event);
}

function drag(target, type, dataTransfer, init = {}) {
  const event=new window.Event(type, {bubbles:true,cancelable:true});
  Object.defineProperty(event,'dataTransfer',{value:dataTransfer});
  Object.defineProperty(event,'clientX',{value:init.clientX ?? 420});
  Object.defineProperty(event,'clientY',{value:init.clientY ?? 260});
  target.dispatchEvent(event);
}

await settle();
const initialCanvasRequestCount=requests.filter(
  item => item.route.endsWith('/canvas')).length;
const initialRenderMs = performance.now() - initialRenderStarted;
const geometry = installGeometry();
const canvas = geometry.canvas;
const cards = [...document.querySelectorAll('.graph-node[data-graph-node]')];
const initialFirstCard = cards[0];
const initialFirstWire = document.querySelector(
  '.universal-wire[data-universal-relation]');
const initialFirstSocket = document.querySelector(
  '[data-universal-interface]');
const initialLibraryPrimitive = document.querySelector(
  '[data-universal-primitive]');
const initialToolbarZoom = document.querySelector(
  '[data-universal-zoom="out"]');
const initialExactSocketCount = document.querySelectorAll(
  '.node-port-exact[data-universal-interface]').length;
const initialExpandedSocketCount = document.querySelectorAll(
  '.node-port:not(.node-port-exact)[data-universal-interface]').length;
const initialCardsById = new Map(cards.map(card => [
  card.dataset.universalRoot,card,
]));
const initialWiresByKey = new Map([...document.querySelectorAll(
  '.universal-wire[data-universal-relation]')].map(wire => [
  wire.dataset.uiKey,wire,
]));
const initialPositions = cards.map(card => ({
  left: card.style.left,
  top: card.style.top,
}));
let wirePreviewCount = 0;
let wireTargetReadyCount = 0;
let rewireTargetReadyCount = 0;
let relationCandidateCount = null;
let selectionFeedbackMs = null;
let selectionCommitMs = null;
let propertyReconcileMs = null;
let topologyReconcileMs = null;
let lensReconcileMs = null;
let wirePreviewMs = null;
let dragFeedbackMs = null;
let dragCommitMs = null;
let wheelFeedbackMs = null;
let wheelCommitMs = null;
let panFeedbackMs = null;
let panCommitMs = null;
let historyPositions = null;
let propertyInputIdentityPreserved = null;
let liveMarquee = null;
let modifierMarquee = null;
let reconciliationChangeDispatches = 0;
let deltaAuthorityCatalog = null;

function selectionBoxSnapshot() {
  const box = document.querySelector('.selection-box');
  return box ? {
    display: box.style.display,
    left: box.style.left,
    top: box.style.top,
    width: box.style.width,
    height: box.style.height,
    mode: box.dataset.mode,
  } : null;
}

if (!cards.length) throw new Error(
  `universal canvas did not render any nodes: ${runtimeErrors.join(' | ')}`);

if (input.scenario === 'duplicate_projection') {
  const candidate={
    ...structuredClone(projection),
    nodes:[...projection.nodes,structuredClone(projection.nodes[0])],
  };
  try {
    window.__archhubUniversalValidateProjection(candidate);
  } catch (error) {
    runtimeErrors.push(String(error.message || error));
  }
} else if (input.scenario === 'click_payload') {
  pointer(cards[1], 'pointerdown', { clientX: 350, clientY: 130 });
  pointer(cards[1], 'pointerup', { clientX: 350, clientY: 130 });
  await new Promise(resolve => window.setTimeout(resolve, 250));
  await waitUntil(() => gestureResponseDelivered >= 1);
  pointer(cards[0], 'pointerdown', { clientX: 170, clientY: 130 });
  pointer(cards[0], 'pointerup', { clientX: 170, clientY: 130 });
  await new Promise(resolve => window.setTimeout(resolve, 250));
  await waitUntil(() => gestureResponseDelivered >= 2);
  await settle();


} else if (input.scenario === 'interface_click_payload') {
  if (!initialFirstSocket) throw new Error('no universal interface rendered');
  initialFirstSocket.click();
  await settle();
} else if (input.scenario === 'shift_remove') {
  pointer(cards[0], 'pointerdown', { shiftKey: true });
  pointer(cards[0], 'pointerup', { shiftKey: true });
  await settle();
} else if (input.scenario === 'ctrl_retains') {
  pointer(cards[0], 'pointerdown', { ctrlKey: true });
  pointer(cards[0], 'pointerup', { ctrlKey: true });
  await settle();
} else if (input.scenario === 'toolbar_group_dynamic') {
  pointer(cards[1], 'pointerdown', {ctrlKey:true});
  pointer(cards[1], 'pointerup', {ctrlKey:true});
  await waitUntil(() => gestureResponseDelivered > 0);
  await settle();
} else if (input.scenario === 'group_control') {
  const group=document.querySelector(
    '[data-universal-control="app:control:canvas:group"]');
  if (!group) throw new Error('Group toolbar control is missing');
  group.click();
  await waitUntil(() => requests.some(item => (
    item.route.endsWith('/interaction')
    && item.payload.control === 'app:control:canvas:group')));
  await settle();
} else if (input.scenario === 'queued_governed_mutations') {
  const first=window.__archhubUniversalCommit({
    roots:[cards[1].dataset.universalRoot],
    focus:cards[1].dataset.universalRoot,
  });
  const second=window.__archhubUniversalCommit({
    roots:[cards[2].dataset.universalRoot],
    focus:cards[2].dataset.universalRoot,
  });
  await Promise.all([first,second]);
  await settle();
} else if (input.scenario === 'scope_navigation') {
  canvas.scrollLeft=420;
  canvas.scrollTop=180;
  const openable=cards.find(card => card.dataset.universalOpenable === 'True');
  if (!openable) throw new Error('no openable graph card is visible');
  const title=openable.querySelector('.node-title') || openable;
  title.dispatchEvent(new window.MouseEvent('dblclick', {
    bubbles:true,cancelable:true,detail:2,
  }));
  await settle();
  const parent=document.querySelector(
    `[data-universal-scope="${initialScope.current}"]`);
  if (!parent) throw new Error('scope breadcrumb was not rendered');
  parent.click();
  await settle();
} else if (input.scenario === 'scope_keyboard') {
  const openable=cards.find(card => card.dataset.universalOpenable === 'True');
  if (!openable) throw new Error('no openable graph card is visible');
  openable.focus();
  openable.dispatchEvent(new window.KeyboardEvent('keydown', {
    key:'Enter',code:'Enter',bubbles:true,cancelable:true,
  }));
  await settle();
} else if (input.scenario === 'scope_reconciliation_change') {
  const openable=cards.find(card => card.dataset.universalOpenable === 'True');
  const property=document.querySelector('[data-universal-event-fact-input]');
  const stage=document.querySelector('.canvas-stage');
  if (!openable || !property || !stage) {
    throw new Error('scope reconciliation fixture is incomplete');
  }
  const stale=document.createElement('div');
  stale.dataset.uiKey='court:stale-projection-input';
  const staleProperty=property.cloneNode(true);
  stale.append(staleProperty);
  stage.append(stale);
  const remove=window.Element.prototype.remove;
  window.Element.prototype.remove=function removeWithSyntheticChange() {
    if (this === stale) {
      reconciliationChangeDispatches+=1;
      staleProperty.dispatchEvent(new window.Event('change', {
        bubbles:true,cancelable:true,
      }));
    }
    return remove.call(this);
  };
  const title=openable.querySelector('.node-title') || openable;
  title.dispatchEvent(new window.MouseEvent('dblclick', {
    bubbles:true,cancelable:true,detail:2,
  }));
  await settle();
  window.Element.prototype.remove=remove;
} else if (input.scenario === 'fit') {
  canvas.scrollLeft=137;
  canvas.scrollTop=251;
  document.querySelector('[data-universal-zoom="fit"]').click();
  await settle();
} else if (input.scenario === 'marquee') {
  pointer(canvas, 'pointerdown', { clientX: 120, clientY: 80 });
  pointer(canvas, 'pointermove', { clientX: 300, clientY: 220 });
  await settle(2);
  liveMarquee = selectionBoxSnapshot();
  pointer(canvas, 'pointerup', { clientX: 300, clientY: 220 });
  await waitUntil(() => gestureResponseDelivered > 0);
  await settle();
} else if (input.scenario === 'marquee_scroll') {
  pointer(cards[1], 'pointerdown', { clientX: 350, clientY: 130 });
  pointer(cards[1], 'pointerup', { clientX: 350, clientY: 130 });
  await new Promise(resolve => window.setTimeout(resolve, 250));
  await waitUntil(() => gestureResponseDelivered >= 1);
  canvas.scrollLeft = 137;
  canvas.scrollTop = 251;
  Object.defineProperty(document.querySelector('.selection-box'), 'offsetParent', {
    configurable: true,
    value: canvas,
  });
  pointer(canvas, 'pointerdown', { clientX: 120, clientY: 80 });
  pointer(canvas, 'pointermove', { clientX: 300, clientY: 220 });
  await settle(2);
  liveMarquee = selectionBoxSnapshot();
  pointer(canvas, 'pointerup', { clientX: 300, clientY: 220 });
  await waitUntil(() => gestureResponseDelivered >= 2);
  await settle();





} else if (input.scenario === 'marquee_viewport') {
  const first = geometry.bounds[0];
  const start = { x: first.left - 10, y: first.top - 10 };
  const end = { x: first.right + 10, y: first.bottom + 10 };
  pointer(canvas, 'pointerdown', { clientX: start.x, clientY: start.y });
  pointer(canvas, 'pointermove', { clientX: end.x, clientY: end.y });
  await settle(2);
  liveMarquee = selectionBoxSnapshot();
  pointer(canvas, 'pointerup', { clientX: end.x, clientY: end.y });
  await settle();
} else if (input.scenario === 'crossing') {
  pointer(canvas, 'pointerdown', { clientX: 500, clientY: 220 });
  pointer(canvas, 'pointermove', { clientX: 260, clientY: 80 });
  await settle(2);
  liveMarquee = selectionBoxSnapshot();
  pointer(canvas, 'pointerup', { clientX: 260, clientY: 80 });
  await settle();
} else if (input.scenario === 'modifier_marquee') {
  const first = geometry.bounds[0];
  const start = { x: first.left - 10, y: first.top - 10 };
  const end = { x: first.right + 10, y: first.bottom + 10 };
  pointer(canvas, 'pointerdown', {
    clientX: start.x, clientY: start.y, shiftKey: true,
  });
  pointer(canvas, 'pointermove', {
    clientX: end.x, clientY: end.y, shiftKey: true,
  });
  pointer(canvas, 'pointerup', {
    clientX: end.x, clientY: end.y, shiftKey: true,
  });
  await waitUntil(() => gestureResponseDelivered > 0);
  await settle();
  const afterShift = [...document.querySelectorAll(
    '[data-universal-root][data-selected="True"]'
  )].map(card => card.dataset.universalRoot);

  pointer(canvas, 'pointerdown', {
    clientX: start.x, clientY: start.y, ctrlKey: true,
  });
  pointer(canvas, 'pointermove', {
    clientX: end.x, clientY: end.y, ctrlKey: true,
  });
  pointer(canvas, 'pointerup', {
    clientX: end.x, clientY: end.y, ctrlKey: true,
  });
  await waitUntil(() => gestureResponseDelivered > 1);
  await settle();
  modifierMarquee = {
    afterShift,
    afterControl: [...document.querySelectorAll(
      '[data-universal-root][data-selected="True"]'
    )].map(card => card.dataset.universalRoot),
  };
} else if (input.scenario === 'cancel') {
  pointer(cards[1], 'pointerdown', { clientX: 360, clientY: 130 });
  pointer(cards[1], 'pointermove', { clientX: 420, clientY: 190 });
  await settle(2);
  pointer(cards[1], 'pointercancel', { clientX: 420, clientY: 190 });
  await settle();
} else if (input.scenario === 'escape_cancel') {
  pointer(cards[1], 'pointerdown', { clientX: 360, clientY: 130 });
  pointer(cards[1], 'pointermove', { clientX: 420, clientY: 190 });
  await settle(2);
  document.dispatchEvent(new window.KeyboardEvent('keydown', {
    key: 'Escape', code: 'Escape', bubbles: true, cancelable: true,
  }));
  await settle();
} else if (input.scenario === 'keyboard_select') {
  cards[0].focus();
  cards[0].dispatchEvent(new window.KeyboardEvent('keydown', {
    key: ' ', code: 'Space', bubbles: true, cancelable: true,
  }));
  await settle();
} else if (input.scenario === 'rejected_gesture') {
  pointer(cards[1], 'pointerdown', { clientX: 350, clientY: 130 });
  pointer(cards[1], 'pointerup', { clientX: 350, clientY: 130 });
  await waitUntil(() => requests.some(item => item.route.endsWith('/gesture')));
  await settle();
} else if (input.scenario === 'rejected_then_success') {
  pointer(cards[1], 'pointerdown', { clientX: 350, clientY: 130 });
  pointer(cards[1], 'pointerup', { clientX: 350, clientY: 130 });
  await waitUntil(() => requests.some(item => item.route.endsWith('/gesture')));
  await settle();
  pointer(cards[2], 'pointerdown', { clientX: 550, clientY: 130 });
  pointer(cards[2], 'pointerup', { clientX: 550, clientY: 130 });
  await waitUntil(() => gestureResponseDelivered > 0);
  await settle();


} else if (input.scenario === 'rapid_queued_gestures') {
  pointer(cards[1], 'pointerdown', {clientX:350,clientY:130});
  pointer(cards[1], 'pointerup', {clientX:350,clientY:130});
  pointer(cards[2], 'pointerdown', {clientX:550,clientY:130});
  pointer(cards[2], 'pointerup', {clientX:550,clientY:130});
  await waitUntil(() => requests.filter(
    item => item.route.endsWith('/gesture')).length === 2);
  await settle();
} else if (input.scenario === 'delta_authority_catalog_merge') {
  const target=projection.nodes[1] || projection.nodes[0];
  const accepted=await window.__archhubUniversalCommit({
    roots:[target.id],
    focus:target.id,
  });
  deltaAuthorityCatalog={
    revision:accepted.revision,
    assignedCanvasRoots:accepted.authorization.assigned_canvas_roots,
    firstDefinitionLabel:accepted.catalog[0].label,
  };
  await settle();
} else if (input.scenario === 'performance_250') {
  const target = cards.at(-1);
  const started = performance.now();
  pointer(target, 'pointerdown', {clientX: 680, clientY: 420});
  await waitUntil(() => target.dataset.selected === 'True');
  selectionFeedbackMs = performance.now() - started;
  pointer(target, 'pointerup', {clientX: 680, clientY: 420});
  await waitUntil(() => gestureResponseDelivered > 0);
  await settle(2);
  selectionCommitMs = performance.now() - started;
} else if (input.scenario === 'performance_lens_250') {
  const build=[...document.querySelectorAll(
    '[data-universal-inspector-lens]')].find(button =>
      button.textContent.trim() === 'Build');
  if (!build) throw new Error('Build lens control is missing');
  const started=performance.now();
  build.click();
  await waitUntil(() => requests.some(item =>
    item.route.endsWith('/interaction')));
  await settle(2);
  lensReconcileMs=performance.now()-started;
} else if (input.scenario === 'performance_wire_preview_250') {
  const output=document.querySelector(
    '[data-universal-output]:not([data-existing-only="true"])');
  if (!output) throw new Error('dense wire-preview source did not render');
  const started=performance.now();
  pointer(output,'pointerdown',{clientX:420,clientY:240});
  wirePreviewMs=performance.now()-started;
  wirePreviewCount=document.querySelectorAll('.universal-wire-preview').length;
  wireTargetReadyCount=document.querySelectorAll(
    '[data-universal-input].wire-target-ready').length;
  if (wirePreviewCount !== 1 || wireTargetReadyCount !== 250) {
    throw new Error('dense wire-preview feedback was not synchronous');
  }
  pointer(output,'pointercancel',{clientX:420,clientY:240});
  await settle(2);
} else if (input.scenario === 'performance_drag_250') {
  const target=cards.at(-1);
  const originalLeft=target.style.left;
  pointer(target,'pointerdown',{clientX:680,clientY:420});
  const started=performance.now();
  pointer(target,'pointermove',{clientX:760,clientY:420});
  await waitUntil(() => target.style.left !== originalLeft);
  dragFeedbackMs=performance.now()-started;
  pointer(target,'pointerup',{clientX:760,clientY:420});
  await waitUntil(() => gestureResponseDelivered > 0);
  await settle(2);
  dragCommitMs=performance.now()-started;
} else if (input.scenario === 'performance_wheel_250') {
  const stage=canvas.querySelector('.canvas-stage');
  const originalTransform=stage.style.transform;
  const started=performance.now();
  wheel(canvas,{deltaY:-180,clientX:480,clientY:320});
  await waitUntil(() => stage.style.transform !== originalTransform);
  wheelFeedbackMs=performance.now()-started;
  await waitUntil(() => requests.some(item => (
    item.route.endsWith('/gesture') && item.payload.viewport
  )));
  await waitUntil(() => gestureResponseDelivered > 0);
  wheelCommitMs=performance.now()-started;
} else if (input.scenario === 'performance_pan_250') {
  const stage=canvas.querySelector('.canvas-stage');
  const originalTransform=stage.style.transform;
  document.dispatchEvent(new window.KeyboardEvent('keydown', {
    code:'Space',key:' ',bubbles:true,cancelable:true,
  }));
  pointer(canvas,'pointerdown',{clientX:420,clientY:280});
  const started=performance.now();
  pointer(canvas,'pointermove',{clientX:500,clientY:340});
  await waitUntil(() => stage.style.transform !== originalTransform);
  panFeedbackMs=performance.now()-started;
  pointer(canvas,'pointerup',{clientX:500,clientY:340});
  await waitUntil(() => gestureResponseDelivered > 0);
  panCommitMs=performance.now()-started;
  document.dispatchEvent(new window.KeyboardEvent('keyup', {
    code:'Space',key:' ',bubbles:true,cancelable:true,
  }));
} else if (input.scenario === 'relation_rewire') {
  const source=document.querySelector('[data-universal-incidence]');
  if (!source) throw new Error('relation endpoint control did not render');
  const endpoint=[projection.selected_relation?.source,
    projection.selected_relation?.target].find(item => (
      item?.incidence === source.dataset.universalIncidence));
  const alternative=endpoint?.rewire_choices?.find(choice => (
    choice.id !== endpoint.participant_interface));
  if (!alternative) throw new Error('relation endpoint has no projected alternative');
  source.value=alternative.id;
  source.dispatchEvent(new window.Event('change', {bubbles:true,cancelable:true}));
  await settle();
} else if (input.scenario === 'wire_endpoint_rewire') {
  const handle=document.querySelector(
    '[data-universal-rewire-side="target"][data-focused="True"]');
  const wire=projection.wires.find(item => (
    item.id === handle?.dataset.universalRewireRelation));
  const choice=wire?.target_rewire_choices?.find(item => (
    item.id !== handle?.dataset.universalRewireInterface));
  const target=[...document.querySelectorAll(
    '[data-universal-input]:not([data-existing-only="true"])')].find(port =>
      port.dataset.universalInterface === choice?.id);
  if (!handle || !target) {
    throw new Error('selected wire has no reconnectable target endpoint');
  }
  document.elementFromPoint=() => target;
  pointer(handle,'pointerdown');
  rewireTargetReadyCount=document.querySelectorAll(
    '.wire-reconnect-ready').length;
  wirePreviewCount=document.querySelectorAll(
    '[data-universal-rewire-preview="true"]').length;
  pointer(handle,'pointermove',{clientX:420,clientY:240});
  pointer(handle,'pointerup',{clientX:420,clientY:240});
  await settle(2);
} else if (input.scenario === 'wire_cancel') {
  const output=document.querySelector(
    '[data-universal-output]:not([data-existing-only="true"])');
  if (!output) throw new Error('no connectable output port rendered');
  pointer(output, 'pointerdown');
  wirePreviewCount=document.querySelectorAll('.universal-wire-preview').length;
  wireTargetReadyCount=document.querySelectorAll(
    '[data-universal-input].wire-target-ready').length;
  pointer(output, 'pointercancel');
  await settle();
} else if (input.scenario === 'wire_rejected') {
  const output=document.querySelector(
    '[data-universal-output]:not([data-existing-only="true"])');
  const sourceNode=projection.nodes.find(node => (
    node.id === output?.dataset.universalOutput));
  const sourcePort=sourceNode?.ports.find(port => (
    port.id === output?.dataset.universalInterface));
  const target=[...document.querySelectorAll('[data-universal-input]')].find(
    item => item.dataset.universalInterface === sourcePort?.connect_choices?.[0]?.id);
  if (!output || !target) throw new Error('connectable wire endpoints are missing');
  document.elementFromPoint=() => target;
  pointer(output,'pointerdown');
  pointer(output,'pointermove',{clientX:420,clientY:260});
  pointer(output,'pointerup',{clientX:420,clientY:260});
  await settle();
} else if (input.scenario === 'wire_delete') {
  document.dispatchEvent(new window.KeyboardEvent('keydown', {
    key:'Delete',code:'Delete',bubbles:true,cancelable:true,
  }));
  await waitUntil(() => requests.some(
    item => item.route.endsWith('/interaction')
      && initialTopologyOperationByControl.get(item.payload.control)
        === 'court:topology:disconnect'));
  await settle();
} else if (input.scenario === 'tabs' || input.scenario === 'tabs_expired_lease') {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  if (tabs.length < 2) throw new Error('Properties did not render applicable panels');
  tabs[1].click();
  await settle();
  const currentTabs = [...document.querySelectorAll('[role="tab"]')];
  currentTabs[0].focus();
  currentTabs[0].dispatchEvent(new window.KeyboardEvent('keydown', {
    key: 'ArrowRight', bubbles: true, cancelable: true,
  }));
  await settle(2);
} else if (input.scenario === 'tabs_after_mutation') {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  if (tabs.length < 2) throw new Error('Properties did not render applicable panels');
  document.querySelector('[data-universal-zoom="fit"]').click();
  tabs[1].click();
  await waitUntil(() => requests.some(item =>
    item.route.endsWith('/interaction')));
  await settle();
} else if (input.scenario === 'build_lens') {
  const build=[...document.querySelectorAll(
    '[data-universal-inspector-lens]')].find(button =>
      button.textContent.trim() === 'Build');
  if (!build) throw new Error('Build lens control is missing');
  build.click();
  await waitUntil(() => requests.some(item =>
    item.route.endsWith('/interaction')));
  await settle();
} else if (input.scenario === 'property_identity') {
  const property=document.querySelector('[data-universal-event-fact-input]');
  if (!property) throw new Error('editable graph property did not render');
  const original=property;
  property.value=property.type === 'color'
    ? '#336699' : `${property.value} updated`;
  property.dispatchEvent(new window.Event('change', {
    bubbles:true,cancelable:true,
  }));
  await settle();
  propertyInputIdentityPreserved=(
    original === document.querySelector(
      `[data-universal-event-fact-input="${original.dataset.universalEventFactInput}"]`)
  );
} else if (input.scenario === 'floor_atom_identity') {
  const atom=document.querySelector(
    `input[data-universal-control="${projection.physical.control}"]`
  );
  if (!atom || !atom.dataset.universalEventFactInput) {
    throw new Error('graph-authorized physical atom field did not render');
  }
  atom.value='Floor value updated';
  atom.dispatchEvent(new window.Event('change', {
    bubbles:true,cancelable:true,
  }));
  await settle();
} else if (input.scenario === 'interface_value_identity') {
  const field=document.querySelector('[data-universal-event-fact-input]');
  if (!field) throw new Error('editable interface value did not render');
  field.value=`${field.value} updated`;
  field.dispatchEvent(new window.Event('change', {
    bubbles:true,cancelable:true,
  }));
  await waitUntil(() => interfaceValueResponseDelivered > 0);
  await settle();
} else if (input.scenario === 'collection_item_identity') {
  const item=projection.selected_interfaces.flatMap(interfaceItem => (
    interfaceItem.mode === 'collection' ? interfaceItem.items : [])).find(
      candidate => typeof candidate.control === 'string');
  const field=document.querySelector(
    `[data-universal-control="${item?.control}"]`
  );
  if (!field) throw new Error('editable collection item did not render');
  field.value=`${field.value} updated`;
  field.dispatchEvent(new window.Event('change', {
    bubbles:true,cancelable:true,
  }));
  await waitUntil(() => collectionValueResponseDelivered > 0);
  await settle();
} else if (input.scenario === 'collection_actions_identity') {
  const collection=projection.selected_interfaces.find(item => (
    item.mode === 'collection'));
  const remove=document.querySelector(
    `[data-universal-control="${collection?.items[0]?.remove_control}"]`);
  const add=document.querySelector(
    `[data-universal-control="${collection?.append_control}"]`);
  const inputField=add?.closest('[data-universal-interaction-scope]')
    ?.querySelector('[data-universal-event-fact-input]');
  if (!remove || !add || !inputField) {
    throw new Error('graph collection action controls did not render');
  }
  remove.click();
  await waitUntil(() => requests.filter(
    item => item.route.endsWith('/interaction')).length >= 1);
  inputField.value='Beta';
  add.click();
  await waitUntil(() => requests.filter(
    item => item.route.endsWith('/interaction')).length >= 2);
  await settle();
} else if (input.scenario === 'topology_reconcile') {
  const property=document.querySelector('[data-universal-event-fact-input]');
  if (!property) throw new Error('editable graph property did not render');
  property.value=property.type === 'color'
    ? '#336699' : `${property.value} updated`;
  property.dispatchEvent(new window.Event('change', {
    bubbles:true,cancelable:true,
  }));
  await settle();
} else if (input.scenario === 'performance_property_250') {
  const property=document.querySelector('[data-universal-event-fact-input]');
  if (!property) throw new Error('editable graph property did not render');
  const original=property;
  property.value=property.type === 'color'
    ? '#336699' : `${property.value} updated`;
  const started=performance.now();
  property.dispatchEvent(new window.Event('change', {
    bubbles:true,cancelable:true,
  }));
  await waitUntil(() => propertyResponseDelivered > 0);
  await settle(2);
  propertyReconcileMs=performance.now()-started;
  propertyInputIdentityPreserved=(
    original === document.querySelector(
      `[data-universal-event-fact-input="${original.dataset.universalEventFactInput}"]`)
  );
} else if (input.scenario === 'property_create') {
  const form=document.querySelector(
    `[data-universal-relation-form="${projection.authoring.property_form.root}"]`);
  const label=form?.querySelector(
    '[data-universal-relation-form-field="label"]');
  const value=form?.querySelector(
    '[data-universal-relation-form-field="value"]');
  const create=form?.querySelector(
    '[data-universal-relation-form-submit]');
  if (!label || !value || !create) {
    throw new Error('graph-authored Add parameter control did not render');
  }
  label.value='Acoustic rating';
  value.value='Rw 50';
  label.dispatchEvent(new window.KeyboardEvent('keydown', {
    key:'Enter',code:'Enter',bubbles:true,cancelable:true,
  }));
  await settle();
} else if (input.scenario === 'interface_create') {
  const form=document.querySelector(
    `[data-universal-relation-form="${projection.authoring.interface_form.root}"]`);
  const name=form?.querySelector(
    '[data-universal-relation-form-field="name"]');
  const presentation=form?.querySelector(
    '[data-universal-relation-form-field="presentation"]');
  const contract=form?.querySelector(
    '[data-universal-relation-form-field="contract"]');
  const create=form?.querySelector('[data-universal-relation-form-submit]');
  if (!name || !presentation || !contract || !create) {
    throw new Error('graph-authored Add interface control did not render');
  }
  name.value='Acoustic source';
  name.dispatchEvent(new window.KeyboardEvent('keydown', {
    key:'Enter',code:'Enter',bubbles:true,cancelable:true,
  }));
  await settle();
} else if (input.scenario === 'presentation_color') {
  const property=projection.properties.find(item => item.presentation_editable);
  const color=document.querySelector(
    `[data-universal-control="${property?.presentation_control}"]`);
  if (!color) throw new Error('graph-authored presentation color did not render');
  color.value='#336699';
  color.dispatchEvent(new window.Event('change', {
    bubbles:true,cancelable:true,
  }));
  await settle();
} else if (input.scenario === 'presentation_reset') {
  const property=projection.properties.find(item => item.presentation_reset);
  const reset=document.querySelector(
    `[data-universal-control="${property?.presentation_reset_control}"]`);
  if (!reset) throw new Error('graph-authored presentation reset did not render');
  reset.click();
  await settle();
} else if (input.scenario === 'theme_preview') {
  const field=projection.configuration.theme_fields.find(
    item => item.key === 'accent');
  const control=document.querySelector(
    `[data-universal-control="${field?.control}"]`);
  if (!control) throw new Error('graph-authored theme field did not render');
  control.value='#336699';
  control.dispatchEvent(new window.Event('change', {
    bubbles:true,cancelable:true,
  }));
  await settle();
} else if (input.scenario === 'theme_restore') {
  const revision=projection.configuration.history.find(item => !item.current);
  const control=document.querySelector(
    `[data-universal-control="${revision?.restore_control}"]`);
  if (!control) throw new Error('graph-authored theme restore did not render');
  control.click();
  await settle();
} else if (input.scenario === 'focus_reason') {
  const reason=document.querySelector('.focus-section .focus-reason-link');
  if (!reason) throw new Error('persistent focus reason did not render');
  reason.click();
  await settle();
} else if (input.scenario === 'relation_composer') {
  const nextEmpty=() => [...document.querySelectorAll(
    'select[data-universal-contract-role]')].find(select => !select.value);
  let select=nextEmpty();
  while (select) {
    const option=select.querySelector('option:not([value=""])');
    if (!option) throw new Error(`relation role has no choice: ${select.outerHTML}`);
    select.value=option.value;
    select.dispatchEvent(new window.Event('change', {
      bubbles:true,cancelable:true,
    }));
    await settle(2);
    select=nextEmpty();
  }
  const create=document.querySelector('[data-universal-contract-create]');
  if (!create || create.disabled) {
    throw new Error(
      'relation composer did not enable a complete candidate: '
      + JSON.stringify({
        rendered:Boolean(create),disabled:create?.disabled,
        complete:projection?.selected_definition?.composer?.complete,
        remaining:relationComposerResponses.length,
      }));
  }
  create.click();
  await settle();
} else if (input.scenario === 'relation_role_edit') {
  const select=[...document.querySelectorAll(
    'select[data-universal-control][data-universal-event-fact-input]'
    + ':not(:disabled)')].find(item =>
      [...item.options].some(option => option.value !== item.value));
  if (!select) throw new Error('no editable relation-role interface rendered');
  const replacement=[...select.options].find(option => option.value !== select.value);
  select.value=replacement.value;
  select.dispatchEvent(new window.Event('change', {
    bubbles:true,cancelable:true,
  }));
  await settle();
} else if (input.scenario === 'relation_role_wire_edit') {
  const socket=document.querySelector(
    '[data-universal-relation-incidence]:not([data-existing-only="true"])');
  if (!socket) throw new Error('no editable incidence socket rendered');
  const owner=projection.nodes.find(
    node => node.id === socket.dataset.universalRoleOwner);
  const port=owner?.ports.find(
    item => item.id === socket.dataset.universalRoleInterface);
  const occupied=new Set((port?.items || []).map(item => item.participant));
  const targetChoice=(port?.choices || []).find(choice => !occupied.has(choice.id));
  const target=cards.find(card =>
    card.dataset.universalRoot === targetChoice?.id);
  if (!target) throw new Error('no authorized incidence rewire target rendered');
  document.elementFromPoint=() => target;
  pointer(socket,'pointerdown');
  relationCandidateCount=document.querySelectorAll(
    '[data-universal-wire-candidate="true"]').length;
  wirePreviewCount=document.querySelectorAll(
    '[data-universal-role-preview="true"]').length;
  pointer(socket,'pointermove',{clientX:420,clientY:240});
  pointer(socket,'pointerup',{clientX:420,clientY:240});
  await settle();
} else if (input.scenario === 'relation_role_wire_append') {
  const socket=[...document.querySelectorAll(
    '[data-universal-relation-role]:not([data-existing-only="true"])')].find(
      item => {
        const owner=projection.nodes.find(
          node => node.id === item.dataset.universalRoleOwner);
        const port=owner?.ports.find(port =>
          port.id === item.dataset.universalRelationRole);
        return port && (port.maximum == null || port.items.length < port.maximum);
      });
  if (!socket) throw new Error('no role socket with remaining capacity rendered');
  const owner=projection.nodes.find(
    node => node.id === socket.dataset.universalRoleOwner);
  const port=owner?.ports.find(
    item => item.id === socket.dataset.universalRelationRole);
  const occupied=new Set((port?.items || []).map(item => item.participant));
  const targetChoice=(port?.choices || []).find(choice => !occupied.has(choice.id));
  const target=cards.find(card =>
    card.dataset.universalRoot === targetChoice?.id);
  if (!target) throw new Error('no authorized role append target rendered');
  document.elementFromPoint=() => target;
  pointer(socket,'pointerdown');
  relationCandidateCount=document.querySelectorAll(
    '[data-universal-wire-candidate="true"]').length;
  wirePreviewCount=document.querySelectorAll(
    '[data-universal-role-preview="true"]').length;
  pointer(socket,'pointermove',{clientX:420,clientY:240});
  pointer(socket,'pointerup',{clientX:420,clientY:240});
  await settle();
} else if (input.scenario === 'nary_wire_select') {
  const wire=document.querySelector(
    '.universal-wire[data-wire-segment][data-wire-role]:not([data-wire-role=""])');
  if (!wire) throw new Error('no n-ary relation segment rendered');
  wire.dispatchEvent(new window.MouseEvent('click', {
    bubbles:true,cancelable:true,
  }));
  await settle();
} else if (input.scenario === 'primitive_drag') {
  const primitive=document.querySelector('[data-universal-primitive]');
  if (!primitive || !primitive.draggable) {
    throw new Error('universal Cell is not a draggable catalogue item');
  }
  const values=new Map();
  const transfer={
    effectAllowed:'none',dropEffect:'none',
    setData(type,value){ values.set(type,String(value)); },
    getData(type){ return values.get(type) || ''; },
    get types(){ return [...values.keys()]; },
  };
  drag(primitive,'dragstart',transfer);
  drag(canvas,'dragover',transfer,{clientX:420,clientY:260});
  drag(canvas,'drop',transfer,{clientX:420,clientY:260});
  await settle();
} else if (
  input.scenario === 'library_search'
  || input.scenario === 'library_search_keyboard'
) {
  const search=document.querySelector('[data-universal-library-search]');
  if (!search) throw new Error('graph-authored Node Library search is missing');
  const requestsBefore=requests.length;
  search.value=input.query || '';
  search.dispatchEvent(new window.Event('input', {
    bubbles:true,cancelable:true,
  }));
  await settle(2);
  librarySearchRequestCount=requests.length-requestsBefore;
  if (input.scenario === 'library_search_keyboard') {
    search.dispatchEvent(new window.KeyboardEvent('keydown', {
      key:'ArrowDown',code:'ArrowDown',bubbles:true,cancelable:true,
    }));
    search.dispatchEvent(new window.KeyboardEvent('keydown', {
      key:'Enter',code:'Enter',bubbles:true,cancelable:true,
    }));
    await settle();
  }
} else if (
  input.scenario === 'library_place'
  || input.scenario === 'library_place_rejected'
  || input.scenario === 'topology_delta_reconcile'
  || input.scenario === 'performance_topology_250'
) {
  const definition=projection.catalog.find(item => !item.composition_contract);
  if (!definition) throw new Error('no directly placeable catalogue definition');
  const place=document.querySelector(
    `[data-universal-definition-place="${definition.id}"]`);
  if (!place) throw new Error('catalogue definition has no explicit place control');
  const started=performance.now();
  place.click();
  if (input.scenario === 'performance_topology_250') {
    await waitUntil(() => topologyResponseDelivered > 0);
    await settle(2);
    topologyReconcileMs=performance.now()-started;
  } else {
    await settle();
  }
} else if (input.scenario === 'toolbar_keyboard') {
  const buttons=[...document.querySelectorAll(
    '.canvas-toolbar button[data-universal-control]')];
  if (buttons.length < 2) throw new Error('canvas toolbar has fewer than two controls');
  buttons[0].focus();
  buttons[0].dispatchEvent(new window.KeyboardEvent('keydown', {
    key:'ArrowRight',code:'ArrowRight',bubbles:true,cancelable:true,
  }));
  await settle(2);
} else if (input.scenario === 'history_keyboard') {
  const card=()=>document.querySelector(
    `[data-universal-root="${input.historyRoot}"]`);
  const before={left:card()?.style.left,top:card()?.style.top};
  document.dispatchEvent(new window.KeyboardEvent('keydown', {
    key:'z',code:'KeyZ',ctrlKey:true,bubbles:true,cancelable:true,
  }));
  await waitUntil(() => requests.some(item => (
    item.route.endsWith('/interaction')
    && initialHistoryOperationByControl.get(item.payload.control) === 'undo')));
  await waitUntil(() => topologyResponseDelivered === 1);
  await settle(2);
  const undone={left:card()?.style.left,top:card()?.style.top};
  document.dispatchEvent(new window.KeyboardEvent('keydown', {
    key:'Z',code:'KeyZ',ctrlKey:true,shiftKey:true,bubbles:true,cancelable:true,
  }));
  await waitUntil(() => requests.some(item => (
    item.route.endsWith('/interaction')
    && initialHistoryOperationByControl.get(item.payload.control) === 'redo')));
  await waitUntil(() => topologyResponseDelivered === 2);
  await settle(2);
  historyPositions={before,undone,redone:{
    left:card()?.style.left,top:card()?.style.top,
  }};
}

const gesture = requests.filter(item => item.route.endsWith('/gesture')).at(-1) || null;
const lensRequest = requests.filter(item => (
  item.route.endsWith('/interaction')
  && initialInspectorLensRoots.has(item.payload.control)
)).at(-1) || null;
const directLensRequestCount=requests.filter(
  item => item.route.endsWith('/inspector-lens')).length;
const compositionRequest=requests.filter(item => (
  item.route.endsWith('/interaction')
  && item.payload.control === 'app:control:canvas:group'
)).at(-1) || null;
const panelRequest = requests.filter(item => item.route.endsWith('/properties-panel')).at(-1) || null;
const interactionRequest = requests.filter(item => item.route.endsWith('/interaction')).at(-1) || null;
const rewireRequest = requests.filter(item => (
  item.route.endsWith('/interaction')
  && initialTopologyOperationByControl.get(item.payload.control)
    === 'court:topology:rewire')).at(-1) || null;
const instantiateRequest = requests.filter(
  item => item.route.endsWith('/instantiate')
    || (
      item.route.endsWith('/interaction')
      && item.payload.control === relationCreateControl
    )
    || (
      item.route.endsWith('/interaction')
      && (
        projection.primitive?.id === item.payload.control
        || projection.catalog.some(definition => (
          definition.id === item.payload.control
          && !definition.composition_contract
        ))
      )
    )).at(-1) || null;
const connectRequest = requests.filter(item => (
  item.route.endsWith('/interaction')
  && initialTopologyOperationByControl.get(item.payload.control)
    === 'court:topology:connect')).at(-1) || null;
const disconnectRequest = requests.filter(item => (
  item.route.endsWith('/interaction')
  && initialTopologyOperationByControl.get(item.payload.control)
    === 'court:topology:disconnect')).at(-1) || null;
const interfaceRequest = requests.filter(
  item => item.route.endsWith('/interface')).at(-1) || null;
const relationMemberRequest = requests.filter(item =>
  item.route.endsWith('/interaction')
  && item.payload.control
  && projection.selected_interfaces.some(interfaceItem => (
    interfaceItem.mode === 'relation-role'
    && (
      interfaceItem.append_control === item.payload.control
      || interfaceItem.items.some(member => [
        member.replace_control,member.remove_control,
      ].includes(item.payload.control))
    )
  ))
).at(-1) || null;
const propertyCreateRequest = requests.filter(item =>
  item.route.endsWith('/interaction')
  && item.payload.event_facts?.some(fact =>
    fact.input === projection.authoring.property_form.inputs.label)
).at(-1) || null;
const propertyEditRequest = requests.filter(item =>
  item.route.endsWith('/interaction')
  && item.payload.event_facts?.some(fact =>
    projection.properties.some(property => (
      property.event_fact_input === fact.input)))
).at(-1) || null;
const interfaceValueRequest = requests.filter(item =>
  item.route.endsWith('/interaction')
  && item.payload.event_facts?.some(fact =>
    projection.selected_interfaces.some(interfaceItem => (
      interfaceItem.event_fact_input === fact.input)))
).at(-1) || null;
const collectionValueRequest = requests.filter(item =>
  item.route.endsWith('/interaction')
  && item.payload.event_facts?.some(fact =>
    projection.selected_interfaces.some(interfaceItem => (
      interfaceItem.mode === 'collection'
      && interfaceItem.items.some(collectionItem => (
        collectionItem.event_fact_input === fact.input)))))
).at(-1) || null;
const relationMemberRequests = requests.filter(item =>
  item.route.endsWith('/interaction')
  && item.payload.control
  && projection.selected_interfaces.some(interfaceItem => (
    interfaceItem.mode === 'collection'
    && (
      interfaceItem.append_control === item.payload.control
      || interfaceItem.items.some(member => [
        member.up_control,member.down_control,member.remove_control,
      ].includes(item.payload.control))
    )
  ))
);
const interfaceCreateRequest = requests.filter(item =>
  item.route.endsWith('/interaction')
  && item.payload.event_facts?.some(fact =>
    fact.input === projection.authoring.interface_form.inputs.name)
).at(-1) || null;
const initialPresentationProperty=(input.projection.properties || []).find(
  item => item.presentation_editable) || null;
const presentationPreviewRequest = requests.filter(item => (
  item.route.endsWith('/interaction')
  && item.payload.control === initialPresentationProperty?.presentation_control
)).at(-1) || null;
const presentationResetRequest = requests.filter(item => (
  item.route.endsWith('/interaction')
  && item.payload.control
    === initialPresentationProperty?.presentation_reset_control
)).at(-1) || null;
const initialThemeField=(input.projection.configuration?.theme_fields || []).find(
  item => item.key === 'accent') || null;
const themePreviewRequest=requests.filter(item => (
  item.route.endsWith('/interaction')
  && item.payload.control === initialThemeField?.control
)).at(-1) || null;
const initialThemeHistory=(input.projection.configuration?.history || []).find(
  item => !item.current) || null;
const themeRestoreRequest=requests.filter(item => (
  item.route.endsWith('/interaction')
  && item.payload.control === initialThemeHistory?.restore_control
)).at(-1) || null;
const tabs = [...document.querySelectorAll('[role="tab"]')];
const panels = [...document.querySelectorAll('[role="tabpanel"]')];
const selectionBox = document.querySelector('.selection-box');
const naryWires = [...document.querySelectorAll(
  '.universal-wire[data-wire-segment][data-wire-role]:not([data-wire-role=""])')];
const incidenceSockets = [...document.querySelectorAll(
  '[data-universal-relation-incidence][data-universal-interface]')];
const portTopValues = [...document.querySelectorAll(
  '.graph-node[data-graph-node]')].flatMap(card => {
    const inputs=[...card.querySelectorAll(
      '.node-port-in:not(.node-port-exact)')].map(port =>
      parseFloat(port.style.top));
    const outputs=[...card.querySelectorAll(
      '.node-port-out:not(.node-port-exact)')].map(port =>
      parseFloat(port.style.top));
    return [inputs,outputs].flatMap(values => values.slice(1).map(
      (value,index) => value-values[index]));
  });
const exactSockets=[...document.querySelectorAll(
  '.node-port-exact[data-universal-interface]')];
const toolbarControls=[...document.querySelectorAll(
  '.canvas-toolbar button[data-universal-control]')];
const placementInteractionBinding=initialInteractionProjection?.bindings?.find(
  binding => binding.control === instantiateRequest?.payload?.control);
const placementValues=new Map(
  (instantiateRequest?.payload?.event_facts || []).map(
    fact => [fact.input,fact.value]));
const placementValue=source => {
  const specification=placementInteractionBinding?.event_facts?.find(
    fact => fact.source === source);
  return specification ? placementValues.get(specification.input) : undefined;
};
const placementPayload=instantiateRequest?.route.endsWith('/interaction') ? {
  ...(instantiateRequest.payload.control === projection.primitive?.id
    ? {primitive:true}
    : {definition:instantiateRequest.payload.control}),
  x:placementValue('canvas-point-x'),
  y:placementValue('canvas-point-y'),
  ...(
    placementValue('canvas-viewport-zoom') == null ? {} : {viewport:{
      pan_x:placementValue('canvas-viewport-pan-x'),
      pan_y:placementValue('canvas-viewport-pan-y'),
      zoom:placementValue('canvas-viewport-zoom'),
    }}
  ),
} : (instantiateRequest?.payload || null);
const placementCardWidth=parseFloat(
  projection.configuration.design_system.components.card.width.value);
const placementMargin=parseFloat(
  projection.configuration.design_system.components.canvas['grid-size'].value);
const placementDefinition=projection.catalog.find(
  item => item.id === placementPayload?.definition);
const placementCardHeight=projection.authoring?.lens === 'build'
  ? Math.max(112,82+(Number(placementDefinition?.interfaces) || 0)*24)
  : 112;
const placementCollisionCount=placementPayload
  ? projection.nodes.filter(node => (
      node.id !== 'court:node:entered'
      && !(
        placementPayload.x+placementCardWidth+placementMargin <= Number(node.x)
        || placementPayload.x >= Number(node.x)+placementCardWidth+placementMargin
        || placementPayload.y+placementCardHeight+placementMargin <= Number(node.y)
        || placementPayload.y >= Number(node.y)+112+placementMargin
      )
    )).length
  : null;

const result = {
  nodeIds,
  gesture,
  gestureRequests: requests.filter(item => item.route.endsWith('/gesture')),
  scopeRequests: requests.filter(item => (
    item.route.endsWith('/interaction')
    && item.payload.projection_mode === 'topology-delta-v1'
  )),
  directScopeRequestCount:requests.filter(
    item => item.route.endsWith('/scope')).length,
  staleGestureCount,
  lensRequest,
  directLensRequestCount,
  compositionRequest,
  directCompositionRequestCount:requests.filter(item => (
    item.route.endsWith('/group') || item.route.endsWith('/ungroup')
  )).length,
  directControlRequestCount:requests.filter(
    item => item.route.endsWith('/control')).length,
  panelRequest,
  rewireRequest,
  instantiateRequest,
  placementPayload,
  connectRequest,
  disconnectRequest,
  directTopologyRequestCount:requests.filter(item => (
    item.route.endsWith('/connect')
    || item.route.endsWith('/disconnect')
    || item.route.endsWith('/rewire')
  )).length,
  historyRequests:requests.filter(item => (
    item.route.endsWith('/interaction')
    && initialHistoryOperationByControl.has(item.payload.control)
  )),
  historyPositions,
  interfaceRequest,
  relationMemberRequest,
  directInterfaceRequestCount:requests.filter(
    item => item.route.endsWith('/interface')).length,
  directCellRequestCount:requests.filter(
    item => item.route.endsWith('/cell')).length,
  propertyCreateRequest,
  interfaceCreateRequest,
  presentationPreviewRequest,
  presentationResetRequest,
  themePreviewRequest,
  themeRestoreRequest,
  themeAccent:document.documentElement.style.getPropertyValue('--accent'),
  selected: [...document.querySelectorAll('.graph-node[data-selected="True"]')]
    .map(card => card.dataset.graphNode),
  fixtureSelection:[...projection.selection],
  focused: document.querySelector('.graph-node[data-focused="True"]')?.dataset.graphNode || null,
  canvasIdentityPreserved: initialFirstCard === document.querySelector(
    `.graph-node[data-graph-node="${nodeIds[0]}"]`),
  wireIdentityPreserved: initialFirstWire === document.querySelector(
    '.universal-wire[data-universal-relation]'),
  socketIdentityPreserved: initialFirstSocket === document.querySelector(
    '[data-universal-interface]'),
  libraryIdentityPreserved: initialLibraryPrimitive === document.querySelector(
    '[data-universal-primitive]'),
  toolbarIdentityPreserved: initialToolbarZoom === document.querySelector(
    '[data-universal-zoom="out"]'),
  retainedCardIdentityCount:[...initialCardsById].filter(([root,node]) =>
    projection.nodes.some(item => item.id === root) &&
    document.querySelector(`[data-universal-root="${root}"]`) === node
  ).length,
  retainedWireIdentityCount:[...initialWiresByKey].filter(([key,wire]) =>
    [...document.querySelectorAll('.universal-wire[data-universal-relation]')]
      .some(item => item.dataset.uiKey === key && item === wire)
  ).length,
  enteredNodeCount:document.querySelectorAll(
    '[data-universal-root="court:node:entered"]').length,
  enteredWireCount:[...document.querySelectorAll(
    '.universal-wire[data-universal-relation]')].filter(
      wire => wire.dataset.universalRelation === 'court:relation:entered'
    ).length,
  renderedNodeCount: document.querySelectorAll(
    '.graph-node[data-graph-node]').length,
  renderedWireCount: document.querySelectorAll(
    '.universal-wire[data-universal-relation]').length,
  wireHitCount: document.querySelectorAll(
    '.wire-hit[data-universal-relation]').length,
  wireHitParity: [...document.querySelectorAll(
    '.universal-wire[data-universal-relation]')].every(wire => {
      const hit=wire.previousElementSibling;
      return hit?.classList.contains('wire-hit')
        && hit.dataset.universalRelation === wire.dataset.universalRelation
        && hit.dataset.wireSegment === wire.dataset.wireSegment;
    }),
  wireEndpointCount:document.querySelectorAll(
    '[data-universal-rewire-incidence]').length,
  wireEndpointRelations:[...document.querySelectorAll(
    '[data-universal-rewire-incidence]')].map(handle =>
      handle.dataset.universalRewireRelation),
  focusedWireEndpointCount:document.querySelectorAll(
    '[data-universal-rewire-incidence][data-focused="True"]').length,
  focusedWireEndpointData:[...document.querySelectorAll(
    '[data-universal-rewire-incidence][data-focused="True"]')].map(handle => ({
      relation:handle.dataset.universalRewireRelation,
      segment:handle.dataset.universalRewireSegment,
      side:handle.dataset.universalRewireSide,
      incidence:handle.dataset.universalRewireIncidence,
      interface:handle.dataset.universalRewireInterface,
      node:handle.dataset.universalRewireNode,
      fixedInterface:handle.dataset.universalRewireFixedInterface,
      fixedNode:handle.dataset.universalRewireFixedNode,
      inLayer:Boolean(handle.closest('.wire-layer')),
      interfaceRendered:Boolean([...document.querySelectorAll(
        '[data-universal-interface]')].some(port =>
          port.dataset.universalInterface === handle.dataset.universalRewireInterface)),
    })),
  naryWireCount: naryWires.length,
  naryWireGeometryCount: naryWires.filter(
    wire => (wire.getAttribute('d') || '').startsWith('M ')).length,
  naryRoleSocketCount: new Set(naryWires.map(
    wire => wire.dataset.targetInterface).filter(Boolean)).size,
  participantIncidenceSocketCount: incidenceSockets.length,
  naryExactParticipantSocketCount: naryWires.filter(wire =>
    incidenceSockets.some(socket =>
      socket.dataset.universalInterface === wire.dataset.sourceInterface)
  ).length,
  relationCandidateCount,
  minimumPortGap: portTopValues.length ? Math.min(...portTopValues) : null,
  initialExactSocketCount,
  initialExpandedSocketCount,
  expandedSocketCount: document.querySelectorAll(
    '.node-port:not(.node-port-exact)[data-universal-interface]').length,
  activeInspectorLens: projection.inspector.lenses.find(
    lens => lens.active)?.name || null,
  exactSocketCount: exactSockets.length,
  exactSocketLabelCount: exactSockets.filter(socket =>
    Boolean(socket.dataset.interfaceLabel && socket.title)).length,
  exactSocketIdentityCount: new Set(exactSockets.map(
    socket => socket.dataset.universalInterface)).size,
  initialFirstSocketId: initialFirstSocket?.dataset.universalInterface || null,
  selectedSocketIds: exactSockets.filter(
    socket => socket.dataset.selected === 'True'
  ).map(socket => socket.dataset.universalInterface),
  pressedSocketIds: exactSockets.filter(
    socket => socket.getAttribute('aria-pressed') === 'true'
  ).map(socket => socket.dataset.universalInterface),
  primitiveDraggable: document.querySelector(
    '[data-universal-primitive]')?.draggable || false,
  primitiveVisible: document.querySelectorAll(
    '[data-universal-primitive]').length,
  primitiveKickerTexts: [...document.querySelectorAll(
    '[data-universal-primitive] .universal-library-kicker'
  )].map(item => item.textContent),
  definitionCount: document.querySelectorAll(
    '[data-universal-definition]').length,
  definitionPlaceControlCount: document.querySelectorAll(
    '[data-universal-definition-place]').length,
  graphIconCount: document.querySelectorAll(
    'svg[data-universal-icon-root]').length,
  railGraphIconCount: document.querySelectorAll(
    '.icon-rail svg[data-universal-icon-root]').length,
  libraryPlaceGraphIconCount: document.querySelectorAll(
    '[data-universal-definition-place] svg[data-universal-icon-root]').length,
  toolbarGraphIconCount: document.querySelectorAll(
    '.canvas-toolbar svg[data-universal-icon-root]').length,
  toolbarControlOwners:toolbarControls.map(
    control => control.dataset.universalControl),
  toolbarControlBindingRoots:toolbarControls.map(
    control => control.dataset.controlBinding || null),
  toolbarTabStopCount:toolbarControls.filter(
    control => control.tabIndex === 0).length,
  activeToolbarControl:document.activeElement?.dataset?.universalControl || null,
  visibleLegacyHistoryControlCount:[...document.querySelectorAll(
    '.history-undo,.history-redo')].filter(control => !control.hidden).length,
  sessionActionHeadings:[...document.querySelectorAll(
    '[data-ui-key="session-actions:heading"]')].map(item => item.textContent),
  sessionActionLabels:[...document.querySelectorAll(
    '[data-ui-key^="session-action:"][data-ui-key$=":label"]')]
    .map(item => item.textContent),
  sessionActionValues:[...document.querySelectorAll(
    '[data-ui-key^="session-action:"][data-ui-key$=":value"]')]
    .map(item => item.childNodes[0]?.textContent || item.textContent),
  missingGraphIconControls: [...document.querySelectorAll(
    '[data-universal-control][data-control-icon]')].filter(control =>
      !control.querySelector('svg[data-universal-icon-root]')
    ).map(control => control.dataset.universalControl),
  textGlyphControlCount: [...document.querySelectorAll('button')].filter(
    control => ['+','-','‹','â€¹'].includes(control.textContent.trim())
  ).length,
  librarySections: [...document.querySelectorAll(
    '[data-universal-library-section]')].map(section => ({
      id:section.dataset.universalLibrarySection,
      label:section.querySelector('.universal-library-section')?.textContent || '',
      definitions:section.querySelectorAll('[data-universal-definition]').length,
    })),
  libraryPanelTitles: [...document.querySelectorAll(
    '.library-panel > .panel-title'
  )].map(item => item.textContent),
  librarySearchPresent:Boolean(document.querySelector(
    '[data-universal-library-search]')),
  librarySearchVisibleNames:[...document.querySelectorAll(
    '[data-universal-definition]')].filter(item => !item.closest(
      '[data-universal-library-entry]')?.hidden
    ).map(item => item.querySelector(
      '.universal-library-name')?.textContent || ''),
  librarySearchVisibleSections:[...document.querySelectorAll(
    '[data-universal-library-section]')].filter(section => !section.hidden)
    .map(section => section.querySelector(
      '.universal-library-section')?.textContent || ''),
  librarySearchResultCount:document.querySelector(
    '[data-universal-library-result-count]')?.textContent || '',
  librarySearchRequestCount,
  librarySearchActiveName:document.querySelector(
    '[data-universal-library-entry][data-search-active="true"] '
    + '.universal-library-name')?.textContent || null,
  librarySearchActivePlaceDisabled:document.querySelector(
    '[data-universal-library-entry][data-search-active="true"] '
    + '[data-universal-definition-place]')?.disabled ?? null,
  requestRoutes:requests.map(item => item.route),
  statusStripTexts: [...document.querySelectorAll(
    '.status-strip > span:not(.status-message)'
  )].map(item => item.textContent),
  initialRenderMs,
  selectionFeedbackMs,
  selectionCommitMs,
  propertyReconcileMs,
  topologyReconcileMs,
  lensReconcileMs,
  wirePreviewMs,
  dragFeedbackMs,
  dragCommitMs,
  wheelFeedbackMs,
  wheelCommitMs,
  panFeedbackMs,
  panCommitMs,
  placementCollisionCount,
  placementNonnegative:placementPayload ? (
    placementPayload.x >= placementMargin
    && placementPayload.y >= placementMargin
  ) : null,
  propertyInputIdentityPreserved,
  reconciliationChangeDispatches,
  propertyEditRequest,
  interfaceValueRequest,
  collectionValueRequest,
  relationMemberRequests,
  propertyCreateControlCount:document.querySelectorAll(
    `[data-universal-relation-form="${projection.authoring.property_form.root}"] `
    +'[data-universal-relation-form-submit]').length,
  interfaceCreateControlCount:document.querySelectorAll(
    `[data-universal-relation-form="${projection.authoring.interface_form.root}"] `
    +'[data-universal-relation-form-submit]').length,
  presentationColorControlCount:initialPresentationProperty
    ? document.querySelectorAll(
      `[data-universal-control="${initialPresentationProperty.presentation_control}"]`
    ).length : 0,
  presentationResetControlCount:initialPresentationProperty
    ?.presentation_reset_control
    ? document.querySelectorAll(
      `[data-universal-control="${initialPresentationProperty.presentation_reset_control}"]`
    ).length : 0,
  presentationSourceTexts:[...document.querySelectorAll(
    '.presentation-source')].map(item => item.textContent),
  positions: [...document.querySelectorAll('.graph-node[data-graph-node]')]
    .map((card,index) => ({
      left:card.style.left,
      top:card.style.top,
      initial:initialPositions[index],
    })),
  pointerOwner: window.__archhubPointerOwner || null,
  canvasScroll:{left:canvas.scrollLeft,top:canvas.scrollTop},
  scopeHeading:document.querySelector('.canvas-heading')?.textContent || null,
  scopeTrail:[...document.querySelectorAll(
    '.canvas-scope-button,.canvas-scope-current')].map(item => item.textContent),
  wirePreviewCount,
  wireTargetReadyCount,
  rewireTargetReadyCount,
  remainingWireTargetReadyCount:document.querySelectorAll(
    '[data-universal-input].wire-target-ready').length,
  remainingRewireTargetReadyCount:document.querySelectorAll(
    '.wire-reconnect-ready').length,
  remainingWirePreviews: document.querySelectorAll(
    '.universal-wire-preview,.wire-preview').length,
  statusMessage: document.querySelector('.status-message')?.textContent || '',
  statusVisible: document.querySelector('.status-message')?.dataset.visible || '',
  inspectorKicker: document.querySelector('.inspector-kicker')?.textContent || '',
  focusSummary: document.querySelector('.focus-summary')?.textContent || '',
  focusReasonLabels: [...document.querySelectorAll(
    '.focus-section .focus-reason-link')].map(item => item.textContent),
  relationEndpointValues: [...document.querySelectorAll(
    '[data-universal-incidence]')].map(input => input.value),
  relationGateCount: document.querySelectorAll(
    '.relation-authority-summary .property-row').length,
  relationPropertyCount: document.querySelectorAll(
    '[data-universal-event-fact-input]').length,
  contractRoleCount: document.querySelectorAll(
    '.universal-contract-role').length,
  marquee: selectionBox ? {
    display: selectionBox.style.display,
    left: selectionBox.style.left,
    top: selectionBox.style.top,
    mode: selectionBox.dataset.mode,
  } : null,
  liveMarquee,
  modifierMarquee,
  expectedMarquee: input.scenario === 'marquee_viewport' ? {
    left: geometry.bounds[0].left - 10 - geometry.overlayBounds.left,
    top: geometry.bounds[0].top - 10 - geometry.overlayBounds.top,
  } : input.scenario === 'marquee' ? {
    left: 120 - geometry.overlayBounds.left,
    top: 80 - geometry.overlayBounds.top,
    width: 300 - 120,
    height: 220 - 80,
  } : input.scenario === 'marquee_scroll' ? {
    left: 120 - 100 + 137,
    top: 80 - 50 + 251,
    width: 300 - 120,
    height: 220 - 80,
  } : input.scenario === 'crossing' ? {
    left: 260 - geometry.overlayBounds.left,
    top: 80 - geometry.overlayBounds.top,
    width: 500 - 260,
    height: 220 - 80,
  } : null,
  tabs: tabs.map(tab => ({
    id: tab.id,
    panel: tab.dataset.universalPropertiesPanel,
    active: tab.dataset.active,
    selected: tab.getAttribute('aria-selected'),
    controls: tab.getAttribute('aria-controls'),
    tabIndex: tab.tabIndex,
  })),
  panels: panels.map(panel => ({
    id: panel.id,
    labelledBy: panel.getAttribute('aria-labelledby'),
    hidden: panel.hidden,
  })),
  inspectorLensLabel:document.querySelector(
    '.inspector-lenses')?.getAttribute('aria-label') || null,
  propertiesTablistLabel:document.querySelector(
    '.inspector-tabs')?.getAttribute('aria-label') || null,
  activeElement: (
    document.activeElement?.dataset?.universalPropertiesPanel
    || document.activeElement?.dataset?.universalInspectorLens
    || null
  ),
  interactionRequest,
  canvasRequestCount:requests.filter(
    item => item.route.endsWith('/canvas')).length,
  refreshCanvasRequestCount:requests.filter(
    item => item.route.endsWith('/canvas')).length-initialCanvasRequestCount,
  interactionRequestCount:requests.filter(
    item => item.route.endsWith('/interaction')).length,
  relationComposerRequestCount,
  deltaAuthorityCatalog,
  directRelationComposerRequestCount:requests.filter(
    item => item.route.endsWith('/relation-composer')).length,
  directRelationCreateRequestCount:requests.filter(
    item => item.route.endsWith('/relation-create')).length,
  expectedUniqueNodeCount,
  errors: runtimeErrors,
};

process.stdout.write(JSON.stringify(result));
dom.window.close();
