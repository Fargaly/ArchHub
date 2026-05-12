"""Bulk-categorise + distinct-senders macro tools.

Built to solve the local-Ollama failure mode: model calls
outlook_set_categories with no entry_id (or a placeholder string)
because it can't grasp the list→loop pattern. The two new macros
let the model express intent in ONE call and have the tool engine
execute the loop internally.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


class TestToolRegistry:
    def test_bulk_categorise_tool_registered(self):
        from tool_engine import TOOLS
        names = {t["name"] for t in TOOLS}
        assert "outlook_set_categories_by_filter" in names

    def test_distinct_senders_tool_registered(self):
        from tool_engine import TOOLS
        names = {t["name"] for t in TOOLS}
        assert "outlook_list_distinct_senders" in names

    def test_bulk_categorise_requires_categories_only(self):
        # All filter fields optional; only `categories` is required.
        from tool_engine import TOOLS
        t = next(t for t in TOOLS
                  if t["name"] == "outlook_set_categories_by_filter")
        assert t["input_schema"]["required"] == ["categories"]

    def test_bulk_categorise_description_advertises_one_call(self):
        from tool_engine import TOOLS
        t = next(t for t in TOOLS
                  if t["name"] == "outlook_set_categories_by_filter")
        desc = t["description"].lower()
        assert "bulk" in desc or "one call" in desc or "one-call" in desc
        # Mentions all filter dimensions.
        for kw in ("sender_contains", "subject_contains",
                    "days", "limit"):
            assert kw in t["description"]


class TestBulkCategoriseImpl:
    """Drives outlook_runner.set_categories_by_filter with stubbed
    COM so we don't need Outlook running for tests."""

    def test_empty_categories_returns_error(self):
        from connectors.outlook_runner import set_categories_by_filter
        with patch("connectors.outlook_runner.com_thread"):
            r = set_categories_by_filter(categories=[])
        assert r["status"] == "error"
        assert "categories" in r["error"].lower()

    def test_filter_calls_search_inner_and_loops(self):
        from connectors import outlook_runner as r
        # Stub _search_inner to return 3 fake messages.
        fake_msgs = [
            {"entry_id": f"id-{i}", "subject": f"Subj {i}",
             "sender_email": f"a{i}@studio.com"}
            for i in range(3)
        ]
        applied = []
        def fake_set(eid, cats, *, mode):
            applied.append((eid, list(cats), mode))
            return {"status": "ok", "entry_id": eid,
                    "categories": list(cats)}
        with patch("connectors.outlook_runner.com_thread"), \
             patch.object(r, "_search_inner", return_value=fake_msgs), \
             patch.object(r, "_set_categories_inner",
                           side_effect=fake_set):
            out = r.set_categories_by_filter(
                categories=["ProjectA"],
                sender_contains="@studio.com",
                limit=10,
            )
        assert out["status"] == "ok"
        assert out["matched"] == 3
        assert out["touched"] == 3
        assert applied == [
            ("id-0", ["ProjectA"], "set"),
            ("id-1", ["ProjectA"], "set"),
            ("id-2", ["ProjectA"], "set"),
        ]

    def test_per_item_errors_collected_not_fatal(self):
        from connectors import outlook_runner as r
        fake_msgs = [{"entry_id": f"id-{i}", "subject": f"S{i}"}
                     for i in range(3)]
        def fake_set(eid, cats, *, mode):
            if eid == "id-1":
                raise RuntimeError("COM blew up")
            return {"status": "ok", "entry_id": eid,
                    "categories": list(cats)}
        with patch("connectors.outlook_runner.com_thread"), \
             patch.object(r, "_search_inner", return_value=fake_msgs), \
             patch.object(r, "_set_categories_inner",
                           side_effect=fake_set):
            out = r.set_categories_by_filter(categories=["x"])
        assert out["touched"] == 2
        assert len(out["errors"]) == 1
        assert out["errors"][0]["entry_id"] == "id-1"


class TestDistinctSendersImpl:
    def test_groups_by_domain(self):
        from connectors import outlook_runner as r
        fake_msgs = [
            {"entry_id": "a", "sender_email": "a1@bayatyarchitects.com",
             "subject": "DD Set Review"},
            {"entry_id": "b", "sender_email": "a2@bayatyarchitects.com",
             "subject": "RFI 0142"},
            {"entry_id": "c", "sender_email": "info@autodesk.com",
             "subject": "Subscription renewal"},
            {"entry_id": "d", "sender_email": "ceo@autodesk.com",
             "subject": "Webinar invite"},
            {"entry_id": "e", "sender_email": "noreply@github.com",
             "subject": "Build passed"},
        ]
        with patch("connectors.outlook_runner.com_thread"), \
             patch.object(r, "_search_inner", return_value=fake_msgs):
            out = r.list_distinct_senders(days=30, limit=200)
        assert out["status"] == "ok"
        assert out["total_messages"] == 5
        assert out["distinct_domains"] == 3
        domains_by_name = {d["domain"]: d for d in out["domains"]}
        assert domains_by_name["bayatyarchitects.com"]["count"] == 2
        assert domains_by_name["autodesk.com"]["count"] == 2
        assert domains_by_name["github.com"]["count"] == 1
        # Sorted desc by count — top entry should be 2-count.
        assert out["domains"][0]["count"] == 2


