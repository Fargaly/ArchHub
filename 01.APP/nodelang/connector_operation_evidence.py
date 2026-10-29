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
tests_replica/test_connector_operation_evidence.py holds this table equal to
the catalogue, and every named court to a test that exists.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping

_LIB = "tests_replica/test_the_library_only_offers_what_runs.py::"
_OWN = "tests_replica/test_connector_operation_evidence.py::"

_REVIT_SCRATCH = ("a Revit session with the authenticated ArchHub add-in that a court may drive; "
                  "none exists here (the running Revit sessions are the founder's and are never driven "
                  "by a court) and setup registers the add-in only after its custody review")
_OFFICE = "an open Excel, Word or PowerPoint in this Windows session (COM); courts never read a person's open documents"
_OUTLOOK = "classic Outlook open with a mail profile (COM); courts never read a person's mailbox"
_GRAPH = "PowerShell with the Microsoft.Graph SDK and a signed-in Microsoft 365 account"
_IMAP = "a company IMAP mailbox signed in with an app password"
_BRAIN = "the personal brain answering at 127.0.0.1:8473 inside its budget (it timed out in this lane's probe)"
_MODEL = "a picked model whose provider answers (a court would spend model calls; none was run)"

EVIDENCE: dict[str, dict[str, str]] = {
    "vision.sketch_lines": {"unavailable": "OpenCV (cv2), which the desktop requirements.txt does not install"},
    "cad.read_lines": {"court": _OWN + "test_cad_read_lines_reads_the_shipped_sample_dxf"},
    "cad.host_lines": {"unavailable": "a running AutoCAD that loads the ArchHub AutoCAD add-in (acad-mcp); setup registers the add-in (ApplicationPlugins bundle) only after its custody review, and courts do not launch hosts"},
    "autocad.verb": {"court": "tests_replica/test_host_verbs_folded.py::test_autocad_verb_node_runs_the_verb_and_carries_the_wired_approval"},
    "lines.watch": {"court": _OWN + "test_lines_watch_passes_real_lines_through"},
    "revit.sessions": {"unavailable": _REVIT_SCRATCH},
    "revit.read": {"unavailable": _REVIT_SCRATCH},
    "revit.build_walls": {"unavailable": _REVIT_SCRATCH},
    "revit.set_parameter_by_name": {"court": "tests_replica/test_nodes_next10_catalogue.py::test_next10_writes_require_gate_and_use_fake_signed_brokers"},
    "revit.create_sheets": {"court": "tests_replica/test_nodes_next10_catalogue.py::test_next10_writes_require_gate_and_use_fake_signed_brokers"},
    "revit.renumber_rename": {"court": "tests_replica/test_nodes_next10_catalogue.py::test_next10_writes_require_gate_and_use_fake_signed_brokers"},
    "revit.elements_of_category": {"court": "tests_replica/test_nodes_next10_catalogue.py::test_next10_read_and_pure_nodes_run_on_fixture_brokers"},
    "revit.get_parameter": {"court": "tests_replica/test_nodes_next10_catalogue.py::test_next10_read_and_pure_nodes_run_on_fixture_brokers"},
    "brain.recall": {"unavailable": _BRAIN},
    "brain.facts": {"unavailable": _BRAIN},
    "brain.write": {"court": "tests_replica/test_baboom_agent_gaps.py::test_approved_brain_write_passes_once"},
    "mods.run": {"court": "tests_domains/test_mods_selfext.py::test_mod_node_runner_is_pure_projection"},
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
    "excel.write_range": {"court": "tests_replica/test_nodes_next10_catalogue.py::test_next10_writes_require_gate_and_use_fake_signed_brokers"},
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
    "library.filter_field": {"court": _LIB + "test_filters_keep_only_rows_that_match"},
    "library.filter_compare": {"court": _LIB + "test_filters_keep_only_rows_that_match"},
    "library.filter_rule": {"court": _LIB + "test_filters_keep_only_rows_that_match"},
    "library.rule_check": {"court": "tests_replica/test_nodes_next10_catalogue.py::test_next10_rule_check_reports_pass_fail_and_adapter_owns_revit_scripts"},
    "library.set_field": {"court": _LIB + "test_set_field_says_it_changed_the_stream_not_the_host"},
    "library.move": {"court": _LIB + "test_geometry_moves_the_real_coordinates"},
    "library.rotate": {"court": _LIB + "test_geometry_moves_the_real_coordinates"},
    "library.scale": {"court": _LIB + "test_geometry_moves_the_real_coordinates"},
    "library.group_by": {"court": _LIB + "test_group_and_sort_reuse_the_evaluator"},
    "library.sort_by": {"court": _LIB + "test_group_and_sort_reuse_the_evaluator"},
    "library.if": {"court": _LIB + "test_logic_passes_one_branch_only"},
    "library.switch": {"court": _LIB + "test_logic_passes_one_branch_only"},
    "library.loop": {"court": _LIB + "test_logic_passes_one_branch_only"},
    "library.merge": {"court": _LIB + "test_merge_concats_and_dedupes"},
    "library.add_text": {"court": _LIB + "test_annotations_are_computed_not_invented"},
    "library.dimensions": {"court": _LIB + "test_annotations_are_computed_not_invented"},
    "library.build_schedule": {"court": _LIB + "test_compose_reads_columns_it_was_given"},
    "library.make_legend": {"court": _LIB + "test_compose_reads_columns_it_was_given"},
    "library.save_skill": {"court": _LIB + "test_save_skill_writes_a_skill_the_catalogue_can_read"},
    "library.think": {"unavailable": _MODEL},
    "library.terminal": {"court": "tests_replica/test_settings_terminal_routes.py::"
                                   "test_a_terminal_card_runs_only_for_the_owner_with_execute"},
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
    "approval.gate": {"court": "tests_replica/test_nodes_next10_catalogue.py::test_next10_writes_require_gate_and_use_fake_signed_brokers"},
    "archhub.dry_run_diff": {"unavailable": "pure governance engine without connector evidence"},
    "brain.remember": {"unavailable": _BRAIN},
    "control.foreach": {"unavailable": "base universal control engine"},
    "evidence.attach": {"unavailable": "local evidence files selected by the user"},
    "host.health": {"court": _OWN + "test_connector_probes_read_this_machine"},
    "host.read": {"unavailable": "a connected host selected by the user"},
    "input.slider": {"unavailable": "base universal input engine"},
    "math.expression": {"court": "tests_replica/test_nodes_next10_catalogue.py::test_next10_read_and_pure_nodes_run_on_fixture_brokers"},
    "math.series": {"court": "tests_replica/test_nodes_next10_catalogue.py::test_next10_read_and_pure_nodes_run_on_fixture_brokers"},
    "text.ops": {"court": "tests_replica/test_nodes_next10_catalogue.py::test_next10_read_and_pure_nodes_run_on_fixture_brokers"},
    "trigger.approval": {"unavailable": "requires an approved workflow run"},
    "trigger.emit": {"unavailable": "base universal trigger engine"},
    "trigger.file": {"unavailable": "a watched folder selected by the user"},
    "trigger.host": {"unavailable": "a connected host event source"},
    "trigger.schedule": {"unavailable": "scheduler runtime"},
    "trigger.webhook": {"unavailable": "server webhook runtime"},
    "skill.wrap": {"court": _OWN + "test_skill_engines_read_real_skill_files"},
    "workshop.conversation": {"court": "tests_replica/test_workshop_milestone_one.py::test_workshop_and_agent_definitions_run_from_the_catalogue"},
    "agent.session": {"court": "tests_replica/test_workshop_milestone_one.py::test_workshop_and_agent_definitions_run_from_the_catalogue"},
    "workshop.review": {"court": "tests_replica/test_workshop_milestone_one.py::test_agent_proposed_workflow_is_edited_approved_executed_and_independently_reviewed"},
    "tool.studio": {"court": _OWN + "test_tool_nodes_return_their_settings_parameters"},
    "tool.workshop": {"court": _OWN + "test_tool_nodes_return_their_settings_parameters"},
    "tool.brain": {"court": _OWN + "test_tool_nodes_return_their_settings_parameters"},
    "tool.baboom": {"court": _OWN + "test_tool_nodes_return_their_settings_parameters"},
    "tool.connectors": {"court": _OWN + "test_tool_nodes_return_their_settings_parameters"},
    "tool.cloud": {"court": _OWN + "test_tool_nodes_return_their_settings_parameters"},
    "library.publish_package": {"court": "tests_replica/test_home3_package_publication.py::test_registered_engine_publishes_reviewed_real_files_once"},
    "archhub.enforce": {"unavailable": "Source courts: tests_replica/test_enforce.py (isolated fake writes and real graph/readback); tools/archhub-compiler/tests/diagnostics.rs (Rust artifact/type rules). Authenticated installed host/session intent admission is not verified."},
}

# Which connector row (probe_connectors id) an operation needs, when it needs one.
_CONNECTOR = {
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
        connector = _CONNECTOR.get(op)
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
