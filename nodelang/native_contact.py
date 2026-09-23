"""User-owned native contact routing through existing graph and Workshop content.

No external actor enrollment, model route, execution grant or message store.
The HTTP owner supplies its existing authenticated browser/CSRF guard.
"""
import hashlib
import json
from .cell_authorization import AuthorizationDenied
from .universal_cell import InvalidCell

APPS={'claude','codex','opencode','antigravity','antigravity-ide'}
LABEL='native contact'
IDENTITY=('app','id','pid','port','socket','cwd','runtimeId')


def _endpoint(row):
    if type(row) is not dict or row.get('app') not in APPS or type(row.get('id')) is not str or not 0<len(row['id'])<=512:
        raise InvalidCell('Invalid native endpoint')
    result={key:row[key] for key in (*IDENTITY,'selector','title') if key in row}
    if any(type(v) not in (str,int,type(None)) or isinstance(v,bool) for v in result.values()):
        raise InvalidCell('Invalid native endpoint metadata')
    if len(json.dumps(result))>8192:raise InvalidCell('Native endpoint exceeds limit')
    return result


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _discover(owner,apps):
    relay=getattr(owner,'native_recipient_relay',None)
    if relay is None or relay._transport is None:return {'status':'not_sent','reason':'transport_unavailable'}
    return relay._transport.discover(timeout_seconds=3,apps=list(apps))


def discover_native_agents(owner, *, apps=('claude',)):
    if type(apps) not in (list,tuple) or not 1<=len(apps)<=5 or any(app not in APPS for app in apps):
        raise InvalidCell('Invalid native discovery scope')
    broker=getattr(owner,'model_execution_broker',None)
    local=broker.local_cli_readiness() if broker is not None else {}
    readiness=[{'app':app,'state':row['state'],'evidence':row['evidence']}
        for app,row in local.items() if app in {'codex','claude','gemini'}
        and row.get('state') in {'executable-discovered','provider-unavailable'}]
    result=_discover(owner,apps)
    if type(result) is not dict or result.get('status')!='ok':
        return {'status':'unavailable','rows':[],'readiness':readiness,'queried_apps':list(apps),'complete_apps':[],'reason':result.get('reason','discovery_unavailable') if type(result) is dict else 'discovery_unavailable','truncated':False}
    source=result.get('recipients',[])
    if type(source) is not list:raise InvalidCell('Native discovery response is invalid')
    rows=[];seen=set()
    for raw in source[:128]:
        try:target=_endpoint(raw)
        except InvalidCell:continue
        if target['app'] not in apps:continue
        key=(target['app'],target['id'])
        if key in seen:
            for row in rows:
                if (row['app'],row['session_id'])==key:row.update(selectable=False,reason='ambiguous_endpoint')
            continue
        seen.add(key)
        rows.append({'kind':'native-session','app':target['app'],'session_id':target['id'],
            'title':str(target.get('title') or target['id'])[:200],'workspace':target.get('cwd'),
            'connected':True,'selectable':True,'reason':None,'next_step':'bind_contact',
            'execution_authority':False})
    truncated=result.get('truncated') is True or len(source)>128 or len(rows)>64
    # Claude registry enumeration is complete. Other providers may omit
    # unavailable runtimes or return a bounded task window; absence there is
    # unknown unless their transport explicitly proves completeness.
    complete=result.get('complete_apps',['claude'] if 'claude' in apps else [])
    complete=[app for app in complete if app in apps] if type(complete) is list and not truncated else []
    return {'status':'ok','rows':rows[:64],'readiness':readiness,'queried_apps':list(apps),
        'complete_apps':complete,'truncated':truncated,'partial':result.get('partial') is True,
        'reason':'discovery_budget' if result.get('partial') is True else None}


def _property(owner,node,context):
    from .universal_application import _require_application_authorization,_require_resource_audience_authority
    from .universal_pipeline import _owner_properties
    snapshot=owner.universal_store.snapshot()
    registry=owner.universal_registry
    _require_application_authorization(snapshot,registry,'read',node,authentication_context=context)
    subject=registry.authorization.broker.resolve(context).subject_root
    custody=_require_resource_audience_authority(snapshot,registry,subject,(node,))[node]
    if custody[2]!=subject:raise AuthorizationDenied('Native contact is not owned by this browser user')
    rows=_owner_properties(snapshot,owner.universal_registry).get(node,{})
    if LABEL in rows:return rows[LABEL]
    value=rows.get('value')
    if value is not None:
        try:
            if json.loads(value[1]).get('kind')=='native-contact':return value
        except (ValueError,AttributeError):pass
    return None


