"""Eight Watcher actions through the real authenticated owner and durable graph."""
import copy
import json
import re
from types import SimpleNamespace
from nodelang import commit_intent
from nodelang.workshop_api import WorkshopAPI
from nodelang.watcher_owner import WatcherOwner

import pytest

from nodelang import clean_revit_adapter
from nodelang.universal_cell import InvalidCell
from tests_replica import test_approval_actions as approval_support

@pytest.fixture(scope="module")
def shared_app(tmp_path_factory):
    # One generated baseline; each test resets only its owned Watcher record, then reopens the actual journal.
    patch = pytest.MonkeyPatch()
    from nodelang import universal_pipeline
    # Unrelated engine-library card seeding is outside these owner/effect courts.
    patch.setattr(universal_pipeline,"seed_engine_library",lambda *args:0)
    fixture = approval_support.approvals.__wrapped__(tmp_path_factory.mktemp("WATCHER"), patch,
        SimpleNamespace(node=SimpleNamespace(name="watcher_shared_durable")))
    surface = next(fixture)
    try:
        yield surface
    finally:
        try:
            next(fixture)
        except StopIteration:
            pass
        patch.undo()


@pytest.fixture
def approvals(shared_app):
    surface = shared_app
    surface.sequence += 1000
    api = WorkshopAPI(surface.server,surface.binding,surface.registry.workshop_root,surface.registry.canvas_root,
        guard=lambda:None,request_id="fixture-reset-"+str(surface.sequence),route="/api/universal/workshop")
    owner = WatcherOwner(api)
    with commit_intent.declare(commit_intent.USER_ACTION,actor=surface.binding.subject_root,reason="reset isolated Watcher fixture state"):
        owner._save(owner.root,{"source":None,"pendingY":None,"proposal":None,"proposals":[],"annotations":[],"applied":False},api.root)
    return surface


@pytest.fixture
def watcher(approvals, monkeypatch):
    model = {"document":"fixture-document", "view":"Level 1", "views":["Level 1", "Level 2"],
        "element":{"id":"wall-unique-214", "label":"Wall 214", "revision":"r1",
                   "start":[120.0,510.0], "end":[980.0,510.0], "lengthMm":12900.0, "thicknessMm":200.0}}
    effects = []
    sessions = [{"port":48884,"pid":1,"document":"Fixture","revit_version":"2025"}]
    monkeypatch.setattr(clean_revit_adapter, "broker_sessions", lambda host: sessions)

    def call(port, route, body=None, **kwargs):
        assert route == "/exec" and port == 48884
        request = json.loads(re.search(r"// WATCHER_REQUEST (.+)", body["code"])[1])
        if request["action"] == "write":
            source = request["source"]
            assert source["document"] == model["document"]
            assert source["element"]["id"] == model["element"]["id"]
            if source["element"]["revision"] != model["element"]["revision"]:
                return {"status":"error","error":"Source revision changed"}
            effects.append(copy.deepcopy(request))
            shift = request["offsetMm"] / 15
            for key in ("start", "end"):
                model["element"][key][1] += shift
            model["element"]["revision"] = "r2"
        result = copy.deepcopy(model)
        result["view"] = request.get("view") or model["view"]
        return {"status":"ok","result":result}

    monkeypatch.setattr(clean_revit_adapter, "_call", call)
    approvals.model, approvals.effects = model, effects
    approvals.call("setWatcherHost", "Revit")
    return approvals


def reopen(w):
    before = w.call("readWatcher")
    w.server.close()
    w.start()
    after = w.call("readWatcher")
    assert after == before
    return after


def test_setWatcherHost_persists_source_identity(watcher):
    state = reopen(watcher)
    assert state["host"] == "Revit" and state["elementId"] == "wall-unique-214"
    assert state["sourceRevision"] == "r1" and state["geometry"]["walls"] == [[120,510,980,510]]
    assert watcher.effects == []


