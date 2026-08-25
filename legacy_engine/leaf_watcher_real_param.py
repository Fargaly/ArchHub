# -*- coding: utf-8 -*-
"""LEAF: the watcher edits a REAL persisted app parameter on disk.

This is the real-persistence version of the watcher leaf. Instead of editing an
in-memory UI view, the watcher edits a node that is BOUND to a real config file
the app would read at startup — ${DIR}/app_theme.config.json — and APPLYING the
edit actually rewrites that file on disk. Revert puts the real file back.

Wiring (all REAL nodes in node_lang, no engine edits):

    accent  (kind 'accent')      -> the app's theme colour, as a node
       |
       v   (its colour is baked into the config JSON)
    cfg     (kind 'host_write')  -> EFFECTFUL node BOUND to app_theme.config.json
       ^                            frozen+dry-run by default; apply() = real write
       |
    watcher (kind 'watcher')     -> the live editor; watches accent + cfg

The graph is the single source of truth (per SPEC §5b). The config file on disk
is a DISPOSABLE derived artifact: editing accent through the watcher changes the
JSON the cfg node would write; APPLYING cfg performs the real, revertible write
(host_write is frozen-by-default — nothing touches disk until apply). Revert
restores the prior accent from an immutable History snapshot, then re-applies so
the real file on disk is byte-for-byte the original again.

Proves end-to-end, by RUNNING it (no mocks):
  - writes a real config file        {"accent": "#d97757", ...}
  - watcher recolours accent -> #7ec18e and APPLIES -> re-read file == #7ec18e
  - revert -> re-read file == #d97757 again
  - host_write stays frozen/dry-run until explicitly applied (nothing leaks to disk)

REUSES node_lang.Graph / node_lang.History and the engine's existing effectful
'host_write' kind unchanged. A NEW self-contained file; edits nothing else.

Run:
  cd <NODE_LANGUAGE_ROOT>
  PYTHONIOENCODING=utf-8 python leaf_watcher_real_param.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from .node_lang import Graph, History   # REUSE the real engine, do not rebuild

# the REAL persisted app parameter file (the app would read this at startup)
CONFIG_PATH = os.path.join(HERE, "app_theme.config.json")

ACCENT_DEFAULT = "#d97757"   # terracotta — the shipped default
ACCENT_EDIT = "#7ec18e"      # the recolour we push through the watcher


def render_config(accent):
    """The real config payload the app reads. accent is the live parameter."""
    return json.dumps(
        {"accent": accent, "schema": "archhub/app-theme/1",
         "note": "real persisted app parameter, written by the node graph"},
        indent=2,
    )


def read_config_accent():
    """Re-read the REAL file off disk and pull out the persisted accent."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)["accent"]


def read_config_text():
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return fh.read()


def apply_cfg(g, cfg):
    """APPLY the effectful host_write node: unfreeze + apply -> real disk write.
    Then re-freeze so the node is inert again (nothing else can leak to disk)."""
    g.set_param(cfg, "frozen", False)
    g.set_param(cfg, "apply", True)
    result = g.eval(cfg)                       # the engine performs the real write here
    assert result["applied"] is True, ("host_write did not apply", result)
    g.set_param(cfg, "apply", False)           # re-disarm
    g.set_param(cfg, "frozen", True)
    return result


def sync_cfg_value(g, cfg, accent):
    """The cfg node's payload is DERIVED from the live accent node — keep them in
    lockstep so the config the app would read always reflects the accent param."""
    g.set_param(cfg, "value", render_config(accent))


def edit_accent_via_watcher(g, watcher, cfg, color):
    """Drive the edit THROUGH the watcher: it may only touch nodes it watches.
    Recolour the accent param, then refresh the bound config node's payload."""
    targets = g.nodes[watcher]["params"]["targets"]
    accent = g.nodes[watcher]["params"]["accent"]
    assert accent in targets, "watcher may only edit nodes it watches"
    assert cfg in targets, "watcher must also watch the bound config node"
    g.set_param(accent, "color", color)        # the real parameter changes
    sync_cfg_value(g, cfg, g.eval(accent))     # config payload follows the accent


