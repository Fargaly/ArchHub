"""The desktop shell for the NOGRAPH server: one window, one tray icon, file pickers.

Called by launcher.py after its single-instance lock and staged-update step.
Nothing runs in the background: no journal, no enrolment, no recovery at boot.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path


def run(state_dir, instance_lock=None, serve_launch_requests=None):
    from .nograph_server import NoGraphServer
    from .pipeline_engines import PIPELINE_ENGINES
    started = time.perf_counter()
    server = NoGraphServer(state_dir, port=int(os.environ.get('ARCHHUB_TEST_HTTP_PORT', '0')),
                           engines=PIPELINE_ENGINES).start()
    print('  nograph    : server up in %.2fs at %s (no graph opened)' % (time.perf_counter() - started, server.public_url), flush=True)
    app_root = Path(__file__).resolve().parents[1]
    restart = {'requested': False, 'quit': None}

    def request_restart():
        # "Update and reload": close the window; after the event loop ends the staged build is armed and relaunched.
        if restart['quit'] is None:
            raise RuntimeError('no desktop window to close')
        restart['requested'] = True
        restart['quit']()
    try:
        from .application_update import ApplicationUpdate
        server.application_update = ApplicationUpdate(Path(state_dir), app_root, request_restart=request_restart,
                                                      report=lambda line: print('  update     : ' + line, flush=True))
    except Exception as refusal:  # noqa: BLE001 - updates say unavailable, the app still opens
        print('  update     : unavailable (%s: %s)' % (type(refusal).__name__, refusal), flush=True)

    def confirm_boot():
        # A build installed by the updater must acknowledge this boot, or the next start restores the old code.
        from .quiet_update import confirm_when_free
        result = confirm_when_free(Path(state_dir), app_root)
        if result.get('confirmed'):
            print('  update     : build %s confirmed after boot' % result.get('build_id'), flush=True)
    def start_baboom():
        try:
            import psutil
            psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        except Exception:  # noqa: BLE001 - priority is a courtesy; BABOOM still starts
            print('  BABOOM     : running at normal priority', flush=True)
        from .baboom_nograph import companion_host, start
        if start(Path(state_dir), Path(__file__).resolve().parents[1], server.public_url) is None:
            return
        try:
            companion['host'] = companion_host()
        except Exception as refused:  # noqa: BLE001 - the Studio stays; the face says why it is missing
            print('  BABOOM     : companion unavailable (%s)' % refused, flush=True)
    companion = {}
    threading.Thread(target=start_baboom, name='archhub-baboom', daemon=True).start()
    if os.environ.get('ARCHHUB_TEST_NO_OPEN'):
        threading.Event().wait()
        return 0
    from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWebEngineCore import QWebEngineProfile
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMenu, QSystemTrayIcon

    app = QApplication(sys.argv)
    app.setApplicationName('ArchHub')
    profile_root = Path(state_dir) / 'web-profile'
    profile_root.mkdir(parents=True, exist_ok=True)
    QWebEngineProfile.defaultProfile().setPersistentStoragePath(str(profile_root))
    icon_path = Path(__file__).resolve().parents[1] / 'archhub.ico'
    icon = QIcon(str(icon_path)) if icon_path.is_file() else QIcon()
    app.setWindowIcon(icon)
    window = QMainWindow()
    window.setWindowTitle('ArchHub')
    view = QWebEngineView(window)
    window.setCentralWidget(view)
    window.resize(1440, 900)
    from .studio_window import lock_studio_navigation
    lock_studio_navigation(view)  # one page in this window: the Studio

    class Asker(QObject):
        ask = pyqtSignal(object)
    asker = Asker()
    asker.ask.connect(lambda job: job())

    def on_gui(work, timeout):
        done, box = threading.Event(), {}
        def job():
            try:
                box['value'] = work()
            finally:
                done.set()
        asker.ask.emit(job)
        return box.get('value') if done.wait(timeout) else None

    server.native_file_picker = lambda title, name_filter='': on_gui(
        lambda: QFileDialog.getOpenFileName(window, title, '', name_filter or 'All files (*.*)')[0], 600) or ''
    server.native_save_file_picker = lambda title, name_filter='': on_gui(
        lambda: QFileDialog.getSaveFileName(window, title, '', name_filter or 'All files (*.*)')[0], 600) or ''
    server.native_folder_picker = lambda title: on_gui(lambda: QFileDialog.getExistingDirectory(window, title, ''), 600) or ''
    if instance_lock is not None and serve_launch_requests is not None:
        class Launch(QObject):
            requested = pyqtSignal(list)
        launch = Launch(app)
        launch.requested.connect(lambda _arguments: (window.showNormal(), window.raise_(), window.activateWindow()))
        threading.Thread(target=serve_launch_requests, args=(instance_lock, launch.requested.emit), daemon=True).start()
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = QSystemTrayIcon(icon, app)
        menu = QMenu()
        menu.addAction('Open ArchHub', lambda: (window.showNormal(), window.activateWindow()))
        menu.addAction('Quit', app.quit)
        tray.setContextMenu(menu)
        tray.show()
    from .window_commands import bind_window_commands
    from .studio_downloads import install_studio_downloads
    window_commands = bind_window_commands(view, window, app.quit, server.public_url)  # Studio window buttons
    downloads = install_studio_downloads(view.page().profile(), view.page(), server.public_url, parent=window,
                                         on_status=lambda status: window.statusBar().showMessage(status['detail']))
    app.aboutToQuit.connect(downloads.close)
    view.load(QUrl(server.public_url + '/studio?bootstrap=' + server.browser_bootstrap_token))

    def land_companion():
        host = companion.get('host')
        if host is None or companion.get('window') is not None:
            return
        try:
            from .baboom_native_runtime import create_baboom_native_projection
            window_ = create_baboom_native_projection(host, position_path=Path(state_dir) / 'baboom-position.json',
                                                      on_stop=host.request_stop)
            window_.show()
            window_.start_projection()
            host.start()
            companion['window'] = window_
            print('  BABOOM     : companion window shown', flush=True)
        except Exception as refused:  # noqa: BLE001 - the Studio stays open without the face
            companion['window'] = refused
            print('  BABOOM     : companion window unavailable (%s)' % refused, flush=True)
        landing.stop()
    landing = QTimer()
    landing.timeout.connect(land_companion)
    landing.start(1000)
    window.show()
    QTimer.singleShot(0, lambda: print('  window     : Studio opened', flush=True))
    view.loadFinished.connect(lambda ok: ok and threading.Thread(target=confirm_boot, name='archhub-update-confirm',
                                                                 daemon=True).start())
    restart['quit'] = app.quit
    code = app.exec()
    del window_commands
    server.close()
    _arm_staged_update(server.application_update, Path(state_dir), app_root, instance_lock, relaunch=restart['requested'])
    return code


def _arm_staged_update(update, state_dir, app_root, instance_lock, *, relaunch):
    """After the last window closed: arm the confirmed (or quit-applied) staged build for the next boot, which
    installs it (launcher.py begin_update_boot / apply_staged); relaunch when the founder asked to reload."""
    if update is None:
        return
    try:
        if relaunch or update.apply_on_quit():
            from .application_update_recovery import arm_update
            from .persistence import application_content_path, application_database_path
            database = application_database_path(state_dir)
            arm_update(state_dir, app_root, database, application_content_path(database), expected_build=update.confirmed_build)
            print('  update     : staged build armed for the next start', flush=True)
            if relaunch:
                import subprocess
                if instance_lock is not None:
                    instance_lock.close()
                subprocess.Popen(['wscript.exe', str(app_root / 'ArchHub.vbs')], close_fds=True,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except Exception as refused:  # noqa: BLE001 - the staged package stays; the next check offers it again
        print('  update     : not armed (%s: %s)' % (type(refused).__name__, refused), flush=True)
    finally:
        update.close()
