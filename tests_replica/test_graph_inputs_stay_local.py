"""A graph is data anyone can hand you: its file inputs must be local files, and
what leaves for the cockpit shows file names, never machine paths."""
from pathlib import Path

import pytest

from nodelang.pipeline_engines import _local_input_path
from nodelang.universal_pipeline import _public_value, sample_input


@pytest.mark.parametrize("bad", ["//evil/share/x.dxf", "smb://evil/x", "file://x", ""])
def test_network_or_empty_inputs_are_refused(bad):
    with pytest.raises(ValueError):
        _local_input_path(bad, label="file_path")


def test_a_local_existing_file_is_admitted(tmp_path):
    f = tmp_path / "a.dxf"
    f.write_text("x", encoding="utf-8")
    assert _local_input_path(str(f), label="file_path") == str(f)


def test_a_bundled_sample_reference_is_resolved_to_the_shipped_file():
    reference = sample_input("sample-plan.png")
    assert reference == "samples/sample-plan.png"
    resolved = Path(_local_input_path(reference, label="image_path"))
    assert resolved.name == "sample-plan.png"
    assert resolved.parent.name == "samples"
    assert resolved.is_file()


def test_a_user_relative_samples_path_is_not_taken_for_a_bundled_sample(tmp_path, monkeypatch):
    # Only files the app ships are sample references; the user's own samples/ folder keeps its meaning.
    from nodelang.universal_pipeline import resolve_sample_input
    assert resolve_sample_input("samples/my-own-plan.png") is None
    assert resolve_sample_input("samples/sub/sample-plan.png") is None
    assert resolve_sample_input("samples/../universal_pipeline.py") is None
    monkeypatch.chdir(tmp_path)
    (tmp_path / "samples").mkdir()
    own = tmp_path / "samples" / "my-own-plan.png"
    own.write_text("x", encoding="utf-8")
    assert Path(_local_input_path("samples/my-own-plan.png", label="image_path")).resolve() == own.resolve()


def test_a_missing_local_file_is_refused(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        _local_input_path(str(tmp_path / "missing.dxf"), label="file_path")


def test_published_values_carry_file_names_not_paths():
    assert _public_value("image_path", "C:" + chr(92) + "Users" + chr(92) + "x" + chr(92) + "plan.png") == "plan.png"
    assert _public_value("note", "D:" + chr(92) + "y" + chr(92) + "z.dxf") == "z.dxf"
    assert _public_value("file_path", "//server/share/a.dxf") == "a.dxf"
    assert _public_value("title", "Ground floor") == "Ground floor"
