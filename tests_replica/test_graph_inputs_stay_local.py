"""A graph is data anyone can hand you: its file inputs must be local files, and
what leaves for the cockpit shows file names, never machine paths."""
import pytest

from nodelang.pipeline_engines import _local_input_path
from nodelang.universal_pipeline import _public_value


@pytest.mark.parametrize("bad", ["//evil/share/x.dxf", "smb://evil/x", "file://x", ""])
def test_network_or_empty_inputs_are_refused(bad):
    with pytest.raises(ValueError):
        _local_input_path(bad, label="file_path")


def test_a_local_existing_file_is_admitted(tmp_path):
    f = tmp_path / "a.dxf"
    f.write_text("x", encoding="utf-8")
    assert _local_input_path(str(f), label="file_path") == str(f)


def test_a_missing_local_file_is_refused(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        _local_input_path(str(tmp_path / "missing.dxf"), label="file_path")


def test_published_values_carry_file_names_not_paths():
    assert _public_value("image_path", "C:" + chr(92) + "Users" + chr(92) + "x" + chr(92) + "plan.png") == "plan.png"
    assert _public_value("note", "D:" + chr(92) + "y" + chr(92) + "z.dxf") == "z.dxf"
    assert _public_value("file_path", "//server/share/a.dxf") == "a.dxf"
    assert _public_value("title", "Ground floor") == "Ground floor"
