"""Run real HWND checks on an unshown Windows desktop; never SwitchDesktop."""
import ctypes
from dataclasses import replace
from ctypes import wintypes as w
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / '05.EVIDENCE/presence1'


def idle_or_away():
    """The effect is away from the founder only on a non-input test desktop."""
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetThreadDesktop.restype = w.HANDLE
    user.OpenInputDesktop.restype = w.HANDLE
    current = user.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
    input_desktop = user.OpenInputDesktop(0, False, 1)
    if not input_desktop:
        return False
    def desktop_name(handle):
        value = ctypes.create_unicode_buffer(256)
        needed = w.DWORD()
        user.GetUserObjectInformationW.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
        if not user.GetUserObjectInformationW(handle, 2, value, ctypes.sizeof(value), ctypes.byref(needed)):
            return ''
        return value.value
    try:
        name = desktop_name(current)
        input_name = desktop_name(input_desktop)
        return bool(name and input_name and name.startswith('ArchHubPresence1_') and name != input_name)
    finally:
        user.CloseDesktop.argtypes = [w.HANDLE]
        user.CloseDesktop(input_desktop)


def launch():
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user.CreateDesktopW.restype = w.HANDLE
    user.CreateDesktopW.argtypes = [w.LPCWSTR, w.LPCWSTR, ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.c_void_p]
    name = 'ArchHubPresence1_' + str(os.getpid())
    desktop = user.CreateDesktopW(name, None, None, 0, 0x10000000, None)
    if not desktop:
        raise ctypes.WinError(ctypes.get_last_error())

    class Startup(ctypes.Structure):
        _fields_ = [('cb',w.DWORD),('reserved',w.LPWSTR),('desktop',w.LPWSTR),('title',w.LPWSTR),
            ('x',w.DWORD),('y',w.DWORD),('xs',w.DWORD),('ys',w.DWORD),('xc',w.DWORD),('yc',w.DWORD),
            ('fill',w.DWORD),('flags',w.DWORD),('show',w.WORD),('cb2',w.WORD),('res2',ctypes.c_void_p),
            ('stdin',w.HANDLE),('stdout',w.HANDLE),('stderr',w.HANDLE)]

    class Process(ctypes.Structure):
        _fields_ = [('process',w.HANDLE),('thread',w.HANDLE),('pid',w.DWORD),('tid',w.DWORD)]

    startup = Startup()
    startup.cb = ctypes.sizeof(startup)
    startup.desktop = name
    startup.flags = 1
    startup.show = 0
    process = Process()
    command = ctypes.create_unicode_buffer(subprocess.list2cmdline([sys.executable, str(Path(__file__)), '--worker', name]))
    try:
        if not kernel.CreateProcessW(None, command, None, None, False, 0x08000000,
                                     None, str(ROOT), ctypes.byref(startup), ctypes.byref(process)):
            raise ctypes.WinError(ctypes.get_last_error())
        kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        code = kernel.WaitForSingleObject(process.process, 45000)
        if code == 258:
            raise RuntimeError('private desktop probe exceeded 45 seconds')
        exit_code = w.DWORD()
        kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        assert kernel.GetExitCodeProcess(process.process, ctypes.byref(exit_code))
        result = json.loads((OUTPUT / 'native-result.json').read_text())
        assert result.get('desktop') == name, 'result belongs to another private desktop run'
        assert exit_code.value == 0, result
        print(json.dumps(result, indent=2))
        return 0 if result.get('ok') else 1
    finally:
        kernel.CloseHandle.argtypes = [w.HANDLE]
        if process.thread:
            kernel.CloseHandle(process.thread)
        if process.process:
            kernel.CloseHandle(process.process)
        user.CloseDesktop.argtypes = [w.HANDLE]
        user.CloseDesktop(desktop)


