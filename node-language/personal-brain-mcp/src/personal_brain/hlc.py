"""Hybrid Logical Clocks — Kulkarni et al. 2014.

64-bit packed wallclock (48 bits ms since epoch) + logical counter (16 bits).
Used to give each memory write a causal, deterministic, monotonic timestamp
across devices without requiring synchronized clocks.

Properties:
  - **Monotonic** across all observers
  - **Causal** — happens-before relationship preserved
  - **Compact** — fits in 64-bit int
  - **Comparable** as plain integers
  - **NTP-drift tolerant** — logical counter absorbs skew
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


_LOGICAL_BITS = 16
_LOGICAL_MASK = (1 << _LOGICAL_BITS) - 1
_PHYS_MAX = (1 << (64 - _LOGICAL_BITS)) - 1


@dataclass
class HLC:
    """Hybrid Logical Clock. Singleton per device; thread-safe."""

    phys_ms: int = 0  # wallclock ms since unix epoch
    logical: int = 0  # logical counter when phys_ms collides

    _lock: threading.Lock = None  # type: ignore

    def __post_init__(self):
        # dataclass can't init a Lock by default
        if self._lock is None:
            object.__setattr__(self, "_lock", threading.Lock())

    @classmethod
    def now(cls) -> "HLC":
        return cls(phys_ms=int(time.time() * 1000), logical=0)

    def tick(self) -> int:
        """Advance clock locally — call before EVERY local write.
        Returns the new packed 64-bit timestamp."""
        with self._lock:
            now_ms = int(time.time() * 1000) & _PHYS_MAX
            if now_ms > self.phys_ms:
                self.phys_ms = now_ms
                self.logical = 0
            else:
                # Wallclock didn't advance (clock skew or sub-ms write) →
                # bump logical counter to preserve monotonicity.
                self.logical = (self.logical + 1) & _LOGICAL_MASK
                if self.logical == 0:
                    # Logical wrapped — advance phys_ms by 1 ms.
                    self.phys_ms = (self.phys_ms + 1) & _PHYS_MAX
            return self._pack()

    def receive(self, remote_ts: int) -> int:
        """Update local clock on receiving a remote write. Take max of
        (now_ms, local_phys, remote_phys) and increment logical when there
        is a tie. This is the rule that makes HLC causal."""
        with self._lock:
            r_phys, r_logical = _unpack(remote_ts)
            now_ms = int(time.time() * 1000) & _PHYS_MAX
            best_phys = max(now_ms, self.phys_ms, r_phys)
            if best_phys == self.phys_ms == r_phys:
                self.logical = (max(self.logical, r_logical) + 1) & _LOGICAL_MASK
            elif best_phys == self.phys_ms:
                self.logical = (self.logical + 1) & _LOGICAL_MASK
            elif best_phys == r_phys:
                self.logical = (r_logical + 1) & _LOGICAL_MASK
            else:
                self.logical = 0
            self.phys_ms = best_phys
            return self._pack()

    def _pack(self) -> int:
        return (self.phys_ms << _LOGICAL_BITS) | (self.logical & _LOGICAL_MASK)

    def packed(self) -> int:
        with self._lock:
            return self._pack()

    def to_str(self) -> str:
        ts = self.packed()
        return f"{ts:016x}"


def pack(phys_ms: int, logical: int = 0) -> int:
    return ((phys_ms & _PHYS_MAX) << _LOGICAL_BITS) | (logical & _LOGICAL_MASK)


def _unpack(packed_ts: int) -> tuple[int, int]:
    return (packed_ts >> _LOGICAL_BITS) & _PHYS_MAX, packed_ts & _LOGICAL_MASK


def unpack(packed_ts: int) -> tuple[int, int]:
    """Public version of _unpack — (phys_ms, logical)."""
    return _unpack(packed_ts)


def compare(a: int, b: int) -> int:
    """-1 if a<b, 0 if a==b, 1 if a>b. Plain int compare works because
    physical bits come first."""
    if a < b: return -1
    if a > b: return 1
    return 0


# ─────────────────────── singleton ─────────────────────────────────────


_DEVICE_HLC: HLC | None = None


def device_clock() -> HLC:
    """Return the process-wide HLC singleton. Pass this everywhere that
    writes to memory."""
    global _DEVICE_HLC
    if _DEVICE_HLC is None:
        _DEVICE_HLC = HLC.now()
    return _DEVICE_HLC


def reset_device_clock() -> None:
    """Test helper. Clears the cached HLC so the next device_clock() call
    starts fresh."""
    global _DEVICE_HLC
    _DEVICE_HLC = None
