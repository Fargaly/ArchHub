"""Selected graph persistence, physical source reads and authenticated route behavior."""
import json
import os
import secrets
from pathlib import Path

import pytest

from nodelang import commit_intent, universal_application as app
from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.social_research_community_backend import SocialResearchCommunityBackend


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    folder = tmp_path_factory.mktemp("SOCIAL")
    os.environ["ARCHHUB_GRAND_MAP_PATH"] = str(Path(app.__file__).parent / "data/public_runtime_map.json")
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    server = ApplicationServer(universal_state_path=folder / "app.sqlite3", universal_key_provider=keys,
        universal_workspace_root=folder, enable_machine_transport=False,
        enable_universal_cloud_gateway=False, enable_machine_projection_prewarm=False, live_watch=False).start()
    server._wire_restore_keys = keys
    binding = server._resolve_browser_session(server.browser_session_token)
    backend = SocialResearchCommunityBackend(server.universal_store, server.universal_registry, binding.context)
    with commit_intent.declare(commit_intent.USER_ACTION,
            actor=server.universal_registry.authorization.subject_root, reason="WIRE-social isolated behavior check"):
        backend.graph.add_graph("Social fixture")
        yield backend, server, folder
    server.close()


def test_empty_profile_and_missing_source_never_invent_content():
    backend = SocialResearchCommunityBackend()
    assert backend.get_social_snapshot()["inbox"] == []
    assert backend.get_social_snapshot()["drafts"] == []
    assert backend.get_social_snapshot()["office"]["name"] == ""
    with pytest.raises(ValueError):
        backend.read_content_source("Web", "https://example.invalid/missing")


def test_office_and_drafts_survive_adapter_reset(live):
    backend, server, _ = live
    backend.update_office_page({"name": "User supplied office"})
    draft = backend.save_social_draft({"platform": "LinkedIn", "text": "User supplied post", "title": "", "kind": "post"})
    reset = SocialResearchCommunityBackend(server.universal_store, server.universal_registry, backend.graph.context)
    state = reset.get_social_snapshot()
    assert state["office"]["name"] == "User supplied office"
    assert state["drafts"][0]["id"] == draft["id"]
    assert state["drafts"][0]["status"] == "Draft"
    backend.discard_social_draft(draft["id"])
    assert reset.get_social_snapshot()["drafts"][0]["status"] == "Archived"


def test_slide_actions_persist_without_demo_content(live):
    backend, server, _ = live
    first, second = backend.add_slide(), backend.add_slide()
    assert first["title"] == first["body"] == ""
    backend.edit_slide(second["id"], {"title": "User title", "body": "User story", "layout": "Plan"})
    backend.reorder_slide(second["id"], first["id"])
    reset = SocialResearchCommunityBackend(server.universal_store, server.universal_registry, backend.graph.context)
    assert reset.get_state()["presentation"]["slides"][0]["title"] == "User title"
    backend.remove_slide(first["id"])
    assert len(reset.get_state()["presentation"]["slides"]) == 1


def test_real_source_file_is_read_and_hashed(live):
    import hashlib
    backend, _, folder = live
    path = folder / "SOURCE.txt"
    raw = b"Actual source first line\nActual source second line"
    path.write_bytes(raw)
    result = backend.read_content_source("File", str(path))
    assert result["transcript"] == ["Actual source first line", "Actual source second line"]
    assert result["sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["keyFrames"] == []
    with pytest.raises(ValueError):
        backend.read_content_source("File", str(folder / "MISSING.txt"))


def test_private_network_and_unknown_dispatch_refused_without_mutation(live):
    backend, server, _ = live
    backend.set_source_read_seconds(2)
    revision = server.universal_store.revision
    for source in ("http://localhost", "https://127.0.0.1", "https://user:password@example.com"):
        with pytest.raises(ValueError):
            backend.read_content_source("Web", source)
    with pytest.raises(ValueError):
        backend.dispatch("_save", [])
    with pytest.raises(ValueError):
        backend.dispatch("add_slide", ["extra"])
    assert server.universal_store.revision == revision


def test_baseline_uses_supplied_measurements_and_retains_them(live):
    backend, _, _ = live
    with pytest.raises(ValueError):
        backend.rebaseline_prototype()
    backend.set_prototype({"measurements": "0.2,0.4", "threshold": 0.05})
    assert backend.rebaseline_prototype()["baseline"] == pytest.approx(0.3)
    backend.set_prototype({"measurements": "0.5,0.7"})
    result = backend.check_verdict_pattern()
    assert result["features"][-1]["value"] == pytest.approx(0.3)
    assert "exceeds" in result["pattern"]
    for values in ({"measurements": "nan,0.4"}, {"threshold": float("nan")}, {"linkedModel": "yes"}):
        with pytest.raises(ValueError):
            backend.set_prototype(values)


def test_calendar_and_consented_transcript_are_actual_sources(live):
    backend, _, folder = live
    calendar = folder / "MEETING.ics"
    calendar.write_text("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:fixture-event\nSUMMARY:Source meeting\n"
                        "URL:https://meet.google.com/fixture\nEND:VEVENT\nEND:VCALENDAR", encoding="utf8")
    backend.import_meeting_calendar(str(calendar))
    assert backend.set_meeting({"calendarId": "fixture-event"})["title"] == "Source meeting"
    transcript = folder / "TRANSCRIPT.vtt"
    transcript.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nActual captured words", encoding="utf8")
    with pytest.raises(ValueError):
        backend.import_meeting_transcript(str(transcript))
    backend.set_meeting({"consent": True})
    turns = backend.import_meeting_transcript(str(transcript))
    assert turns[0]["text"] == "Actual captured words"
    assert turns[0]["speaker"] == ""
    assert turns[0]["at"] == "00:00:01.000"


def test_http_route_confirms_write_and_rejects_unregistered_calls(live):
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    backend, server, _ = live

    def post(body):
        request = Request(server.public_url + "/api/universal/social-surface",
            data=json.dumps(body).encode(), headers={"Content-Type": "application/json",
            "X-ArchHub-Session": server.browser_session_token, "X-ArchHub-CSRF": server.browser_csrf_token}, method="POST")
        try:
            with urlopen(request, timeout=20) as response:
                return json.load(response)
        except HTTPError as error:
            print("HTTP refusal:", error.read().decode())
            raise

    result = post({"op": "update_office_page", "args": [{"headline": "HTTP confirmed"}]})
    assert result["state"]["social"]["office"]["headline"] == "HTTP confirmed"
    assert backend.get_social_snapshot()["office"]["headline"] == "HTTP confirmed"
    with pytest.raises(HTTPError) as failure:
        post({"op": "_save", "args": []})
    assert failure.value.code in (400, 409)


def test_graph_state_survives_application_restart(live):
    backend, server, folder = live
    expected = backend.get_social_snapshot()
    server.close()
    restored = ApplicationServer(universal_state_path=folder / "app.sqlite3",
        universal_key_provider=server._wire_restore_keys, universal_workspace_root=folder,
        enable_machine_transport=False, enable_universal_cloud_gateway=False,
        enable_machine_projection_prewarm=False, live_watch=False).start()
    try:
        binding = restored._resolve_browser_session(restored.browser_session_token)
        recovered = SocialResearchCommunityBackend(restored.universal_store, restored.universal_registry, binding.context)
        assert recovered.get_social_snapshot() == expected
        assert recovered.get_state()["presentation"]["slides"][0]["title"] == "User title"
    finally:
        restored.close()
