"""The desktop shell for the NOGRAPH server: one window, one tray icon, file pickers.

Called by launcher.py after its single-instance lock and staged-update step.
Nothing runs in the background: no journal, no enrolment, no recovery at boot.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path


def _native_boot_document():
    """The same #studio-boot card, with no script, so the window can paint before the server exists."""
    studio = Path(__file__).resolve().parent / 'studio'
    page = (studio / 'studio.html').read_text(encoding='utf-8')
    card_at = page.index('<div id="studio-boot"')
    card = page[card_at:page.index('<script>', card_at)].strip()
    css = (studio / 'style.css').read_text(encoding='utf-8')
    rules = css[css.index('/* boot-screen */'):css.index('/* boot-end */')]
    return ('<!doctype html><html><head><meta charset="utf-8"><style>'
            'html,body{margin:0;height:100%;background:#0e0e11}' + rules +
            '</style></head><body>' + card + '</body></html>')


def _open_launch(arguments, companion, show_home, show_unavailable):
    """Route both initial and handed-off argv through the existing windows."""
    if '--tray' in arguments:
        return None  # an update relaunch that was in the tray stays there
    if '--baboom' not in arguments:
        show_home()
        return None
    try:
        link = companion.get('link')
        if link is None:
            from .baboom_nograph import reason
            raise RuntimeError(companion.get('error') or reason())
        if companion.get('stopped'):
            raise RuntimeError('BABOOM is stopped for this launch.')
        from .baboom_nograph import shows_as_choice
        if shows_as_choice(link.state_dir) == 'Hidden':
            raise RuntimeError('BABOOM is hidden in Settings.')
        if not link.running():
            raise RuntimeError('BABOOM is starting.')
        link.tell('open')  # its own process opens its box
        return None
    except Exception as refusal:  # noqa: BLE001 - a launch must give a visible result
        detail = 'BABOOM unavailable: %s' % refusal
        show_unavailable(detail)
        return detail


def _open_task(window, view, task_id):
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError('No such Workshop task')
    from .window_commands import show_again
    show_again(window)
    window.raise_()
    window.activateWindow()
    view.page().runJavaScript("window.dispatchEvent(new CustomEvent('archhub:open-task', {detail: "
                              + json.dumps({'task_id': task_id}) + "}))")


def _show_unless_tray(window, arguments, tray_available):
    """Show the Studio window, except for an update relaunch from the tray: that one never takes his screen.

    Returns True when the start stays in the tray.
    """
    in_tray = '--tray' in arguments and tray_available
    if not in_tray:
        window.show()
    return in_tray


