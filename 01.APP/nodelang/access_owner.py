"""Plan & access device choice, from what this PC can prove; the choice is one Settings row.

Before NOGRAPH the device list was the graph's founder device-custody report
(signed device keys, retired by D-009) and selectDevice refused even then
("no receipt-bound device handoff"). The account is the identity: the cloud's
GET /v1/devices lists every PC and browser signed in on it, and this PC answers
POST /v1/devices/heartbeat on sign-in and inside the account-session check.
Sending work to another device has no owner yet and answers a visible notice.
"""
import logging
import platform
import re
import threading
from urllib.parse import quote

from .social_surface import open_item

THIS_PC = 'this-pc'
DEVICE_NOTICE = open_item('your other signed-in devices',
                          'The ArchHub cloud has no device list for your account yet; this PC is shown.')
FUNCTIONS = ('readDevices', 'selectDevice', 'signOutDevice', 'grantAccess', 'rollBack')


def _settings_file():
    from .nograph_server import JsonFile
    from .session_files import profile_directory
    return JsonFile(profile_directory() / 'settings/settings.json', {})


def device_id(settings=None):
    """This PC's stable device identity, kept in the Settings file (the same id account sync sends)."""
    settings = settings or _settings_file()
    held = settings.read().get('deviceId')
    if type(held) is str and re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', held):
        return held
    from .account_sync import _device
    settings.update({'deviceId': _device()})
    return settings.read()['deviceId']


def heartbeat(session=None, settings=None):
    """Tell the account this PC is signed in. Best effort, off the caller's thread; never a timer."""
    def send():
        from .settings_owner import cloud_call
        try:
            cloud_call('POST', '/v1/devices/heartbeat',
                       {'device_id': device_id(settings), 'name': (platform.node() or 'This PC')[:120]},
                       session=session)
        except (OSError, ValueError) as refused:
            # The Signed in on row still lists this PC; the next account check says it again.
            logging.getLogger(__name__).warning('This PC could not tell the account it is signed in: %s', refused)
    threading.Thread(target=send, name='device-heartbeat', daemon=True).start()


def _this_pc(settings):
    return {'id': THIS_PC, 'name': platform.node() or 'This PC', 'status': 'This PC · online',
            'available': True, 'current': True}


def _devices(settings, cloud=None):
    from .settings_owner import cloud_call
    rows, notice = [], ''
    try:
        listed = (cloud or cloud_call)('GET', '/v1/devices').get('devices') or []
    except ValueError:
        listed, notice = None, DEVICE_NOTICE
    if listed is not None:
        mine = device_id(settings)
        for row in listed:
            if row.get('signed_out'):
                continue
            if row.get('current') or row.get('device_id') == mine:
                continue  # this PC is listed first, as itself
            rows.append({'id': str(row.get('device_id')), 'name': str(row.get('name') or 'Device'),
                         'status': 'online' if row.get('online') else 'signed in', 'available': False,
                         'current': False})
    return {'devices': [_this_pc(settings), *rows],
            'activeDevice': settings.read().get('activeDevice', THIS_PC), 'deviceNotice': notice}


def access_action(settings, function, args, *, cloud=None):
    """settings is the Settings owner's file (settings/settings.json)."""
    if function == 'readDevices':
        return _devices(settings, cloud)
    if function == 'selectDevice':
        if len(args) != 1 or type(args[0]) is not str:
            raise ValueError('Choose a listed device.')
        if args[0] != THIS_PC:
            raise ValueError(open_item('sending work to another device', 'Tasks run on this PC in this release.'))
        settings.update({'activeDevice': THIS_PC})
        return {**_devices(settings, cloud), 'message': 'Tasks run on this PC.'}
    if function == 'signOutDevice':
        if len(args) != 1 or type(args[0]) is not str or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', args[0]):
            raise ValueError('Choose a listed device.')
        if args[0] == THIS_PC:
            raise ValueError('Use Sign out to sign this PC out.')
        from .settings_owner import cloud_call
        (cloud or cloud_call)('POST', '/v1/devices/%s/sign-out' % quote(args[0], safe=''))
        return {**_devices(settings, cloud), 'message': 'That device is signed out.'}
    if function == 'grantAccess':
        raise ValueError(open_item('granting a permission from Plan & access',
                                   'Approve or deny the request on the Approve card where it waits.'))
    if function == 'rollBack':
        raise ValueError(open_item('rolling back to a backup',
                                   'Backups return with Back up now; canvas files keep their own History meanwhile.'))
    raise ValueError('Choose a Plan & access action.')