def bind_native_contact(owner,browser,body,*,browser_guard):
    if type(body) is not dict or set(body) not in ({'root','scope','node','app','session_id','revision'},{'root','scope','app','session_id','revision'}) or body['app'] not in APPS or type(body['revision']) is not int:
        raise InvalidCell('Native contact bind fields are invalid')
    if any(type(body[key]) is not str or not 0<len(body[key])<=4096 for key in ('root','scope','app','session_id')) or (body.get('node') is not None and type(body['node']) is not str):
        raise InvalidCell('Native contact identity fields are invalid')
    registry=owner.universal_registry
    if body['scope']!=registry.workshop_workbench_root:
        raise AuthorizationDenied('Native contact must use this application Workshop')
    browser_guard()
    navigation=workshop_metadata(owner,browser.context)
    if body['root']!=registry.workshop_root:
        _admit_contact_conversation(owner,browser,body['root'],body['scope'])
    found=_discover(owner,[body['app']])
    if type(found) is not dict or found.get('status')!='ok':raise InvalidCell('Native discovery unavailable')
    matches=[row for row in found.get('recipients',[]) if row.get('app')==body['app'] and row.get('id')==body['session_id']]
    if len(matches)!=1:raise InvalidCell('Choose exactly one live native session')
    target=_endpoint(matches[0])
    with owner.mutation_lock:
        browser_guard()
        registry=owner.universal_registry
        if body['root']!=registry.workshop_root:
            _admit_contact_conversation(owner,browser,body['root'],body['scope'])
        value={'kind':'native-contact','version':1,'endpoint':target,'conversation':body['root'],
               'scope':body['scope'],'owner':browser.subject_root}
        encoded=json.dumps(value,sort_keys=True,separators=(',',':'))
        from .universal_application import create_universal_property,edit_universal_property
        node=body.get('node')
        if node is None:
            from .universal_pipeline import _owner_properties
            for candidate,properties in _owner_properties(owner.universal_store.snapshot(),registry).items():
                raw=properties.get(LABEL) or properties.get('value')
                if raw is None:continue
                try:
                    held=json.loads(raw[1])
                    if (set(held)!={'kind','version','endpoint','conversation','scope','owner'} or held.get('version')!=1
                            or held.get('kind')!='native-contact' or held.get('owner')!=browser.subject_root
                            or held.get('conversation')!=value['conversation'] or held.get('scope')!=value['scope']
                            or any(held.get('endpoint',{}).get(key)!=target.get(key) for key in IDENTITY)):continue
                    _property(owner,candidate,browser.context)
                except (ValueError,TypeError,AttributeError,AuthorizationDenied,InvalidCell):continue
                return {'ok':True,'contact':candidate,'binding_digest':_digest(held),'app':target['app'],
                    'session_id':target['id'],'root':held['conversation'],'scope':held['scope'],
                    'scope_path':navigation['scope_path'],'revision':owner.universal_store.revision,'reused':True,'execution_authority':False}
        if owner.universal_store.revision!=body['revision']:raise AuthorizationDenied('Contact selection revision changed')
        if node is None:
            from .universal_application import instantiate_universal_primitive
            node,_=instantiate_universal_primitive(owner.universal_store,registry,x=240,y=200,
                title='Contact: '+str(target.get('title') or target['app'])[:150],atom=encoded,
                mutation_route='/api/universal/native-contact',authentication_context=browser.context)
        else:
            prior=_property(owner,node,browser.context)
            if prior is None:
                create_universal_property(owner.universal_store,registry,node,LABEL,encoded,authentication_context=browser.context)
            else:
                edit_universal_property(owner.universal_store,registry,prior[0],encoded,authentication_context=browser.context)
        return {'ok':True,'contact':node,'binding_digest':_digest(value),'app':target['app'],
            'session_id':target['id'],'root':value['conversation'],'scope':value['scope'],
            'scope_path':navigation['scope_path'],'revision':owner.universal_store.revision,'execution_authority':False}


def _admit_contact_conversation(owner,browser,root,scope):
    from .existing_workshop_conversation import _admit
    snapshot,_space=_admit(owner,browser,root,scope,allow_child=True)
    registry=owner.universal_registry
    if root!=registry.workshop_root:
        from .workshop_conversation_catalog import validate_workshop_conversation_scope
        validate_workshop_conversation_scope(snapshot,registry.deliberation_protocol,
            application_root=registry.application_root,canonical_root=registry.workshop_root,root=root)


def read_contact(owner,browser,contact,binding_digest,root,scope):
    with owner.mutation_lock:
        _admit_contact_conversation(owner,browser,root,scope)
        row=_property(owner,contact,browser.context)
        if row is None:raise InvalidCell('Native contact is not bound')
        value=json.loads(row[1])
        registry=owner.universal_registry
        # A general Workshop contact is bound to the application Workshop home
        # (bind_native_contact requires it); the browser may stand on any canvas.
        home=getattr(registry,'workshop_workbench_root',None) if root==registry.workshop_root else None
        if (set(value)!={'kind','version','endpoint','conversation','scope','owner'} or value['kind']!='native-contact' or value['version']!=1
                or value['owner']!=browser.subject_root or value['conversation']!=root or value['scope']!=(home or scope)
                or _digest(value)!=binding_digest):raise AuthorizationDenied('Native contact selection changed')
        return _endpoint(value['endpoint'])