def run(state_dir, instance_lock=None, serve_launch_requests=None):
    app_root = Path(__file__).resolve().parents[1]
    from .quiet_update import stage_app_folder, finish_app_folder
    from .session_files import migrate_sessions
    import atexit
    # A crash before health is acknowledged restores the staged entries on next launch.
    stage_app_folder(state_dir)
    atexit.register(finish_app_folder, state_dir, healthy=False)
    migrate_sessions(state_dir)
    restart = {'requested': False, 'quit': None, 'tray': False}
    app = window = view = icon = title_bar = None
    if not os.environ.get('ARCHHUB_TEST_NO_OPEN'):
        # Cold start shows the loading card before the server and pipeline import.
        from PyQt6.QtGui import QColor, QIcon
        from PyQt6.QtWebEngineCore import QWebEngineProfile
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        from PyQt6.QtWidgets import QApplication, QMainWindow
        if os.name == 'nt':
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('ArchHub.ArchHub')
        app = QApplication(sys.argv)
        app.setApplicationName('ArchHub')
        profile_root = Path(state_dir) / 'web-profile'
        profile_root.mkdir(parents=True, exist_ok=True)
        QWebEngineProfile.defaultProfile().setPersistentStoragePath(str(profile_root))
        icon_path = app_root / 'archhub.ico'
        icon = QIcon(str(icon_path)) if icon_path.is_file() else QIcon()
        app.setWindowIcon(icon)
        window = QMainWindow()
        window.setWindowTitle('ArchHub')
        window.setMinimumWidth(900)
        view = QWebEngineView(window)
        window.setCentralWidget(view)
        window.resize(1440, 900)
        from .window_chrome import install_one_title_bar
        title_bar = install_one_title_bar(window, view)
        from .studio_window import lock_studio_navigation
        lock_studio_navigation(view)
        view.page().setBackgroundColor(QColor('#0e0e11'))
        view.setHtml(_native_boot_document())
        from PyQt6.QtWidgets import QSystemTrayIcon
        _show_unless_tray(window, sys.argv[1:], QSystemTrayIcon.isSystemTrayAvailable())
        app.processEvents()
    started = time.perf_counter()

    def boot_server():
        from .nograph_server import NoGraphServer
        from .pipeline_engines import PIPELINE_ENGINES
        return NoGraphServer(state_dir, port=int(os.environ.get('ARCHHUB_TEST_HTTP_PORT', '0')),
                             engines=PIPELINE_ENGINES).start()

    if app is None:
        server = boot_server()
    else:
        box = {}

        def serve():
            try:
                box['server'] = boot_server()
            except Exception as failure:  # noqa: BLE001 - the GUI thread reports the start failure
                box['error'] = failure
        worker = threading.Thread(target=serve, name='archhub-nograph-http-boot', daemon=True)
        worker.start()
        while worker.is_alive():
            app.processEvents()
            worker.join(0.05)
        if 'error' in box:
            raise box['error']
        server = box['server']
    print('  nograph    : server up in %.2fs at %s (no graph opened)' % (time.perf_counter() - started, server.public_url), flush=True)

    def request_restart():
        # "Update and reload": close the window; after the event loop ends the staged build is armed and relaunched.
        if restart['quit'] is None:
            raise RuntimeError('no desktop window to close')
        restart['requested'] = True
        restart['tray'] = window is not None and not window.isVisible()  # an idle install from the tray stays there
        restart['quit']()
    try:
        from .application_update import ApplicationUpdate
        # Restart, Quit-install and idle/tray auto-install all ask this first; live work is never interrupted.
        server.application_update = ApplicationUpdate(Path(state_dir), app_root, request_restart=request_restart,
                                                      report=lambda line: print('  update     : ' + line, flush=True),
                                                      restart_refusal=lambda: _update_refusal(server, state_dir, app_root))
    except Exception as refusal:  # noqa: BLE001 - updates say unavailable, the app still opens
        print('  update     : unavailable (%s: %s)' % (type(refusal).__name__, refusal), flush=True)

    def confirm_boot():
        # A build installed by the updater must acknowledge this boot, or the next start restores the old code.
        from .quiet_update import confirm_when_free
        try:
            healthy = server.health_check()
        except Exception as error:
            healthy = False
            print('  cleanup    : health check failed (%s)' % error, flush=True)
        finish_app_folder(state_dir, healthy=healthy)
        if not healthy:
            print('  cleanup    : staged entries restored', flush=True)
            return
        result = confirm_when_free(Path(state_dir), app_root)
        if result.get('confirmed'):
            print('  update     : build %s confirmed after boot' % result.get('build_id'), flush=True)
    def start_baboom():
        try:
            import psutil
            psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        except Exception:  # noqa: BLE001 - priority is a courtesy; BABOOM still starts
            print('  BABOOM     : running at normal priority', flush=True)
        from .baboom_nograph import start
        if start(Path(state_dir), Path(__file__).resolve().parents[1], server.public_url) is None:
            return
        try:
            # The companion window runs in its own process (founder: "why isn't it running outside the program?"):
            # nothing it draws, reads or waits on can slow or freeze this window. The app keeps the brain.
            from .baboom_companion_process import CompanionLink
            link = CompanionLink(Path(state_dir), Path(__file__).resolve().parents[1], server.public_url,
                                 pin=server.files['companion'])
            if os.environ.get('ARCHHUB_TEST_NO_OPEN'):
                companion['link'] = link
                return
            companion['link'] = link.supervise()  # set last: land_companion binds it once it appears
        except Exception as refused:  # noqa: BLE001 - the Studio stays; the face says why it is missing
            companion['error'] = str(refused)
            print('  BABOOM     : companion unavailable (%s)' % refused, flush=True)
    companion = {}
    threading.Thread(target=start_baboom, name='archhub-baboom', daemon=True).start()
    if os.environ.get('ARCHHUB_TEST_NO_OPEN'):
        confirm_boot()
        threading.Event().wait()
        return 0
    from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
    from PyQt6.QtWidgets import QFileDialog, QMenu
    from .window_commands import show_again

    def show_home():
        show_again(window)  # the tray and a second launch: a maximised window comes back maximised
        window.raise_()
        window.activateWindow()
        view.page().runJavaScript("window.dispatchEvent(new CustomEvent('archhub:open-home'))")

    def show_unavailable(detail):
        show_home()
        window.statusBar().showMessage(detail)

    def ask_baboom(words=''):
        # A click on BABOOM: ArchHub's one composer, pointed at BABOOM, with the caret in it. A line of his menu
        # that the user finishes in his own words (Remember..., Tell an agent...) starts the composer with them.
        if window.isMinimized() or not window.isVisible():
            show_again(window)  # minimised or in the tray: the same restore as the tray's Open ArchHub
        window.raise_()
        window.activateWindow()
        view.setFocus()
        view.page().runJavaScript("window.dispatchEvent(new CustomEvent('archhub:ask-baboom',{detail:{text:%s}}))"
                                  % json.dumps(str(words or '')))

    def open_launch(arguments):
        return _open_launch(arguments, companion, show_home, show_unavailable)

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
    server.native_save_file_picker = lambda title, name_filter='', default_path='': on_gui(
        lambda: QFileDialog.getSaveFileName(window, title, default_path, name_filter or 'All files (*.*)')[0], 600) or ''
    server.native_folder_picker = lambda title: on_gui(lambda: QFileDialog.getExistingDirectory(window, title, ''), 600) or ''
    if instance_lock is not None and serve_launch_requests is not None:
        class Launch(QObject):
            requested = pyqtSignal(list)
        launch = Launch(app)
        launch.requested.connect(open_launch)
        threading.Thread(target=serve_launch_requests, args=(instance_lock, launch.requested.emit), daemon=True).start()
    from .window_commands import CloseToTray, bind_window_commands
    quit_app = app.quit
    if QSystemTrayIcon.isSystemTrayAvailable():
        # Closing the window keeps ArchHub, its server, BABOOM and agent work running in the tray.
        tray = QSystemTrayIcon(icon, app)
        app.setQuitOnLastWindowClosed(False)
        def install_on_close():
            # Never closes here: the next update tick asks the live page for unsaved work first.
            QTimer.singleShot(0, consider_update)
            return False
        stay = CloseToTray(window, tray, app.quit, Path(state_dir) / 'tray-notice-shown', install_on_close)
        quit_app = stay.quit
        open_window = show_home
        menu = QMenu()
        menu.addAction('Open ArchHub', open_window)
        restart_update = {'action': None}

        def show_restart_item():
            update = getattr(server, 'application_update', None)
            ready = False
            if update is not None:
                try:
                    status = update.status()
                    ready = status.get('state') == 'ready' and bool(status.get('available_build'))
                except Exception:
                    ready = False
            action = restart_update['action']
            if ready and action is None:
                def restart():
                    try:
                        update.reload()
                    except Exception as error:
                        print('  update     : restart refused (%s)' % error, flush=True)
                restart_update['action'] = menu.addAction('Restart to update', restart)
            elif action is not None and not ready:
                menu.removeAction(action)
                restart_update['action'] = None

        show_restart_item()
        menu.addAction('Quit ArchHub', quit_app)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: reason == QSystemTrayIcon.ActivationReason.Trigger and open_window())
        tray.show()
    from .studio_downloads import install_studio_downloads
    window_commands = bind_window_commands(view, window, quit_app, server.public_url, title_bar)  # Studio window buttons
    from .baboom_nograph import set_studio_surface
    from .window_commands import CompanionFollows, StudioGone
    StudioGone(window, view.page(), set_studio_surface)  # the pet comes back when the Studio is gone
    downloads = install_studio_downloads(view.page().profile(), view.page(), server.public_url, parent=window,
                                         on_status=lambda status: window.statusBar().showMessage(status['detail']))
    app.aboutToQuit.connect(downloads.close)
    app.aboutToQuit.connect(lambda: companion.get('link') and companion['link'].close())  # the companion process ends with the app
    view.load(QUrl(server.public_url + '/studio?bootstrap=' + server.browser_bootstrap_token))

    def companion_asks(request):
        # A click on BABOOM in its own process: ArchHub's window answers it here, on its GUI thread.
        if request['do'] == 'home':
            asker.ask.emit(show_home)
        elif request['do'] == 'ask':
            asker.ask.emit(lambda: ask_baboom(request.get('words', '')))
        elif request['do'] == 'task':
            asker.ask.emit(lambda: _open_task(window, view, request['task_id']))
        elif request['do'] == 'stopped':
            companion['stopped'] = True

    def land_companion():
        link = companion.get('link')
        if link is None or companion.get('follows') is not None:
            return
        try:
            link.ui = companion_asks
            # BABOOM belongs to ArchHub: beside its composer, wherever the window goes, never left on another screen.
            companion['follows'] = CompanionFollows(window, view, window_commands, link)
            if '--baboom' in sys.argv[1:]:
                open_launch(['--baboom'])
            print('  BABOOM     : companion process started', flush=True)
        except Exception as refused:  # noqa: BLE001 - the Studio stays open without the face
            companion['error'] = str(refused)
            print('  BABOOM     : companion unavailable (%s)' % refused, flush=True)
        landing.stop()
    landing = QTimer()
    landing.timeout.connect(land_companion)
    landing.start(1000)
    in_tray = _show_unless_tray(window, sys.argv[1:], QSystemTrayIcon.isSystemTrayAvailable())
    if '--baboom' in sys.argv[1:]:
        QTimer.singleShot(0, lambda: open_launch(sys.argv[1:]))
    seen_open = {"value": in_tray}
    def consider_update():
        update = server.application_update
        if update is None:
            return
        try:
            if window.isVisible():
                seen_open["value"] = True
            update.check_if_due()
            from .application_update import canvas_job_running
            # Idle installs while the window is open. Closed to the tray installs
            # on the next tick, including a download that was not ready at the close.
            # A build already refused is left alone: no close, no relaunch, until a newer one or Retry.
            if not _auto_install_held(state_dir):
                closing = seen_open["value"] and not window.isVisible()

                def answered(live):
                    # Reconciled with the live Studio right before an automatic close: only a page that answers
                    # "nothing unsaved" lets it go on. No answer (a busy or broken page) holds the install.
                    if _live_page_clean(live):
                        update.install_if_safe(closing=closing, canvas_running=canvas_job_running(server))
                view.page().runJavaScript(
                    "window.__archhubEditState ? window.__archhubEditState() : null", answered)
            if QSystemTrayIcon.isSystemTrayAvailable():
                show_restart_item()
        except Exception as error:  # noqa: BLE001 - a failed check is shown, the window stays
            update.note_failure(error)
    update_pulse = QTimer(app)
    update_pulse.timeout.connect(consider_update)
    update_pulse.start(60_000)
    app._update_pulse = update_pulse
    QTimer.singleShot(0, consider_update)
    QTimer.singleShot(0, lambda: print('  window     : Studio opened', flush=True))
    def warm_provider(ok):
        if not ok or getattr(server, '_provider_warm_started', False):
            return
        server._provider_warm_started = True

        def warm():
            try:
                from .model_router import prewarm_default_provider
                prewarm_default_provider()
            except Exception as failure:
                print('  router     : background provider warm skipped (%s)' % type(failure).__name__, flush=True)
        threading.Thread(target=warm, name='archhub-provider-warm', daemon=True).start()
    view.loadFinished.connect(warm_provider)
    view.loadFinished.connect(lambda ok: threading.Thread(target=confirm_boot if ok else lambda: finish_app_folder(state_dir, healthy=False), name='archhub-update-confirm', daemon=True).start())
    restart['quit'] = quit_app
    code = app.exec()
    del window_commands
    server.close()
    _arm_staged_update(server.application_update, Path(state_dir), app_root, instance_lock, relaunch=restart['requested'],
                       tray=restart['tray'])
    return code


