"""Governance policy expressed as node-language data.

The desktop app launcher/watchdog is an effectful governance surface. This
module builds that surface into the one-table node language so the production
installer consumes a node-backed policy instead of becoming the policy itself.
"""
from __future__ import annotations

from collections.abc import Iterable

from .core import Store


DEFAULT_DESKTOP_COMMANDS = ("codex", "claude", "gemini", "antigravity")


def build_desktop_launch_policy(
    store: Store,
    *,
    commands: Iterable[str] = DEFAULT_DESKTOP_COMMANDS,
) -> dict[str, object]:
    app_nodes: list[str] = []
    for command in commands:
        app_nodes.append(
            store.add(
                "value",
                "Desktop app: %s" % command,
                floor={
                    "op": "value",
                    "value": {
                        "command": command,
                        "entry": "normal-window-app",
                        "requires": "governed-parent-or-watchdog-restart",
                    },
                },
            )
        )

    watchdog_effect = store.add(
        "op",
        "Install governed desktop watchdog",
        floor={
            "op": "effect",
            "target": "windows-startup-task",
            "change": {
                "task": "ArchHub-Governed-Agent-Watchdog",
                "mode": "restart-ungoverned-primary-apps",
            },
        },
        frozen=True,
    )
    shortcut_effect = store.add(
        "op",
        "Install governed desktop shortcuts",
        floor={
            "op": "effect",
            "target": "windows-shortcuts",
            "change": {
                "mode": "normal-app-shortcuts-point-to-brainwrap",
                "apps": list(commands),
            },
        },
        frozen=True,
    )

    probes: list[str] = []
    for check in (
        "brain-health",
        "hook-coverage",
        "process-ancestry-governed",
        "normal-app-watchdog",
    ):
        probes.append(
            store.add(
                "op",
                "Probe: %s" % check,
                floor={
                    "op": "probe",
                    "kind": "governance",
                    "spec": {"check": check},
                },
            )
        )

    probe_scores: list[str] = []
    governance_score = store.add(
        "op",
        "Desktop governance score",
        floor={"op": "math", "fn": "avg"},
    )
    for probe in probes:
        check = store.nodes[probe]["body"]["floor"]["spec"]["check"]
        score = store.add(
            "op",
            "OK?: %s" % check,
            floor={"op": "probe_ok", "probe": probe},
        )
        store.wire(probe, score)
        store.wire(score, governance_score)
        probe_scores.append(score)

    session = store.add(
        "session",
        "Desktop Launch Governance",
        inner=(
            app_nodes
            + [watchdog_effect, shortcut_effect]
            + probes
            + probe_scores
            + [governance_score]
        ),
    )
    return {
        "session": session,
        "apps": app_nodes,
        "watchdog_effect": watchdog_effect,
        "shortcut_effect": shortcut_effect,
        "probes": probes,
        "probe_scores": probe_scores,
        "governance_score": governance_score,
    }
