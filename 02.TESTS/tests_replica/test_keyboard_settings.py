"""Real Settings route and atomic JSON owner; never a live user profile."""
import os
import sys
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

class KeyboardSettingsTests(unittest.TestCase):
    def test_round_trip_conflicts_reset_and_unbind(self):
        with tempfile.TemporaryDirectory(prefix='archhub-keyboard-') as directory:
            self.profile = Path(directory)
            environment = {name: str(self.profile / name) for name in
                           ('USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA', 'ARCHHUB_TEST_STATE_DIR', 'WORKSHOP_STATE_DIR')}
            for value in environment.values():
                Path(value).mkdir()
            with patch.dict(os.environ, environment):
                from nodelang.nograph_server import JsonFile, Refused, r_settings_action
                from nodelang.settings_owner import keyboard_settings
                store = JsonFile(self.profile / 'settings.json', {'unrelated': 42})
                owner = SimpleNamespace(files={'settings': store, 'companion': None})
                view = {}
                def call(function, args=()):
                    result = r_settings_action(owner, SimpleNamespace(body={
                        'function': function, 'args': list(args),
                        'context': {'settingsDestination': view.get('settingsDestination')}}))['result']
                    if 'settingsDestination' in result:
                        view.update(result)
                    return result

                first = call('readKeybindings')
                assert any(row['id'] == 'menu.copy' and row['value'] == 'Ctrl C' for row in first['keyboardCommands'])
                assert not store.path.exists(), 'reading defaults must not create state'
                with self.assertRaises(Refused) as missing:
                    call('setKeybinding', ['menu.copy', 'Ctrl Shift C'])
                assert missing.exception.code == 'settings_destination_changed'
                assert not store.path.exists(), 'a missing destination must refuse without writes'
                call('readPreferences')  # the UI owner returns the scope and destination to bind
                changed = call('setKeybinding', ['menu.copy', 'Ctrl Shift C'])
                assert changed['keybindings'] == {'menu.copy': 'Ctrl Shift C'}
                assert store.read()['unrelated'] == 42
                reopened = JsonFile(store.path, {})
                assert keyboard_settings(settings=reopened)['keybindings'] == changed['keybindings']
                original = store.path.read_bytes()
                for identity, chord in [('unknown', 'Ctrl J'), ('menu.copy', 'Ctrl Z'), ('menu.copy', 'Alt F4'),
                                        ('menu.copy', 'Ctrl Ctrl C'), ('menu.copy', 'Ctrl W'), ('menu.copy', {'bad': True}), ('menu.copy', 'Ctrl Shift >'), ('menu.copy', '/'), ('menu.copy', 'Ctrl 0'), ('menu.copy', 'Shift !')]:
                    try:
                        call('setKeybinding', [identity, chord])
                    except Refused:
                        pass
                    else:
                        raise AssertionError((identity, chord, 'must refuse'))
                    assert store.path.read_bytes() == original, 'invalid update wrote state'
                reset = call('setKeybinding', ['menu.copy', None])
                assert not reset['keybindings']
                assert next(row for row in reset['keyboardCommands'] if row['id'] == 'menu.copy')['value'] == 'Ctrl C'
                unbound = call('setKeybinding', ['menu.copy', ''])
                assert next(row for row in unbound['keyboardCommands'] if row['id'] == 'menu.copy')['value'] == ''
                assert call('resetKeybindings')['keybindings'] == {}
                store.update({'keybindings': {'retired-command': 'broken'}})
                assert call('resetKeybindings')['keybindings'] == {}, 'reset must recover an invalid old map'
                assert store.read()['unrelated'] == 42
                # Exercise readControls itself; unrelated owners are supplied safe fixture values, never real credentials.
                owner.files['companion'] = JsonFile(self.profile / 'companion.json', {})
                settings_module = sys.modules['nodelang.settings_owner']
                server_module = sys.modules['nodelang.nograph_server']
                for old_keys in ({'retired-command': 'broken'}, ['not-a-map'], {'menu.copy': {'bad': True}}, {'menu.copy': 'Ctrl Z'}):
                    store.update({'keybindings': old_keys, 'appearanceTheme': 'Light'})
                    before_read = store.path.read_bytes()
                    with patch.object(server_module, '_secrets', return_value=[]), patch.object(settings_module, 'read_router_settings', return_value={'providerPreferences': {}}):
                        controls = call('readControls')
                    assert controls['keyboardError']
                    assert controls['keybindings'] == {}
                    assert next(row for row in controls['appearanceSettings'] if row['id'] == 'Appearance.Theme')['value'] == 'Light'
                    assert controls['keyboardCommands'], 'Reset remains reachable with the default keyboard rows'
                    assert store.path.read_bytes() == before_read, 'reading an invalid map must not repair or write silently'
                    assert call('resetKeybindings')['keyboardError'] == ''
                    assert store.read()['appearanceTheme'] == 'Light'

if __name__ == '__main__':
    unittest.main()