def _update_refusal(server, state_dir=None, app_root=None, *, preflight=None, desktop_pids=None):
    """Why an update must not close the Studio now; None when it may.

    First the NoGraph server's own live work (chat turns, canvas runs, automations). Then whether the
    install would be refused before Setup: then the Studio is never closed, and the refusal is recorded
    so automatic installs leave this build alone until a newer one or the user's own Retry.
    """
    busy = server.busy_reason()
    if busy or state_dir is None:
        return busy
    from .quiet_update import hold_auto_install, preflight_refusal
    if desktop_pids is None:
        import psutil
        me = psutil.Process()
        desktop_pids = {me.pid, *(p.pid for p in me.parents()), *(p.pid for p in me.children(recursive=True))}
    refusal = (preflight or preflight_refusal)(Path(app_root), desktop_pids=desktop_pids)
    if refusal:
        hold_auto_install(Path(state_dir), refusal)
        return "The update would be refused (%s); ArchHub stays open." % refusal
    return None


def _live_page_clean(live):
    """The live Studio's own answer: True only for an explicit 'nothing unsaved'."""
    return isinstance(live, dict) and live.get('unsaved') is False


def _auto_install_held(state_dir):
    """A refused build is not tried again automatically (the minute-by-minute close/reopen loop)."""
    from .quiet_update import auto_install_held
    return auto_install_held(Path(state_dir))