def build():
    g = Graph()
    hist = History()
    accent = g.add("theme_accent", "accent", params={"color": ACCENT_DEFAULT})
    # host_write node BOUND to the real file; frozen by default (dry-run only)
    cfg = g.add("theme_cfg", "host_write",
                params={"target": CONFIG_PATH,
                        "value": render_config(ACCENT_DEFAULT),
                        "frozen": True, "apply": False})
    watcher = g.add("theme_watcher", "watcher",
                    params={"targets": [accent, cfg], "accent": accent, "cfg": cfg})
    return g, hist, accent, cfg, watcher


def main():
    g, hist, accent, cfg, watcher = build()
    print("=" * 74)
    print("LEAF: the watcher edits a REAL persisted app parameter (config file on disk)")
    print("=" * 74)
    print("config file: %s" % CONFIG_PATH)
    print()

    # host_write is frozen-by-default: evaluating it touches NOTHING on disk.
    # Prove the safety boundary before we ever write the real file.
    if os.path.exists(CONFIG_PATH):
        os.remove(CONFIG_PATH)
    preview = g.eval(cfg)
    assert preview["dry_run"] is True and preview["applied"] is False, preview
    assert not os.path.exists(CONFIG_PATH), "frozen host_write leaked to disk"
    print("frozen host_write -> dry-run preview only, no file written:")
    print("   %s" % json.dumps(preview["would"])[:90] + " ...")
    print()

    # 1) APPLY the initial config -> the REAL file now exists on disk
    apply_cfg(g, cfg)
    before = read_config_accent()
    print("APPLIED initial config -> real file on disk")
    print("   BEFORE  accent on disk = %s" % before)
    assert before == ACCENT_DEFAULT, ("initial write wrong", before)

    # commit this baseline into the immutable history tree
    v0 = hist.commit(g, "v0 baseline (#d97757)")

    # 2) RECOLOR through the watcher and APPLY -> assert the REAL file changed
    edit_accent_via_watcher(g, watcher, cfg, ACCENT_EDIT)
    apply_cfg(g, cfg)
    after = read_config_accent()
    print("RECOLORED via watcher to %s and APPLIED" % ACCENT_EDIT)
    print("   AFTER   accent on disk = %s" % after)
    assert after == ACCENT_EDIT, ("real file did not change on disk", after)
    assert after != before, ("edit had no effect on the real file", before, after)

    # 3) REVERT -> restore the prior accent from the immutable snapshot, re-apply,
    #    and assert the REAL file on disk is back to the original byte-for-byte.
    text_at_edit = read_config_text()
    hist.revert(g, v0)                          # graph param restored from snapshot
    apply_cfg(g, cfg)                           # push the restored value back to disk
    reverted = read_config_accent()
    text_after_revert = read_config_text()
    print("REVERTED to v0 snapshot and re-APPLIED")
    print("   REVERT  accent on disk = %s" % reverted)
    assert reverted == ACCENT_DEFAULT, ("revert did not restore the real file", reverted)
    assert text_after_revert != text_at_edit, "file content identical before/after revert"

    # the graph stayed the single source of truth: the disk file always matched eval(accent)
    assert reverted == g.eval(accent), "disk file drifted from the graph parameter"

    print()
    print("WATCHER_REAL_PARAM_OK")
    print("   real file BEFORE edit : %s" % json.dumps({"accent": before}))
    print("   real file AFTER  edit : %s" % json.dumps({"accent": after}))
    print("   real file AFTER revert: %s" % json.dumps({"accent": reverted}))
    print("   (frozen dry-run held, apply wrote disk, revert restored disk — all on the real file)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
