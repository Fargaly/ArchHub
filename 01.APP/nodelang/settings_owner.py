"""Settings translations over current account and plain-file owners."""
from __future__ import annotations

from .user_paths import state_directory, stamp_test_write

import inspect
import json
import math
from pathlib import Path
import re
import os
import threading
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError


_ROUTER_LOCK = threading.RLock()
_ACCOUNT_FILE_LOCK = threading.RLock()


def router_settings_path():
    return state_directory() / 'settings' / 'router.json'


def read_router_settings():
    from .model_router import DEFAULT_FREE_ROUTE, _OPENROUTER_FREE_MODELS_DEFAULT
    defaults = {'default_model': DEFAULT_FREE_ROUTE,
                'fallback_models': ['openrouter/' + model for model in _OPENROUTER_FREE_MODELS_DEFAULT], 'free_first': True,
                'providers': {'openrouter': {'credential': 'wcm://ArchHub/openrouter', 'enabled': True}},
                'agents': {}, 'providerPreferences': {},
                'generation': {'max_tokens': 900, 'temperature': 0.0, 'top_p': 1.0}}
    try:
        path = router_settings_path()
        if path.stat().st_size > 65536:
            raise ValueError('Router settings exceed 64 KiB.')
        values = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return defaults
    except (OSError, ValueError):
        raise ValueError('Router settings could not be read.') from None
    if type(values) is not dict:
        raise ValueError('Router settings must be an object.')
    values.pop('_test_writer', None)
    return _checked_router_settings({**defaults, **values})


def _checked_router_settings(values):
    from .model_router import resolve_model_route
    allowed = {'default_model', 'fallback_models', 'free_first', 'providers', 'agents',
               'providerPreferences', 'generation'}
    if type(values) is not dict or set(values) - allowed or values.get('free_first') is not True:
        raise ValueError('Router settings require free-first and credential references only.')
    def route(value, *, free=False):
        if type(value) is not str or len(value) > 200:
            raise ValueError('Choose a free model route.')
        destination = resolve_model_route(value)
        if free and (destination.family != 'openrouter' or not (destination.model == 'openrouter/free' or destination.model.endswith(':free'))):
            raise ValueError('Choose a free OpenRouter model; paid fallbacks are disabled.')
    route(values['default_model'])
    fallbacks = values['fallback_models']
    if type(fallbacks) is not list or len(fallbacks) > 8:
        raise ValueError('Choose at most eight free fallback models.')
    for value in fallbacks:
        route(value, free=True)
    providers = values['providers']
    if (type(providers) is not dict or set(providers) != {'openrouter'} or
            type(providers['openrouter']) is not dict or
            set(providers['openrouter']) != {'credential', 'enabled'} or
            providers['openrouter']['credential'] != 'wcm://ArchHub/openrouter' or
            type(providers['openrouter']['enabled']) is not bool):
        raise ValueError('Use the existing OpenRouter Windows credential reference.')
    agents = values['agents']
    if type(agents) is not dict or len(agents) > 64:
        raise ValueError('Agent profiles exceed the router limit.')
    for agent, profile in agents.items():
        if (type(agent) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', agent) or
                type(profile) is not dict or set(profile) - {'model', 'prompt', 'purpose', 'humanOwner',
                    'admins', 'autonomy', 'questionsPerDay', 'memoryScope', 'skillIds'} or
                type(profile.get('prompt', '')) is not str or len(profile.get('prompt', '')) > 4096):
            raise ValueError('Use a named agent profile with a model and short prompt.')
        if 'model' in profile:
            route(profile['model'])
        for name in ('purpose', 'humanOwner', 'memoryScope', 'admins'):
            if name in profile and (type(profile[name]) is not str or len(profile[name]) > 4096):
                raise ValueError('Agent profile text is invalid.')
        for name in ('skillIds',):
            if name in profile and (type(profile[name]) is not list or len(profile[name]) > 128 or
                    any(type(item) is not str or len(item) > 200 for item in profile[name])):
                raise ValueError('Agent profile list is invalid.')
        if 'questionsPerDay' in profile and (type(profile['questionsPerDay']) is not int or profile['questionsPerDay'] < 0):
            raise ValueError('Questions per day must be a nonnegative integer.')
        autonomy = profile.get('autonomy', {})
        if (type(autonomy) is not dict or set(autonomy) - {'Read', 'Write', 'Send', 'Spend'} or
                any(value not in {'Review all', 'Escalate hard', 'Autonomous'} for value in autonomy.values())):
            raise ValueError('Choose a supported autonomy policy.')
    preferences = values['providerPreferences']
    if type(preferences) is not dict or set(preferences) - {'openrouter', 'lmstudio', 'ollama', 'cloud',
            'openai', 'google', 'nvidia', 'anthropic', 'claude-code', 'codex', 'copilot', 'gemini-cli', 'opencode', 'antigravity', 'cursor'}:
        raise ValueError('Provider preference is invalid.')
    for provider, value in preferences.items():
        route(value)
        if SettingsOwner._provider_id(value) != provider:
            raise ValueError('Choose a model belonging to its configured provider.')
    generation = values['generation']
    if type(generation) is not dict or set(generation) != {'max_tokens', 'temperature', 'top_p'}:
        raise ValueError('Generation settings are invalid.')
    if (type(generation['max_tokens']) is not int or not 1 <= generation['max_tokens'] <= 32000 or
            any(type(generation[key]) not in (int, float) or not math.isfinite(generation[key]) or
                not 0 <= generation[key] <= limit for key, limit in (('temperature', 2), ('top_p', 1)))):
        raise ValueError('Generation settings are outside their allowed range.')
    if len(json.dumps(values, allow_nan=False).encode('utf-8')) > 65536:
        raise ValueError('Router settings exceed 64 KiB.')
    return values