def _apply_staged_after_quit(app_root, *, relaunch=False, tray=False):
    """A hidden helper waits for this process to exit, installs the staged build, and reopens it on Restart."""
    import sys
    python = Path(sys.executable)
    if python.name.lower() == "python.exe":
        windowless = python.with_name("pythonw.exe")
        if windowless.is_file():
            python = windowless
    from .quiet_update import spawn_detached
    spawn_detached([str(python), "-E", "-s", str(Path(app_root) / "nodelang" / "quiet_update.py"),
                    "--apply-staged", str(app_root)] + (["--relaunch"] if relaunch else [])
                   + (["--tray"] if relaunch and tray else []))


def _arm_staged_update(update, state_dir, app_root, instance_lock, *, relaunch, tray=False):
    """After the last window closed: arm the staged build. Restart relaunches into it.
    Quit installs it in a helper that does not open the window."""
    if update is None:
        return
    try:
        if relaunch or (not _auto_install_held(state_dir) and update.apply_on_quit()):
            # Canvas files and settings are not installer payloads; the updater
            # verifies the installer under its existing exclusive lock.
            if instance_lock is not None:
                instance_lock.close()
            _apply_staged_after_quit(app_root, relaunch=relaunch, tray=tray)
    except Exception as refused:  # noqa: BLE001 - the staged package stays; the next check offers it again
        print('  update     : not armed (%s: %s)' % (type(refused).__name__, refused), flush=True)
    finally:
        update.close()
