"""One brain per machine, guaranteed by the daemon itself.

The founder repeatedly found three to six `personal_brain.server --http 8473`
processes while the port was free or held by one that answered nothing, and
told me to fix it at the root rather than patch it.

The root, read out of the code: the real bind happens LAST -- after the
engine is built and every worker runs -- so a daemon paid for a whole engine
before finding out it lost, and for the minutes in between the port looked
FREE, so every starter concluded no brain was coming and began one more.

The guarantee lives in the DAEMON, where it cannot go stale: it asks for the
port before it builds anything and exits when the answer is no. Guarding it
with a lock file instead was wrong twice over -- it solved what that question
already solves, and when a starter died mid-boot its lock outlived it and
left the founder with NO brain at all until the lock aged out (2026-09-07).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
PRODUCTION = ROOT.parent / "12.PRODUCTION"
SERVER = (
    PRODUCTION / "personal-brain-mcp" / "src" / "personal_brain" / "server.py"
).read_text(encoding="utf-8")


def test_the_port_is_one_fixed_number():
    """A brain nobody can find is a brain nobody has."""
    service = (
        PRODUCTION / "personal-brain-mcp" / "src" / "personal_brain"
        / "service.py"
    ).read_text(encoding="utf-8")
    assert "DEFAULT_PORT = 8473" in service
    wrapper = (PRODUCTION / "tools" / "brainwrap.py").read_text(encoding="utf-8")
    assert "DAEMON_PORT = 8473" in wrapper
    assert '"--http", "8473"' in LAUNCHER


def test_the_daemon_asks_for_the_port_before_it_builds_anything():
    refusal = SERVER.index("_refuse_if_port_is_taken(args.http)")
    engine = SERVER.index('server.run(transport="http"')
    assert refusal < engine, "the question must come before the engine"
    body = SERVER[SERVER.index("def _refuse_if_port_is_taken"):engine]
    assert "raise SystemExit(1)" in body, "a losing daemon must exit"


def test_the_question_is_asked_the_way_windows_answers_it():
    """A plain bind can succeed beside a listener that permits reuse."""
    body = SERVER[SERVER.index("def _refuse_if_port_is_taken"):]
    body = body[:body.index("def main(")]
    assert "SO_EXCLUSIVEADDRUSE" in body
    assert "setsockopt" in body
    assert "probe.close()" in body, "this is a question, not the serving bind"


def test_nothing_outlives_the_listener():
    """A returned run() means serving is over, so the process is over."""
    after = SERVER[SERVER.index('server.run(transport="http"'):]
    after = after[:after.index("# stdio is the default transport.")]
    assert "raise SystemExit(0)" in after


def test_no_starter_keeps_a_lock_that_can_outlive_it():
    """The lock left the founder with no brain when its owner died mid-boot."""
    for gone in (
        "_claim_brain_start",
        "_release_brain_start_claim",
        "_brain_start_claim_path",
        "_BRAIN_START_CLAIM_SECONDS",
        "archhub-brain-daemon-start.lock",
    ):
        assert gone not in LAUNCHER, "%s must not come back" % gone
    wrapper = (PRODUCTION / "tools" / "brainwrap.py").read_text(encoding="utf-8")
    for gone in ("_claim_daemon_start_lock", "_daemon_start_lock_path"):
        assert gone not in wrapper, "%s must not come back" % gone


def test_a_starter_still_checks_before_it_spawns():
    """Cheap to lose is not a licence to spawn on every tick."""
    wrapper = (PRODUCTION / "tools" / "brainwrap.py").read_text(encoding="utf-8")
    ensure = wrapper[wrapper.index("def ensure_daemon("):]
    ensure = ensure[:ensure.index("# ── 2. wiring announce")]
    assert ensure.index("_port_held(DAEMON_PORT)") < ensure.index("subprocess.Popen")
    alive = LAUNCHER[LAUNCHER.index("def _ensure_brain("):]
    alive = alive[:alive.index("_sp.Popen(")]
    assert "if _alive():" in alive, "the app must adopt a running brain"
