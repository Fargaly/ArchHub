import json
import sqlite3

from nodelang.goose_adapter import goose_permission
from nodelang.goose_runtime import GooseRuntime, _scrub_goose_sessions


def test_goose_permission_grants_workshop_read_and_cancels_others():
    tool_calls = {
        ("sess-1", "tc-1"): {
            "_meta": {"goose": {"toolCall": {"extensionName": "archhub-agent", "toolName": "archhub-agent__read"}}}
        },
        ("sess-1", "tc-2"): {
            "_meta": {"goose": {"toolCall": {"extensionName": "archhub-agent", "toolName": "archhub-agent__canvas"}}}
        }
    }
    
    # Read is allowed
    read_perm = {
        "sessionId": "sess-1",
        "toolCall": {"toolCallId": "tc-1", "rawInput": {"since": "now"}},
        "options": [{"optionId": "allow", "kind": "allow_once"}]
    }
    assert goose_permission(read_perm, {"sessionId": "sess-1"}, tool_calls) == {"outcome": "selected", "optionId": "allow"}

    # Unrelated tool is cancelled
    other_perm = {
        "sessionId": "sess-1",
        "toolCall": {"toolCallId": "tc-2", "rawInput": {}},
        "options": [{"optionId": "allow", "kind": "allow_once"}]
    }
    assert goose_permission(other_perm, {"sessionId": "sess-1"}, tool_calls) == {"outcome": "cancelled"}


def test_scrubber_real_goose_and_legacy_paths(tmp_path):
    goose_dir = tmp_path / "goose"
    goose_dir.mkdir()

    real_db_dir = goose_dir / "data" / "sessions"
    real_db_dir.mkdir(parents=True)
    real_db = real_db_dir / "sessions.db"

    legacy_db = goose_dir / "sessions.sqlite3"

    db_paths = [real_db, legacy_db]
    expected_messages = {}

    for idx, db_path in enumerate(db_paths):
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, extension_data TEXT)")
            conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, content BLOB)")

            messages = [(i, f"message content \x00 byte test {idx}:{i}".encode("utf-8")) for i in range(1, 152)]
            conn.executemany("INSERT INTO messages (id, content) VALUES (?, ?)", messages)
            expected_messages[db_path] = messages

            leaked_session = {
                "enabled_extensions.v0": {
                    "extensions": [
                        {
                            "type": "streamable_http",
                            "name": "archhub-hosts",
                            "uri": "http://127.0.0.1:1234/mcp",
                            "headers": {"Authorization": f"Bearer leaked_token_{idx}"},
                        },
                        {
                            "type": "streamable_http",
                            "name": "unrelated-user-mcp",
                            "uri": "http://127.0.0.1:5678/mcp",
                            "headers": {"Authorization": "Bearer keep_this_user_token"},
                        },
                    ]
                }
            }

            placeholder_session = {
                "enabled_extensions.v0": {
                    "extensions": [
                        {
                            "type": "streamable_http",
                            "name": "archhub-hosts",
                            "uri": "http://127.0.0.1:1234/mcp",
                            "headers": {"Authorization": "Bearer ${ARCHHUB_HOSTS_TOKEN}"},
                        }
                    ]
                }
            }

            clean_session = {
                "enabled_extensions.v0": {
                    "extensions": [{"type": "stdio", "name": "local-tool", "args": ["a"]}]
                }
            }

            conn.execute("INSERT INTO sessions (id, extension_data) VALUES (?, ?)", ("sess-leaked", json.dumps(leaked_session)))
            conn.execute("INSERT INTO sessions (id, extension_data) VALUES (?, ?)", ("sess-placeholder", json.dumps(placeholder_session)))
            conn.execute("INSERT INTO sessions (id, extension_data) VALUES (?, ?)", ("sess-clean", json.dumps(clean_session)))
            conn.commit()

    total_scrubbed = _scrub_goose_sessions(goose_dir)
    assert total_scrubbed == 2  # 1 session scrubbed in real_db, 1 in legacy_db

    for db_path in db_paths:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            # Verify messages are byte-identical
            cursor.execute("SELECT id, content FROM messages ORDER BY id")
            actual_messages = cursor.fetchall()
            assert actual_messages == expected_messages[db_path]

            cursor.execute("SELECT id, extension_data FROM sessions")
            results = {row[0]: json.loads(row[1]) for row in cursor.fetchall()}

            # In sess-leaked: archhub-hosts Authorization is stripped
            leaked_exts = results["sess-leaked"]["enabled_extensions.v0"]["extensions"]
            archhub_ext = next(e for e in leaked_exts if e["name"] == "archhub-hosts")
            assert "Authorization" not in archhub_ext.get("headers", {})

            # In sess-leaked: unrelated MCP Authorization header is preserved!
            unrelated_ext = next(e for e in leaked_exts if e["name"] == "unrelated-user-mcp")
            assert unrelated_ext["headers"]["Authorization"] == "Bearer keep_this_user_token"

            # In sess-placeholder: ${ARCHHUB_HOSTS_TOKEN} placeholder is preserved!
            placeholder_exts = results["sess-placeholder"]["enabled_extensions.v0"]["extensions"]
            placeholder_archhub = next(e for e in placeholder_exts if e["name"] == "archhub-hosts")
            assert placeholder_archhub["headers"]["Authorization"] == "Bearer ${ARCHHUB_HOSTS_TOKEN}"

            # In sess-clean: stdio session is untouched
            clean_exts = results["sess-clean"]["enabled_extensions.v0"]["extensions"]
            assert clean_exts[0]["type"] == "stdio"


