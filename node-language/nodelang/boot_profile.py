"""Where does boot spend its time? Sample the booting thread and say.

The founder's boot went from 45s to 694s (2026-09-05) and nobody could say
what the 694s WERE. A copy of the store cannot be booted elsewhere (its CDE
signing key is bound to the machine, the user and the path), so the
measurement has to happen inside the real boot. This sampler reads the
booting thread's stack every ``interval`` seconds and, when boot ends,
writes the frames it saw most -- inclusive (anywhere on the stack) and
leaf (top of the stack) -- to ``boot-profile.log`` beside the launcher log.
"""
from __future__ import annotations

import collections
import sys
import threading
import time
from pathlib import Path


class BootSampler:
    def __init__(self, thread_id: int, *, interval: float = 0.25) -> None:
        self.thread_id = int(thread_id)
        self.interval = float(interval)
        self.inclusive: collections.Counter[str] = collections.Counter()
        self.leaf: collections.Counter[str] = collections.Counter()
        self.samples = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="archhub-boot-sampler", daemon=True)

    def start(self) -> "BootSampler":
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.is_set():
            frame = sys._current_frames().get(self.thread_id)
            if frame is not None:
                self.samples += 1
                seen = set()
                top = True
                while frame is not None:
                    code = frame.f_code
                    key = "%s:%s" % (Path(code.co_filename).name, code.co_name)
                    if top:
                        self.leaf[key] += 1
                        top = False
                    if key not in seen:
                        seen.add(key)
                        self.inclusive[key] += 1
                    frame = frame.f_back
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)

    def report(self, *, elapsed: float, top: int = 30) -> str:
        lines = ["boot %.0fs, %d samples every %.2fs" % (elapsed, self.samples, self.interval)]
        total = max(1, self.samples)
        lines.append("--- inclusive (share of samples with this frame on the stack)")
        for key, count in self.inclusive.most_common(top):
            lines.append("%5.1f%%  %s" % (100.0 * count / total, key))
        lines.append("--- leaf (where the thread actually was)")
        for key, count in self.leaf.most_common(top):
            lines.append("%5.1f%%  %s" % (100.0 * count / total, key))
        return "\n".join(lines) + "\n"


def profile_boot(boot, *, state_dir: Path, interval: float = 0.25):
    """Run ``boot()`` on this thread, sampling it, and write the profile."""
    sampler = BootSampler(threading.get_ident(), interval=interval).start()
    started = time.perf_counter()
    try:
        return boot()
    finally:
        elapsed = time.perf_counter() - started
        sampler.stop()
        try:
            out = Path(state_dir) / "boot-profile.log"
            out.write_text(
                "=== boot %s\n" % time.strftime("%Y-%m-%d %H:%M:%S") + sampler.report(elapsed=elapsed),
                encoding="utf-8",
            )
        except OSError:
            pass


__all__ = ["BootSampler", "profile_boot"]
