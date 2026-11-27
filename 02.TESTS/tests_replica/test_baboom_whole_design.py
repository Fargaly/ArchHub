"""Behavioral courts for BABOOM whole-design alignment (AG-01..AG-08, app.js:1120-1181).

Exercises real offscreen Qt widgets (CompanionWindow, WindowCommands, CompanionFollows)
and real WebEngine React/DOM execution of studio/companion.jsx + COMPANION_BRIDGE.
"""
from __future__ import annotations

import html
import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QObject, QPoint, QUrl, Qt
from PyQt6.QtGui import QEnterEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QWidget

import nodelang.baboom_native_companion as native
from nodelang.baboom_companion_placement import (
    Rect,
    place_baboom_beside_composer,
    place_baboom_work_area,
)
from nodelang.baboom_native_companion import baboom_state_tooltip
from nodelang.baboom_native_visual import bbm_state
from nodelang.window_commands import COMPANION_BRIDGE, CompanionFollows, WindowCommands
from test_baboom_stays_with_archhub import (
    APP,
    LEFT,
    RIGHT,
    _BrainUp,
    _beside,
    _clock,
    _close,
    _composer,
    _stands,
    _with_archhub,
)
from test_baboom_native_companion import _sprite_points


def test_ag01_poses_dnd_moments_and_step_progress_bar(tmp_path, monkeypatch):
    """AG-01: bbmState poses (ponder, cast, wave 900 ms, present 1500 ms, idle), DND/moments, and pp progress bar."""
    assert bbm_state() == "idle"
    assert bbm_state(running=True) == "cast"
    assert bbm_state(needs=2, running=True) == "ponder"
    assert bbm_state(needs=2, running=True, dnd=True) == "idle"
    assert bbm_state(needs=1, running=True, moments=False) == "idle"

    now = _clock(monkeypatch)
    court = _with_archhub(tmp_path, transport=_BrainUp())
    window = court.window
    try:
        window._greeting = False
        window.refresh()
        assert window._frame.motion == "idle"
        assert not window._step_bar.isVisible()

        # Running step -> cast pose + horizontal progress bar with width = round(progress * 100)% and tooltip
        step_state = {
            "surface": "task-file",
            "task": "t-permit",
            "dnd": False,
            "moments": True,
            "running": {"session": "Permit set", "step": "Export sheets", "progress": 0.646},
        }
        window.follow_app(APP, _composer(APP), (), (LEFT, RIGHT), 0, False, step_state)
        assert window._frame.motion == "cast"
        assert window._step_bar.isVisible()
        assert window._step_progress_pct == "65%"
        assert window._step_bar.toolTip() == "Permit set: Export sheets"
        assert window._step_fill.width() == round(window._step_bar.width() * 65 / 100)

        # Approval waiting outranks running -> ponder pose + count badge
        window.follow_app(APP, _composer(APP), (), (LEFT, RIGHT), 2, False, step_state)
        assert window._frame.motion == "ponder"
        assert window._state_badge.isVisible() and window._state_badge.text() == "2"

        # Back to idle when step finishes and approvals clear
        idle_step = {"surface": "task-file", "task": "t-permit", "dnd": False, "moments": True, "running": None}
        window.follow_app(APP, _composer(APP), (), (LEFT, RIGHT), 0, False, idle_step)
        assert window._frame.motion == "idle"
        assert not window._step_bar.isVisible()

        # Click triggers 900 ms wave one-shot, then returns to state pose
        _transparent, opaque = _sprite_points(window)
        QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=opaque)
        QTest.qWait(window._quiet_click.interval() + 60)
        court.app.processEvents()
        assert window._frame.motion == "wave"
        now[0] += 0.95
        window.refresh()
        assert window._frame.motion == "idle"

        # Tutorial completion triggers 1500 ms present one-shot, then returns to state pose
        window.follow_app(
            APP,
            _composer(APP),
            (),
            (LEFT, RIGHT),
            0,
            False,
            {**idle_step, "tutorial_done": "canvas-intro"},
        )
        assert window._frame.motion == "present"
        now[0] += 1.0
        window.refresh()
        assert window._frame.motion == "present"
        now[0] += 0.6
        window.refresh()
        assert window._frame.motion == "idle"

        # Do Not Disturb hides count badge, step progress bar, live dot, and forces idle pose
        dnd_step = {**step_state, "dnd": True}
        window.follow_app(APP, _composer(APP), (), (LEFT, RIGHT), 4, False, dnd_step)
        assert window._frame.motion == "idle"
        assert not window._state_badge.isVisible()
        assert not window._step_bar.isVisible()
        assert not window._dot_shown()
        window.bbm("wave", 900)
        assert window._frame.motion == "idle"

        # moments=False suppresses poses and one-shots while keeping non-DND dot
        quiet_moments = {**step_state, "dnd": False, "moments": False}
        window.follow_app(APP, _composer(APP), (), (LEFT, RIGHT), 2, False, quiet_moments)
        assert window._frame.motion == "idle"
        window.bbm("present", 1500)
        assert window._frame.motion == "idle"
    finally:
        _close(court)


