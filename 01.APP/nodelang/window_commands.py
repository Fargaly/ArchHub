"""The Studio's window buttons call the existing Qt window, not another owner."""
import json
import logging
import math
import threading

from PyQt6.QtCore import QEvent, QFile, QIODevice, QObject, QPoint, Qt, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEngineScript


def show_again(window):
    """Bring the window back from the tray or the taskbar as the user left it: a maximised window stays maximised."""
    if window.isMinimized():
        window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
    window.show()


class WindowCommands(QObject):
    voiceFinished = pyqtSignal(str, 'QVariantMap')
    companionHomeChanged = pyqtSignal()

    def __init__(self, view, window, quit_application, origin, title_bar=None, *, require_access=None):
        super().__init__(view.page())
        self.view, self.window, self.quit_application, self.title_bar = view, window, quit_application, title_bar
        self.origin = QUrl(origin)
        self.require_access = require_access
        self.companion_home = (None, [])  # the composer box and the busy boxes above it, as the page last reported
        self.companion_sees = (0, False)  # Home's count of what needs the user, and BABOOM's panel open, likewise
        self.companion_step = None        # active running step progress, surface, DND/moments and work area, when reported
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
            from .cloud_session import DesktopAccessRefused
            try:
                if self.require_access is not None:
                    self.require_access()
                result = {'ok': True, 'text': self._voice_input.capture_once(cancel=cancel)}
            except DesktopAccessRefused as refused:
                result = {'ok': False, 'code': refused.code, 'state': refused.state, 'error': str(refused)}
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
            show_again(self.window)
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

    @pyqtSlot("QVariantList", "QVariantList")
    def companionHome(self, composer, busy):
        """Where BABOOM stands: the Studio's composer box, and the controls and text just above its right end."""
        if self._in_studio():
            self.companion_home = (_page_box(composer), [box for box in map(_page_box, busy[:64]) if box])
            self.companionHomeChanged.emit()

    @pyqtSlot(int, bool)
    def companionSees(self, needs, listening):
        """What BABOOM draws from the page: Home's own count of what needs the user, and whether his panel is open."""
        if self._in_studio():
            self.companion_sees = (needs, listening)
            self.companionHomeChanged.emit()

    @pyqtSlot("QVariantMap")
    def companionStep(self, detail):
        """Active step progress, surface/task identity, work area and DND/moments from Studio."""
        if not self._in_studio() or not isinstance(detail, dict):
            return
        running = detail.get("running")
        active_run = None
        if isinstance(running, dict) and running.get("step"):
            raw_prog = running.get("progress")
            prog = float(raw_prog) if isinstance(raw_prog, (int, float)) and math.isfinite(raw_prog) else 0.0
            active_run = {
                "session": str(running.get("session") or "ArchHub")[:120],
                "step": str(running.get("step") or "")[:120],
                "progress": max(0.0, min(1.0, prog)),
            }
        self.companion_step = {
            "work_area": _page_box(detail.get("workArea")),
            "surface": str(detail.get("surface") or "")[:64],
            "task": str(detail.get("task") or "")[:128],
            "dnd": detail.get("dnd") is True,
            "moments": detail.get("moments") is not False,
            "reduced_motion": detail.get("reduceMotion") is True,
            "composer_listening": detail.get("composerListening") is True,
            "tutorial_done": str(detail.get("tutorialDone") or "")[:128],
            "running": active_run,
        }
        self.companionHomeChanged.emit()


def _page_box(values):
    """One page rectangle (left, top, width, height) the page reported, or None when it is not one."""
    if (type(values) is not list or len(values) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 100000 for v in values)
            or values[2] <= 0 or values[3] <= 0):
        return None
    return tuple(values)