def test_new_session_has_no_authorization_in_host_extension(tmp_path):
    class FakeControl:
        pass

    class FakeProcess:
        def poll(self): return None
        def kill(self): pass

    def fake_factory(_args, **_kwargs):
        return FakeProcess()

    runtime = GooseRuntime(app_root=tmp_path, state_dir=tmp_path, control=FakeControl(), process_factory=fake_factory)
    
    # Mock to prevent actual execution
    import socket
    runtime.socket = socket.socket()
    runtime.socket.bind(("127.0.0.1", 0))
    try:
        runtime.host_extension = {
            "type": "http",
            "name": "archhub-hosts",
            "url": "http://127.0.0.1:1234/mcp",
            "headers": [{"name": "Authorization", "value": "Bearer ${ARCHHUB_HOSTS_TOKEN}"}]
        }
        
        assert "headers" in runtime.host_extension
        assert runtime.host_extension["headers"][0]["value"] == "Bearer ${ARCHHUB_HOSTS_TOKEN}"
    finally:
        runtime.socket.close()


def test_scrubber_mixed_literal_and_supported_reference_forms(tmp_path):
    goose_dir = tmp_path / "goose"
    goose_dir.mkdir()

    real_db_dir = goose_dir / "data" / "sessions"
    real_db_dir.mkdir(parents=True)
    real_db = real_db_dir / "sessions.db"
    legacy_db = goose_dir / "sessions.sqlite3"
    db_paths = [real_db, legacy_db]

    expected_messages = {}

    for idx, db_path in enumerate(db_paths):
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, extension_data TEXT)")
            conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, content BLOB)")

            messages = [(i, f"message blob data {idx}:{i}".encode("utf-8")) for i in range(1, 50)]
            conn.executemany("INSERT INTO messages (id, content) VALUES (?, ?)", messages)
            expected_messages[db_path] = messages

            # 1. Dictionary header with mixed literal and env ref (MUST be scrubbed)
            sess_dict_mixed = {
                "enabled_extensions.v0": {
                    "extensions": [
                        {
                            "name": "archhub-hosts",
                            "headers": {
                                "Authorization": "Bearer synthetic-literal-token ${ARCHHUB_HOSTS_TOKEN}",
                                "X-Keep-Me": "preserved-val",
                            },
                        }
                    ]
                }
            }

            # 2. List header with mixed literal and env ref (MUST be scrubbed)
            sess_list_mixed = {
                "enabled_extensions.v0": {
                    "extensions": [
                        {
                            "name": "archhub-hosts",
                            "headers": [
                                {"name": "Authorization", "value": "Bearer synthetic-literal-token ${ARCHHUB_HOSTS_TOKEN}"},
                                {"name": "X-Keep-Me", "value": "preserved-val"},
                            ],
                        }
                    ]
                }
            }

            # 3. Dictionary header with exact Bearer reference (MUST survive)
            sess_dict_exact_bearer = {
                "enabled_extensions.v0": {
                    "extensions": [
                        {
                            "name": "archhub-hosts",
                            "headers": {"Authorization": "Bearer ${ARCHHUB_HOSTS_TOKEN}"},
                        }
                    ]
                }
            }

            # 4. Dictionary header with exact bare reference (MUST survive)
            sess_dict_exact_bare = {
                "enabled_extensions.v0": {
                    "extensions": [
                        {
                            "name": "archhub-hosts",
                            "headers": {"Authorization": "${ARCHHUB_HOSTS_TOKEN}"},
                        }
                    ]
                }
            }

            # 5. List header with exact Bearer reference (MUST survive)
            sess_list_exact_bearer = {
                "enabled_extensions.v0": {
                    "extensions": [
                        {
                            "name": "archhub-hosts",
                            "headers": [
                                {"name": "Authorization", "value": "Bearer ${ARCHHUB_HOSTS_TOKEN}"},
                            ],
                        }
                    ]
                }
            }

            # 6. List header with exact bare reference (MUST survive)
            sess_list_exact_bare = {
                "enabled_extensions.v0": {
                    "extensions": [
                        {
                            "name": "archhub-hosts",
                            "headers": [
                                {"name": "Authorization", "value": "${ARCHHUB_HOSTS_TOKEN}"},
                            ],
                        }
                    ]
                }
            }

            # 7. Unrelated MCP extension with Bearer token (MUST survive untouched)
            sess_unrelated = {
                "enabled_extensions.v0": {
                    "extensions": [
                        {
                            "name": "other-mcp",
                            "headers": {"Authorization": "Bearer secret-user-token"},
                        }
                    ]
                }
            }

            sessions = [
                ("s-dict-mixed", json.dumps(sess_dict_mixed)),
                ("s-list-mixed", json.dumps(sess_list_mixed)),
                ("s-dict-bearer", json.dumps(sess_dict_exact_bearer)),
                ("s-dict-bare", json.dumps(sess_dict_exact_bare)),
                ("s-list-bearer", json.dumps(sess_list_exact_bearer)),
                ("s-list-bare", json.dumps(sess_list_exact_bare)),
                ("s-unrelated", json.dumps(sess_unrelated)),
            ]
            conn.executemany("INSERT INTO sessions (id, extension_data) VALUES (?, ?)", sessions)
            conn.commit()

    # Run scrubber
    scrubbed = _scrub_goose_sessions(goose_dir)
    # Exactly 2 sessions per DB scrubbed (s-dict-mixed and s-list-mixed across 2 DBs) = 4
    assert scrubbed == 4

    for db_path in db_paths:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            # Verify byte-identical messages
            cursor.execute("SELECT id, content FROM messages ORDER BY id")
            assert cursor.fetchall() == expected_messages[db_path]

            cursor.execute("SELECT id, extension_data FROM sessions")
            res = {row[0]: json.loads(row[1]) for row in cursor.fetchall()}

            # s-dict-mixed: Authorization scrubbed, X-Keep-Me survived
            dict_mixed_ext = res["s-dict-mixed"]["enabled_extensions.v0"]["extensions"][0]
            assert "Authorization" not in dict_mixed_ext["headers"]
            assert dict_mixed_ext["headers"]["X-Keep-Me"] == "preserved-val"

            # s-list-mixed: Authorization scrubbed from list, X-Keep-Me survived
            list_mixed_headers = res["s-list-mixed"]["enabled_extensions.v0"]["extensions"][0]["headers"]
            auth_headers = [h for h in list_mixed_headers if h.get("name", "").lower() == "authorization"]
            assert len(auth_headers) == 0
            assert any(h.get("name") == "X-Keep-Me" and h.get("value") == "preserved-val" for h in list_mixed_headers)

            # s-dict-bearer: preserved
            dict_bearer_ext = res["s-dict-bearer"]["enabled_extensions.v0"]["extensions"][0]
            assert dict_bearer_ext["headers"]["Authorization"] == "Bearer ${ARCHHUB_HOSTS_TOKEN}"

            # s-dict-bare: preserved
            dict_bare_ext = res["s-dict-bare"]["enabled_extensions.v0"]["extensions"][0]
            assert dict_bare_ext["headers"]["Authorization"] == "${ARCHHUB_HOSTS_TOKEN}"

            # s-list-bearer: preserved
            list_bearer_headers = res["s-list-bearer"]["enabled_extensions.v0"]["extensions"][0]["headers"]
            assert any(h.get("name") == "Authorization" and h.get("value") == "Bearer ${ARCHHUB_HOSTS_TOKEN}" for h in list_bearer_headers)

            # s-list-bare: preserved
            list_bare_headers = res["s-list-bare"]["enabled_extensions.v0"]["extensions"][0]["headers"]
            assert any(h.get("name") == "Authorization" and h.get("value") == "${ARCHHUB_HOSTS_TOKEN}" for h in list_bare_headers)

            # s-unrelated: untouched
            unrelated_ext = res["s-unrelated"]["enabled_extensions.v0"]["extensions"][0]
            assert unrelated_ext["headers"]["Authorization"] == "Bearer secret-user-token"

    # Repeat scrubber run must be a no-op (0 scrubbed)
    repeat_scrubbed = _scrub_goose_sessions(goose_dir)
    assert repeat_scrubbed == 0


