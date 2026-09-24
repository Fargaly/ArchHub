"""'Nothing leaves this machine' is only true while the upload path is closed."""
from pathlib import Path

from nodelang.cloud_publish_consent import (
    CONSENT_FILE, cloud_publish_allowed, record_cloud_publish_consent,
)


def test_no_record_means_no_publish(tmp_path):
    assert cloud_publish_allowed(tmp_path) is False


def test_a_malformed_or_false_record_stays_closed(tmp_path):
    (tmp_path / CONSENT_FILE).write_text("not json", encoding="utf-8")
    assert cloud_publish_allowed(tmp_path) is False
    (tmp_path / CONSENT_FILE).write_text('{"publish_map": false}', encoding="utf-8")
    assert cloud_publish_allowed(tmp_path) is False


def test_an_explicit_record_opens_and_deleting_it_closes(tmp_path):
    record = record_cloud_publish_consent(tmp_path, account="founder@example.test")
    assert cloud_publish_allowed(tmp_path, "Founder@Example.test") is True
    record.unlink()
    assert cloud_publish_allowed(tmp_path, "founder@example.test") is False


def test_consent_belongs_to_the_account_that_gave_it(tmp_path):
    """Identity = account: signing out or switching accounts closes the path."""
    record_cloud_publish_consent(tmp_path, account="founder@example.test")
    assert cloud_publish_allowed(tmp_path, "founder@example.test") is True
    assert cloud_publish_allowed(tmp_path, "colleague@example.test") is False
    assert cloud_publish_allowed(tmp_path, None) is False


def test_the_launcher_checks_consent_before_any_network():
    src = (Path(__file__).resolve().parents[1] / "launch_archhub_test.py").read_text(encoding="utf-8")
    gate = src.index("cloud_publish_allowed(state_dir)")
    assert gate < src.index("urllib.request.Request(\n        base.rstrip")
    assert "no consent recorded; nothing left this machine" in src
