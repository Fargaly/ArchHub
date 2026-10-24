"""Settings translations over the selected CellStore and existing cloud owners."""
from __future__ import annotations

import inspect
import json
import math
from pathlib import Path
import re
import uuid
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from .universal_cell import Cell, NULL_CELL_ID, InvalidCell
from .cell_accounts import upsert_account, ensure_accounts


class CloudRouteUnavailable(InvalidCell):
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
            raise InvalidCell('Choose a registered Settings command.')
        method = getattr(self, function)
        try:
            inspect.signature(method).bind(*args)
        except TypeError:
            raise InvalidCell('Settings arguments changed. Refresh this page and retry.') from None
        return method(*args)

    def _account(self):
        me = self.cloud('GET', '/v1/me')
        if not me.get('email') or not me.get('user_id'):
            raise InvalidCell('Sign in with your browser, then retry.')
        ensure_accounts(self.store, founder_email=None)
        root, _email, _tier = upsert_account(self.store, me['email'])
        return me, root

    def _preferences(self, root):
        held = self.store.snapshot().cells.get(root + ':settings')
        return json.loads(bytes(held.atom)) if held else {}

    def _save(self, root, values):
        values = {**self._preferences(root), **values}
        snapshot = self.store.snapshot()
        cell = Cell(root + ':settings', NULL_CELL_ID, NULL_CELL_ID,
                    json.dumps(values, ensure_ascii=False, allow_nan=False).encode('utf-8'))
        if len(cell.atom) > 65536:
            raise InvalidCell('Settings exceed 64 KiB. Shorten workspace rules and retry.')
        self.store.commit(snapshot.revision, **{'replace' if cell.id in snapshot.cells else 'create': (cell,)})
        return values

    def _subject(self):
        if self.runtime is None or self.authentication_context is None:
            raise InvalidCell('Reopen Settings through the application owner.')
        return self.runtime.universal_registry.authorization.subject_root

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
        payload = self.runtime._project_model_discovery('/api/universal/models')
        if payload.get('ok') is False:
            raise InvalidCell('Model catalogue unavailable. Refresh Agents and retry.')
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
        return self._control_preferences().get('providerPreferences', {}).get(provider, route)

    def setProviderModel(self, id, model):
        self._subject()
        if type(id) is not str or type(model) is not str or model not in self._provider_models().get(id, []):
            raise InvalidCell('Choose a current model belonging to this provider.')
        held = self._control_preferences().get('providerPreferences', {})
        self._save(self._subject(), {'providerPreferences': {**held, id: model}})
        return {'providerPreferences': self._control_preferences()['providerPreferences']}

    def _secrets(self, listing=None):
        from .model_router import list_social_credentials
        listing = list_social_credentials() if listing is None else listing
        return [{'id': row['vault_entry'], 'name': row.get('display_name') or row['account_id'],
                 'status': 'Connected', 'vault_entry': row['vault_entry'], 'provider': row['provider'],
                 'account_id': row['account_id'], 'disconnectable': row.get('disconnectable', True)}
                for row in [*listing['items'], *listing.get('stored_items', [])]]

    def disconnectSecret(self, id):
        from .model_router import revoke_social_credential
        self._subject()
        matches = [row for row in self._secrets() if row['id'] == id]
        if type(id) is not str or len(matches) != 1:
            raise InvalidCell('Choose an existing connected account, then retry.')
        row = matches[0]
        if not row['disconnectable']:
            raise InvalidCell('Manage this credential through its existing provider settings.')
        def guard():
            self.runtime.require_universal_http_route('POST', '/api/universal/social-credential-remove',
                authentication_context=self.authentication_context, revalidate=True)
        result = revoke_social_credential({key: row[key] for key in ('vault_entry', 'provider', 'account_id')},
                                        before_replace=guard)
        remaining = self._secrets()
        if result.get('ok') is not True or result.get('state') not in {'removed', 'absent'} or any(
                item['id'] == id for item in remaining):
            raise InvalidCell('Disconnect was not confirmed. Refresh connected accounts before retrying.')
        held = self._control_preferences().get('disconnectedAccounts', {})
        self._save(self._subject(), {'disconnectedAccounts': {**held, id: {
            key: result[key] for key in ('vault_entry', 'provider', 'account_id', 'state', 'provider_token_revoked')}}})
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
            raise InvalidCell('Use a companion mode, a finite x/y position and an on/off pin.')
        self._save(self._subject(), {'companion': {**self.companionState(), **values}})
        return {'companion': self.companionState()}

    def readControls(self):
        from .model_router import ProviderCredentialError, list_social_credentials
        result = {'companion': self.companionState(),
                  'providerPreferences': self._control_preferences().get('providerPreferences', {}),
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
        except InvalidCell:
            result['providerModels'] = {}
            result['controlErrors']['providerModels'] = 'Model catalogue unavailable. Refresh Agents.'
        return result

    @staticmethod
    def _setting_page(parameter):
        kind = (parameter.get('setting') or {}).get('kind', 'property')
        return ('Appearance' if kind == 'theme' else 'BABOOM' if kind == 'baboom' else
                'Agents' if 'model' in kind or kind == 'generation' else
                'Library & Mods' if kind.startswith('mod') else 'System graph')

    def exposeSettingsPage(self, page):
        from .canvas_graph_owner import CanvasOwner
        from .universal_application import select_universal_root
        self._subject()
        canvas = CanvasOwner(self.store, self.runtime.universal_registry, self.authentication_context).canvas()
        matches = [node for node in canvas['nodes'] if node.get('application') and any(
            self._setting_page(parameter) == page for parameter in node.get('properties', node.get('params', [])))]
        if not matches:
            raise InvalidCell('This page has no application node in the current scope. Open its graph first.')
        # Multiple parameters may share a page; focus its first existing application owner, never a copy.
        node = matches[0]
        select_universal_root(self.store, self.runtime.universal_registry, node['id'],
                              authentication_context=self.authentication_context)
        return {'id': node['id'], 'page': page, 'revision': self.store.revision}

    def _roots(self):
        if self.workspace_roots is not None:
            return self.workspace_roots()
        from .workspace_roots_catalogue import forward_workspace_settings, settings_principal
        route = getattr(self.runtime, '_clean_workspace_roots', None)
        result = (route({'action': 'list'}, admission={'principal': settings_principal()})
                  if route is not None else forward_workspace_settings({'action': 'list'}))
        return [*([{**result['built_in'], 'root_id': result['built_in']['id']}]
                  if result.get('built_in') else []), *result.get('roots', [])]

    def _workspace(self, id):
        if type(id) is not str or not id:
            raise InvalidCell('Choose a registered workspace in Account settings, then retry.')
        matches = [row for row in self._roots() if row.get('root_id', row.get('id')) == id]
        if len(matches) != 1:
            raise InvalidCell('This workspace is no longer registered. Refresh Account settings.')
        return matches[0]

    def _graph(self, id):
        if type(id) is not str or not id:
            raise InvalidCell('Open the graph whose workspace scope you want to edit.')
        if self.runtime is not None:
            from .canvas_graph_owner import CanvasOwner
            canvas = CanvasOwner(self.store, self.runtime.universal_registry, self.authentication_context).canvas()
            if id != canvas.get('scope', {}).get('current', canvas.get('root')):
                raise InvalidCell('The graph changed. Refresh Settings and retry.')

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
            raise InvalidCell('Use a private privacy tier, text rules and an on/off learning choice.')
        if workspace.get('privacy') == 'public':
            raise InvalidCell('Register this client folder as private before saving private workspace rules.')
        _me, root = self._account()
        policies = self._preferences(root).get('workspacePolicies', {})
        policy = {**policies.get(id, {}), **values}
        if policy.get('privacy') == 'Secret' and policy.get('shareLearning'):
            raise InvalidCell('Secret work cannot share learned rules. Turn team learning off first.')
        self._save(root, {'workspacePolicies': {**policies, id: policy}})
        return {'workspacePolicies': self._preferences(root)['workspacePolicies'], 'message': 'Workspace policy saved'}

    def setSettingsScope(self, scope, workspace='', graph=''):
        if scope not in ('User', 'Workspace'):
            raise InvalidCell('Choose User or Workspace scope.')
        if scope == 'Workspace':
            self._workspace(workspace)
        _me, root = self._account()
        target = ''
        if self.runtime is not None:
            from .universal_graphs import open_graph
            registry = self.runtime.universal_registry
            target = registry.canvas_root
            if scope == 'Workspace':
                linked = self._preferences(root).get('graphWorkspaces', {})
                candidates = [id for id, roots in linked.items() if workspace in roots]
                if graph in candidates:
                    target = graph
                elif len(candidates) == 1:
                    target = candidates[0]
                else:
                    raise InvalidCell('Choose this workspace in one graph first, then select Workspace scope.')
            open_graph(self.store, registry, target, authentication_context=self.authentication_context)
        self._save(root, {'settingsScope': scope, 'activeWorkspace': workspace if scope == 'Workspace' else ''})
        return {'settingsScope': scope, 'activeWorkspace': workspace if scope == 'Workspace' else '',
                'scopeRoot': target, 'message': 'Settings scope saved'}

    def setGraphWorkspaces(self, graph, ids):
        self._graph(graph)
        if type(ids) is not list or len(ids) > 100 or any(type(id) is not str for id in ids) or len(set(ids)) != len(ids):
            raise InvalidCell('Choose each registered workspace at most once.')
        for id in ids:
            self._workspace(id)
        _me, root = self._account()
        held = self._preferences(root).get('graphWorkspaces', {})
        self._save(root, {'graphWorkspaces': {**held, graph: ids}})
        return {'workspaceIds': self._preferences(root)['graphWorkspaces'][graph], 'message': 'Graph workspaces saved'}

    def executionContext(self, graph):
        """The Workshop reads the same saved policy at the point of dispatch."""
        from .cloud_session import signed_in_cloud_account
        from .cell_accounts import _account_root, _normal
        email = signed_in_cloud_account()
        if not email:
            return {'workspaces': [], 'device': ''}
        prefs = self._preferences(_account_root(_normal(email)))
        policies = prefs.get('workspacePolicies', {})
        workspaces = []
        for id in prefs.get('graphWorkspaces', {}).get(graph, []):
            workspace = self._workspace(id)
            policy = policies.get(id, {})
            workspaces.append({'id': id, 'path': workspace.get('path', ''), **policy})
        return {'workspaces': workspaces, 'device': prefs.get('activeDevice', '')}

    def _devices(self):
        if self.runtime is None:
            return []
        from .universal_application import project_universal_founder_device_custody_report
        report = project_universal_founder_device_custody_report(self.store, self.runtime.universal_registry)
        return [{'id': row['device_ref'], 'name': row['label'],
                 'status': 'Online' if row['runtime_present'] and row['state'] == 'active' else row['state'],
                 'available': row['state'] == 'active' and row['runtime_present'] and row['baboom_bound']}
                for row in report['devices']]

    def selectDevice(self, id):
        selected = next((row for row in self._devices() if row['id'] == id and row['available']), None)
        if selected is None:
            raise InvalidCell('This device is unavailable. Open BABOOM on that device, refresh Access, then retry.')
        raise InvalidCell('This device is connected, but browser task routing has no receipt-bound device handoff. '
                          'Open its BABOOM device handoff node to send work; the current task target was kept.')

    def grantAccess(self, id):
        if self.runtime is None or type(id) is not str or not id:
            raise InvalidCell('Open the pending Permission Request node in System graph and retry.')
        from .cell_state_machine import read_instance_state_machine, read_transition
        from .cell_permission_requests import read_permission_request
        from .universal_application import transition_universal_operational_state
        registry = self.runtime.universal_registry
        snapshot = self.store.snapshot()
        operational = registry.standard_library.state_machine_protocol
        definition = registry.standard_library.governed_domains.definitions['permission-request'].definition_root
        read_permission_request(snapshot, registry.assembly_protocol, operational, id, expected_definition_root=definition)
        machine = read_instance_state_machine(snapshot, registry.assembly_protocol, operational, id)
        transitions = [read_transition(snapshot, operational, root) for root in machine.transition_roots]
        matches = [row for row in transitions if row.from_state_root == machine.current_state_root
                   and snapshot.cells[row.event_root].atom == b'approve']
        if len(matches) != 1:
            raise InvalidCell('This permission is no longer pending. Refresh its node before retrying.')
        revision = transition_universal_operational_state(self.store, registry, id, matches[0].event_root,
            machine.current_state_root, authentication_context=self.authentication_context)
        return {'revision': revision, 'message': 'Permission decision recorded by its owner'}

    def _recovery_directory(self):
        if self.content is None or self.authentication_context is None or self.store.database_path is None:
            raise InvalidCell('Open ArchHub through its launcher to use the admitted recovery owner.')
        from .persistence import application_state_directory
        from .application_recovery_files import installer_backup_directory
        state = application_state_directory(self.store.database_path)
        return Path(installer_backup_directory(state.parent, self.store.database_path))

    def _backups(self):
        if self.content is None or self.store.database_path is None:
            return []
        directory = self._recovery_directory()
        if not directory.is_dir():
            return []
        result = []
        for path in sorted(directory.glob('application-recovery-*'), reverse=True):
            if path.is_dir() and not path.is_symlink() and not path.is_junction() and (path / 'recovery.json').is_file():
                result.append({'id': path.name, 'name': path.name, 'location': 'Configured recovery location'})
        return result

    def backUpNow(self):
        directory = self._recovery_directory()
        directory.mkdir(parents=True, exist_ok=True)
        path = self.content.backup_recovery(directory, authentication_context=self.authentication_context,
                                            timeout_seconds=self._recovery_timeout())
        return {'backups': self._backups(), 'backup': Path(path).name,
                'message': 'Verified graph and content backup created at the configured recovery location'}

    def rollBack(self, id):
        if type(id) is not str or not re.fullmatch(r'application-recovery-[0-9]{8}-[0-9a-f]{32}', id):
            raise InvalidCell('Choose a verified backup from Storage and retry.')
        directory = self._recovery_directory()
        source = directory / id
        if id not in {row['id'] for row in self._backups()}:
            raise InvalidCell('This backup is unavailable. Refresh Storage and retry.')
        destination = directory / ('RESTORE-' + uuid.uuid4().hex.upper())
        path = self.content.prepare_recovery_restore(source, destination,
            authentication_context=self.authentication_context, timeout_seconds=self._recovery_timeout())
        return {'status': 'prepared', 'restored': False, 'restoreDirectory': str(path),
                'message': 'Restore verified and prepared. Live data is unchanged; activation requires the launcher recovery path.'}

    def _recovery_timeout(self):
        from .universal_application import _workshop_board_int_param, _APPLICATION_SETTING_SPECS, _application_setting_default
        key = 'recovery_timeout_seconds'
        bounds = _APPLICATION_SETTING_SPECS[key][1]
        return _workshop_board_int_param(self.store.snapshot(), self.runtime.universal_registry, key,
            default=_application_setting_default(key), lower=bounds['min'], upper=bounds['max'])

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
        except CloudRouteUnavailable:
            invitations = []
            errors['officeInvitations'] = 'Signed in. Office invitations unavailable until the cloud service is updated.'
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
            raise InvalidCell('Edit your name or firm here; identity changes use browser sign-in.')
        if any(type(v) is not str or not v.strip() or len(v) > 120 for v in values.values()):
            raise InvalidCell('Use a name and firm between 1 and 120 characters.')
        _me, root = self._account()
        profile = {**self._preferences(root).get('profile', {}), **{k: v.strip() for k, v in values.items()}}
        self._save(root, {'profile': profile})
        return {'profile': profile, 'message': 'Profile saved'}

    def _company(self):
        rows = self.cloud('GET', '/v1/companies/mine').get('companies', [])
        selected = next((r for r in rows if r.get('is_current')), None)
        if not selected:
            raise InvalidCell('Select your office in Account settings, then retry.')
        return quote(selected['id'], safe='')

    def selectFirm(self, id):
        if type(id) is not str or not id:
            raise InvalidCell('Choose an office from your account memberships.')
        result = self.cloud('POST', '/v1/companies/' + quote(id, safe='') + '/switch', {})
        return {**result, **self.read()}

    def invitePerson(self, email):
        if type(email) is not str or '@' not in email or len(email) > 254:
            raise InvalidCell('Enter your teammate’s email address and retry.')
        result = self.cloud('POST', '/v1/companies/' + self._company() + '/invites',
                            {'email': email.strip(), 'role': 'member'})
        # An issued invite is not proof that the mail provider delivered it.
        return {'email': result['email'], 'message': 'Invitation issued; delivery is confirmed by your mail provider.'}

    def acceptOfficeInvitation(self, id):
        if type(id) is not str or not id:
            raise InvalidCell('Refresh your office invitations and choose one belonging to this account.')
        self.cloud('POST', '/v1/companies/invites/accept', {'invite_token': id})
        return self.read()

    def declineOfficeInvitation(self, id):
        if type(id) is not str or not id:
            raise InvalidCell('Refresh your office invitations and choose one belonging to this account.')
        self.cloud('POST', '/v1/companies/invites/decline', {'invite_token': id})
        return self.read()

    def archiveActivity(self):
        if self.content is None or self.authentication_context is None:
            raise InvalidCell('Reopen ArchHub through its launcher to use the active conversation owner.')
        report = self.content.maintain_retention(authentication_context=self.authentication_context)
        return {'retention': report, 'message': '%s: %s conversations archived; %s protected.' % (report['status'], report['archived'], report['protected'])}

    def setTeamAccess(self, id, values):
        roles = {'Owner': 'owner', 'Administrator': 'admin', 'Member': 'member', 'Viewer': 'viewer'}
        if type(id) is not str or not id or type(values) is not dict or not values or set(values) - {'accessRole', 'expires'}:
            raise InvalidCell('Select an existing team member and edit role or access date.')
        if 'accessRole' in values and values['accessRole'] not in roles:
            raise InvalidCell('Choose Owner, Administrator, Member or Viewer.')
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
            raise InvalidCell('Edit a billing plan or cycle, then review it.')
        me, root = self._account()
        billing = self._billing(me, self._preferences(root))
        if 'cycle' in values and values['cycle'] not in ('Monthly', 'Annual'):
            raise InvalidCell('Choose Monthly or Annual billing.')
        if 'checkout' in values and values['checkout'] is not None:
            raise InvalidCell('Create checkout with Review plan; payment confirmation belongs to billing.')
        if 'requestedPlan' in values:
            plans = billing['plans']
            ids = {x.get('tier') for x in plans} if isinstance(plans, list) else set(plans)
            if {'Personal':'solo','Office':'studio','Team':'firm'}.get(values['requestedPlan'], values['requestedPlan']) not in ids:
                raise InvalidCell('Refresh billing and choose a currently published plan.')
        saved = {**self._preferences(root).get('billing', {}), **values}
        self._save(root, {'billing': saved})
        return self.refreshBilling()

    def prepareCheckout(self):
        me, root = self._account()
        b = self._billing(me, self._preferences(root))
        result = self.cloud('POST', '/v1/billing/checkout', {'tier': {'Personal':'solo','Office':'studio','Team':'firm'}.get(b['requestedPlan'], b['requestedPlan']), 'annual': b['cycle'] == 'Annual'})
        url = result.get('checkout_url') or result.get('url')
        if not url:
            raise InvalidCell('Billing did not return a checkout. Refresh billing and review the published offer.')
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


def cloud_call(method, path, body=None, *, timeout_seconds=15):
    from .cloud_session import cloud_session_path, _pinned_base
    from .cloud_signin import read_cloud_session
    try:
        held = read_cloud_session(cloud_session_path())
    except (OSError, ValueError):
        raise InvalidCell('Not signed in. Sign in with your browser, then retry.') from None
    if not held.get('token'):
        raise InvalidCell('Not signed in. Sign in with your browser, then retry.')
    request = Request(_pinned_base(held) + path, method=method,
                      data=None if body is None else json.dumps(body).encode('utf-8'),
                      headers={'Authorization': 'Bearer ' + held['token'], 'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            result = json.loads(response.read(1024 * 1024))
    except HTTPError as error:
        if error.code == 404 and method == 'GET' and path == '/v1/companies/invites/mine':
            raise CloudRouteUnavailable('Cloud feature unavailable. Update the cloud service and retry.') from None
        raise InvalidCell('Cloud backend refused (HTTP %s). Refresh account status and retry.' % error.code) from None
    except OSError:
        raise InvalidCell('Cloud backend unreachable. Check your connection and retry.') from None
    except ValueError:
        raise InvalidCell('Cloud backend returned an invalid response. Refresh account status and retry.') from None
    if not isinstance(result, dict) or result.get('ok') is False:
        raise InvalidCell('Cloud backend returned an unconfirmed response. Refresh account status before retrying.')
    return result