def test_ag02_collision_stepping_bottom_left_peek_and_walk(tmp_path, monkeypatch):
    """AG-02: y-24, y-48, x-48, bottom-left fallback, peek on form pages, and 900 ms walk on intra-route moves."""
    composer = _composer(APP)
    assert place_baboom_beside_composer(APP, RIGHT, sprite_size=(80, 87), composer=composer) == _beside(APP)
    # A dock row on the design place (beside the rail) sends him above the right end of the composer.
    dock_row = Rect(APP.x + 64, APP.y, 268, APP.height)   # the open left dock
    home = Rect(composer.right - 80, composer.y - 4 - 87, 80, 87)
    assert place_baboom_beside_composer(APP, RIGHT, sprite_size=(80, 87), composer=composer, busy=(dock_row,)) == home

    # 1. Step y-24 when a 20 px control sits at the bottom of home
    low_bar = Rect(home.x, home.bottom - 20, 80, 20)
    spot_24 = place_baboom_beside_composer(APP, RIGHT, sprite_size=(80, 87), composer=composer, busy=(dock_row, low_bar))
    assert (spot_24.x, home.y - spot_24.y) == (home.x, 24)

    # 2. Step y-48 when a 30 px control covers both home and y-24
    tall_bar = Rect(home.x, home.bottom - 30, 80, 30)
    spot_48 = place_baboom_beside_composer(APP, RIGHT, sprite_size=(80, 87), composer=composer, busy=(dock_row, tall_bar))
    assert (spot_48.x, home.y - spot_48.y) == (home.x, 48)

    # 3. Step x-48 when vertical column blocks (0,0), (0,-24), (0,-48) at home.x
    right_col = Rect(home.right - 20, home.y - 60, 30, 160)
    spot_left48 = place_baboom_beside_composer(APP, RIGHT, sprite_size=(80, 87), composer=composer, busy=(dock_row, right_col))
    assert (home.x - spot_left48.x, spot_left48.y) == (48, home.y)

    # 4. The whole right side busy: the design place on the left is free
    right_half = Rect(APP.x + 500, APP.y, APP.width - 500, APP.height)
    spot_bl, peek_bl = place_baboom_work_area(
        APP, RIGHT, sprite_size=(80, 87), composer=composer, busy=(right_half,), surface="docs"
    )
    assert spot_bl == _beside(APP) and not peek_bl

    # 5. Peek mode: on form pages (docs/settings) when ALL candidates overlap, peek=True; on canvas, peek=False
    full_form = Rect(APP.x, APP.y, APP.width, APP.height)
    _spot_canvas, peek_canvas = place_baboom_work_area(
        APP, RIGHT, sprite_size=(80, 87), composer=composer, busy=(full_form,), surface="task-file"
    )
    _spot_form, peek_form = place_baboom_work_area(
        APP, RIGHT, sprite_size=(80, 87), composer=composer, busy=(full_form,), surface="settings"
    )
    assert peek_canvas is False
    assert peek_form is True

    # 6. Live CompanionWindow: peek tuck/rise on hover + 900 ms walk on intra-route move (skipped on route switch & reduceMotion)
    now = _clock(monkeypatch)
    court = _with_archhub(tmp_path)
    window = court.window
    try:
        window._greeting = False
        # Route switch to task-file: initial placement does NOT trigger walk
        now[0] = 5.0
        window.follow_app(
            APP,
            composer,
            (dock_row,),
            (LEFT, RIGHT),
            0,
            False,
            {"surface": "task-file", "task": "t1", "dnd": False, "moments": True, "running": None},
        )
        assert window._frame.motion == "idle"

        # Intra-route move after route settles (>1 s): walks for 900 ms and faces left when stepping left
        now[0] = 7.0
        window.follow_app(
            APP,
            composer,
            (dock_row, right_col),
            (LEFT, RIGHT),
            0,
            False,
            {"surface": "task-file", "task": "t1", "dnd": False, "moments": True, "running": None},
        )
        assert window._frame.motion == "walk"
        assert window._frame.facing_left is True
        now[0] = 8.0
        window.refresh()
        assert window._frame.motion == "idle"

        # Reduced motion skips walk on intra-route move
        now[0] = 10.0
        window.follow_app(
            APP,
            composer,
            (),
            (LEFT, RIGHT),
            0,
            False,
            {"surface": "task-file", "task": "t1", "dnd": False, "moments": True, "reduced_motion": True, "running": None},
        )
        assert window._frame.motion == "idle"

        # Route switch to docs with full-form busy controls: tucks to bottom edge in peek, rises on hover!
        now[0] = 12.0
        window.follow_app(
            APP,
            composer,
            (full_form,),
            (LEFT, RIGHT),
            0,
            False,
            {"surface": "docs", "task": "", "dnd": False, "moments": True, "reduced_motion": False, "running": None},
        )
        assert window._peek is True
        assert window._frame.motion == "idle", "no walk across screen on route switch"
        tucked_y = _stands(window).y
        assert tucked_y > _beside(APP).y, "tucked down to hat at bottom edge when unhovered"

        # Hover rises BABOOM to full standing position; leave tucks him back
        enter = QEnterEvent(QPoint(10, 10).toPointF(), QPoint(10, 10).toPointF(), QPoint(10, 10).toPointF())
        court.app.sendEvent(window, enter)
        assert _stands(window).y == _beside(APP).y, "hover rises BABOOM out of peek at the design place"
        court.app.sendEvent(window, QEvent(QEvent.Type.Leave))
        assert _stands(window).y == tucked_y, "leaving tucks BABOOM back"
    finally:
        _close(court)


