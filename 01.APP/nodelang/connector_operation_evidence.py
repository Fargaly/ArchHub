"""Every connector operation in the catalogue, with the evidence that it works or why it cannot.

One row per engine in pipeline_engines.PIPELINE_ENGINES (which already carries
host_brokers.ENGINES and library_engines.LIBRARY_ENGINES; the library item
cards map onto these engines). A row is exactly one of:

* ``court``: a named test that runs the real engine against a real input
  (a DXF file, skill files, a directory, this machine's probes, real rows)
  and checks its real output. Fakes of a host do not count.
* ``unavailable``: the exact dependency that must exist before a real court
  can run. Nothing is claimed for it.

A court proves the operation, not that a host is connected now. The live
connector state is added beside each row (``connector_state``) so the UI can
say both at once: "court passed · Rhino not running" or "unavailable: ...".
02.TESTS/tests_replica/test_connector_operation_evidence.py holds this table equal to
the catalogue, and every named court to a test that exists.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping

_OWN = "02.TESTS/tests_replica/test_connector_operation_evidence.py::"
_UNVERIFIED = {"unavailable": "Unverified: no named behavioral test of this operation on a real input."}

_REVIT_SCRATCH = "an authorized scratch Revit session with an answering add-in and verified operation output"
_ACAD = "an authorized scratch AutoCAD session with an answering add-in and verified operation output"
_OFFICE = "an open Excel, Word or PowerPoint in this Windows session (COM); courts never read a person's open documents"
_OUTLOOK = "classic Outlook open with a mail profile (COM); courts never read a person's mailbox"
_GRAPH = "PowerShell with the Microsoft.Graph SDK and a signed-in Microsoft 365 account"
_IMAP = "a company IMAP mailbox signed in with an app password"
_BRAIN = "a verified response from the personal Brain service"
_MODEL = "a picked model whose provider answers (a court would spend model calls; none was run)"

EVIDENCE: dict[str, dict[str, str]] = {
    "vision.sketch_lines": {"unavailable": "OpenCV (cv2), which the desktop requirements.txt does not install"},
    "cad.read_lines": {"court": _OWN + "test_cad_read_lines_reads_the_shipped_sample_dxf"},
    "cad.host_lines": {"unavailable": "a running AutoCAD that loads the ArchHub AutoCAD add-in (acad-mcp); setup registers the add-in (ApplicationPlugins bundle) only after its custody review, and courts do not launch hosts"},
    "autocad.verb": {"unavailable": _ACAD},
    "lines.watch": {"court": _OWN + "test_lines_watch_passes_real_lines_through"},
    "revit.sessions": {"unavailable": _REVIT_SCRATCH},
    "revit.read": {"unavailable": _REVIT_SCRATCH},
    "revit.build_walls": {"unavailable": _REVIT_SCRATCH},
    "revit.set_parameter_by_name": {"unavailable": _REVIT_SCRATCH},
    "revit.create_sheets": {"unavailable": _REVIT_SCRATCH},
    "revit.renumber_rename": {"unavailable": _REVIT_SCRATCH},
    "revit.elements_of_category": {"unavailable": _REVIT_SCRATCH},
    "revit.get_parameter": {"unavailable": _REVIT_SCRATCH},
    "brain.recall": {"unavailable": _BRAIN},
    "brain.facts": {"unavailable": _BRAIN},
    "brain.write": _UNVERIFIED,
    "mods.run": _UNVERIFIED,
    "connector.status": {"court": _OWN + "test_connector_probes_read_this_machine"},
    "skills.catalogue": {"court": _OWN + "test_skill_engines_read_real_skill_files"},
    "skills.read": {"court": _OWN + "test_skill_engines_read_real_skill_files"},
    "skills.thinking_chain": {"court": _OWN + "test_skill_engines_read_real_skill_files"},
    "max.exec": {"unavailable": "3ds Max running with the MaxMCP startup script loaded; setup places the script only when the build carries its custody review, and courts do not launch hosts"},
    "max.info": {"unavailable": "3ds Max running with the MaxMCP startup script loaded; setup places the script only when the build carries its custody review, and courts do not launch hosts"},
    "max.python": {"unavailable": "3ds Max running with the MaxMCP startup script loaded; setup places the script only when the build carries its custody review, and courts do not launch hosts"},
    "rhino.exec": {"unavailable": "Rhino 8 running the ArchHub bridge script on :9879; courts do not launch hosts on this machine"},
    "blender.exec": {"unavailable": "Blender running the ArchHub add-on on :9876; courts do not launch hosts on this machine"},
    "office.read": {"unavailable": _OFFICE},
    "excel.write_range": {"unavailable": _OFFICE},
    "outlook.inbox": {"unavailable": _OUTLOOK},
    "notion.search": {"unavailable": "a Notion integration token (Settings > keys > notion)"},
    "notion.connect": {"unavailable": "a Notion integration token (Settings > keys > notion)"},
    "dropbox.list": {"court": _OWN + "test_dropbox_list_reads_a_real_folder"},
    "connector.rows": {"court": _OWN + "test_connector_probes_read_this_machine"},
    "outlook.graph.inbox": {"unavailable": _GRAPH},
    "outlook.graph.status": {"unavailable": _GRAPH},
    "outlook.graph.categories": {"unavailable": _GRAPH},
    "outlook.graph.categorize": {"unavailable": _GRAPH},
    "outlook.imap.inbox": {"unavailable": _IMAP},
    "outlook.imap.status": {"unavailable": _IMAP},
    "outlook.imap.message": {"unavailable": _IMAP},
    "library.filter_field": _UNVERIFIED,
    "library.filter_compare": _UNVERIFIED,
    "library.filter_rule": _UNVERIFIED,
    "library.rule_check": _UNVERIFIED,
    "library.set_field": _UNVERIFIED,
    "library.move": _UNVERIFIED,
    "library.rotate": _UNVERIFIED,
    "library.scale": _UNVERIFIED,
    "library.group_by": _UNVERIFIED,
    "library.sort_by": _UNVERIFIED,
    "library.if": _UNVERIFIED,
    "library.switch": _UNVERIFIED,
    "library.loop": _UNVERIFIED,
    "library.merge": _UNVERIFIED,
    "library.add_text": _UNVERIFIED,
    "library.dimensions": _UNVERIFIED,
    "library.build_schedule": _UNVERIFIED,
    "library.make_legend": _UNVERIFIED,
    "library.save_skill": _UNVERIFIED,
    "library.think": {"unavailable": _MODEL},
    "library.terminal": _UNVERIFIED,
    "library.match_skill": {"court": _OWN + "test_skill_engines_read_real_skill_files"},
    "library.embed": {"unavailable": _BRAIN},
    "library.notify": {"unavailable": "the running desktop's tray surface, which the application registers at start"},
    "library.draft_email": {"unavailable": _OUTLOOK},
    "library.vision": {"unavailable": _MODEL},
    "library.publish_pdf": {"unavailable": _REVIT_SCRATCH},
    "library.tag_rooms": {"unavailable": _REVIT_SCRATCH},
    "library.place_tags": {"unavailable": _REVIT_SCRATCH},
    "library.place_on_sheet": {"unavailable": _REVIT_SCRATCH},
    "library.push_speckle": {"unavailable": "a Speckle server address and a token for it"},
    "speckle.send": {"unavailable": "a Speckle server address and a token for it"},
    "ai.master": {"unavailable": _MODEL},
    "approval.gate": _UNVERIFIED,
    "archhub.dry_run_diff": {"unavailable": "pure governance engine without connector evidence"},
    "brain.remember": {"unavailable": _BRAIN},
    "control.foreach": {"unavailable": "base universal control engine"},
    "evidence.attach": {"unavailable": "local evidence files selected by the user"},
    "host.health": {"court": _OWN + "test_connector_probes_read_this_machine"},
    "host.read": {"unavailable": "a connected host selected by the user"},
    "input.slider": {"unavailable": "base universal input engine"},
    "math.expression": {"court": "02.TESTS/tests_replica/test_designv22g.py::test_bypass_and_disabled_wire_change_real_run"},
    "math.series": {"court": _OWN + "test_text_replaces_input_and_series_returns_values"},
    "text.ops": {"court": _OWN + "test_text_replaces_input_and_series_returns_values"},
    "trigger.approval": {"unavailable": "requires an approved workflow run"},
    "trigger.emit": {"unavailable": "base universal trigger engine"},
    "trigger.file": {"unavailable": "a watched folder selected by the user"},
    "trigger.host": {"unavailable": "a connected host event source"},
    "trigger.schedule": {"unavailable": "scheduler runtime"},
    "trigger.webhook": {"unavailable": "server webhook runtime"},
    "skill.wrap": {"court": _OWN + "test_skill_engines_read_real_skill_files"},
    "tool.studio": {"court": _OWN + "test_tool_nodes_return_their_settings_parameters"},
    "tool.workshop": {"court": _OWN + "test_tool_nodes_return_their_settings_parameters"},
    "tool.brain": {"court": _OWN + "test_tool_nodes_return_their_settings_parameters"},
    "tool.baboom": {"court": _OWN + "test_tool_nodes_return_their_settings_parameters"},
    "tool.connectors": {"court": _OWN + "test_tool_nodes_return_their_settings_parameters"},
    "tool.cloud": {"court": _OWN + "test_tool_nodes_return_their_settings_parameters"},
    "library.publish_package": _UNVERIFIED,
    "archhub.enforce": {"unavailable": "Authenticated installed host/session intent admission is unverified."},
    "revit.verb": {"unavailable": _REVIT_SCRATCH},
    "revit.export_ifc": {"unavailable": _REVIT_SCRATCH},
    "revit.export_dwg": {"unavailable": _REVIT_SCRATCH},
    "revit.execute_csharp": {"unavailable": _REVIT_SCRATCH},
    "revit.info": {"unavailable": _REVIT_SCRATCH},
    "revit.open_document": {"unavailable": _REVIT_SCRATCH},
    "revit.screenshot": {"unavailable": _REVIT_SCRATCH},
    "acad.execute_csharp": {"unavailable": _ACAD},
    "acad.info": {"unavailable": _ACAD},
    "acad.ping": {"unavailable": _ACAD},
    "outlook.forward_draft": {"unavailable": _OUTLOOK},
    "outlook.read_thread": {"unavailable": _OUTLOOK},
    "outlook.reply_draft": {"unavailable": _OUTLOOK},
    "outlook.search": {"unavailable": _OUTLOOK},
    "excel.build_workbook": {"unavailable": _OFFICE},
    "excel.open": {"unavailable": _OFFICE},
    "excel.read_table": {"unavailable": _OFFICE},
    "excel.share_workbook": {"unavailable": _OFFICE},
    "excel.write_cells": {"unavailable": _OFFICE},
    "connector.call": _UNVERIFIED,
    "host.exec": {"court": "02.TESTS/tests/test_host_exec.py::test_python_host_binds_a_parameter_and_stamps_a_pdf"},
    "hosts.state": _UNVERIFIED,
    "pdf.extract_text": {"court": _OWN + "test_pdf_extract_text_reads_a_real_page_twice"},
    "pdf.snip": _UNVERIFIED,
    "decide.optimize": {"court": "02.TESTS/tests/test_g6_optimize_schedule.py::test_optimize_knapsack_picks_the_best_pair"},
    "decide.schedule": {"court": "02.TESTS/tests/test_g6_optimize_schedule.py::test_schedule_respects_after_links_and_crews"},
    "research.weighted": {"court": "02.TESTS/tests/test_g6_decision_score.py::test_topsis_ranks_and_closeness_is_between_zero_and_one"},
    "script.python": {"court": "02.TESTS/tests_replica/test_designv22g.py::test_pure_saved_script_solves_without_writing_its_definition"},
    "data.convert": {"court": _OWN + "test_convert_reads_a_numeric_input"},
}

# Which connector row (probe_connectors id) an operation needs, when it needs one.
_CONNECTOR = {
    "cad.host_lines": "autocad",
    "max.exec": "max", "max.info": "max", "max.python": "max",
    "rhino.exec": "rhino", "blender.exec": "blender",
    "outlook.inbox": "outlook", "library.draft_email": "outlook",
    "notion.search": "notion", "dropbox.list": "dropbox",
    "outlook.graph.inbox": "outlook-new", "outlook.graph.status": "outlook-new",
    "outlook.graph.categories": "outlook-new", "outlook.graph.categorize": "outlook-new",
    "outlook.imap.inbox": "outlook-imap", "outlook.imap.status": "outlook-imap",
    "outlook.imap.message": "outlook-imap",
}


def operation_rows(connectors: Iterable[Mapping[str, object]] | None = None) -> list[dict]:
    """One row per catalogue engine: evidence, plus the live connector state when known."""
    from .pipeline_engines import PIPELINE_ENGINES
    states = {str(row.get("id")): str(row.get("state")) for row in (connectors or ())
              if isinstance(row, Mapping)}
    rows = []
    for op in sorted(PIPELINE_ENGINES):
        evidence = EVIDENCE.get(op) or {"unavailable": "no evidence is recorded for this operation"}
        row = {"op": op}
        if "court" in evidence:
            row.update(evidence="court", detail=evidence["court"])
        else:
            row.update(evidence="unavailable", detail=evidence["unavailable"])
        family = op.partition(".")[0]
        connector = _CONNECTOR.get(op) or {"revit": "revit", "acad": "autocad", "autocad": "autocad",
                                           "excel": "excel", "outlook": "outlook"}.get(family)
        if connector and connector in states:
            row["connector_state"] = states[connector]
        rows.append(row)
    return rows


def host_projection() -> dict:
    """What hosts.status and the Hosts panel read: probes and the evidence table."""
    from .pipeline_engines import probe_connectors
    connectors = probe_connectors()
    return {"ok": True, "connectors": connectors, "operations": operation_rows(connectors)}


__all__ = ["EVIDENCE", "host_projection", "operation_rows"]
