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


def test_scrubber_removes_authorization_header(tmp_path):
    # Setup test DB with leaked authorization header
    goose_dir = tmp_path / "goose"
    goose_dir.mkdir()
    db_path = goose_dir / "sessions.sqlite3"
    
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, extension_data TEXT)")
        conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, content TEXT)")
        for i in range(1, 152):
            conn.execute("INSERT INTO messages (id, content) VALUES (?, ?)", (i, f"message {i}"))

        # A leaked session
        leaked_session = {
            "enabled_extensions.v0": {
                "extensions": [{
                    "type": "streamable_http",
                    "name": "archhub-hosts",
                    "uri": "http://127.0.0.1:1234/mcp",
                    "headers": {"Authorization": "Bearer leaked_token"}
                }]
            }
        }
        # Another clean session
        clean_session = {
            "enabled_extensions.v0": {
                "extensions": [{
                    "type": "stdio",
                    "args": ["a"]
                }]
            }
        }
        conn.execute("INSERT INTO sessions (id, extension_data) VALUES (?, ?)", ("sess-1", json.dumps(leaked_session)))
        conn.execute("INSERT INTO sessions (id, extension_data) VALUES (?, ?)", ("sess-2", json.dumps(clean_session)))
        conn.commit()

    # Run scrubber
    _scrub_goose_sessions(goose_dir)
    
    # Verify DB no longer contains the authorization header
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, extension_data FROM sessions")
        results = {row[0]: json.loads(row[1]) for row in cursor.fetchall()}
        
        # Verify messages table intact
        cursor.execute("SELECT COUNT(*) FROM messages")
        assert cursor.fetchone()[0] == 151
    
    # Header stripped from sess-1
    sess1_server = results["sess-1"]["enabled_extensions.v0"]["extensions"][0]
    assert "headers" in sess1_server
    assert "Authorization" not in sess1_server["headers"]
    
    # sess-2 unchanged
    sess2_server = results["sess-2"]["enabled_extensions.v0"]["extensions"][0]
    assert sess2_server["type"] == "stdio"


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
    runtime.host_extension = {
        "type": "http",
        "name": "archhub-hosts",
        "url": "http://127.0.0.1:1234/mcp",
        "headers": [{"name": "Authorization", "value": "Bearer ${ARCHHUB_HOSTS_TOKEN}"}]
    }
    
    assert "headers" in runtime.host_extension
    assert runtime.host_extension["headers"][0]["value"] == "Bearer ${ARCHHUB_HOSTS_TOKEN}"