def test_ag03_live_state_tooltips_and_window_commands_feed(tmp_path, monkeypatch):
    """AG-03: exact live tooltip strings on the sprite widget across all 5 states + WindowCommands.companionStep."""
    assert baboom_state_tooltip("idle") == "BABOOM: click to talk"
    assert baboom_state_tooltip("listening") == "BABOOM is listening: type in the composer"
    assert baboom_state_tooltip("working", session_title="Tower A", step_title="Tag rooms") == "BABOOM: Tower A is on Tag rooms"
    assert baboom_state_tooltip("needs", needs=3) == "BABOOM: 3 waiting for you, in the Workshop"
    assert baboom_state_tooltip("quiet") == "BABOOM: do not disturb"

    _clock(monkeypatch)
    court = _with_archhub(tmp_path)
    window = court.window
    host_win = QWidget()
    host_win.setGeometry(APP.x, APP.y, APP.width, APP.height)
    host_win.show()
    court.app.processEvents()
    page = QObject()
    view = SimpleNamespace(
        page=lambda: page,
        url=lambda: QUrl("http://127.0.0.1:4321/studio"),
        urlChanged=SimpleNamespace(connect=lambda _f: None),
        mapToGlobal=host_win.mapToGlobal,
        zoomFactor=lambda: 1.0,
    )
    commands = WindowCommands(view, host_win, lambda: None, "http://127.0.0.1:4321")
    follows = CompanionFollows(host_win, view, commands, window)
    try:
        window._greeting = False
        commands.companionHome([280.0, 804.0, 1120.0, 72.0], [])
        commands.companionSees(0, False)
        assert window.toolTip() == "BABOOM: click to talk"

        # Listening via open panel or composer focus
        commands.companionSees(0, True)
        assert window.toolTip() == "BABOOM is listening: type in the composer"
        commands.companionSees(0, False)
        commands.companionStep({"surface": "home", "composerListening": True})
        assert window.toolTip() == "BABOOM is listening: type in the composer"

        # Working via active step
        commands.companionStep({
            "surface": "task-file",
            "composerListening": False,
            "running": {"session": "Tower A", "step": "Tag rooms", "progress": 0.4},
        })
        assert window.toolTip() == "BABOOM: Tower A is on Tag rooms"

        # Needs approval outranks working
        commands.companionSees(3, False)
        assert window.toolTip() == "BABOOM: 3 waiting for you, in the Workshop"

        # Quiet (DND) outranks everything
        commands.companionStep({
            "surface": "task-file",
            "dnd": True,
            "running": {"session": "Tower A", "step": "Tag rooms", "progress": 0.4},
        })
        assert window.toolTip() == "BABOOM: do not disturb"
    finally:
        del follows
        host_win.close()
        _close(court)


