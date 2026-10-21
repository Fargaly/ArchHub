"""The BABOOM context reader accepts exactly what the graph projects.

The reader froze at the twelve keys of an earlier lens while the projection
grew five more, so every real response was rejected as an invalid shape.
An exact contract is right; an exact contract nobody re-derives is a trap.
This court derives the expected set from the projection itself, so the two
cannot drift apart again (2026-09-07).
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

from nodelang import application_machine_transport as transport
from nodelang import universal_application as app_module

ROOT = Path(__file__).resolve().parents[1]


def _projected_context_keys() -> set[str]:
    """The literal keys of the dict project_universal_baboom_context returns."""
    source = inspect.getsource(app_module.project_universal_baboom_context)
    tree = ast.parse(source.lstrip())
    returns = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
    ]
    assert len(returns) == 1, "the lens must have one literal return shape"
    keys = set()
    for key in returns[0].value.keys:
        assert isinstance(key, ast.Constant) and isinstance(key.value, str)
        keys.add(key.value)
    return keys


def _reader_expected_keys() -> set[str]:
    source = inspect.getsource(transport.UniversalRuntimeClient.baboom_context)
    tree = ast.parse(source.lstrip())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "expected"
                for target in node.targets
            )
            and isinstance(node.value, ast.Set)
        ):
            return {
                element.value for element in node.value.elts
                if isinstance(element, ast.Constant)
            }
    raise AssertionError("baboom_context must state its expected key set")


def test_the_reader_expects_exactly_what_the_lens_projects():
    projected = _projected_context_keys()
    expected = _reader_expected_keys()
    assert expected == projected, (
        "the reader expects %s; the lens projects %s"
        % (sorted(expected - projected), sorted(projected - expected))
    )


def test_the_reader_still_refuses_a_shape_it_did_not_ask_for():
    """Widening the contract must not turn it into no contract at all."""
    source = inspect.getsource(transport.UniversalRuntimeClient.baboom_context)
    assert "if set(result) != expected:" in source
    assert "BABOOM context response shape is invalid" in source
