"""brain.list_facts returns a page, never the whole store by default.

Measured on the founder's brain: the default call scanned 54,076 rows in 88
seconds, and a thread dump caught four such calls in flight at once beside the
organize worker, every one scanning the whole store while brain.health waited
behind them and the app's watchdog concluded the daemon was dead.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from personal_brain import brain_facts
from personal_brain.storage import (
    BrainStore, Confidence, Fragment, FragmentKind, Provenance, Scope, Visibility,
)


def _fact(i: int) -> Fragment:
    return Fragment(
        id="fact-%04d" % i, kind=FragmentKind.FACT, text="fact %d" % i,
        subject="user", predicate="knows", object="thing %d" % i,
        scope=Scope.USER, visibility=Visibility.PRIVATE, owner_user="founder",
        confidence=Confidence.EXTRACTED,
        provenance=Provenance(contributing_agent="court", contributing_user="founder",
                              created_at=datetime.now(timezone.utc)),
    )


@pytest.fixture
def store(tmp_path):
    made = BrainStore.open(tmp_path / "brain.db")
    for i in range(1_200):
        made.write_fragment(_fact(i))
    yield made
    made.close()


def test_the_default_is_a_page_and_says_how_much_is_held(store):
    out = brain_facts.list_facts(store, owner_user="founder")
    assert out["ok"]
    assert out["total"] == brain_facts.DEFAULT_LIST_LIMIT, out["total"]
    assert out["held"] == 1_200
    assert out["limit"] == brain_facts.DEFAULT_LIST_LIMIT and out["offset"] == 0
    assert brain_facts.DEFAULT_LIST_LIMIT <= 1_000


def test_a_caller_that_wants_everything_says_so(store):
    out = brain_facts.list_facts(store, owner_user="founder", limit=100_000)
    assert out["total"] == 1_200


def test_pages_do_not_overlap(store):
    first = brain_facts.list_facts(store, owner_user="founder", limit=10, offset=0)
    second = brain_facts.list_facts(store, owner_user="founder", limit=10, offset=10)
    ids = lambda page: [f["id"] for folder in page["folders"] for f in folder["facts"]]
    assert len(ids(first)) == 10 and len(ids(second)) == 10
    assert not set(ids(first)) & set(ids(second))


def test_the_tool_exposes_limit_and_offset():
    import inspect

    from personal_brain import server

    source = inspect.getsource(server)
    tool = source[source.index("def brain_list_facts_tool("):]
    tool = tool[:tool.index("@mcp.tool(")]
    assert "limit: int = 500" in tool and "offset: int = 0" in tool
    assert "limit=limit, offset=offset" in tool


def test_bad_bounds_are_refused_not_guessed(store):
    out = brain_facts.list_facts(store, owner_user="founder", limit="all")
    assert out["ok"] is False and "integer" in out["error"]