def test_ag06_first_visit_greeting_copy_timing_and_dismiss_button(tmp_path, monkeypatch):
    """AG-06: exact design greeting copy, 1.2 s delay, 8 s duration, once per session, and × Dismiss button."""
    params = native.GREETING_NODE["params"]
    assert params["after_ms"] == 1200
    assert params["for_ms"] == 8000
    assert params["text"] == "Hi, I'm BABOOM. Ask me about your work or the office standard, or tell me what to do."

    now = _clock(monkeypatch)
    now[0] = 100.0
    court = _with_archhub(tmp_path)
    window = court.window
    try:
        assert not window._state_bubble.isVisible()
        assert not window._greeting_dismiss.isVisible()

        # Appears at 1.2 s with Dismiss × button
        now[0] = 101.25
        window.refresh()
        assert window._state_bubble.isVisible()
        assert window._state_bubble.text() == html.escape(params["text"])
        assert window._greeting_dismiss.isVisible()
        assert window._greeting_dismiss.accessibleName() == "Dismiss"
        assert window._greeting_dismiss.text() == "×"

        # Clicking × dismisses immediately and never shows again this session
        QTest.mouseClick(window._greeting_dismiss, Qt.MouseButton.LeftButton)
        court.app.processEvents()
        assert not window._state_bubble.isVisible()
        assert not window._greeting_dismiss.isVisible()
        now[0] = 103.0
        window.refresh()
        assert not window._state_bubble.isVisible()
    finally:
        _close(court)