class CompanionFollows(QObject):
    """BABOOM stands with the ArchHub window: the companion is told where the window and its composer are.

    Told again on every move, resize, show, hide, minimise and monitor change, and whenever the page reports
    a new composer box, so the companion is never left on another screen or away from the window. With the
    window minimised or in the tray it is told so, and stays on the desktop (F277).
    """

    def __init__(self, window, view, commands, companion):
        super().__init__(window)
        self.window, self.view, self.commands, self.companion = window, view, commands, companion
        window.installEventFilter(self)
        commands.companionHomeChanged.connect(self.tell)
        QGuiApplication.instance().screenRemoved.connect(self.tell)
        self.tell()

    def tell(self, *_changed):
        from .baboom_companion_placement import Rect
        window = self.window
        desk = lambda area: Rect(area.x(), area.y(), area.width(), area.height())
        screens = [desk(screen.availableGeometry()) for screen in QGuiApplication.screens()]
        if not window.isVisible() or window.isMinimized():
            self.companion.follow_app(None, None, (), screens)
            return
        origin, zoom = self.view.mapToGlobal(QPoint(0, 0)), self.view.zoomFactor() or 1.0
        placed = lambda box: Rect(origin.x() + round(box[0] * zoom), origin.y() + round(box[1] * zoom),
                                  max(1, round(box[2] * zoom)), max(1, round(box[3] * zoom)))
        composer, busy = self.commands.companion_home
        if self.commands.companion_step is None:
            self.companion.follow_app(desk(window.geometry()), placed(composer) if composer else None,
                                      [placed(box) for box in busy], screens, *self.commands.companion_sees)
            return
        step = dict(self.commands.companion_step)
        if step.get("work_area"):
            step["work_area"] = placed(step["work_area"])
        self.companion.follow_app(desk(window.geometry()), placed(composer) if composer else None,
                                  [placed(box) for box in busy], screens, *self.commands.companion_sees, step)

    def eventFilter(self, watched, event):
        # WindowActivate: a click into ArchHub brings BABOOM, which no ArchHub window owns, back above it too.
        if watched is self.window and event.type() in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show,
                                                       QEvent.Type.Hide, QEvent.Type.WindowStateChange,
                                                       QEvent.Type.WindowActivate):
            self.tell()
        elif watched is self.window and event.type() == QEvent.Type.WinIdChange and self.companion.isVisible():
            self.companion._disown()  # Qt rebuilt the ArchHub window: BABOOM belongs to the new one
        return False


class StudioGone(QObject):
    """The window hidden to the tray, minimised or closed, or its renderer dead: the Studio shows no screen.

    The shell tells the surface owner directly, so the companion never waits on a page that cannot speak.
    """

    def __init__(self, window, page, clear):
        super().__init__(window)
        self.window, self.clear = window, clear
        window.installEventFilter(self)
        page.renderProcessTerminated.connect(lambda *_: self.clear(''))

    def eventFilter(self, watched, event):
        kind = event.type()
        if watched is self.window and (kind in (QEvent.Type.Hide, QEvent.Type.Close)
                                       or (kind == QEvent.Type.WindowStateChange and self.window.isMinimized())):
            self.clear('')
        return False


class CloseToTray(QObject):
    """Closing the window (title bar x, Alt+F4, taskbar) hides it to the tray; the app keeps running.

    Only quit() ends the app: the tray's Quit ArchHub and the Studio's Quit call it.
    """

    def __init__(self, window, tray, quit_application, notice_path, on_close=None):
        super().__init__(window)
        self.window, self.tray, self.quit_application, self.notice_path = window, tray, quit_application, notice_path
        self.on_close = on_close
        self.quitting = False
        window.installEventFilter(self)

    def quit(self):
        self.quitting = True  # Qt 6 quit() closes windows first; a refused close would cancel it
        self.quit_application()

    def eventFilter(self, watched, event):
        if watched is self.window and event.type() == QEvent.Type.Close and not self.quitting:
            event.ignore()
            if callable(self.on_close) and self.on_close():
                return True
            self.window.hide()
            if not self.notice_path.exists():
                self.notice_path.parent.mkdir(parents=True, exist_ok=True)
                self.notice_path.write_text("shown\n", encoding="utf-8")
                self.tray.showMessage("ArchHub", "ArchHub keeps running in the tray", self.tray.icon(), 5000)
            return True
        return False


def bind_window_commands(view, window, quit_application, origin, title_bar=None, *, require_access=None):
    page = view.page()
    channel = page.webChannel()
    if channel is None:
        channel = QWebChannel(page)
        page.setWebChannel(channel)
    commands = WindowCommands(view, window, quit_application, origin, title_bar, require_access=require_access)
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
        "});});\n" + (TITLE_BAR_BRIDGE if title_bar is not None else "") + COMPANION_BRIDGE + VOICE_BRIDGE + "\n});})();")
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