def test_setWatcherView_persists_exact_view(watcher):
    state = watcher.call("setWatcherView", "Level 2")
    assert state["view"] == "Level 2"
    assert reopen(watcher)["view"] == "Level 2"
    with pytest.raises(InvalidCell):
        watcher.call("setWatcherView", "Invented")


def test_addDimension_persists_bound_measurement(watcher):
    state = watcher.call("addDimension", {"from":{"x":120,"y":510},"to":{"x":220,"y":510}})
    dimension = state["dimensions"][0]
    assert dimension["valueMm"] == 1500 and dimension["element"] == "wall-unique-214"
    assert reopen(watcher)["dimensions"] == state["dimensions"]


def test_editWall_persists_pending_without_host_write(watcher):
    state = watcher.call("editWall", 530)
    assert state["pendingY"] == 530 and state["wallY"] == 510
    assert reopen(watcher)["pendingY"] == 530
    assert watcher.effects == [] and watcher.model["element"]["revision"] == "r1"


def test_addMark_persists_source_bound_points(watcher):
    state = watcher.call("addMark", {"tool":"Mark","points":[{"x":100,"y":500},{"x":200,"y":520}]})
    assert state["marks"][0]["revision"] == "r1"
    assert reopen(watcher)["marks"] == state["marks"]


def test_addComment_persists_author_and_element(watcher):
    state = watcher.call("addComment", {"text":"Keep clear","x":130,"y":510,"element":"wall-unique-214"})
    assert state["comments"][0]["text"] == "Keep clear" and state["comments"][0]["author"]
    assert reopen(watcher)["comments"] == state["comments"]


def test_proposeWatcherEdit_one_approval_reopen_then_broker_write(watcher):
    watcher.call("editWall", 530)
    card = watcher.call("proposeWatcherEdit")
    assert card["approvalKind"] == "watcher" and card["sourceRevision"] == "r1"
    assert card["elementId"] == "wall-unique-214" and watcher.effects == []
    assert watcher.call("proposeWatcherEdit")["id"] == card["id"]
    assert len([c for c in watcher.call("listApprovals") if c["approvalKind"] == "watcher"]) == 1
    reopen(watcher)
    assert watcher.call("listApprovals")[-1]["id"] == card["id"]
    watcher.call("postponeApproval", card["id"])
    with pytest.raises(InvalidCell):
        watcher.call("decideWatcherEdit",card["id"],card["input_digest"],"approve")
    watcher.call("resumeApproval", card["id"])
    result = watcher.call("decideWatcherEdit",card["id"],card["input_digest"],"approve")
    assert result["status"] == "approved" and len(watcher.effects) == 1
    assert watcher.call("readWatcher")["wallY"] == 530
    assert reopen(watcher)["applied"] is True
    watcher.call("decideWatcherEdit",card["id"],card["input_digest"],"approve")
    assert len(watcher.effects) == 1


def test_discardWatcherChanges_cancels_approval_and_keeps_annotations(watcher):
    watcher.call("addComment", {"text":"Retain annotation","x":130,"y":510,"element":"wall-unique-214"})
    watcher.call("editWall", 530)
    card = watcher.call("proposeWatcherEdit")
    state = watcher.call("discardWatcherChanges")
    assert state["pendingY"] == state["wallY"] == 510
    assert state["comments"][0]["text"] == "Retain annotation"
    assert reopen(watcher)["pendingY"] == 510
    with pytest.raises(InvalidCell):
        watcher.call("decideWatcherEdit",card["id"],card["input_digest"],"approve")
    assert watcher.effects == []


def test_stale_revision_and_invalid_annotation_cannot_write(watcher):
    revision = watcher.store.revision
    for method,args in [("addDimension",({"from":{"x":0,"y":0},"to":{"x":0,"y":0}},)),
                        ("editWall",(float("nan"),)),
                        ("addComment",({"text":"bad","x":0,"y":0,"element":"other"},))]:
        with pytest.raises(InvalidCell): watcher.call(method,*args)
        assert watcher.store.revision == revision
    watcher.call("editWall", 530)
    card = watcher.call("proposeWatcherEdit")
    watcher.model["element"]["revision"] = "changed-externally"
    with pytest.raises(InvalidCell):
        watcher.call("decideWatcherEdit",card["id"],card["input_digest"],"approve")
    assert watcher.effects == []


