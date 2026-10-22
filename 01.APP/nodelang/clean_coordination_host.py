"""Local coordination is a surface of the existing desktop application."""
from __future__ import annotations

from . import commit_intent
from .runtime_activity import RuntimeActivity
from .universal_cell import InvalidCell


class CleanCoordinationHost:
    """No graph opener, signing owner, caller key or adoption ceremony."""

    def __init__(self, owner):
        self.owner = owner
        self.store = owner.universal_store
        self.activity = RuntimeActivity()

    def begin_shutdown(self):
        self.activity.begin_shutdown()

    def dispatch(self, request, *, peer=None):
        if (type(request) is not dict or set(request) != {'method', 'path', 'body'}
                or request['method'] not in ('GET', 'POST')
                or type(request['path']) is not str or type(request['body']) is not dict):
            raise InvalidCell('coordination requires one desktop method, path and body')
        from .cloud_session import signed_in_cloud_account
        from .installed_workshop_coordination import MAILBOX_ROUTES
        with self.activity.admit():
            account = signed_in_cloud_account()
            with commit_intent.declare(commit_intent.USER_ACTION,
                    actor=account or self.owner.universal_registry.authorization.subject_root,
                    reason='local coordination %s %s' % (request['method'], request['path'])):
                if (request['method'], request['path']) in MAILBOX_ROUTES:
                    result = self.owner.shared_agent_mail(request['path'].rsplit('/', 1)[-1],
                        request['body'], peer=peer, account=account)
                elif (request['method'], request['path']) == ('POST', '/api/universal/workspace-roots'):
                    # Settings -> Workspaces from this user's own desktop: the owner's route,
                    # with the settings admission the route already expects. No key.
                    from .workspace_roots_catalogue import settings_principal
                    result = self.owner._clean_workspace_roots(request['body'],
                        admission={'principal': settings_principal()})
                elif (request['method'], request['path']) == ('GET', '/api/universal/workspace-roots-state'):
                    from .workspace_roots_catalogue import current_registry_state
                    result = current_registry_state(self.owner.clean_authority, caller=self.owner.clean_caller)
                else:
                    result = self.owner.dispatch_universal_machine_route(request)
            return {**result, 'account': account}


__all__ = ['CleanCoordinationHost']