def worker():
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    if not idle_or_away():
        raise RuntimeError('probe requires a non-input private test desktop')
    os.environ['QT_QPA_PLATFORM'] = 'windows'
    for key in ('APPDATA','LOCALAPPDATA','TEMP','TMP'):
        folder = ROOT / 'node_modules/.cache/presence1-native-profiles' / sys.argv[2] / key
        folder.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(folder)
    from PyQt6.QtGui import QPainter, QCursor
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QLabel
    import nodelang.baboom_native_companion as module
    from nodelang.baboom_companion_placement import Rect
    from nodelang.baboom_native_host import BaboomNativeHost
    from nodelang.baboom_native_runtime import default_baboom_sprite_atlas_path
    from nodelang.baboom_visual_assets import BaboomSpriteAtlas
    from tests_replica.test_baboom_native_companion import _Transport

    app = QApplication([])
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetThreadDesktop.restype = w.HANDLE
    desktop = user.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
    name = ctypes.create_unicode_buffer(256)
    needed = w.DWORD()
    user.GetUserObjectInformationW.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    assert user.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed))
    assert name.value.startswith('ArchHubPresence1_'), name.value
    output = {'desktop': name.value, 'platform': app.platformName(), 'founder_desktop_accessed': False,
              'source_sha256': hashlib.sha256((ROOT / '01.APP/nodelang/baboom_native_companion.py').read_bytes()).hexdigest()}
    screen = Rect(0, 0, 1280, 800)
    occupied = []
    mode = ['Tray']
    opened = []
    cursor = [QPoint(-10000, -10000)]
    QCursor.pos = staticmethod(lambda: cursor[0])

    class Transport(_Transport):
        def baboom_native_frame(self, **kwargs):
            frame = super().baboom_native_frame(**kwargs)
            frame['context']['shows_as'] = mode[0]
            return frame

    atlas = BaboomSpriteAtlas(path=default_baboom_sprite_atlas_path(), width=1536,
        height=2288, columns=8, rows=11, cell_width=192, cell_height=208)
    module.desktop_input_idle_seconds = lambda: 10.0
    module.foreign_foreground_window = lambda: False
    transport = Transport()
    host = BaboomNativeHost(transport, external_session_id='presence1-private-desktop',
        device_credential_provider=lambda challenge: {'proof':'test'})
    host.connect()

    def create(owner):
        controller = owner.BaboomNativeCompanionController(host, atlas, occupied_provider=lambda: occupied)
        widget = owner.create_baboom_native_companion_window(controller, on_open=lambda: opened.append(True))
        widget._screen_rect = lambda: screen
        widget.start_projection()
        app.processEvents()
        return widget

    foreground = QLabel('Synthetic work window\nSession list and work content')
    foreground.setStyleSheet('background:#20242a;color:white;font-size:22px;padding:20px')
    foreground.setGeometry(0, 0, 1280, 800)
    foreground.show()
    app.processEvents()

    def capture(widget, filename):
        # Compose captures of our own widgets only. No QScreen/desktop grabs.
        image = foreground.grab().toImage()
        if widget.isVisible():
            painter = QPainter(image)
            painter.drawPixmap(widget.x(), widget.y(), widget.grab())
            painter.end()
        assert image.save(str(OUTPUT / filename))

    canonical = r'C:\Users\fargaly\00.ARCHUB\10.PRODUCT\11.ARCHHUB-APP'
    baseline = subprocess.check_output(['git','-C',canonical,'show','b7fc5330:01.APP/nodelang/baboom_native_companion.py'], text=True, encoding='utf-8')
    output['base_source_sha256'] = hashlib.sha256(baseline.encode('utf-8')).hexdigest()
    baseline_folder = ROOT / 'tmp-base'
    baseline_folder.mkdir(exist_ok=False)
    baseline_path = baseline_folder / 'baboom_native_companion.py'
    baseline_path.write_text(baseline, encoding='utf-8')
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location('nodelang.presence1_baseline', baseline_path)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    before = create(old)
    output['before_visible'] = before.isVisible()
    capture(before, 'native-before-fresh.png')
    host.connection_state = 'closed'
    before.refresh()
    output['before_closed_open_button'] = before._open.isVisible()
    capture(before, 'native-before-closed.png')
    saved_snapshot = host.latest_snapshot
    host._latest = replace(saved_snapshot, frame_expires_at=time.time() - 601)
    host.connection_state = 'reconnecting'
    before.refresh()
    output['before_long_reconnect_panel'] = before._report.isVisible()
    capture(before, 'native-before-reconnect.png')
    assert output['before_visible'] and output['before_closed_open_button'] and output['before_long_reconnect_panel']
    host._latest = saved_snapshot
    host.connection_state = 'live'
    before.stop_projection()
    before.close()
    baseline_path.unlink()
    baseline_folder.rmdir()
    window = create(module)
    try:
        output['fresh_visible'] = window.isVisible()
        capture(window, 'native-after-fresh.png')
        assert not window.isVisible()
        for state in ('reconnecting','closed','live'):
            host.connection_state = state
            window.refresh()
            assert not window.isVisible()
        output['reconnect_windows'] = 0
        capture(window, 'native-after-reconnect.png')
        host.connection_state = 'live'
        mode[0] = 'Screen'
        host.poll()
        window.refresh()
        app.processEvents()
        hwnd = int(window.winId())
        style = user.GetWindowLongW(ctypes.c_void_p(hwnd), -20)
        output.update(hwnd=hwnd, ex_style=style, ws_ex_transparent=bool(style & 0x20),
                      bounds=[window.x(),window.y(),window.width(),window.height()])
        assert user.IsWindow(ctypes.c_void_p(hwnd))
        assert style & 0x20, 'real HWND lacks WS_EX_TRANSPARENT'
        assert window.width() <= 56 and window.height() <= 56
        capture(window, 'native-screen.png')
        # Real window bounds from this isolated synthetic window are fed through
        # the same foreground provider; no SendInput reaches the input desktop.
        token = str(os.getpid())
        child = subprocess.Popen([sys.executable, str(Path(__file__)), '--foreground', token], creationflags=0x08000000)
        try:
            record = OUTPUT / ('foreground-' + token + '.json')
            deadline = time.monotonic() + 10
            while not record.exists() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
            foreign = json.loads(record.read_text())
            assert foreign['token'] == token and foreign['pid'] != os.getpid()
            class GuiThread(ctypes.Structure):
                _fields_ = [('size',w.DWORD),('flags',w.DWORD),('active',w.HWND),('focus',w.HWND),
                    ('capture',w.HWND),('menu',w.HWND),('move',w.HWND),('caret',w.HWND),('rect',w.RECT)]
            gui = GuiThread()
            gui.size = ctypes.sizeof(gui)
            assert user.GetGUIThreadInfo(foreign['thread'], ctypes.byref(gui))
            output['foreign_hwnd'] = foreign['hwnd']
            output['foreign_pid'] = foreign['pid']
            output['foreign_active_hwnd'] = gui.active
            output['foreground_adapter'] = 'private-desktop foreign GUI thread; synthetic input age/cursor; no founder screen use'
            assert gui.active == foreign['hwnd'], 'synthetic worker has no active window'
            owner_pid = w.DWORD()
            owner_thread = user.GetWindowThreadProcessId(ctypes.c_void_p(foreign['hwnd']), ctypes.byref(owner_pid))
            assert owner_pid.value == foreign['pid'] and owner_thread == foreign['thread']
            output['foreign_hwnd_owner_verified'] = True
            bounds = w.RECT()
            assert user.GetWindowRect(ctypes.c_void_p(foreign['hwnd']), ctypes.byref(bounds))
            assert user.IsZoomed(ctypes.c_void_p(foreign["hwnd"])), "foreign window must be maximized"
            output["foreign_maximized"] = True
            occupied.append(Rect(bounds.left,bounds.top,bounds.right-bounds.left,bounds.bottom-bounds.top))
            module.desktop_input_idle_seconds = lambda: 0.0
            module.foreign_foreground_window = lambda: gui.active == foreign['hwnd']
            start = time.monotonic()
            while window.isVisible() and time.monotonic() - start < 2:
                app.processEvents()
                time.sleep(.01)
            output['overlap_hide'] = {'observed': time.monotonic() - start, 'unit': 's'}
            assert not window.isVisible() and output['overlap_hide']['observed'] < 2
            # Round2 comparison uses only one archived source file and our own widgets.
            baseline_folder.mkdir(exist_ok=False)
            round2_source = subprocess.check_output(['git','show','b4900593:01.APP/nodelang/baboom_native_companion.py'])
            baseline_path.write_bytes(round2_source)
            spec = importlib.util.spec_from_file_location('nodelang.presence1_r2_baseline', baseline_path)
            round2 = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(round2)
            round2.desktop_input_idle_seconds = lambda: 10.0
            round2.foreign_foreground_window = lambda: True
            previous = create(round2)
            output['round2_before_maximized_idle_visible'] = previous.isVisible()
            capture(previous, 'r2-before-maximized-idle.png')
            assert not previous.isVisible()
            previous.stop_projection()
            previous.close()
            baseline_path.unlink()
            baseline_folder.rmdir()
            module.desktop_input_idle_seconds = lambda: 2.1
            start = time.monotonic()
            while not window.isVisible() and time.monotonic() - start < 2:
                app.processEvents()
                time.sleep(.01)
            output['round2_maximized_idle_return'] = {'observed': time.monotonic() - start, 'unit': 's'}
            assert window.isVisible() and output['round2_maximized_idle_return']['observed'] < 2
            capture(window, 'r2-after-maximized-idle.png')
            module.desktop_input_idle_seconds = lambda: 0.0
            for point in (QPoint(window.x() - 16, window.geometry().center().y()), window.geometry().center()):
                cursor[0] = point
                deadline = time.monotonic() + .9
                while time.monotonic() < deadline:
                    app.processEvents()
                    assert window.isVisible(), 'approach/hover must not hide the sprite'
                    time.sleep(.01)
            deadline = time.monotonic() + .9
            while time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
            style = user.GetWindowLongW(ctypes.c_void_p(int(window.winId())), -20)
            assert not style & 0x20, 'hover must release native click-through'
            QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=window.rect().center())
            assert opened == [True], opened
            output['round2_approach_hover_visible'] = True
            output['round2_hover_ex_style'] = style
            output['round2_sprite_click_opened'] = len(opened)
        finally:
            child.wait(timeout=25)
        output['ok'] = True
    finally:
        window.stop_projection()
        window.close()
        foreground.close()
        host.stop(timeout_seconds=.01)
    return output


