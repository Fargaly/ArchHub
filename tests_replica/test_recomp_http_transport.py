"""Transport construction and physical graph reads have one owner each."""
import sqlite3

import pytest

from nodelang import http_server, universal_cell


@pytest.mark.parametrize("threaded", [False, True])
def test_transport_owner_preserves_the_callers_concurrency_policy(monkeypatch, threaded):
    calls = []
    handler = object()
    result = object()

    def synchronous(address, request_handler):
        calls.append((False, address, request_handler))
        return result

    def concurrent(address, request_handler):
        calls.append((True, address, request_handler))
        return result

    monkeypatch.setattr(http_server, "HTTPServer", synchronous, raising=False)
    monkeypatch.setattr(http_server, "ThreadingHTTPServer", concurrent)
    assert http_server.create_http_server(("127.0.0.1", 0), handler,
                                          threaded=threaded) is result
    assert calls == [(threaded, ("127.0.0.1", 0), handler)]


def test_readonly_graph_opener_cannot_create_a_missing_journal(tmp_path):
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        universal_cell.open_read_only_cell_journal(missing)
    assert not missing.exists()


def test_readonly_graph_opener_encodes_paths_and_never_claims_write_ownership(tmp_path):
    path = tmp_path / "graph # percent %.sqlite3"
    owner = universal_cell.CellStore(path)
    try:
        before = path.read_bytes()
        connection = universal_cell.open_read_only_cell_journal(
            path, timeout=0.2, isolation_level=None)
        try:
            assert connection.isolation_level is None
            assert connection.execute("PRAGMA query_only").fetchone() == (1,)
            assert connection.execute("PRAGMA busy_timeout").fetchone() == (200,)
            assert connection.execute("SELECT COUNT(*) FROM revisions").fetchone() == (1,)
            with pytest.raises(sqlite3.OperationalError):
                connection.execute("CREATE TABLE forbidden (value)")
            assert path.read_bytes() == before
            # The real owner can still write while the observer is connected.
            owner.commit(owner.revision, create=[universal_cell.Cell(
                "owner-write", universal_cell.NULL_CELL_ID,
                universal_cell.NULL_CELL_ID, b"owner remains writable")])
            assert connection.execute("SELECT COUNT(*) FROM revisions").fetchone() == (2,)
        finally:
            connection.close()
        assert owner.revision == 1
    finally:
        owner.close()
