"""Tests for math.op + text.op engines (slice J)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows.nodes import math_text  # noqa: F401
from workflows.registry import get as registry_get  # noqa: E402


# ---------------------------------------------------------------------------
# math.op


@pytest.fixture
def math_ex():
    _, ex = registry_get("math.op")
    return ex


@pytest.mark.parametrize("op, a, b, expected", [
    ("add", 2, 3, 5),
    ("add", 1.5, 2.5, 4.0),
    ("sub", 10, 4, 6),
    ("mul", 3, 7, 21),
    ("div", 10, 4, 2.5),
    ("mod", 10, 3, 1),
    ("pow", 2, 8, 256),
])
def test_math_binary_numeric(math_ex, op, a, b, expected):
    r = math_ex({"op": op}, {"a": a, "b": b}, None)
    assert r["value"] == expected


@pytest.mark.parametrize("op, a, expected", [
    ("round", 3.6, 4),
    ("round", 3.4, 3),
    ("abs", -7, 7),
    ("neg", 5, -5),
    ("ceil", 3.1, 4),
    ("floor", 3.9, 3),
])
def test_math_unary(math_ex, op, a, expected):
    r = math_ex({"op": op}, {"a": a, "b": None}, None)
    assert r["value"] == expected


@pytest.mark.parametrize("op, a, b, expected", [
    ("eq", 5, 5, True),
    ("eq", 5, 4, False),
    ("neq", 5, 4, True),
    ("gt", 5, 4, True),
    ("gt", 4, 5, False),
    ("lt", 4, 5, True),
    ("gte", 5, 5, True),
    ("lte", 4, 5, True),
])
def test_math_compare(math_ex, op, a, b, expected):
    r = math_ex({"op": op}, {"a": a, "b": b}, None)
    assert r["value"] is expected


@pytest.mark.parametrize("op, a, b, expected", [
    ("and", True, True, True),
    ("and", True, False, False),
    ("or", True, False, True),
    ("or", False, False, False),
    ("xor", True, False, True),
    ("xor", True, True, False),
    ("not", True, None, False),
    ("not", False, None, True),
    ("not", "", None, True),    # falsy string
    ("not", "x", None, False),  # truthy string
])
def test_math_logic(math_ex, op, a, b, expected):
    r = math_ex({"op": op}, {"a": a, "b": b}, None)
    assert r["value"] is expected


def test_math_div_by_zero_is_nan(math_ex):
    r = math_ex({"op": "div"}, {"a": 10, "b": 0}, None)
    assert math.isnan(r["value"])


def test_math_unknown_op_surfaces_error(math_ex):
    r = math_ex({"op": "magic"}, {"a": 1, "b": 2}, None)
    assert r["value"] is None
    assert "unknown" in r["error"].lower()


def test_math_default_op_is_add(math_ex):
    r = math_ex({}, {"a": 1, "b": 2}, None)
    assert r["value"] == 3


def test_math_coerces_strings_to_numbers(math_ex):
    r = math_ex({"op": "add"}, {"a": "3", "b": "4"}, None)
    assert r["value"] == 7.0


def test_math_bool_coerces_to_one(math_ex):
    r = math_ex({"op": "add"}, {"a": True, "b": True}, None)
    assert r["value"] == 2.0


# ---------------------------------------------------------------------------
# text.op


@pytest.fixture
def text_ex():
    _, ex = registry_get("text.op")
    return ex


def test_text_concat_default_separator(text_ex):
    r = text_ex({"op": "concat"}, {"a": "hello", "b": "world"}, None)
    assert r["value"] == "helloworld"


def test_text_concat_with_separator(text_ex):
    r = text_ex({"op": "concat", "separator": " · "},
                {"a": "hello", "b": "world"}, None)
    assert r["value"] == "hello · world"


def test_text_split_default_whitespace(text_ex):
    r = text_ex({"op": "split"}, {"a": "a b c"}, None)
    assert r["value"] == ["a", "b", "c"]


def test_text_split_by_separator(text_ex):
    r = text_ex({"op": "split", "separator": ","},
                {"a": "a,b,c"}, None)
    assert r["value"] == ["a", "b", "c"]


def test_text_replace(text_ex):
    r = text_ex({"op": "replace", "pattern": "foo", "replacement": "bar"},
                {"a": "foofoo"}, None)
    assert r["value"] == "barbar"


def test_text_format_with_template(text_ex):
    r = text_ex({"op": "format", "template": "Hello {a}, {b}"},
                {"a": "world", "b": "again"}, None)
    assert r["value"] == "Hello world, again"


def test_text_match_returns_boolean(text_ex):
    r = text_ex({"op": "match", "pattern": r"\d+"},
                {"a": "v123"}, None)
    assert r["value"] is True
    r2 = text_ex({"op": "match", "pattern": r"\d+"},
                 {"a": "nope"}, None)
    assert r2["value"] is False


def test_text_upper_lower_trim_length(text_ex):
    assert text_ex({"op": "upper"}, {"a": "hi"}, None)["value"] == "HI"
    assert text_ex({"op": "lower"}, {"a": "HI"}, None)["value"] == "hi"
    assert text_ex({"op": "trim"}, {"a": "  hi  "}, None)["value"] == "hi"
    assert text_ex({"op": "length"}, {"a": "hello"}, None)["value"] == 5


def test_text_unknown_op_errors(text_ex):
    r = text_ex({"op": "encrypt"}, {"a": "x"}, None)
    assert r["value"] is None
    assert "unknown" in r["error"].lower()


def test_text_none_coerces_to_empty(text_ex):
    r = text_ex({"op": "concat"}, {"a": None, "b": "x"}, None)
    assert r["value"] == "x"


# ---------------------------------------------------------------------------
# Spec shape


@pytest.mark.parametrize("type_name", ["math.op", "text.op"])
def test_executor_registered(type_name):
    tup = registry_get(type_name)
    assert tup is not None
    spec, ex = tup
    assert callable(ex)
    assert spec.display_name
    assert {p.name for p in spec.inputs} == {"a", "b"}
    assert spec.outputs[0].name == "value"