class TestAutoCategoriseImpl:
    """auto_categorize_by_sender — zero-arg one-shot."""

    def test_groups_and_tags_each_domain(self):
        from connectors import outlook_runner as r
        fake_msgs = [
            {"entry_id": "a1", "sender_email": "alice@bayatyarchitects.com",
             "subject": "RFI 0142"},
            {"entry_id": "a2", "sender_email": "bob@bayatyarchitects.com",
             "subject": "DD Set"},
            {"entry_id": "b1", "sender_email": "info@autodesk.com",
             "subject": "Renewal"},
            {"entry_id": "b2", "sender_email": "ceo@autodesk.com",
             "subject": "Webinar"},
            {"entry_id": "c1", "sender_email": "noreply@github.com",
             "subject": "Build ok"},   # only 1 — should be skipped
        ]
        tagged = []
        def fake_set(eid, cats, *, mode):
            tagged.append((eid, list(cats), mode))
            return {"status": "ok", "entry_id": eid,
                    "categories": list(cats)}
        with patch("connectors.outlook_runner.com_thread"), \
             patch.object(r, "_search_inner", return_value=fake_msgs), \
             patch.object(r, "_set_categories_inner",
                           side_effect=fake_set):
            out = r.auto_categorize_by_sender(days=30, min_messages=2)
        assert out["status"] == "ok"
        # Two domains qualified (count >= 2), one skipped.
        cats_by_domain = {a["domain"]: a for a in out["categorised"]}
        assert "bayatyarchitects.com" in cats_by_domain
        assert "autodesk.com" in cats_by_domain
        assert cats_by_domain["bayatyarchitects.com"]["category"] == "Bayatyarchitects"
        assert cats_by_domain["autodesk.com"]["category"] == "Autodesk"
        assert cats_by_domain["bayatyarchitects.com"]["touched"] == 2
        # github skipped (only 1 msg).
        assert any(s["domain"] == "github.com" for s in out["skipped"])
        # 4 tag operations fired.
        assert len(tagged) == 4
        # mode='add' so we never wipe existing tags.
        assert all(mode == "add" for _, _, mode in tagged)

    def test_zero_messages_no_crash(self):
        from connectors import outlook_runner as r
        with patch("connectors.outlook_runner.com_thread"), \
             patch.object(r, "_search_inner", return_value=[]):
            out = r.auto_categorize_by_sender()
        assert out["status"] == "ok"
        assert out["total_messages"] == 0
        assert out["categorised"] == []

    def test_mail_prefix_stripped(self):
        # 'mail.archhub.app' should derive 'Archhub' not 'Mail'.
        from connectors import outlook_runner as r
        fake_msgs = [
            {"entry_id": f"x{i}", "sender_email": f"u{i}@mail.archhub.app",
             "subject": "x"} for i in range(3)
        ]
        with patch("connectors.outlook_runner.com_thread"), \
             patch.object(r, "_search_inner", return_value=fake_msgs), \
             patch.object(r, "_set_categories_inner",
                           return_value={"status": "ok"}):
            out = r.auto_categorize_by_sender(min_messages=2)
        names = [a["category"] for a in out["categorised"]]
        assert "Archhub" in names


class TestAutoCategoriseByKeywords:
    def test_keyword_matches_subject(self):
        from connectors import outlook_runner as r
        fake_msgs = [
            {"entry_id": "a", "subject": "Tower-A DD Set", "body_preview": ""},
            {"entry_id": "b", "subject": "RFI 0142 Tower-A",
             "body_preview": "Re: foundation"},
            {"entry_id": "c", "subject": "Invoice 99",
             "body_preview": "Please pay"},
        ]
        tagged = []
        def fake_set(eid, cats, *, mode):
            tagged.append((eid, list(cats), mode))
            return {"status": "ok", "entry_id": eid,
                    "categories": list(cats)}
        with patch("connectors.outlook_runner.com_thread"), \
             patch.object(r, "_search_inner", return_value=fake_msgs), \
             patch.object(r, "_set_categories_inner",
                           side_effect=fake_set):
            out = r.auto_categorize_by_subject_keywords(keyword_map={
                "Tower-A": "Tower-A",
                "Invoice": "Finance",
            })
        # Tower-A keyword should hit msgs a, b (both have Tower-A).
        # Invoice should hit c.
        # Total tags: 3 (2 for Tower-A, 1 for Finance).
        assert out["status"] == "ok"
        applied = {a["keyword"]: a for a in out["applied"]}
        assert applied["Tower-A"]["matched"] == 2
        assert applied["Invoice"]["matched"] == 1
        assert all(mode == "add" for _, _, mode in tagged)

    def test_empty_keyword_map_errors(self):
        from connectors import outlook_runner as r
        with patch("connectors.outlook_runner.com_thread"):
            out = r.auto_categorize_by_subject_keywords(keyword_map={})
        assert out["status"] == "error"


class TestSystemPromptAdvertisesBulkTool:
    def test_prompt_mentions_set_categories_by_filter(self):
        from unittest.mock import MagicMock
        import llm_router
        from tool_engine import ToolEngine
        mgr = MagicMock(); mgr.entries = []
        router = llm_router.LLMRouter(ToolEngine(mgr))
        prompt = router._build_system_prompt()
        # The macro tool must be advertised so models pick it for bulk
        # requests instead of failing on per-item loops.
        assert "set_categories_by_filter" in prompt
        assert "list_distinct_senders" in prompt
        assert "auto_categorize_by_sender" in prompt
