"""The Studio's window buttons call the existing Qt window, not another owner."""
import json

from PyQt6.QtCore import QFile, QIODevice, QObject, QTimer, QUrl, pyqtSlot
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEngineScript


class WindowCommands(QObject):
    def __init__(self, view, window, quit_application, origin):
        super().__init__(view.page())
        self.view, self.window, self.quit_application = view, window, quit_application
        self.origin = QUrl(origin)

    @pyqtSlot(str, result="QVariantMap")
    def perform(self, action):
        url = self.view.url()
        if ((url.scheme(), url.host(), url.port()) !=
                (self.origin.scheme(), self.origin.host(), self.origin.port())
                or url.path() not in ("/studio", "/studio/")):
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
        "});});});})();")
    page.scripts().insert(script)
    return commands
