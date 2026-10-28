"""Console seat delivery on a real Windows console: empty composer gets the line, a draft is never typed over."""
import subprocess
import sys
import time
from pathlib import Path

import pytest

from nodelang.workshop import console_seat

PROMPT = r'''
import sys, pathlib
out = pathlib.Path(sys.argv[1])
while True:
    line = input("› ")
    out.write_text(out.read_text() + line + "\n" if out.exists() else line + "\n")
'''


@pytest.fixture
def seat(tmp_path):
    script, out = tmp_path / 'seat.py', tmp_path / 'received.txt'
    script.write_text(PROMPT, encoding='utf-8')
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0
    child = subprocess.Popen([sys.executable, '-I', str(script), str(out)], startupinfo=info,
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
    time.sleep(1.5)
    yield child.pid, out
    child.kill()


def received(out, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if out.exists() and out.read_text().strip():
            return out.read_text()
        time.sleep(0.1)
    return ''


def test_reader_patterns():
    assert console_seat.classify(['› Ask Codex to do anything'], 0) == ('empty', '')
    assert console_seat.classify(['❯ 1. Yes'], 0)[0] == 'selection_open'
    assert console_seat.staged('reaches the end of it', 'a long message that reaches the end of it')
    classify = console_seat.classify
    assert classify(['╭───╮', '│ >   Type your message or @path/to/file │', '╰───╯'], 1) == ('empty', '')
    assert classify(['❯ fix the wall'], 0) == ('draft', 'fix the wall')
    assert classify(['plain output'], 0)[0] == 'unknown'
    assert classify(['▄▄▄', ' *   Type your message or @path/to/file', '▀▀▀'], 1) == ('empty', '')
    assert not console_seat.staged('somebody else typed', 'our message')
    assert classify(['  → first part of a long', '    wrapped message'], 0) == ('draft', 'first part of a long wrapped message')
    assert classify(['  ┃', '  ┃', '  ┃  Build · Inkling (free) OpenRouter'], 1) == ('empty', '')
    assert classify(['  ┃  hello there', '  ┃  Build · x'], 0) == ('draft', 'hello there')
    assert classify(['Update Available', '┃', '┃  Build · x'], 1)[0] == 'selection_open'


def test_delivers_into_an_empty_composer(seat):
    pid, out = seat
    state, reason = console_seat.deliver(pid, 'hello from the Workshop')
    assert state == 'delivered', reason
    assert received(out).strip() == 'hello from the Workshop'


def test_never_types_over_a_draft(seat):
    pid, out = seat
    code = ('import sys;sys.path.insert(0,sys.argv[1]);from nodelang.workshop import console_seat as c;k=c._kernel();k.FreeConsole();'
            'k.AttachConsole(int(sys.argv[2]));c._type(k,c._open(k,"CONIN$"),"half typed",enter=False)')
    subprocess.run([sys.executable, '-I', '-c', code, str(Path(console_seat.__file__).resolve().parents[2]), str(pid)],
                   check=True, creationflags=0x08000000)
    time.sleep(0.5)
    state, reason = console_seat.deliver(pid, 'must not be typed')
    assert state == 'draft_present', reason
    assert not out.exists()