class AccountFiles:
    """NOGRAPH: the account's local preferences in one plain owner file instead of graph cells."""

    def __init__(self, path):
        self.path = Path(path)

    def read(self, root):
        try:
            return json.loads(self.path.read_text(encoding='utf-8')).get(root, {})
        except FileNotFoundError:
            return {}

    def write(self, root, values):
        with _ACCOUNT_FILE_LOCK:
            self._write(root, values)

    def _write(self, root, values):
        import tempfile
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            data = {}
        if root.startswith('cached-read:'):
            data = {key: value for key, value in data.items() if not key.startswith('cached-read:')}
        data[root] = values
        encoded = json.dumps(stamp_test_write(data), ensure_ascii=False, allow_nan=False, indent=1)
        if len(encoded.encode('utf-8')) > 65536:
            raise ValueError('Settings exceed 64 KiB. Shorten workspace rules and retry.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(encoded)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


class CloudRouteUnavailable(ValueError):
    """The pinned cloud does not serve a requested feature."""


class SettingsOwner:
    PUBLIC = ('read', 'updateProfile', 'invitePerson', 'selectFirm', 'setTeamAccess',
              'setBilling', 'refreshBilling', 'prepareCheckout', 'completeCheckout',
              'retryPayment', 'downgradeBilling', 'manageDependency', 'checkDependencies',
              'acceptOfficeInvitation', 'declineOfficeInvitation', 'archiveActivity',
              'readOperations', 'setWorkspaceRules', 'setSettingsScope', 'setGraphWorkspaces', 'ensureDependency',
              'selectDevice', 'grantAccess', 'backUpNow', 'rollBack',
              'readControls', 'exposeSettingsPage', 'setProviderModel', 'disconnectSecret', 'setCompanionState')

    def __init__(self, store, *, cloud=None, dependencies=None, content=None, authentication_context=None,
                 workspace_roots=None, runtime=None):
        self.store = store
        self.runtime = runtime
        self.workspace_roots = workspace_roots
        self.content = content
        self.authentication_context = authentication_context
        self.cloud = cloud or cloud_call
        if dependencies is None:
            from .managed_dependencies import ManagedDependencies
            dependencies = ManagedDependencies()
        self.dependencies = dependencies

    def dispatch(self, function, args):
        if function not in self.PUBLIC or type(args) is not list:
            raise ValueError('Choose a registered Settings command.')
        method = getattr(self, function)
        try:
            inspect.signature(method).bind(*args)
        except TypeError:
            raise ValueError('Settings arguments changed. Refresh this page and retry.') from None
        return method(*args)

    def _account(self):
        me = self.cloud('GET', '/v1/me')
        if not me.get('email') or not me.get('user_id'):
            raise ValueError('Sign in with your browser, then retry.')
        return me, 'account:' + me['user_id']

    def _preferences(self, root):
        return self.store.read(root)

    def _save(self, root, values):
        values = {**self._preferences(root), **values}
        self.store.write(root, values)
        return values

    def _subject(self):
        return self._account()[1]

    def _control_preferences(self):
        return self._preferences(self._subject())

    @staticmethod
    def _provider_id(route):
        from .model_router import resolve_model_route, _CLI_ROUTE_NAME
        destination = resolve_model_route(route)
        if destination.family == 'local-cli':
            assistant = destination.model.split('/', 1)[0]
            return next((id for id, name in _CLI_ROUTE_NAME.items() if name == assistant), '')
        return destination.family

    def _provider_models(self):
        from .model_catalogue import live_model_groups, groups_with_routes
        from .model_router import default_cloud_session
        payload = groups_with_routes(live_model_groups(default_cloud_session()))
        if payload.get('ok') is False:
            raise ValueError('Model catalogue unavailable. Refresh Agents and retry.')
        result = {}
        for group in payload.get('groups', []):
            for item in group.get('items', []):
                route = item.get('routed') or item.get('route')
                if not route:
                    continue
                try:
                    provider = self._provider_id(route)
                except ValueError:
                    continue
                if provider and route not in result.setdefault(provider, []):
                    result[provider].append(route)
        return result

    def providerModel(self, route):
        if not route:
            return route
        try:
            provider = self._provider_id(route)
        except ValueError:
            return route
        return read_router_settings()['providerPreferences'].get(provider, route)

    def setProviderModel(self, id, model):
        if type(model) is not str or self._provider_id(model) != id:
            raise ValueError('Choose a model belonging to this provider.')
        with _ROUTER_LOCK:
            return self.setRouterSettings({'default_model': model, 'providerPreferences': {
                **read_router_settings()['providerPreferences'], id: model}})

    def routerSettings(self):
        from .model_router import request_profiles
        from .model_catalogue import cached_free_routes
        return {**read_router_settings(), **cached_free_routes(), 'requests': request_profiles()}

    def setRouterSettings(self, changes):
        if type(changes) is not dict:
            raise ValueError('Router settings must be an object.')
        with _ROUTER_LOCK:
            values = _checked_router_settings({**read_router_settings(), **changes})
            path = router_settings_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.tmp')
            try:
                temporary.write_text(json.dumps(stamp_test_write(values), ensure_ascii=False, allow_nan=False), encoding='utf-8')
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        return values

    def _secrets(self, listing=None):
        from .model_router import list_social_credentials
        listing = list_social_credentials() if listing is None else listing
        return [{'id': row['vault_entry'], 'name': row.get('display_name') or row['account_id'],
                 'status': 'Connected', 'vault_entry': row['vault_entry'], 'provider': row['provider'],
                 'account_id': row['account_id'], 'disconnectable': row.get('disconnectable', True)}
                for row in [*listing['items'], *listing.get('stored_items', [])]]

    def disconnectSecret(self, id):
        from .model_router import revoke_social_credential
        matches = [row for row in self._secrets() if row['id'] == id]
        if type(id) is not str or len(matches) != 1 or not matches[0]['disconnectable']:
            raise ValueError('Choose an existing connected account, then retry.')
        row = matches[0]
        result = revoke_social_credential({key: row[key] for key in ('vault_entry', 'provider', 'account_id')})
        remaining = self._secrets()
        if result.get('ok') is not True or any(item['id'] == id for item in remaining):
            raise ValueError('Disconnect was not confirmed. Refresh connected accounts before retrying.')
        return {**result, 'secrets': remaining}

    def companionState(self):
        return {'mode': 'idle', 'x': None, 'y': None, 'pinned': False,
                **self._control_preferences().get('companion', {})}

    def setCompanionState(self, values):
        if (type(values) is not dict or not values or set(values) - {'mode', 'x', 'y', 'pinned'}
                or ('mode' in values and (type(values['mode']) is not str or
                    values['mode'] not in {'idle', 'listening', 'thinking', 'speaking', 'done'}))
                or ('pinned' in values and type(values['pinned']) is not bool)
                or (('x' in values) != ('y' in values))
                or any(type(values[key]) not in (int, float) or not math.isfinite(values[key])
                       or not -100000 <= values[key] <= 100000 for key in ('x', 'y') if key in values)):
            raise ValueError('Use a companion mode, a finite x/y position and an on/off pin.')
        self._save(self._subject(), {'companion': {**self.companionState(), **values}})
        return {'companion': self.companionState()}

    def readControls(self):
        from .model_router import ProviderCredentialError, list_social_credentials
        result = {'companion': self.companionState(),
                  'providerPreferences': read_router_settings()['providerPreferences'],
                  'controlErrors': {}}
        try:
            listing = list_social_credentials()
            result['secrets'] = self._secrets(listing)
            if listing.get('issues'):
                result['controlErrors']['secrets'] = ' '.join(item['message'] for item in listing['issues'])
        except ProviderCredentialError:
            result['secrets'] = []
            result['controlErrors']['secrets'] = 'Connected account index could not be read. Refresh Connections.'
        try:
            result['providerModels'] = self._provider_models()
        except ValueError:
            result['providerModels'] = {}
            result['controlErrors']['providerModels'] = 'Model catalogue unavailable. Refresh Agents.'
        return result

    @staticmethod
    def exposeSettingsPage(page):
        from .canvas_documents import thing_items
        items = [row for row in thing_items() if (row.get('setting') or {}).get('page') == page]
        if not items:
            raise ValueError('This page has no editable Settings rows.')
        nodes = [{'id': 'setting:' + row['setting']['id'], 'item': row['id'], 'type': 'thing.setting',
                  'title': row['title'], 'params': {'setting': row['setting']['id']},
                  'position': {'x': 80 + i % 3 * 320, 'y': 100 + i // 3 * 240}}
                 for i, row in enumerate(items)]
        return {'id': nodes[0]['id'], 'page': page, 'nodes': nodes}

    def _roots(self):
        if self.workspace_roots is not None:
            return self.workspace_roots()
        from .nograph_server import JsonFile
        return JsonFile(state_directory() / 'settings/workspaces.json', {'roots': []}).read()['roots']

    def _workspace(self, id):
        if type(id) is not str or not id:
            raise ValueError('Choose a registered workspace in Account settings, then retry.')
        matches = [row for row in self._roots() if row.get('root_id', row.get('id')) == id]
        if len(matches) != 1:
            raise ValueError('This workspace is no longer registered. Refresh Account settings.')
        return matches[0]

    def _graph(self, id):
        from .session_files import SessionFiles
        if type(id) is not str or id != SessionFiles().canvas()['root']:
            raise ValueError('The session changed. Refresh Settings and retry.')

    def readOperations(self, graph=''):
        _me, root = self._account()
        prefs = self._preferences(root)
        return {'settingsScope': prefs.get('settingsScope', 'User'),
                'activeWorkspace': prefs.get('activeWorkspace', ''),
                'workspacePolicies': prefs.get('workspacePolicies', {}),
                'workspaceIds': prefs.get('graphWorkspaces', {}).get(graph, []),
                'devices': self._devices(), 'activeDevice': prefs.get('activeDevice', ''),
                'backups': self._backups()}

    def setWorkspaceRules(self, id, values):
        workspace = self._workspace(id)
        if (type(values) is not dict or not values or set(values) - {'privacy', 'rules', 'shareLearning'}
                or ('privacy' in values and values['privacy'] not in ('Internal', 'Confidential', 'Secret'))
                or ('rules' in values and (type(values['rules']) is not str or len(values['rules']) > 16000))
                or ('shareLearning' in values and type(values['shareLearning']) is not bool)):
            raise ValueError('Use a private privacy tier, text rules and an on/off learning choice.')
        if workspace.get('privacy') == 'public':
            raise ValueError('Register this client folder as private before saving private workspace rules.')
        _me, root = self._account()
        policies = self._preferences(root).get('workspacePolicies', {})
        policy = {**policies.get(id, {}), **values}
        if policy.get('privacy') == 'Secret' and policy.get('shareLearning'):
            raise ValueError('Secret work cannot share learned rules. Turn team learning off first.')
        self._save(root, {'workspacePolicies': {**policies, id: policy}})
        return {'workspacePolicies': self._preferences(root)['workspacePolicies'], 'message': 'Workspace policy saved'}

    def setSettingsScope(self, scope, workspace='', graph=''):
        if scope not in ('User', 'Workspace'):
            raise ValueError('Choose User or Workspace scope.')
        if scope == 'Workspace':
            self._workspace(workspace)
        _me, root = self._account()
        active = workspace if scope == 'Workspace' else ''
        self._save(root, {'settingsScope': scope, 'activeWorkspace': active})
        return {'settingsScope': scope, 'activeWorkspace': active, 'scopeRoot': graph,
                'message': 'Settings scope saved'}

    def setGraphWorkspaces(self, graph, ids):
        self._graph(graph)
        if type(ids) is not list or len(ids) > 100 or any(type(id) is not str for id in ids) or len(set(ids)) != len(ids):
            raise ValueError('Choose each registered workspace at most once.')
        for id in ids:
            self._workspace(id)
        _me, root = self._account()
        held = self._preferences(root).get('graphWorkspaces', {})
        self._save(root, {'graphWorkspaces': {**held, graph: ids}})
        return {'workspaceIds': self._preferences(root)['graphWorkspaces'][graph], 'message': 'Graph workspaces saved'}

    def executionContext(self, graph):
        _me, root = self._account()
        prefs = self._preferences(root)
        policies = prefs.get('workspacePolicies', {})
        return {'workspaces': [{'id': id, 'path': self._workspace(id).get('path', ''), **policies.get(id, {})}
                               for id in prefs.get('graphWorkspaces', {}).get(graph, [])], 'device': ''}

    def _devices(self):
        return []

    def selectDevice(self, id):
        selected = next((row for row in self._devices() if row['id'] == id and row['available']), None)
        if selected is None:
            raise ValueError('This device is unavailable. Open BABOOM on that device, refresh Access, then retry.')
        raise ValueError('This device is connected, but browser task routing has no receipt-bound device handoff. '
                          'Open its BABOOM device handoff node to send work; the current task target was kept.')

    def grantAccess(self, id):
        raise ValueError('Graph permission requests are unavailable. Use the current Approve card.')


    def _backups(self):
        return []

    def backUpNow(self):
        raise ValueError('Graph journal backups are unavailable. Canvas files retain their own history.')

    def rollBack(self, id):
        raise ValueError('Graph journal restore is unavailable. Open the session file and its History.')


    def read(self):
        me, root = self._account()
        prefs = self._preferences(root)
        companies = self.cloud('GET', '/v1/companies/mine').get('companies', [])
        active = next((x for x in companies if x.get('is_current')), None)
        detail = self.cloud('GET', '/v1/companies/' + quote(active['id'], safe='')) if active else {}
        profile = {key: me[field] for key, field in (('name', 'full_name'), ('firm', 'firm_name'))
                   if isinstance(me.get(field), str) and me[field].strip()}
        billing = self._billing(me, prefs)
        errors = {}
        try:
            invitations = self.cloud('GET', '/v1/companies/invites/mine').get('invitations', [])
        except CloudRouteUnavailable as missing:
            # A cloud deploy behind the app is ours to fix, not the founder's: no invitations, logged, no toast.
            import logging
            logging.getLogger(__name__).warning('cloud lacks /v1/companies/invites/mine (%s); no office invitations shown', missing)
            invitations = []
        return {'profile': {**profile, **prefs.get('profile', {}), 'plan': {'solo':'Personal','studio':'Office','firm':'Team','trial':'Personal'}.get(me['plan'], me['plan'])},
                'firms': companies, 'activeFirm': active['id'] if active else '',
                'people': [{'id': m['user_id'], 'name': m.get('full_name') or m['email'],
                            'email': m['email'], 'accessRole': {'owner': 'Owner', 'admin': 'Administrator',
                            'member': 'Member', 'viewer': 'Viewer'}[m['role']],
                            'expires': m.get('access_until') or ''} for m in detail.get('members', [])],
                'billing': billing, 'controlErrors': errors,
                'officeInvitations': invitations}

    def updateProfile(self, values):
        if type(values) is not dict or not values or set(values) - {'name', 'firm'}:
            raise ValueError('Edit your name or firm here; identity changes use browser sign-in.')
        if any(type(v) is not str or not v.strip() or len(v) > 120 for v in values.values()):
            raise ValueError('Use a name and firm between 1 and 120 characters.')
        _me, root = self._account()
        profile = {**self._preferences(root).get('profile', {}), **{k: v.strip() for k, v in values.items()}}
        self._save(root, {'profile': profile})
        return {'profile': profile, 'message': 'Profile saved'}

    def _company(self):
        rows = self.cloud('GET', '/v1/companies/mine').get('companies', [])
        selected = next((r for r in rows if r.get('is_current')), None)
        if not selected:
            raise ValueError('Select your office in Account settings, then retry.')
        return quote(selected['id'], safe='')

    def selectFirm(self, id):
        if type(id) is not str or not id:
            raise ValueError('Choose an office from your account memberships.')
        result = self.cloud('POST', '/v1/companies/' + quote(id, safe='') + '/switch', {})
        return {**result, **self.read()}

    def invitePerson(self, email):
        if type(email) is not str or '@' not in email or len(email) > 254:
            raise ValueError('Enter your teammate’s email address and retry.')
        result = self.cloud('POST', '/v1/companies/' + self._company() + '/invites',
                            {'email': email.strip(), 'role': 'member'})
        # An issued invite is not proof that the mail provider delivered it.
        return {'email': result['email'], 'message': 'Invitation issued; delivery is confirmed by your mail provider.'}

    def acceptOfficeInvitation(self, id):
        if type(id) is not str or not id:
            raise ValueError('Refresh your office invitations and choose one belonging to this account.')
        self.cloud('POST', '/v1/companies/invites/accept', {'invite_token': id})
        return self.read()

    def declineOfficeInvitation(self, id):
        if type(id) is not str or not id:
            raise ValueError('Refresh your office invitations and choose one belonging to this account.')
        self.cloud('POST', '/v1/companies/invites/decline', {'invite_token': id})
        return self.read()

    def archiveActivity(self):
        if self.content is None or self.authentication_context is None:
            raise ValueError('Reopen ArchHub through its launcher to use the active conversation owner.')
        report = self.content.maintain_retention(authentication_context=self.authentication_context)
        return {'retention': report, 'message': '%s: %s conversations archived; %s protected.' % (report['status'], report['archived'], report['protected'])}

    def setTeamAccess(self, id, values):
        roles = {'Owner': 'owner', 'Administrator': 'admin', 'Member': 'member', 'Viewer': 'viewer'}
        if type(id) is not str or not id or type(values) is not dict or not values or set(values) - {'accessRole', 'expires'}:
            raise ValueError('Select an existing team member and edit role or access date.')
        if 'accessRole' in values and values['accessRole'] not in roles:
            raise ValueError('Choose Owner, Administrator, Member or Viewer.')
        company = self._company()
        if values.get('accessRole') == 'Owner':
            self.cloud('POST', '/v1/companies/' + company + '/transfer-ownership', {'new_owner_user_id': id})
        else:
            body = {('role' if k == 'accessRole' else 'access_until'): roles[v] if k == 'accessRole' else v for k, v in values.items()}
            self.cloud('PATCH', '/v1/companies/{company_id}/members/{user_id}'.format(company_id=company, user_id=quote(id, safe='')), body)
        return self.read()

    def _billing(self, me, prefs):
        plans = self.cloud('GET', '/v1/billing/plans')
        selected = prefs.get('billing', {})
        return {'status': me['plan'], 'requestedPlan': selected.get('requestedPlan', {'solo':'Personal','studio':'Office','firm':'Team'}.get(me['plan'], me['plan'])),
                'cycle': selected.get('cycle', 'Monthly'), 'checkout': selected.get('checkout'),
                'invoices': plans.get('invoices', []), 'limitReached': me.get('remaining_messages') == 0,
                'plans': plans.get('tiers', []), 'offer': {'pricingVisible': plans.get('pricing_visible'), 'currency': plans.get('currency')},
                'remainingMessages': me.get('remaining_messages'), 'periodEnd': me.get('period_end')}

    def refreshBilling(self):
        me, root = self._account()
        return {'billing': self._billing(me, self._preferences(root)),
                'profile': {'plan': {'solo':'Personal','studio':'Office','firm':'Team','trial':'Personal'}.get(me['plan'], me['plan'])}}

    def setBilling(self, values):
        if type(values) is not dict or not values or set(values) - {'requestedPlan', 'cycle', 'checkout'}:
            raise ValueError('Edit a billing plan or cycle, then review it.')
        me, root = self._account()
        billing = self._billing(me, self._preferences(root))
        if 'cycle' in values and values['cycle'] not in ('Monthly', 'Annual'):
            raise ValueError('Choose Monthly or Annual billing.')
        if 'checkout' in values and values['checkout'] is not None:
            raise ValueError('Create checkout with Review plan; payment confirmation belongs to billing.')
        if 'requestedPlan' in values:
            plans = billing['plans']
            ids = {x.get('tier') for x in plans} if isinstance(plans, list) else set(plans)
            if {'Personal':'solo','Office':'studio','Team':'firm'}.get(values['requestedPlan'], values['requestedPlan']) not in ids:
                raise ValueError('Refresh billing and choose a currently published plan.')
        saved = {**self._preferences(root).get('billing', {}), **values}
        self._save(root, {'billing': saved})
        return self.refreshBilling()

    def prepareCheckout(self):
        me, root = self._account()
        b = self._billing(me, self._preferences(root))
        result = self.cloud('POST', '/v1/billing/checkout', {'tier': {'Personal':'solo','Office':'studio','Team':'firm'}.get(b['requestedPlan'], b['requestedPlan']), 'annual': b['cycle'] == 'Annual'})
        url = result.get('checkout_url') or result.get('url')
        if not url:
            raise ValueError('Billing did not return a checkout. Refresh billing and review the published offer.')
        self._save(root, {'billing': {**self._preferences(root).get('billing', {}), 'checkout': {'url': url, 'plan': b['requestedPlan'], 'cycle': b['cycle'], 'status': 'Awaiting payment provider confirmation'}}})
        return {**self.refreshBilling(), 'open_url': url}

    def completeCheckout(self):
        return self.refreshBilling()

    def retryPayment(self):
        result = self.cloud('GET', '/v1/billing/portal')
        return {'open_url': result.get('url') or result.get('portal_url'), **self.refreshBilling()}

    def downgradeBilling(self):
        # The billing portal owns cancellation and its confirmation; no local entitlement write.
        return self.retryPayment()

    def checkDependencies(self):
        return {'dependencies': self.dependencies.check()}

    ACCOUNT = ('read', 'updateProfile', 'invitePerson', 'selectFirm', 'setTeamAccess', 'setBilling', 'refreshBilling',
               'prepareCheckout', 'completeCheckout', 'retryPayment', 'downgradeBilling', 'acceptOfficeInvitation',
               'declineOfficeInvitation', 'manageDependency', 'ensureDependency', 'checkDependencies')

    def manageDependency(self, id, action):
        return self.dependencies.manage(id, action)

    def ensureDependency(self, id):
        rows = self.dependencies.check()
        row = next((row for row in rows if row['id'] == id), None)
        if row is None:
            raise ValueError('Choose a listed dependency.')
        if row['state'] in ('Ready', 'Update ready'):
            return {'dependencies': rows}
        return self.manageDependency(id, 'Repair' if row['state'] == 'Needs repair' else 'Install')


def cloud_call(method, path, body=None, *, timeout_seconds=15, session=None):
    from .cloud_session import cloud_session_path, _pinned_base
    from .cloud_signin import read_cloud_session
    try:
        held = session if session is not None else read_cloud_session(cloud_session_path())
    except (OSError, ValueError):
        raise ValueError('Not signed in. Sign in with your browser, then retry.') from None
    if not held.get('token'):
        raise ValueError('Not signed in. Sign in with your browser, then retry.')
    request = Request(_pinned_base(held) + path, method=method,
                      data=None if body is None else json.dumps(body).encode('utf-8'),
                      headers={'Authorization': 'Bearer ' + held['token'], 'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            result = json.loads(response.read(1024 * 1024))
    except HTTPError as error:
        if error.code == 404 and method == 'GET' and path == '/v1/companies/invites/mine':
            raise CloudRouteUnavailable('Cloud feature unavailable. Update the cloud service and retry.') from None
        raise ValueError('Cloud backend refused (HTTP %s). Refresh account status and retry.' % error.code) from None
    except OSError:
        raise ValueError('Cloud backend unreachable. Check your connection and retry.') from None
    except ValueError:
        raise ValueError('Cloud backend returned an invalid response. Refresh account status and retry.') from None
    if not isinstance(result, dict) or result.get('ok') is False:
        raise ValueError('Cloud backend returned an unconfirmed response. Refresh account status before retrying.')
    return result


def appearance_settings(function='readControls', args=(), settings=None):
    """Appearance rows and node bindings use the same validated settings owner."""
    from .nograph_server import JsonFile, Refused
    from .session_files import profile_directory
    settings = settings or JsonFile(profile_directory() / 'settings/settings.json', {})
    import re
    tokens = json.loads((Path(__file__).with_name('studio') / 'design-tokens.json').read_text(encoding='utf-8'))
    design = tokens['archhub-design-parameters']
    dimensions = {
        'appearanceInspectorWidth': {'min': 280, 'max': 480, 'tokenId': 'layout.inspectorWidth'},
        'appearanceRowSpacing': {'min': 0, 'max': 16, 'tokenId': 'layout.nodeRowGap'},
        'appearanceNodeRadius': {'min': 0, 'max': 24, 'tokenId': 'node.radius'},
        'appearanceNodeHeader': {'tokenId': 'color.bgPanel'},
    }
    appearance = {
        'Appearance.Theme': ('appearanceTheme', 'Theme', 'Dark', ('Dark', 'Light', 'System')),
        'Appearance.High contrast': ('appearanceContrast', 'High contrast', False, ()),
        'Appearance.Canvas grid': ('appearanceGrid', 'Canvas grid', True, ()),
        'Appearance.Reduce motion': ('appearanceReduceMotion', 'Reduce motion', False, ()),
        'Appearance.Accent colour': ('appearanceAccent', 'Accent colour', '#d97757', ()),
        'Appearance.Text scale': ('appearanceTextScale', 'Text scale', 100, ()),
        'Appearance.Default zoom': ('appearanceDefaultZoom', 'Default zoom', 100, ()),
        'Appearance.Inspector width': ('appearanceInspectorWidth', 'Inspector width', int(design['layout']['inspectorWidth']['$value'].removesuffix('px')), ()),
        'Appearance.Row spacing': ('appearanceRowSpacing', 'Row spacing', int(design['layout']['nodeRowGap']['$value'].removesuffix('px')), ()),
        'Appearance.Node radius': ('appearanceNodeRadius', 'Node radius', int(design['node']['radius']['$value'].removesuffix('px')), ()),
        'Appearance.Node header colour': ('appearanceNodeHeader', 'Node header colour', tokens['archhub-original']['color']['bgPanel']['$value'], ()),
    }
    preferences = settings.read()
    if function == 'setAppearance':
        if len(args) != 2 or not isinstance(args[0], str) or args[0] not in appearance:
            raise Refused('Choose a supported Appearance setting.')
        key, _label, default, choices = appearance[args[0]]
        value = args[1]
        if (choices and value not in choices) or (type(default) is bool and type(value) is not bool):
            raise Refused('Choose a valid value for this Appearance setting.')
        if key in ('appearanceAccent', 'appearanceNodeHeader') and (not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value)):
            raise Refused('Choose a six-digit accent colour.')
        if key == 'appearanceTextScale' and (type(value) is not int or not 75 <= value <= 150):
            raise Refused('Choose a text scale from 75 to 150 percent.')
        if key == 'appearanceDefaultZoom' and (type(value) is not int or not 10 <= value <= 400):
            raise Refused('Choose a default zoom from 10 to 400 percent.')
        limits = dimensions.get(key, {})
        if 'min' in limits and (type(value) is not int or not limits['min'] <= value <= limits['max']):
            raise Refused('Choose a value within the Appearance setting limits.')
        preferences = settings.update({key: value}, remove=('homeLayout',) if key == 'appearanceInspectorWidth' else ())
    rows = [{'id': id, 'page': 'Appearance', 'label': label, 'default': default,
             'type': 'enum' if choices else 'boolean' if type(default) is bool else 'number' if type(default) is int else 'color',
             'value': preferences.get(key, default), 'overridden': key in preferences,
             **dimensions.get(key, {}),
             **({'min': 75, 'max': 150} if key == 'appearanceTextScale' else {}),
             **({'min': 10, 'max': 400} if key == 'appearanceDefaultZoom' else {}),
             **({'options': list(choices)} if choices else {})}
            for id, (key, label, default, choices) in appearance.items()]
    return {'appearanceSettings': rows, 'homeLayout': preferences.get('homeLayout', {})}


def appearance_setting(identity):
    row = next((row for row in appearance_settings()['appearanceSettings'] if row['id'] == identity), None)
    if row is None:
        raise ValueError('This Settings row no longer exists: %s' % identity)
    return row


_APPLICATION_SETTING_SPECS = {
    "stale_claim_after_idle_minutes": ("number", {"min": 1, "max": 1440, "step": 1}),
    "archive_after_idle_days": ("number", {"min": 1, "max": 3650, "step": 1}),
    "tick_cadence_minutes": ("number", {"min": 1, "max": 1440, "step": 1}),
    "backup_count": ("number", {"min": 1, "max": 100, "step": 1}),
    "backup_budget_bytes": ("number", {"min": 1048576, "max": 1099511627776, "step": 1048576}),
    "recovery_timeout_seconds": ("number", {"min": 1, "max": 3600, "step": 1}),
    "instance_retry_ms": ("number", {"min": 1, "max": 3600000, "step": 1}),
    "preflight_database_ms": ("number", {"min": 1, "max": 3600000, "step": 1}),
    "broker_start_ms": ("number", {"min": 1, "max": 3600000, "step": 1}),
    "home_load_ms": ("number", {"min": 1000, "max": 300000, "step": 1000}),
    "refusal_poll_ms": ("number", {"min": 1, "max": 3600000, "step": 1}),
    "quit_watchdog_ms": ("number", {"min": 1, "max": 3600000, "step": 1}),
    "account_http_ms": ("number", {"min": 1, "max": 3600000, "step": 1}),
    "session_minimum_validity_seconds": ("number", {"min": 1, "max": 3600, "step": 1}),
    "session_poll_ms": ("number", {"min": 1, "max": 3600000, "step": 1}),
    "worker_join_ms": ("number", {"min": 1, "max": 3600000, "step": 1}),
    "host_stop_ms": ("number", {"min": 1, "max": 3600000, "step": 1}),
    "host_cancel_ms": ("number", {"min": 1, "max": 3600000, "step": 1}),
    "mutation_poll_ms": ("number", {"min": 1, "max": 3600000, "step": 1}),
    "desktop_refresh_ms": ("number", {"min": 1, "max": 3600000, "step": 1}),
    "archive_step_ms": ("number", {"min": 1, "max": 3600000, "step": 1}),
    "cloud_shutdown_ms": ("number", {"min": 1, "max": 3600000, "step": 1}),
    "update_shutdown_ms": ("number", {"min": 1, "max": 3600000, "step": 1}),
    "export_release_ms": ("number", {"min": 1, "max": 3600000, "step": 1}),
    "toast_visible_ms": ("number", {"min": 1, "max": 3600000, "step": 1}),
    "voice_hold_ms": ("number", {"min": 1, "max": 3600000, "step": 1}),
    "model_request_ms": ("number", {"min": 1, "max": 3600000, "step": 1}),
    "model_cli_request_ms": ("number", {"min": 1, "max": 3600000, "step": 1}),
    "keep_running_in_tray": ("boolean", {"min": 0, "max": 1, "step": 1}),
    "update_check_interval_minutes": ("number", {"min": 1, "max": 1440, "step": 1}),
    "update_idle_minutes": ("number", {"min": 1, "max": 1440, "step": 1}),
    "update_auto_apply_on_quit": ("boolean", {"min": 0, "max": 1, "step": 1}),
    "update_preview_channel": ("boolean", {"min": 0, "max": 1, "step": 1}),
    "backup_location": ("text", {}),
}

def _application_setting_default(key: str) -> int | str:
    from .library_engines import LIBRARY_ITEM_ENGINES
    value = LIBRARY_ITEM_ENGINES['tool_workshop']['params'][key]
    return str(value) if key == 'backup_location' else int(value)


THEME = {
    'bg': '#0e0e11',
    'bg_panel': '#15151a',
    'bg_soft': '#1c1c23',
    'bg_hover': '#22222a',
    'bg_deep': '#0a0a0d',
    'bg_canvas': '#101015',
    'bg_raised': '#1d1d22',
    'bg_ink': '#18181e',
    'ink': '#ece8e0',
    'ink_soft': '#9b938a',
    'ink_muted': '#8b837a',
    'ink_dim': '#8a837c',
    'on_fill': '#180f08',
    'line': '#26262e',
    'line_soft': '#1e1e24',
    'line_hair': '#1a1a20',
    'accent': '#d97757',
    'accent_soft': '#3a2018',
    'accent_dim': '#2a1812',
    'accent_hi': '#e8896a',
    'accent_press': '#a04832',
    'ok': '#7ec18e',
    'warn': '#e5b25a',
    'err': '#e6705f',
    'cyan': '#5fb3b3',
    'purple': '#a98cd6',
    'blue': '#7898d6',
    'l_bg': '#f7f4ee',
    'l_bg_panel': '#fbf9f4',
    'l_bg_soft': '#efeae0',
    'l_ink': '#1a1612',
    'l_ink_soft': '#6b6256',
    'l_ink_muted': '#9a9183',
    'l_line': '#e3ddd0',
    'l_accent': '#c96442',
}
