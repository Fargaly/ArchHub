"""The Studio's window buttons call the existing Qt window, not another owner."""
import json
import logging
import threading

from PyQt6.QtCore import QEvent, QFile, QIODevice, QObject, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEngineScript


class WindowCommands(QObject):
    voiceFinished = pyqtSignal(str, 'QVariantMap')

    def __init__(self, view, window, quit_application, origin, title_bar=None):
        super().__init__(view.page())
        self.view, self.window, self.quit_application, self.title_bar = view, window, quit_application, title_bar
        self.origin = QUrl(origin)
        from .baboom_native_voice import BaboomVoiceInput
        self._voice_input = BaboomVoiceInput()
        self._voice_cancel = threading.Event()
        self._voice_worker = None
        view.page().destroyed.connect(lambda: self._voice_cancel.set())
        view.urlChanged.connect(lambda _url: self._voice_cancel.set())

    def _in_studio(self):
        url = self.view.url()
        return ((url.scheme(), url.host(), url.port()) ==
                (self.origin.scheme(), self.origin.host(), self.origin.port())
                and url.path() in ('/studio', '/studio/'))

    @pyqtSlot(str, result='QVariantMap')
    def startVoice(self, request_id):
        if not self._in_studio():
            return {'ok': False, 'error': 'Voice is available only in the Studio'}
        if not request_id or len(request_id) > 128:
            return {'ok': False, 'error': 'Invalid voice request'}
        if self._voice_worker and self._voice_worker.is_alive():
            return {'ok': False, 'error': 'Finish the current voice capture first'}
        from .baboom_native_voice import BaboomVoiceCancelled, BaboomVoiceError
        cancel = self._voice_cancel = threading.Event()

        def capture():
            try:
                result = {'ok': True, 'text': self._voice_input.capture_once(cancel=cancel)}
            except BaboomVoiceCancelled:
                result = {'ok': True, 'cancelled': True}
            except BaboomVoiceError as exc:
                result = {'ok': False, 'error': str(exc)}
            except Exception:
                result = {'ok': False, 'error': 'Windows speech input failed. Type your sentence and retry.'}
            try:
                self.voiceFinished.emit(request_id, result)
            except RuntimeError:
                logging.getLogger(__name__).debug('Voice receipt discarded after Studio page closed')

        self._voice_worker = threading.Thread(target=capture, name='Studio voice', daemon=True)
        self._voice_worker.start()
        return {'ok': True}

    @pyqtSlot(result='QVariantMap')
    def stopVoice(self):
        if not self._in_studio():
            return {'ok': False, 'error': 'Voice is available only in the Studio'}
        self._voice_cancel.set()
        return {'ok': True}

    @pyqtSlot(str, result="QVariantMap")
    def perform(self, action):
        if not self._in_studio():
            return {"ok": False, "error": "Window controls are available only in the Studio"}
        if action == "hide":
            self.window.hide()
        elif action == "minimize":
            self.window.showMinimized()
        elif action == "maximize":
            self.window.showNormal() if self.window.isMaximized() else self.window.showMaximized()
        elif action == "close":
            QTimer.singleShot(0, self.window.close)  # the same close the native caption button did
        elif action == "open":
            self.window.showNormal()
            self.window.raise_()
            self.window.activateWindow()
        elif action == "quit":
            self._voice_cancel.set()
            # Let WebChannel deliver the receipt before the existing quit path
            # closes the page and flushes the application owner.
            QTimer.singleShot(0, self.quit_application)
        else:
            return {"ok": False, "error": "Unknown window action"}
        return {"ok": True, "action": action, "visible": self.window.isVisible(),
                "minimized": self.window.isMinimized()}

    @pyqtSlot(float, "QVariantList", "QVariantList")
    def titleBar(self, caption, holes, buttons):
        """The Studio header's layout: caption height, interactive boxes, minimize/maximize/close boxes."""
        if self.title_bar is not None and self._in_studio():
            self.title_bar.layout(caption, holes, buttons)