COMPANION_BRIDGE = """
(() => {
 // BABOOM stands above the right end of the composer, or bottom right on a page with none. Report that box and
 // every control and line of text in the candidate patches (bottom-right + offsets and bottom-left fallback);
 // place_baboom_beside_composer picks the spot.
 const controls = "button,a[href],input,select,textarea,label,.node,.srow,.prow,.hsnode,.sw,[role=button],[role=switch],.scard,.scb,.insp-card,.card,[tabindex]:not([tabindex='-1'])";
 const box = r => [r.left, r.top, r.width, r.height];
 let sent = "", queued = false, seen = [], needs = 0, told = "", stepSent = "", subscribed = false;
 const workAreaEl = () => {
  const screen = document.querySelector("[data-screen]")?.getAttribute("data-screen") || "";
  if (screen === "canvas" || screen === "task-file") {
   return document.querySelector(".v22g-canvas:not([hidden]), .dock.left:not(.empty):not(.col), .dcenter") || document.querySelector(".screen-with-composer");
  }
  if (screen === "home") return document.querySelector(".home-map-stage, .dx-home") || document.querySelector(".screen-with-composer");
  return document.querySelector(".screen-with-composer") || document.documentElement;
 };
 const scanPatch = (busy, composer, x0, x1, y0, y1) => {
  for (let x = Math.max(0, x0); x < Math.min(innerWidth, x1); x += 20)
   for (let y = Math.max(0, y0); y < Math.min(innerHeight, y1); y += 24)
    for (const e of document.elementsFromPoint(x, y)) {
     if (e.closest && e.closest(".pet-bubble,.bbm-panel,.bbm-bubble")) continue;
     const hit = e.closest(controls) || (e.childElementCount === 0 && e.textContent.trim() ? e : null);
     if (hit && !(composer && composer.contains(hit))) busy.add(hit);
    }
 };
 const report = () => {
  queued = false;
  if (!subscribed && window.ArchHubAPI?.subscribe) {
   subscribed = true;
   window.ArchHubAPI.subscribe(see);
  }
  see();
  const composer = [...document.querySelectorAll("[data-design='composer.surface']")].filter(e => e.offsetParent).pop();
  const area = workAreaEl(), ar = area ? area.getBoundingClientRect() : null;
  const c = composer ? composer.getBoundingClientRect() : null, busy = new Set();
  const right = Math.min(c ? c.right : (ar ? ar.right : innerWidth), innerWidth - 16);
  const floor = c ? c.top - 4 : (ar ? ar.bottom - 16 : innerHeight - 16);
  const left = ar ? ar.left + 16 : 16;
  scanPatch(busy, composer, right - 136, right, floor - 140, floor);
  scanPatch(busy, composer, left, left + 104, floor - 140, floor);
  if (c && ar && ar.bottom - 16 > floor + 16) {
   scanPatch(busy, composer, right - 136, right, ar.bottom - 156, ar.bottom - 16);
   scanPatch(busy, composer, left, left + 104, ar.bottom - 156, ar.bottom - 16);
  }
  const layout = [c ? box(c) : [], [...busy].slice(0, 64).map(e => box(e.getBoundingClientRect()))];
  const text = JSON.stringify(layout);
  if (text !== sent) { sent = text; channel.objects.desktopWindow.companionHome(layout[0], layout[1]); }
 };
 const activeRunOf = data => {
  if (!data) return null;
  const nodes = (data.graph?.nodes || []).filter(n => !n.fixed);
  const runNode = nodes.find(n => /^running$/i.test(n.status || ""));
  if (runNode) {
   const done = nodes.filter(n => /^done$/i.test(n.status || "")).length;
   const prog = typeof runNode.progress === "number" ? runNode.progress : (nodes.length ? Math.max(0.08, (done + 0.5) / nodes.length) : 0.5);
   const taskRow = (data.tasks || []).find(t => t.sessionOpen || t.id === data.desktopView?.task);
   return {session: taskRow?.title || data.graph?.name || "Workflow", step: runNode.title || runNode.id, progress: prog};
  }
  const streamStep = (data.composerAnswer?.steps || []).find(s => /^running$/i.test(s.status || ""));
  if (streamStep) {
   const all = data.composerAnswer.steps || [], done = all.filter(s => /^(ok|completed|succeeded|success)$/i.test(s.status || "")).length;
   const prog = typeof streamStep.progress === "number" ? streamStep.progress : (all.length ? Math.max(0.1, (done + 0.5) / all.length) : 0.5);
   return {session: data.composerAnswer.provider || "BABOOM", step: streamStep.title || streamStep.tool || "Working", progress: prog};
  }
  for (const t of data.tasks || []) {
   const act = (t.activity || []).find(r => /^running$/i.test(r.status || ""));
   if (act) {
    const wf = t.workflow || [], stepTitle = wf.find(w => w.id === act.id)?.title || act.title || act.id || "Step";
    const done = (t.activity || []).filter(r => /^done$/i.test(r.status || "")).length;
    const total = Math.max(wf.length, (t.activity || []).length, 1);
    const prog = typeof act.progress === "number" ? act.progress : Math.max(0.08, (done + 0.5) / total);
    return {session: t.title || "Task", step: stepTitle, progress: prog};
   }
  }
  return null;
 };
 // His badge is Home's own count of what needs the user (counted again only when the data changes), and his
 // ground glows cyan while his panel is open.
 const see = () => {
  const data = window.ArchHubAPI && window.ArchHubAPI.getSnapshot ? window.ArchHubAPI.getSnapshot() : null;
  const rows = window.UI && window.UI.homeRows;
  const inputs = data && [data.tasks, data.approvals, data.graphs, data.agentGraph?.sessions, data.homeLayout];
  if (rows && inputs && inputs.some((value, index) => value !== seen[index])) {
   const {sessionRows, sectionOf} = rows(data, data.homeLayout);
   needs = sessionRows.filter(row => sectionOf(row) === "Needs you").length;
   seen = inputs;
  }
  const open = !!document.querySelector("[aria-label='BABOOM companion']"), now = needs + "/" + open;
  if (now !== told) { told = now; channel.objects.desktopWindow.companionSees(needs, open); }
  if (channel.objects.desktopWindow.companionStep) {
   const area = workAreaEl(), ar = area ? area.getBoundingClientRect() : null;
   const surface = document.querySelector(".settings-sheet") ? "settings" : (document.querySelector("[data-screen]")?.getAttribute("data-screen") || data?.desktopView?.route || "");
   const settings = data?.settings || [];
   const dnd = data?.companion?.dnd === true || settings.find(r => /do not disturb/i.test(r.id || r.label || ""))?.value === true;
   const momentsRow = settings.find(r => /moments/i.test(r.id || r.label || ""));
   const moments = momentsRow ? momentsRow.value !== false : data?.companion?.moments !== false;
   const active = document.activeElement;
   const rec = active?.closest?.("[data-design='composer.surface']")?.querySelector?.(".recipient-name")?.textContent?.trim();
   const composerListening = !!active?.matches?.("[data-design='composer.msg']") && (!rec || rec === "@BABOOM");
   const detail = {
    workArea: ar && ar.width > 0 && ar.height > 0 ? box(ar) : [],
    surface,
    task: String(data?.desktopView?.task || ""),
    dnd,
    moments,
    reduceMotion: document.documentElement.dataset.reducedMotion === "true",
    composerListening,
    tutorialDone: String(document.documentElement.dataset.baboomTutorialDone || ""),
    running: activeRunOf(data),
   };
   const stepText = JSON.stringify(detail);
   if (stepText !== stepSent) { stepSent = stepText; channel.objects.desktopWindow.companionStep(detail); }
  }
 };
 const schedule = () => { if (!queued) { queued = true; requestAnimationFrame(report); } };
 new MutationObserver(schedule).observe(document.documentElement, {subtree: true, childList: true, characterData: true});
 for (const kind of ["resize", "scroll", "pointerup", "wheel", "focusin", "focusout"]) window.addEventListener(kind, schedule, true);
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
