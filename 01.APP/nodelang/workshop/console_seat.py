"""Live delivery into a terminal-hosted agent's console seat (Windows), draft-aware.

Fitted from OpenRig (github.com/mvschwarz/openrig, Apache-2.0):
  packages/daemon/src/domain/composer-prompts.ts  -> COMPOSER_* patterns below (empty / draft /
      numbered selection / Codex placeholder), extended with the glyphs the Windows CLIs draw;
  packages/daemon/src/domain/session-transport.ts readSeatBeforePaste / hasExpectedStagedText
      -> read the seat before typing, type only into an EMPTY composer, re-read and confirm the
      staged text before Enter; honest refusal codes instead of a silent drop.
OpenRig types into tmux panes. Windows has no tmux: the seat here is the console the agent
process owns (AttachConsole on its pid), read with ReadConsoleOutputCharacterW and written with
WriteConsoleInputW. This runs in its own short process because attaching a console replaces
the caller's.

Codes: delivered | draft_present | composer_unknown | selection_open | console_unavailable |
staged_text_mismatch. Nothing is held for later.
"""
from __future__ import annotations

import ctypes
import json
import re
import subprocess
import sys
import time
from ctypes import wintypes

# Console seat node: its typed parameters (recheck cadence before Enter, helper process budgets).
SEAT_NODE = {'id': 'workshop.console_seat', 'params': {'recheck_seconds': 0.05, 'recheck_tries': 40,
                                                       'deliver_timeout_seconds': 15, 'peek_timeout_seconds': 10}}
PROMPT_GLYPHS = '❯›»>*→'  # Claude ❯, Codex › », '>' most CLIs, '*' Gemini YOLO, '→' cursor-agent
BOX = '│┃║|╭╰╮╯─━▄▀█ '
PLACEHOLDERS = re.compile(r'^(Ask Codex to do anything|Type your message.*|Ask anything.*|Plan, search, build anything.*|Add a follow-up.*|'
                          r'Enter a prompt.*|Type @ to mention.*|How can I help.*|Send a message.*)$', re.I)
SELECTION = re.compile(r'^[%s]\s*\d+[.)]' % PROMPT_GLYPHS)


DIALOG = re.compile(r'(\bConfirm\b.*\b(Skip|Cancel)\b|\b(Skip|Cancel)\b.*\bConfirm\b|Update Available)')
OPENCODE_FOOTER = re.compile(r'^\s*\u2503\s+(Build|Plan)\b')


def classify(lines, cursor_row):
    """OpenRig's composer reading, Windows edition: (state, composer_text)."""
    rows = [line.rstrip() for line in lines]
    if any(DIALOG.search(row) for row in rows):
        return 'selection_open', 'a dialog is open'
    # OpenCode draws no glyph: its input is the bar-edged block above the 'Build/Plan . model' line.
    footer = next((i for i in range(len(rows) - 1, -1, -1) if OPENCODE_FOOTER.match(rows[i])), None)
    if footer is not None:
        block = []
        for line in reversed(rows[:footer]):
            if not line.strip().startswith('\u2503'):
                break
            block.insert(0, line.strip()[1:].strip())
        text = ' '.join(part for part in block if part)
        return ('draft', text) if text and not PLACEHOLDERS.match(text) else ('empty', '')
    for index in range(min(cursor_row, len(rows) - 1), -1, -1):
        stripped = rows[index].strip(BOX)
        if not stripped or stripped[0] not in PROMPT_GLYPHS:
            continue
        if SELECTION.match(stripped):
            return 'selection_open', stripped
        text = stripped[1:].strip(BOX)
        if not text or PLACEHOLDERS.match(text):
            return 'empty', ''
        # A wrapped draft continues on the indented lines below the prompt line.
        indent = len(rows[index]) - len(rows[index].lstrip(BOX)) + 1
        for line in rows[index + 1:]:
            if not line.strip(BOX) or not line.startswith(' ' * indent) or line.strip(BOX)[:1] in PROMPT_GLYPHS:
                break
            text += ' ' + line.strip(BOX)
        return 'draft', text
    return 'unknown', ''


def staged(composer, typed):
    """OpenRig hasExpectedStagedText, fitted: the composer ends with what we typed (its start may scroll away)."""
    squash = lambda value: ''.join(value.split())
    composer, typed = squash(composer), squash(typed)
    return bool(composer) and (composer == typed or (len(composer) >= 12 and typed.endswith(composer[-40:])))


# --- Win32 console, used only inside the helper process ---------------------------------
class _COORD(ctypes.Structure):
    _fields_ = [('X', wintypes.SHORT), ('Y', wintypes.SHORT)]


class _SMALL_RECT(ctypes.Structure):
    _fields_ = [('Left', wintypes.SHORT), ('Top', wintypes.SHORT), ('Right', wintypes.SHORT), ('Bottom', wintypes.SHORT)]


class _CSBI(ctypes.Structure):
    _fields_ = [('dwSize', _COORD), ('dwCursorPosition', _COORD), ('wAttributes', wintypes.WORD),
                ('srWindow', _SMALL_RECT), ('dwMaximumWindowSize', _COORD)]


class _KEY(ctypes.Structure):
    _fields_ = [('bKeyDown', wintypes.BOOL), ('wRepeatCount', wintypes.WORD), ('wVirtualKeyCode', wintypes.WORD),
                ('wVirtualScanCode', wintypes.WORD), ('uChar', wintypes.WCHAR), ('dwControlKeyState', wintypes.DWORD)]


class _EVENT(ctypes.Union):
    _fields_ = [('KeyEvent', _KEY), ('_pad', ctypes.c_byte * 16)]


class _INPUT(ctypes.Structure):
    _fields_ = [('EventType', wintypes.WORD), ('Event', _EVENT)]