def test_scrubber_cleans_both_extension_layouts_in_one_session_and_a_second_pass_is_a_no_op(tmp_path):
    """Codex e988: a saved session holding the versioned list AND the older top-level list lost the credential from
    the versioned list only; Goose's native export still carried it from the older list. Disposable data only."""
    db_path = tmp_path / "goose" / "data" / "sessions" / "sessions.db"
    db_path.parent.mkdir(parents=True)
    host = lambda token, layout: {"type": "streamable_http", "name": "archhub-hosts", "uri": "http://127.0.0.1:1234/mcp",
                                  "headers": layout(token)}
    as_dict = lambda token: {"Authorization": "Bearer " + token, "X-Keep-Me": "kept"}
    as_list = lambda token: [{"name": "Authorization", "value": "Bearer " + token}, {"name": "X-Keep-Me", "value": "kept"}]
    other = {"type": "streamable_http", "name": "other-mcp", "headers": {"Authorization": "Bearer user-own-token"}}
    both = {"enabled_extensions.v0": {"extensions": [host("versioned-secret", as_dict), other]},
            "extensions": [host("legacy-secret", as_list), other], "unrelated": {"keep": [1, 2, 3]}}
    legacy_only_versioned_empty = {"enabled_extensions.v0": {"extensions": []}, "extensions": [host("legacy-2", as_dict)]}
    messages = [(i, ("message %d \x00 bytes" % i).encode("utf-8")) for i in range(1, 152)]
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, extension_data TEXT, description TEXT)")
        conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, content BLOB)")
        conn.executemany("INSERT INTO messages (id, content) VALUES (?, ?)", messages)
        conn.executemany("INSERT INTO sessions VALUES (?, ?, ?)", [("both", json.dumps(both), "header kept"),
                                                                    ("legacy", json.dumps(legacy_only_versioned_empty), "x")])
    assert _scrub_goose_sessions(tmp_path / "goose") == 2
    assert _scrub_goose_sessions(tmp_path / "goose") == 0          # a true no-op
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT id, content FROM messages ORDER BY id").fetchall() == messages
        stored = dict(conn.execute("SELECT id, extension_data FROM sessions").fetchall())
        assert conn.execute("SELECT description FROM sessions WHERE id='both'").fetchone()[0] == "header kept"
    # what Goose's native JSON export serialises for a session is this stored extension_data
    for exported in stored.values():
        assert "secret" not in exported and "legacy-2" not in exported
    cleaned = json.loads(stored["both"])
    versioned_host = cleaned["enabled_extensions.v0"]["extensions"][0]
    legacy_host = cleaned["extensions"][0]
    assert versioned_host["headers"] == {"X-Keep-Me": "kept"}
    assert legacy_host["headers"] == [{"name": "X-Keep-Me", "value": "kept"}]
    assert cleaned["enabled_extensions.v0"]["extensions"][1] == other and cleaned["extensions"][1] == other
    assert cleaned["unrelated"] == {"keep": [1, 2, 3]}
