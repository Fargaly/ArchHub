"""The Studio's window buttons call the existing Qt window, not another owner."""
import json
import logging
import threading

from PyQt6.QtCore import QFile, QIODevice, QObject, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEngineScript


class WindowCommands(QObject):
    voiceFinished = pyqtSignal(str, 'QVariantMap')

    def __init__(self, view, window, quit_application, origin):
        super().__init__(view.page())
        self.view, self.window, self.quit_application = view, window, quit_application
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


def bind_window_commands(view, window, quit_application, origin):
    page = view.page()
    channel = page.webChannel()
    if channel is None:
        channel = QWebChannel(page)
        page.setWebChannel(channel)
    commands = WindowCommands(view, window, quit_application, origin)
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
        "});});\n" + VOICE_BRIDGE + "\n});})();")
    page.scripts().insert(script)
    return commands


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