def _kernel():
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateFileW.restype = wintypes.HANDLE
    return k


def _open(k, name):
    handle = k.CreateFileW(name, 0xC0000000, 3, None, 3, 0, None)  # GENERIC_READ|WRITE, share R|W, OPEN_EXISTING
    if handle in (None, wintypes.HANDLE(-1).value):
        raise OSError(ctypes.get_last_error(), 'cannot open ' + name)
    return handle


def _capture(k, out):
    info = _CSBI()
    if not k.GetConsoleScreenBufferInfo(out, ctypes.byref(info)):
        raise OSError(ctypes.get_last_error(), 'no screen buffer')
    window = info.srWindow
    width = window.Right - window.Left + 1
    lines = []
    for row in range(window.Top, window.Bottom + 1):
        buffer = ctypes.create_unicode_buffer(width + 1)
        read = wintypes.DWORD()
        k.ReadConsoleOutputCharacterW(out, buffer, width, _COORD(window.Left, row), ctypes.byref(read))
        lines.append(buffer.value[:read.value])
    return lines, info.dwCursorPosition.Y - window.Top


def _type(k, conin, text, enter):
    records = []
    for char in text:
        for down in (True, False):
            record = _INPUT()
            record.EventType = 1
            record.Event.KeyEvent = _KEY(down, 1, 0, 0, char, 0)
            records.append(record)
    if enter:
        for down in (True, False):
            record = _INPUT()
            record.EventType = 1
            record.Event.KeyEvent = _KEY(down, 1, 0x0D, 0x1C, '\r', 0)
            records.append(record)
    array = (_INPUT * len(records))(*records)
    written = wintypes.DWORD()
    if not k.WriteConsoleInputW(conin, array, len(records), ctypes.byref(written)) or written.value != len(records):
        raise OSError(ctypes.get_last_error(), 'console input refused')


def _helper(pid, text):
    k = _kernel()
    k.FreeConsole()
    if not k.AttachConsole(int(pid)):
        return {'state': 'console_unavailable', 'reason': 'the agent process has no console to attach (%d)' % ctypes.get_last_error()}
    conout, conin = _open(k, 'CONOUT$'), _open(k, 'CONIN$')
    lines, row = _capture(k, conout)
    state, _ = classify(lines, row)
    if state != 'empty':
        return {'state': {'draft': 'draft_present', 'unknown': 'composer_unknown'}.get(state, state),
                'reason': 'the founder or agent has unsent text in the composer' if state == 'draft' else
                          'a numbered choice is open in the session' if state == 'selection_open' else
                          'no composer prompt is visible in the session', 'screen_tail': lines[-6:]}
    flat = ' '.join(text.split())
    _type(k, conin, flat, enter=False)
    for _ in range(SEAT_NODE['params']['recheck_tries']):  # re-check before Enter: our text, and only ours, is staged
        time.sleep(SEAT_NODE['params']['recheck_seconds'])
        lines, row = _capture(k, conout)
        state, composer = classify(lines, row)
        if state == 'draft' and staged(composer, flat):
            _type(k, conin, '', enter=True)
            return {'state': 'delivered'}
    return {'state': 'staged_text_mismatch', 'reason': 'the typed text did not appear in the composer; not submitted',
            'screen_tail': lines[-6:]}


def _peek_helper(pids):
    k = _kernel()
    out = {}
    for pid in pids:
        k.FreeConsole()
        if not k.AttachConsole(int(pid)):
            continue
        try:
            lines, row = _capture(k, _open(k, 'CONOUT$'))
            out[str(pid)] = classify(lines, row)[0]
        except OSError:
            continue
    return out


def peek_many(pids, timeout=SEAT_NODE['params']['peek_timeout_seconds']):
    """Read-only composer state of several consoles in one short helper process: {pid: state}."""
    if not pids:
        return {}
    code = ('import json,sys;sys.path.insert(0,sys.argv[1]);from nodelang.workshop.console_seat import _peek_helper;'
            'print(json.dumps(_peek_helper(sys.argv[2:])))')
    from pathlib import Path
    done = subprocess.run([sys.executable, '-I', '-c', code, str(Path(__file__).resolve().parents[2]), *map(str, pids)],
                          capture_output=True, text=True, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        return {int(k): v for k, v in json.loads(done.stdout.strip().splitlines()[-1]).items()}
    except (ValueError, IndexError):
        return {}


def peek(pid):
    return peek_many([pid]).get(int(pid))


def deliver(pid, text, timeout=SEAT_NODE['params']['deliver_timeout_seconds']):
    """Run the helper in its own process; returns (state, reason)."""
    code = ('import json,sys;sys.path.insert(0,sys.argv[1]);from nodelang.workshop.console_seat import _helper;'
            'print(json.dumps(_helper(int(sys.argv[2]),sys.argv[3])))')
    from pathlib import Path
    done = subprocess.run([sys.executable, '-I', '-c', code, str(Path(__file__).resolve().parents[2]), str(pid), text],
                          capture_output=True, text=True, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        result = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 'console_unavailable', (done.stderr or 'console helper failed').strip()[-200:]
    return result['state'], result.get('reason', '')


def main(argv):
    """Workshop's console seat adapter: `python -m nodelang.workshop.console_seat deliver <pid>...` (text on stdin)."""
    if len(argv) < 2 or argv[0] != 'deliver':
        print(json.dumps({'state': 'seat_failed', 'reason': 'usage: deliver <pid>...'}))
        return 2
    text = sys.stdin.read()
    state, reason = 'console_unavailable', 'no process of this session has a console'
    for pid in argv[1:]:
        state, reason = deliver(int(pid), text)
        if state != 'console_unavailable':
            break
    print(json.dumps({'state': state, 'reason': reason}))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
