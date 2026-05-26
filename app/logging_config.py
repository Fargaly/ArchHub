"""Central logging config — AgDR-0047 §B2.

Single entry point `init_logging()` configures Python's stdlib logging
so every `logging.getLogger(__name__)` call across the app writes to a
rotated file under `%LOCALAPPDATA%/ArchHub/logs/`.

Per-file separation preserved for §B1 reader contracts:

  * root → ``archhub.log``      (catches everything via propagation)
  * ``archhub.boot``  → ``boot.log``       (mirrors app/main.py startup writer)
  * ``archhub.llm``   → ``llm_trace.log``  (mirrors app/llm_router._trace)

Existing dedicated file writers in ``app/main.py`` (boot.log) and
``app/llm_router.py`` (llm_trace.log) are migrated to use the named
loggers above; the file paths they emit to are unchanged, so the
readers (``agents/status_report.py`` + ``scripts/reality_smoke.py``)
keep working without further edits.

Rotation: 5 MB per file, 5 backups (``boot.log.1`` … ``boot.log.5``).

Idempotent: calling ``init_logging()`` more than once is a no-op after
the first call. ``app/main.py`` calls it once before any other app
import; subprocesses + tests calling it again just reuse the existing
handlers.

Failure-tolerant: every step of handler setup is best-effort. A
permission error on ``%LOCALAPPDATA%`` falls back to ``~/.archhub/logs/``.
The app must still boot even when logging is unreachable.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
_INITIALISED: bool = False

_LOG_DIR_ENV: Final[str] = "LOCALAPPDATA"
_FORMAT: Final[str] = "%(asctime)s [%(name)s] %(levelname)s %(message)s"
_DATEFMT: Final[str] = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES: Final[int] = 5 * 1024 * 1024  # 5 MB
_BACKUP_COUNT: Final[int] = 5


def _resolve_log_dir() -> Path:
    """Pick a writable log directory. LOCALAPPDATA first, ~/.archhub fallback."""
    primary = Path(os.environ.get(_LOG_DIR_ENV, str(Path.home()))) \
              / "ArchHub" / "logs"
    try:
        primary.mkdir(parents=True, exist_ok=True)
        # Smoke-write to confirm we can write here.
        probe = primary / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return primary
    except Exception:
        fallback = Path.home() / ".archhub" / "logs"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _add_rotating_handler(logger: logging.Logger, path: Path) -> None:
    """Attach a RotatingFileHandler to the given logger at ``path``.

    Skips if a handler with the same baseFilename is already attached
    (idempotent re-init in tests / subprocesses).
    """
    target = str(path.resolve())
    for h in logger.handlers:
        if isinstance(h, RotatingFileHandler) \
                and getattr(h, "baseFilename", None) == target:
            return
    handler = RotatingFileHandler(
        target,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
    logger.addHandler(handler)


def init_logging() -> Path:
    """Idempotent root logging setup. Returns the resolved log dir.

    Called from ``app/main.py`` before any other app import. Sub-modules
    that emit via ``logging.getLogger(__name__)`` automatically route to
    the root handler (and to a named handler if their logger name matches
    one of the named files below).
    """
    global _INITIALISED
    log_dir = _resolve_log_dir()
    if _INITIALISED:
        return log_dir

    # Root → catches everything.
    root = logging.getLogger()
    if root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
    _add_rotating_handler(root, log_dir / "archhub.log")

    # Named per-file handlers so legacy readers keep working.
    boot = logging.getLogger("archhub.boot")
    boot.setLevel(logging.INFO)
    _add_rotating_handler(boot, log_dir / "boot.log")

    llm = logging.getLogger("archhub.llm")
    llm.setLevel(logging.INFO)
    _add_rotating_handler(llm, log_dir / "llm_trace.log")

    _INITIALISED = True
    return log_dir