if __name__ == '__main__':
    if '--foreground' in sys.argv:
        if not idle_or_away():
            raise RuntimeError('foreground probe refused before creating any widget')
        os.environ['QT_QPA_PLATFORM'] = 'windows'
        from PyQt6.QtWidgets import QApplication, QLabel
        from PyQt6.QtCore import QTimer
        app = QApplication([])
        widget = QLabel('Synthetic foreign-process work')
        widget.setGeometry(0,0,1280,800)
        if idle_or_away():
            widget.showMaximized()
            widget.activateWindow()
            app.processEvents()
            ctypes.windll.user32.SetForegroundWindow(ctypes.c_void_p(int(widget.winId())))
            ctypes.windll.user32.SetActiveWindow(ctypes.c_void_p(int(widget.winId())))
        else:
            raise RuntimeError('foreground effect refused on an input or non-test desktop')
        (OUTPUT / ('foreground-' + sys.argv[-1] + '.json')).write_text(json.dumps({'pid':os.getpid(), 'token':sys.argv[-1], 'hwnd':int(widget.winId()), 'thread':ctypes.windll.kernel32.GetCurrentThreadId()}))
        QTimer.singleShot(20000, app.quit)
        sys.exit(app.exec())
    elif '--worker' in sys.argv:
        try:
            result = worker()
        except Exception:
            import traceback
            result = {'ok':False,'desktop':sys.argv[-1],'error':traceback.format_exc()}
        (OUTPUT / 'native-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        sys.exit(0 if result.get('ok') else 1)
    sys.exit(launch())
