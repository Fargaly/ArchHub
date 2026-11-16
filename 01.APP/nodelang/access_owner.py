"""Plan & access device choice, from what this PC can prove; the choice is one Settings row.

Before NOGRAPH the device list was the graph's founder device-custody report
(signed device keys, retired by D-009) and selectDevice refused even then
("no receipt-bound device handoff"). The account is the identity: this PC is the
one device the app can prove, so it is listed and selectable. Other signed-in
devices and sending work to them have no owner yet and answer a visible notice.
"""
import platform

from .social_surface import open_item

THIS_PC = 'this-pc'
DEVICE_NOTICE = open_item('your other signed-in devices',
                          'The ArchHub cloud has no device list for your account yet; this PC is shown.')
FUNCTIONS = ('readDevices', 'selectDevice', 'grantAccess', 'rollBack')


def _devices(settings):
    return {'devices': [{'id': THIS_PC, 'name': platform.node() or 'This PC', 'status': 'This PC · online',
                         'available': True}],
            'activeDevice': settings.read().get('activeDevice', THIS_PC), 'deviceNotice': DEVICE_NOTICE}


def access_action(settings, function, args):
    """settings is the Settings owner's file (settings/settings.json)."""
    if function == 'readDevices':
        return _devices(settings)
    if function == 'selectDevice':
        if len(args) != 1 or type(args[0]) is not str:
            raise ValueError('Choose a listed device.')
        if args[0] != THIS_PC:
            raise ValueError(open_item('sending work to another device', 'Tasks run on this PC in this release.'))
        settings.update({'activeDevice': THIS_PC})
        return {**_devices(settings), 'message': 'Tasks run on this PC.'}
    if function == 'grantAccess':
        raise ValueError(open_item('granting a permission from Plan & access',
                                   'Approve or deny the request on the Approve card where it waits.'))
    if function == 'rollBack':
        raise ValueError(open_item('rolling back to a backup',
                                   'Backups return with Back up now; canvas files keep their own History meanwhile.'))
    raise ValueError('Choose a Plan & access action.')
