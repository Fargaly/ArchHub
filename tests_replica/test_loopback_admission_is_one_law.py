"""DNS rebinding makes an attacker's page same-origin; only Host tells the truth.
One admission, applied by every loopback surface."""
import inspect

from nodelang.http_server import local_browser_admission_error


def test_loopback_host_without_origin_is_admitted():
    assert local_browser_admission_error({"Host": "127.0.0.1:8080"}, 8080) is None
    assert local_browser_admission_error(
        {"Host": "localhost:8080", "Origin": "http://localhost:8080"}, 8080) is None


def test_rebound_host_is_denied_even_when_origin_looks_local():
    assert local_browser_admission_error({"Host": "evil.example:8080"}, 8080) == "host denied"
    assert local_browser_admission_error(
        {"Host": "127.0.0.1:8080", "Origin": "http://evil.example"}, 8080) == "origin denied"
    assert local_browser_admission_error({"Host": "127.0.0.1:9999"}, 8080) == "host denied"


def test_every_loopback_surface_calls_the_one_admission():
    import nodelang.application_server as app_srv
    import nodelang.runtime_gateway as gw
    src = inspect.getsource(app_srv)
    assert src.count("local_browser_admission_error(") >= 3, "clean handler + do_GET + do_POST"
    gsrc = inspect.getsource(gw)
    fwd = gsrc.index("def _forward(self):")
    assert gsrc.index("local_browser_admission_error(", fwd) < gsrc.index('headers["Host"] = ', fwd)
