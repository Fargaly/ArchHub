"""Admitted browser lifecycle over existing Workshop ordinary page records."""
from .cell_authorization import AuthorizationDenied
from .conversation_content import read_content_binding
from .conversation_pages import IDENTITY_FIELDS
from .existing_workshop_conversation import _admit
from .universal_cell import InvalidCell


PAGE_ACTIONS = frozenset(('page-open', 'page-status', 'page-change',
                          'page-owner-discard', 'page-owner-review', 'page-tracking-resolve',
                          'conversation-archive', 'conversation-purge'))
_COMMON = {'root', 'scope', 'revision', 'action'}


def perform_browser_page_action(owner, binding, body, *, browser_guard):
    """Admitted ordinary history lifecycle; never migrate or rewrite the graph."""
    if type(body) is not dict or type(body.get('action')) is not str or body['action'] not in PAGE_ACTIONS:
        raise InvalidCell('Unknown conversation page action')
    action = body['action']
    own_page = action in ('page-open', 'page-status', 'page-change')
    fields = {'page-open':{'request_key'}, 'page-status':{'page_id'},
        'page-change':{'page_id', 'page_revision', 'change'},
        'page-owner-discard':{'page_id', 'page_revision'},
        'page-owner-review':{'limit'},
        'conversation-archive':{'activity_revision', 'archive_revision', 'head', 'content_generation'},
        'conversation-purge':{'activity_revision', 'archive_revision', 'head', 'content_generation'},
        'page-tracking-resolve':{'activity_revision', 'disposition'}}[action]
    optional = ({'resolution_reference'} if action == 'page-change' else
        {'after_page_id'} if action == 'page-owner-review' else set())
    if (set(body) - optional != _COMMON | fields or type(body['revision']) is not int
            or body['revision'] < 0 or not callable(browser_guard)):
        raise InvalidCell('Conversation page fields or revision are invalid')
    if any(type(body[key]) is not str or not body[key] for key in ('root', 'scope')):
        raise InvalidCell('Conversation page requires an exact root and scope')
    if any(type(body[key]) is not int or not 0 <= body[key] < 2**63
           for key in ('revision', 'page_revision', 'activity_revision', 'archive_revision', 'head', 'content_generation') if key in body):
        raise InvalidCell('Conversation page revisions must be bounded integers')
    identity = tuple(getattr(binding, field) for field in IDENTITY_FIELDS)
    registry, store = owner.universal_registry, owner.universal_store
    authority, service = registry.authorization, owner.conversation_content
    with owner.mutation_lock:
        with authority.broker.live_context(binding.context):
            browser_guard()
            # Own draft metadata is admitted against current graph controls and
            # its exact page CAS. Unrelated graph edits must not strand editors.
            # Owner storage decisions still require the reviewed graph revision.
            with store.stable_snapshot(expected_revision=None if own_page else body['revision']) as snapshot:
                if body['revision'] > snapshot.revision:
                    raise InvalidCell('Conversation page revision is ahead of the current graph')
                def guard():
                    browser_guard()
                    service._require_live_owner()
                    if not service.belongs_to(store, registry):
                        raise AuthorizationDenied('Conversation service belongs to another owner')
                    current, space = _admit(owner, binding, body['root'], body['scope'], allow_child=True)
                    if current.revision != snapshot.revision or binding.subject_root not in space.participant_roots:
                        raise AuthorizationDenied('Conversation page membership or scope changed')
                    authority.broker.resolve(binding.context)
                    service._authorize_content_read(snapshot, registry, space_root=body['root'],
                        authentication_context=binding.context, principal=binding.subject_root, machine=False)
                    if action in ('page-owner-discard', 'page-owner-review', 'page-tracking-resolve',
                                  'conversation-archive', 'conversation-purge') and binding.subject_root != authority.subject_root:
                        raise AuthorizationDenied('Reviewing or resolving another or untracked page requires the application owner')
                guard()
                content = read_content_binding(snapshot, registry.deliberation_protocol,
                    application_root=registry.application_root, space_root=body['root'])
                history = service._history_for(content)
                page = None
                review = None
                retention_result = None
                if action == 'page-open':
                    page = history.open_conversation_page(body['root'], identity=identity,
                        request_key=body['request_key'], before_commit=guard)
                elif action == 'page-status':
                    page = history.read_conversation_page(body['root'], body['page_id'], identity=identity)
                elif action == 'page-owner-review':
                    review = history.review_conversation_pages(body['root'], limit=body['limit'],
                        after_page_id=body.get('after_page_id'))
                elif action == 'page-change':
                    if body['change'] not in ('dirty', 'unknown', 'close', 'initial-empty', 'saved', 'discard'):
                        raise InvalidCell('Conversation page change is invalid')
                    if body['change'] == 'saved':
                        current = history.read_conversation_page(body['root'], body['page_id'], identity=identity)
                        message = history.get(body['root'], body.get('resolution_reference'), principal=binding.subject_root)
                        # Permit the exact latest receipt retry too. Never clear
                        # a newer draft just because any earlier message exists.
                        retry = (current['page_revision'] == body['page_revision'] + 1
                            and current['resolution_kind'] == 'saved'
                            and current['resolution_reference'] == body.get('resolution_reference'))
                        if (message is None or message['author'] != binding.subject_root or not retry and
                                (current['draft_state'] != 'dirty' or not current['resolution_reference']
                                 or current['resolution_reference'] != message['idempotency_key'])):
                            raise InvalidCell('Saved receipt does not match this page draft')
                    page = history.change_conversation_page(body['root'], body['page_id'], identity=identity,
                        expected_page_revision=body['page_revision'], action=body['change'],
                        resolution_reference=body.get('resolution_reference'), before_commit=guard)
                elif action == 'page-owner-discard':
                    page = history.resolve_abandoned_page(body['root'], body['page_id'], resolver_identity=identity,
                        expected_page_revision=body['page_revision'], before_commit=guard)
                elif action in ('conversation-archive', 'conversation-purge'):
                    from .workshop_retention_guard import admit_conversation_retention
                    with admit_conversation_retention(owner, snapshot, body['root'], before_commit=guard) as commit_guard:
                        operation = history.archive if action == 'conversation-archive' else history.purge_archived
                        retention_result = operation(body['root'],
                            expected_activity_revision=body['activity_revision'],
                            expected_archive_revision=body['archive_revision'], expected_head=body['head'],
                            expected_content_generation=body['content_generation'],
                            protected=False, before_commit=commit_guard)
                else:
                    if body['disposition'] != 'discard-untracked-drafts':
                        raise InvalidCell('Untracked drafts require an explicit owner disposition')
                    history.resolve_page_tracking(body['root'], resolver_identity=identity,
                        expected_activity_revision=body['activity_revision'], before_commit=guard)
                protection = history.page_protection_status(body['root'])
                retained = history.retention_status(body['root'])
                activity = retained['activity_revision']
                guard()
                result = {'ok':True, 'graph_id':registry.application_root, 'root':body['root'],
                    'scope_root':body['scope'], 'revision':snapshot.revision,
                    'page':None if page is None else {field:page[field] for field in
                        ('page_id', 'page_revision', 'state', 'draft_state', 'resolution_kind')},
                    'protection':protection, 'activity_revision':activity,
                    'retention':{field:retained[field] for field in ('last_activity_at', 'archived_at',
                        'activity_revision', 'archive_revision', 'last_sequence', 'content_generation')}}
                if own_page:
                    result.update(request_revision=body['revision'], owner=binding.subject_root, view=binding.view_root)
                if review is not None:
                    result.update(review)
                if retention_result is not None:
                    result['retention_result'] = retention_result
                return result