class CloseToTray(QObject):
    """Closing the window (title bar x, Alt+F4, taskbar) hides it to the tray; the app keeps running.

    Only quit() ends the app: the tray's Quit ArchHub and the Studio's Quit call it.
    """

    def __init__(self, window, tray, quit_application, notice_path):
        super().__init__(window)
        self.window, self.tray, self.quit_application, self.notice_path = window, tray, quit_application, notice_path
        self.quitting = False
        window.installEventFilter(self)

    def quit(self):
        self.quitting = True  # Qt 6 quit() closes windows first; a refused close would cancel it
        self.quit_application()

    def eventFilter(self, watched, event):
        if watched is self.window and event.type() == QEvent.Type.Close and not self.quitting:
            event.ignore()
            self.window.hide()
            if not self.notice_path.exists():
                self.notice_path.parent.mkdir(parents=True, exist_ok=True)
                self.notice_path.write_text("shown\n", encoding="utf-8")
                self.tray.showMessage("ArchHub", "ArchHub keeps running in the tray", self.tray.icon(), 5000)
            return True
        return False


def bind_window_commands(view, window, quit_application, origin, title_bar=None):
    page = view.page()
    channel = page.webChannel()
    if channel is None:
        channel = QWebChannel(page)
        page.setWebChannel(channel)
    commands = WindowCommands(view, window, quit_application, origin, title_bar)
    channel.registerObject("desktopWindow", commands)
    resource = QFile(":/qtwebchannel/qwebchannel.js")
    if not resource.open(QIODevice.OpenModeFlag.ReadOnly):
        raise RuntimeError("Qt's native window-control resource is unavailable")
    try:
        library = bytes(resource.readAll()).decode("utf-8")
    finally:
        resource.close()
    script = QWebEngineScript()
    script.setName("ArchHub window controls")
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(False)
    script.setSourceCode(library + "\n(() => {\n"
        "if(location.origin!==" + json.dumps(origin.rstrip("/")) + ")return;\n"
        "new QWebChannel(qt.webChannelTransport, channel => {\n"
        "window.ARCHHUB_WINDOW_ACTION = action => new Promise((resolve,reject) => {\n"
        "channel.objects.desktopWindow.perform(action, result => {\n"
        "if(result.ok)resolve(result);else reject(new Error(result.error));\n"
        "});});\n" + (TITLE_BAR_BRIDGE if title_bar is not None else "") + VOICE_BRIDGE + "\n});})();")
    page.scripts().insert(script)
    return commands


TITLE_BAR_BRIDGE = """
window.ARCHHUB_ONE_TITLE_BAR = true;
(() => {
 // Header controls stay clickable; an open dialog or menu layer takes the whole band.
 const controls = "button,a[href],input,select,textarea,[role=button],[tabindex]:not([tabindex='-1'])", layers = ".overlay,.context-dismiss,.context-menu";
 const box = element => { const r = element.getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; };
 let sent = "", queued = false;
 const report = () => {
  queued = false;
  const header = document.querySelector("[data-window-caption]");
  const caption = header ? header.getBoundingClientRect().bottom : 0;
  const buttons = header ? ["minimize", "maximize", "close"].map(name => header.querySelector("[data-window-button=" + name + "]")) : [];
  const holes = caption ? [...header.querySelectorAll(controls)].filter(e => !buttons.includes(e)).concat([...document.querySelectorAll(layers)]).map(box).filter(b => b[1] < caption) : [];
  const boxes = buttons.map(b => b ? box(b) : []);
  const layout = JSON.stringify([caption, holes, boxes]);
  if (layout !== sent) { sent = layout; channel.objects.desktopWindow.titleBar(caption, holes, boxes); }
 };
 const schedule = () => { if (!queued) { queued = true; requestAnimationFrame(report); } };
 new MutationObserver(schedule).observe(document.documentElement, {subtree: true, childList: true, characterData: true});
 window.addEventListener("resize", schedule);
 schedule();
})();
"""


VOICE_BRIDGE = """
const desktopVoice = channel.objects.desktopWindow, captures = new Map();
desktopVoice.voiceFinished.connect((id, result) => {
 const pending = captures.get(id);
 if (!pending) return;
 captures.delete(id);
 if (result.ok) pending.resolve(result); else pending.reject(new Error(result.error));
});
window.ARCHHUB_VOICE_START = () => new Promise((resolve, reject) => {
 const id = crypto.randomUUID();
 captures.set(id, {resolve, reject});
 desktopVoice.startVoice(id, result => {
  if (!result.ok) { captures.delete(id); reject(new Error(result.error)); }
 });
});
window.ARCHHUB_VOICE_STOP = () => new Promise((resolve, reject) => {
 desktopVoice.stopVoice(result => result.ok ? resolve(result) : reject(new Error(result.error)));
});
window.addEventListener('pagehide', () => desktopVoice.stopVoice(() => {}));
window.dispatchEvent(new Event('archhub:capabilities'));
"""
