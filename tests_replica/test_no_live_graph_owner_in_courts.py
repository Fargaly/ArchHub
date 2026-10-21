"""The whole court suite starts with no path to the live graph owner (:8474)."""
import pytest

from nodelang import workspace_roots_catalogue as roots
from nodelang.universal_cell import InvalidCell


def test_the_suite_default_context_refuses_before_any_request():
    assert roots.graph_context is not roots._default_graph_context
    with pytest.raises(AssertionError, match="live coordination service"):
        roots.graph_context()


def test_an_unpinned_admission_fails_closed_without_touching_the_live_service():
    with pytest.raises(InvalidCell, match="unavailable"):
        roots._require_graph_current({"roots": []})
