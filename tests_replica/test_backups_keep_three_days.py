"""Court (fix 6): after a new verified backup only the last three days of backups are kept.

Founder 2026-09-23: graph backups piled to 220 GB; keep the last 3 days only, judging age by
the date in the backup folder name, not by file times (a reboot touched every folder's
modification time to the same minute). Real application recovery on a temporary graph;
retention runs on temporary folders only.
"""
import os
import re
from datetime import date
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / "launch_archhub_test.py"
HEX = "0123456789abcdef" * 2


def test_retention_reads_the_folder_name_date_and_keeps_the_last_three_days(tmp_path):
    from nodelang.backup_retention import prune_backups
    backups = tmp_path / "backups"
    names = ["20260918-integrated-r5-closed", "graph-repair-r3-20260920", "application-recovery-20260921-" + HEX,
             "20260922-integrated-r7-closed", "application-recovery-" + HEX, ".application-recovery-stage",
             "application-recovery-20260923-" + HEX]
    for name in names:
        (backups / name).mkdir(parents=True)
        (backups / name / "graph.sqlite3").write_bytes(b"x")
    (backups / "note-20200101.txt").write_text("a plain file", encoding="utf-8")
    for entry in backups.iterdir():
        os.utime(entry, (1_790_000_000, 1_790_000_000))   # one reboot minute for every folder
    result = prune_backups(backups, keep=backups / names[-1], today=date(2026, 9, 23))
    left = sorted(entry.name for entry in backups.iterdir())
    assert result["removed"] == ["20260918-integrated-r5-closed", "graph-repair-r3-20260920"], result
    assert left == sorted(names[2:] + ["note-20200101.txt"]), left
    assert result["undated_kept"] == ["application-recovery-" + HEX]


def test_nothing_is_deleted_without_a_new_verified_backup_inside_the_directory(tmp_path):
    import pytest
    from nodelang.backup_retention import prune_backups
    backups = tmp_path / "backups"
    (backups / "20200101-old").mkdir(parents=True)
    with pytest.raises(ValueError):
        prune_backups(backups, keep=tmp_path / "elsewhere", today=date(2026, 9, 23))
    assert (backups / "20200101-old").is_dir()


def test_application_recovery_folder_names_carry_their_date(tmp_path):
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    provider = MemorySigningKeyProvider("archhub.local.relationship-authority", b"r" * 32)
    provider.add_key("archhub.local.court-attestation", b"c" * 32)
    server = ApplicationServer(universal_state_path=tmp_path / "graph.sqlite3", universal_key_provider=provider,
        enable_machine_transport=False, enable_universal_cloud_gateway=False, live_watch=False).start()
    try:
        recovery = server.conversation_content.backup_recovery(tmp_path / "backups",
            authentication_context=server.universal_registry.authorization.session.context(),
            timeout_seconds=60.0)
    finally:
        server.close()
    assert re.fullmatch(r"application-recovery-[0-9]{8}-[0-9a-f]{32}", recovery.name), recovery.name
    assert recovery.name.split("-")[2] == date.today().strftime("%Y%m%d")


def test_the_launcher_applies_retention_after_each_verified_backup():
    source = LAUNCHER.read_text(encoding="utf-8")
    startup = source.index("checked post-construction recovery saved")
    armed = source.index("arm_update(state_dir")
    for anchor in (startup, armed):
        assert "_prune_backups(state_dir / \"backups\", recovery)" in source[anchor:anchor + 400], anchor