def test_autocad_source_offset_uses_same_one_approval_owner(watcher):
    state = watcher.call("setWatcherHost", "AutoCAD")
    assert state["host"] == "AutoCAD"
    watcher.call("editWall", 520)
    card = watcher.call("proposeWatcherEdit")
    watcher.call("decideWatcherEdit",card["id"],card["input_digest"],"approve")
    assert len(watcher.effects) == 1 and watcher.effects[0]["offsetMm"] == 150
    assert reopen(watcher)["wallY"] == 520


def test_mask_bounds_refuse_outside_edits_and_pin_follows_committed_wall(watcher):
    watcher.call("addMark", {"tool":"Mask","points":[{"x":100,"y":500},{"x":1000,"y":540}]})
    watcher.call("addComment", {"text":"Attached pin","x":130,"y":510,"element":"wall-unique-214"})
    with pytest.raises(InvalidCell): watcher.call("editWall", 550)
    watcher.call("editWall", 530)
    card = watcher.call("proposeWatcherEdit")
    watcher.call("decideWatcherEdit",card["id"],card["input_digest"],"approve")
    assert reopen(watcher)["comments"][0]["y"] == 530


def test_uncertain_host_completion_is_never_replayed(watcher, monkeypatch):
    from nodelang.watcher_owner import WatcherOwner
    watcher.call("editWall", 530)
    card = watcher.call("proposeWatcherEdit")
    original = WatcherOwner._save
    def interrupted(self, root, value, parent, *, state=None):
        if state is not None:
            raise RuntimeError("simulated crash before final atomic graph commit")
        return original(self,root,value,parent)
    monkeypatch.setattr(WatcherOwner,"_save",interrupted)
    with pytest.raises(RuntimeError):
        watcher.call("decideWatcherEdit",card["id"],card["input_digest"],"approve")
    monkeypatch.setattr(WatcherOwner,"_save",original)
    assert len(watcher.effects) == 1
    reopen(watcher)
    assert watcher.call("listApprovals")[-1]["status"] == "executing"
    with pytest.raises(InvalidCell):
        watcher.call("decideWatcherEdit",card["id"],card["input_digest"],"approve")
    with pytest.raises(InvalidCell): watcher.call("discardWatcherChanges")
    assert len(watcher.effects) == 1


def test_proposal_request_reuse_preserves_approved_history_in_memory(watcher):
    watcher.call("editWall", 530)
    card = watcher.call("proposeWatcherEdit")
    proposal_sequence = watcher.sequence
    watcher.call("decideWatcherEdit",card["id"],card["input_digest"],"approve")
    watcher.call("editWall", 540)
    watcher.sequence = proposal_sequence - 1
    with pytest.raises(InvalidCell): watcher.call("proposeWatcherEdit")
    cards = watcher.call("listApprovals")
    assert len(cards) == 1 and cards[0]["status"] == "approved" and cards[0]["input_digest"] == card["input_digest"]


def test_selecting_another_element_does_not_shift_saved_pins_in_memory(watcher):
    watcher.call("addComment", {"text":"First wall","x":130,"y":510,"element":"wall-unique-214"})
    watcher.model["element"].update(id="another-wall",start=[120,700],end=[980,700])
    watcher.call("setWatcherHost", "Revit")
    assert watcher.call("readWatcher")["comments"][0]["y"] == 510


@pytest.mark.parametrize("court", [
    "test_postpone_approval_persists_and_keeps_requested_permission",
    "test_resume_approval_persists_without_granting",
    "test_contest_decision_persists_reason_and_blocks_grant",
    "test_refresh_approval_persists_new_request_and_old_history",
    "test_review_proof_row_persists_and_reject_blocks_approve",
    "test_set_approval_rubric_persists_and_false_blocks_approve",
])
def test_existing_approval_regression(approvals, court):
    getattr(approval_support,court)(approvals)