def test_ag04_ag05_ag08_studio_companion_panel_and_bridge_in_dom():
    """AG-04, AG-05, AG-08: real esbuild JSX compilation + React 19 + DOM execution of studio/companion.jsx and COMPANION_BRIDGE."""
    import subprocess

    repo_root = Path(__file__).resolve().parents[2]
    companion_path = repo_root / "01.APP" / "nodelang" / "studio" / "companion.jsx"
    node_harness = f"""
import fs from 'node:fs';
import esbuild from 'esbuild';
import {{ JSDOM }} from 'jsdom';
import React from 'react';
import ReactDOMClient from 'react-dom/client';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const dom = new JSDOM(`<!doctype html><html><body>
  <div class="dock left"></div>
  <div data-screen="home">
    <form data-design="composer.surface">
      <span class="recipient-name">@BABOOM</span>
      <button type="button" data-design="composer.to" aria-pressed="false">Session</button>
      <textarea data-design="composer.msg" placeholder="Ask for anything"></textarea>
    </form>
  </div>
  <div id="mount"></div>
</body></html>`, {{ url: 'http://127.0.0.1:4321/studio', pretendToBeVisual: true }});

const {{ window }} = dom;
window.ResizeObserver = class {{ observe() {{}} disconnect() {{}} }};
window.requestAnimationFrame = cb => {{ cb(); return 1; }};
window.cancelAnimationFrame = () => {{}};
if (!window.document.elementsFromPoint) window.document.elementsFromPoint = () => [];
Object.defineProperty(window, 'innerWidth', {{ value: 900, configurable: true }});
Object.defineProperty(window, 'innerHeight', {{ value: 700, configurable: true }});
Object.assign(globalThis, {{
  window,
  document: window.document,
  innerWidth: 900,
  innerHeight: 700,
  HTMLElement: window.HTMLElement,
  MutationObserver: window.MutationObserver,
  ResizeObserver: window.ResizeObserver,
  requestAnimationFrame: window.requestAnimationFrame,
  cancelAnimationFrame: window.cancelAnimationFrame,
  CustomEvent: window.CustomEvent,
  Event: window.Event,
  KeyboardEvent: window.KeyboardEvent,
  React,
}});

const dockEl = document.querySelector('.dock.left');
dockEl.getBoundingClientRect = () => ({{ left: 64, top: 40, right: 524, bottom: 660, width: 460, height: 620 }});

const composerForm = document.querySelector('[data-design="composer.surface"]');
const composerTa = document.querySelector('[data-design="composer.msg"]');
for (const el of [composerForm, composerTa]) {{
  Object.defineProperty(el, 'offsetParent', {{ get: () => document.body }});
  el.getBoundingClientRect = () => ({{ left: 540, top: 620, right: 876, bottom: 684, width: 336, height: 64 }});
}}
const origRect = window.HTMLElement.prototype.getBoundingClientRect;
window.HTMLElement.prototype.getBoundingClientRect = function() {{
  if (this.classList?.contains('bbm-panel')) {{
    const rightPx = parseFloat(this.style.right || '24');
    const bottomPx = parseFloat(this.style.bottom || '172');
    const width = this.style.maxWidth ? parseFloat(this.style.maxWidth) : 380;
    return {{
      width,
      height: 320,
      left: window.innerWidth - rightPx - width,
      right: window.innerWidth - rightPx,
      top: window.innerHeight - bottomPx - 320,
      bottom: window.innerHeight - bottomPx,
    }};
  }}
  return origRect.call(this);
}};

window.__approved = [];
window.__shown = [];
window.__scopeClicked = 0;
document.querySelector('[data-design="composer.to"]').addEventListener('click', function() {{
  window.__scopeClicked++;
  this.setAttribute('aria-pressed', 'true');
}});

const listeners = new Set();
window.__state = {{
  desktopView: {{ route: 'home', task: 't1' }},
  graph: {{ id: 'g1', name: 'Permit workflow', nodes: [{{ id: 'n1', title: 'Export IFC', status: 'Running', progress: 0.72 }}] }},
  tasks: [{{
    id: 't1',
    title: 'Permit set',
    status: 'WIP',
    workflow: [{{ id: 'step-1', title: 'Publish sheets' }}],
    messages: Array.from({{ length: 8 }}, (_, i) => ({{ id: 'm' + (i + 1), who: i % 2 ? 'BABOOM' : 'You', text: 'Message ' + (i + 1) }})),
  }}],
  approvals: [{{ id: 'ap-1', status: 'pending', work: 't1', nodeId: 'step-1', title: 'Fallback title' }}],
  settings: [],
}};
window.executeAction = (id, a, b) => {{
  if (id === 'ui.state') return a(b);
  if (id === 'ui.select') return a();
  return undefined;
}};
window.ArchHubAPI = {{
  executeAction: window.executeAction,
  getSnapshot: () => window.__state,
  subscribe: fn => {{ listeners.add(fn); return () => listeners.delete(fn); }},
  approve: async id => {{ window.__approved.push(id); return {{ ok: true }}; }},
  listTasks: async () => window.__state.tasks,
}};
window.UI = {{
  api: window.ArchHubAPI,
  useData: () => React.useSyncExternalStore(window.ArchHubAPI.subscribe, window.ArchHubAPI.getSnapshot),
  useApp: () => window.__appCtx,
  Btn: ({{ p, sm, plain, children, ...rest }}) => React.createElement('button', {{ type: 'button', ...rest }}, children),
}};

const src = fs.readFileSync({json.dumps(str(companion_path))}, 'utf8');
const compiled = esbuild.transformSync(src, {{ loader: 'jsx' }}).code;
(0, eval)(compiled);

function Harness() {{
  const [open, setOpen] = React.useState(true);
  const [route, setRoute] = React.useState('home');
  window.__setOpen = setOpen;
  window.__setRoute = setRoute;
  window.__appCtx = {{
    route,
    act: fn => fn(),
    openTaskFile: (tid, face) => {{ window.__shown.push([tid, face]); return Promise.resolve(); }},
    setSelectedNodeId: nid => window.__shown.push(['node', nid]),
    go: dest => window.__shown.push(['go', dest]),
  }};
  return React.createElement(window.UI.BaboomSprite, {{ open, setOpen, taskId: 't1' }});
}}

const root = ReactDOMClient.createRoot(document.getElementById('mount'));
await React.act(async () => {{
  root.render(React.createElement(Harness));
}});

window.__bridgeSteps = [];
{{
  const channel = {{ objects: {{ desktopWindow: {{
    companionHome() {{}},
    companionSees() {{}},
    companionStep(d) {{ window.__bridgeSteps.push(d); }},
  }} }} }};
  {COMPANION_BRIDGE}
}}

const p = document.querySelector('[aria-label="BABOOM companion"]');
const dockRight = dockEl.getBoundingClientRect().right;
const panelBox = p.getBoundingClientRect();
const snapshot = {{
  hasMini: !!p.querySelector('.bbm-ph .bbm-mini'),
  title: p.querySelector('.bbm-ph b')?.textContent,
  subtitle: p.querySelector('.bbm-ph b + span')?.textContent,
  headButtons: [...p.querySelectorAll('.bbm-ph button')].map(b => b.getAttribute('aria-label')),
  hasFooter: p.textContent.includes('View in Workshop') || p.textContent.includes('tasks running'),
  ariaLive: p.querySelector('.bbm-log')?.getAttribute('aria-live'),
  msgs: [...p.querySelectorAll('.bbm-log > p.bbm-msg')].map(m => [m.textContent, m.lang, m.dir, m.className]),
  actText: p.querySelector('.bbm-msg.bbm-act span')?.textContent,
  quick: [...p.querySelectorAll('.pbacts [data-bb]')].map(b => [b.dataset.bb, b.textContent]),
  tipHidden: p.querySelector('.pbtip')?.hidden,
  maxWidth: p.style.maxWidth,
  overlapsLeftDock: panelBox.left < dockRight,
  bridgeStep: window.__bridgeSteps.at(-1),
}};

const tips = {{}};
await React.act(async () => {{ p.querySelector('[data-bb="teach"]').click(); }});
tips.home = [p.querySelector('.pbtip').hidden, p.querySelector('.pbtip').textContent];
for (const r of ['task-file', 'docs', 'settings/Appearance']) {{
  await React.act(async () => {{ window.__setRoute(r); }});
  tips[r] = p.querySelector('.pbtip').textContent;
}}
await React.act(async () => {{ p.querySelector('[data-bb="work"]').click(); }});
tips.workPlaceholder = composerTa.placeholder;
tips.focusedComposer = document.activeElement === composerTa;
tips.scopeClicked = window.__scopeClicked;
await React.act(async () => {{ p.querySelector('[data-bbmok="ap-1"]').click(); }});
await React.act(async () => {{ p.querySelector('[data-bbmshow="ap-1"]').click(); }});
tips.approved = window.__approved;
tips.shown = window.__shown;
tips.closedAfterShow = !document.querySelector('[aria-label="BABOOM companion"]');

console.log('RESULT_JSON:' + JSON.stringify({{ snapshot, tips }}));
process.exit(0);
"""
    proc = subprocess.run(
        ["node", "--max-old-space-size=512", "--input-type=module", "-"],
        input=node_harness,
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=str(repo_root),
        timeout=30,
    )
    assert proc.returncode == 0, f"node failed ({proc.returncode}):\n{proc.stderr}\n{proc.stdout}"
    marker = next(line for line in proc.stdout.splitlines() if line.startswith("RESULT_JSON:"))
    data = json.loads(marker.removeprefix("RESULT_JSON:"))
    snapshot = data["snapshot"]
    tips = data["tips"]

    assert snapshot["hasMini"] is True
    assert snapshot["title"] == "BABOOM"
    assert snapshot["subtitle"] == "Your ArchHub assistant"
    assert snapshot["headButtons"] == ["Close BABOOM"], "no extra Brain or Settings buttons in .bbm-ph"
    assert snapshot["hasFooter"] is False, "no N tasks running / View in Workshop footer"
    assert snapshot["ariaLive"] == "polite"
    # 2 welcome lines (EN + AR) + last 6 of the 8 messages (Message 3..Message 8)
    assert len(snapshot["msgs"]) == 8
    assert snapshot["msgs"][0][:3] == [
        "Welcome. Ask me about your work or the standard, or tell me what to do. Type below; I answer here.",
        "",
        "",
    ]
    assert snapshot["msgs"][1][:3] == [
        "أهلاً. اسألني عن شغلك أو الستاندرد، أو قولّي أعمل إيه. اكتب تحت وأنا أرد هنا.",
        "ar",
        "rtl",
    ]
    assert [row[0] for row in snapshot["msgs"][2:]] == [f"Message {i}" for i in range(3, 9)]
    assert "me" in snapshot["msgs"][2][3] and "me" not in snapshot["msgs"][3][3]
    assert snapshot["actText"] == "Publish sheets in Permit set needs your approval."
    assert snapshot["quick"] == [
        ["ask", "Ask BABOOM"],
        ["work", "Give BABOOM a task"],
        ["teach", "Teach me this page"],
    ]
    assert snapshot["tipHidden"] is True
    assert snapshot["maxWidth"] == "336px"
    assert snapshot["overlapsLeftDock"] is False
    assert snapshot["bridgeStep"]["running"] == {
        "session": "Permit set",
        "step": "Export IFC",
        "progress": 0.72,
    }

    assert tips["home"] == [
        False,
        "Home is your queue. Pick a row to answer it here; type below to start a task.",
    ]
    assert tips["task-file"] == "Click a node to see its properties. Run runs every step; writes wait for your Approve."
    assert tips["docs"] == "Type a question below and I open the article."
    assert tips["settings/Appearance"] == 'Type what you want to change below, for example "light theme".'
    assert tips["workPlaceholder"] == "Say what BABOOM should do. It gets its own task and Canvas"
    assert tips["focusedComposer"] is True
    assert tips["scopeClicked"] == 1
    assert tips["approved"] == ["ap-1"]
    assert tips["shown"] == [["t1", "canvas"], ["node", "step-1"]]
    assert tips["closedAfterShow"] is True