def send_native_contact(owner,browser,body,*,browser_guard):
    fields={'root','scope','contact','binding_digest','text','idempotency_key'}
    if type(body) is not dict or set(body)!=fields:raise InvalidCell('Native contact send fields are invalid')
    if any(type(body[key]) is not str or not body[key] for key in fields):raise InvalidCell('Native contact send values are invalid')
    if type(body['idempotency_key']) is not str or not 1<=len(body['idempotency_key'])<=128:
        raise InvalidCell('Native message requires an exact idempotency key')
    def revalidate():
        browser_guard()
        return read_contact(owner,browser,body['contact'],body['binding_digest'],body['root'],body['scope'])
    with owner.mutation_lock:
        endpoint=revalidate()
        from .universal_application import validate_universal_workshop_entry_content
        text=validate_universal_workshop_entry_content(body['text'])
        registry=owner.universal_registry
        service=owner.conversation_content
        if service is None or not service.belongs_to(owner.universal_store,registry):raise InvalidCell('Existing conversation owner unavailable')
        result=service.append_authenticated(space_root=body['root'],actor_root=browser.subject_root,
            category_root=registry.workshop_category_roots['note'],content=text,
            idempotency_key=body['idempotency_key'],recipient_roots=(browser.subject_root,),
            reference_roots=(body['contact'],),authentication_context=browser.context,
            expected_revision=owner.universal_store.revision)
        message=result['message']
        relay=owner.native_recipient_relay.request_contact(space_root=body['root'],message_id=message['id'],
            sender_root=browser.subject_root,contact_root=body['contact'],endpoint=endpoint,
            revalidate=revalidate,text=text)
        return {'ok':True,'root':body['root'],'message_id':message['id'],'contact':body['contact'],
            'relay':relay,'delivery':relay,'storage':'conversation-content','idempotency_key':body['idempotency_key'],
            'revision':owner.universal_store.revision,'execution_authority':False}


def project_native_contacts(owner,browser,*,root,scope,discovery,maximum=64):
    if type(maximum) is not int or not 1 <= maximum <= 65:
        raise InvalidCell('Native contact projection limit is invalid')
    from .existing_workshop_conversation import _admit
    from .universal_pipeline import _owner_properties
    contacts=[]
    with owner.mutation_lock:
        _admit(owner,browser,root,scope,allow_child=True)
        properties=_owner_properties(owner.universal_store.snapshot(),owner.universal_registry)
        for node,rows in properties.items():
            if LABEL not in rows and 'value' not in rows:continue
            try:
                raw=rows.get(LABEL) or rows['value']
                value=json.loads(raw[1])
                endpoint=read_contact(owner,browser,node,_digest(value),root,scope)
            except (ValueError,KeyError,TypeError,InvalidCell,AuthorizationDenied):continue
            contacts.append({'root':node,'label':str(endpoint.get('title') or endpoint['app'])[:200],
                'app':endpoint['app'],'session_id':endpoint['id'],'binding_digest':_digest(value),
                'connected':native_contact_presence(discovery,endpoint['app'],endpoint['id'])})
            if len(contacts)>=maximum:break
    return contacts


def workshop_metadata(owner,context):
    from .universal_application import _canvas_roots,_nested_canvas_scope,_require_application_authorization
    with owner.mutation_lock:
        registry=owner.universal_registry;snapshot=owner.universal_store.snapshot()
        brain=registry.map.domains['brain'];scope=registry.workshop_workbench_root
        roots,_,_=_canvas_roots(snapshot,registry)
        children,_,_=_nested_canvas_scope(snapshot,registry,brain)
        if brain not in roots or scope not in children:raise InvalidCell('Workshop navigation path is unavailable')
        for node in (brain,scope,registry.workshop_root):
            _require_application_authorization(snapshot,registry,'read',node,authentication_context=context)
        return {'root':registry.workshop_root,'scope':scope,'scope_path':[brain,scope]}


def native_contact_presence(discovery,app,session_id):
    if discovery.get('status')!='ok':return None
    matches=[row for row in discovery.get('rows',[]) if row.get('app')==app and row.get('session_id')==session_id]
    if matches:return True if len(matches)==1 and matches[0].get('selectable') else None
    if (discovery.get('truncated') or app not in discovery.get('queried_apps',[])
            or app not in discovery.get('complete_apps',[])):return None
    return False
