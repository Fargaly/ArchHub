"""Pinned release download retries, without network calls or real waits."""
from http.client import IncompleteRead
import io
import json
from unittest.mock import Mock, call
from urllib.error import HTTPError, URLError

import pytest

from test_betterleaks_payload import PIN, _stage_module


URL = "https://github.com/betterleaks/betterleaks/releases/download/v1.9.0/asset.zip"


class Response(io.BytesIO):
    def __init__(self, data, *, length=None):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data) if length is None else length)}


@pytest.fixture
def download(monkeypatch):
    module = _stage_module()
    opener, sleep = Mock(), Mock()
    monkeypatch.setattr(module.urllib.request, "urlopen", opener)
    monkeypatch.setattr(module.time, "sleep", sleep)
    return module, opener, sleep


def test_two_504s_then_success_starts_each_attempt_empty(download, tmp_path):
    module, opener, sleep = download
    folder = tmp_path / "download"
    folder.mkdir()
    dest = folder / "asset.zip"
    dest.write_bytes(b"old partial bytes")

    def open_attempt(request, *, timeout):
        assert request.full_url == URL and timeout == 60
        assert dest.read_bytes() == b""
        if opener.call_count < 3:
            raise HTTPError(URL, 504, "Gateway Timeout", {}, None)
        return Response(b"correct bytes")

    opener.side_effect = open_attempt
    assert module._download(URL, dest, 100) == dest
    assert dest.read_bytes() == b"correct bytes"
    assert list(folder.iterdir()) == [dest]
    assert opener.call_count == 3
    assert sleep.call_args_list == [call(5), call(15)]


@pytest.mark.parametrize("error", [ConnectionError("connection reset"), TimeoutError("timeout"),
                                 URLError("connection lost"), IncompleteRead(b"partial", 20)])
def test_partial_read_failure_then_success(download, tmp_path, error):
    module, opener, sleep = download
    broken = Response(b"partial bytes")
    broken.read = Mock(side_effect=[b"partial bytes", error])
    opener.side_effect = [broken, Response(b"ok")]
    folder = tmp_path / "download"
    folder.mkdir()
    dest = folder / "asset.zip"
    module._download(URL, dest, 100)
    assert dest.read_bytes() == b"ok"
    assert list(folder.iterdir()) == [dest]
    assert opener.call_count == 2
    sleep.assert_called_once_with(5)


def test_content_length_short_read_retries(download, tmp_path):
    module, opener, sleep = download
    opener.side_effect = [Response(b"short", length=20), Response(b"ok")]
    dest = tmp_path / "asset.zip"
    module._download(URL, dest, 100)
    assert dest.read_bytes() == b"ok"
    sleep.assert_called_once_with(5)


@pytest.mark.parametrize("code", [400, 403, 404])
def test_permanent_http_error_fails_immediately(download, tmp_path, code):
    module, opener, sleep = download
    error = HTTPError(URL, code, "refused", {}, None)
    opener.side_effect = error
    dest = tmp_path / "asset.zip"
    with pytest.raises(HTTPError) as raised:
        module._download(URL, dest, 100)
    assert raised.value is error
    assert not dest.exists()
    assert opener.call_count == 1
    sleep.assert_not_called()


def test_six_504s_raise_original_error(download, tmp_path):
    module, opener, sleep = download
    errors = [HTTPError(URL, 504, "Gateway Timeout", {}, None) for _ in range(6)]
    opener.side_effect = errors
    dest = tmp_path / "asset.zip"
    with pytest.raises(HTTPError) as raised:
        module._download(URL, dest, 100)
    assert raised.value is errors[-1] and raised.value.code == 504
    assert not dest.exists()
    assert opener.call_count == 6
    assert sleep.call_args_list == [call(seconds) for seconds in (5, 15, 30, 60, 120)]


def test_429_retries(download, tmp_path):
    module, opener, sleep = download
    opener.side_effect = [HTTPError(URL, 429, "rate limited", {}, None), Response(b"ok")]
    assert module._download(URL, tmp_path / "asset.zip", 100).read_bytes() == b"ok"
    sleep.assert_called_once_with(5)


def test_wrong_archive_hash_still_refuses(download, tmp_path):
    module, opener, sleep = download
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    checksums = (pin["sha256"] + "  " + pin["asset"] + "\n").encode()
    opener.side_effect = [Response(checksums), Response(b"wrong archive")]
    destination = tmp_path / "staged"
    with pytest.raises(ValueError, match="archive SHA-256 differs"):
        module.fetch_betterleaks(destination)
    assert not destination.exists()
    assert opener.call_count == 2
    sleep.assert_not_called()


def test_size_limit_does_not_retry(download, tmp_path):
    module, opener, sleep = download
    opener.return_value = Response(b"too big")
    with pytest.raises(ValueError, match="exceeds the pinned size"):
        module._download(URL, tmp_path / "asset.zip", 2)
    assert opener.call_count == 1
    sleep.assert_not_called()


def test_unpinned_url_never_opens(download, tmp_path):
    module, opener, sleep = download
    with pytest.raises(ValueError, match="not a pinned GitHub release"):
        module._download("https://example.com/asset.zip", tmp_path / "asset.zip", 100)
    opener.assert_not_called()
    sleep.assert_not_called()
