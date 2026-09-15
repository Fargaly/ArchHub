"""Operator policy for recurring maintenance, independent of MCP transport.

Maintenance is opt-in. This does not gate foreground tools or provide a resource
budget for an explicitly requested maintenance operation. The pause marker is
checked at each start; creating it does not stop already running workers.
"""
import os
from pathlib import Path

_ON = {"1", "on", "true", "yes", "enabled"}
_OFF = {"0", "off", "false", "no", "disabled"}
_MASTER = "BRAIN_HTTP_RUNTIME_SERVICES"  # Retain existing operator setting.
_COMPONENTS = ("BRAIN_WORKERS", "BRAIN_HOOK_COVERAGE_MONITOR")


def ambient_runtime_allowed(component: str | None = None, *, force: bool = False) -> tuple[bool, str]:
    """Return startup permission and reason; pause/master-off always win.

    Existing component flags remain independent opt-ins. The legacy master ON
    opts into both components, subject to each explicit component OFF. force is
    an explicit programmatic worker request, never an override of suspension.
    """
    local = os.environ.get("LOCALAPPDATA")
    if local:
        marker = Path(local) / "ArchHub" / "brain" / "ambient-runtime.suspended"
        try:
            if marker.is_file():
                return False, str(marker)
        except OSError:
            return False, "suspension marker unavailable"
    master = os.environ.get(_MASTER, "").strip().lower()
    if master in _OFF or (master and master not in _ON):
        return False, _MASTER
    if force:
        return True, "explicit programmatic request"
    if component is None:
        decisions = [ambient_runtime_allowed(name) for name in _COMPONENTS]
        return next((decision for decision in decisions if decision[0]), (False, "ambient maintenance defaults off"))
    if component not in _COMPONENTS:
        return False, "unknown ambient component"
    value = os.environ.get(component, "").strip().lower()
    if value:
        return value in _ON, component
    return master in _ON, _MASTER if master else "ambient maintenance defaults off"
