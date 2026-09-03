"""A dead browser session must not stay resident.

Courting the absence: every sign-in put a binding -- which pins a held
interaction projection -- into an in-process dict, and nothing ever took
one out until shutdown. A boot loop that signed in once per reload grew
the owner by one pinned projection per attempt, forever. The court holds
that minting a session buries the sessions whose graph state is no longer
active.
"""
from __future__ import annotations

from nodelang.application_server import ApplicationServer
from nodelang.cell_browser_sessions import revoke_browser_session


def test_minting_a_session_prunes_bindings_whose_graph_session_died():
    server = ApplicationServer().start()
    try:
        context = server.universal_registry.authorization.broker.\
            mint_authenticated_context(
                server.universal_registry.authorization.subject_root,
                tenant_root=server.universal_registry.authorization.tenant_root,
                assurance_root=(
                    server.universal_registry.authorization.assurance_root
                ),
                lifetime_seconds=600,
            )
        baseline = len(server._browser_sessions)
        first_token, _csrf = server.issue_browser_session(context)
        assert len(server._browser_sessions) == baseline + 1
        first_binding = next(
            binding for binding in server._browser_sessions.values()
            if binding.csrf_token == _csrf
        )
        revoke_browser_session(
            server.universal_store,
            server.universal_registry.browser_session_protocol,
            first_binding.session_root,
            reason="the court closes the first session",
        )
        # The dict still holds the corpse; only the next mint may bury it.
        assert len(server._browser_sessions) == baseline + 1
        server.issue_browser_session(context)
        roots = [
            binding.session_root
            for binding in server._browser_sessions.values()
        ]
        assert first_binding.session_root not in roots, (
            "a revoked session's binding stayed resident"
        )
    finally:
        server.shutdown() if hasattr(server, "shutdown") else None
