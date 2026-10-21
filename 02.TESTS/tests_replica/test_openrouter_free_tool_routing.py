import io
import json
import urllib.error

import pytest

from nodelang import model_router


class _Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False


@pytest.fixture(autouse=True)
def _reset_tool_catalogue_cache():
    model_router._reset_openrouter_free_tool_catalogue_cache()
    yield
    model_router._reset_openrouter_free_tool_catalogue_cache()


class _Wire:
    def __init__(self, payloads, *, catalogue_rows=(), catalogue_error=None):
        self.payloads = list(payloads)
        self.catalogue_rows = list(catalogue_rows)
        self.catalogue_error = catalogue_error
        self.sent = []

    def __call__(self, request, timeout=None):
        self.sent.append(request)
        if request.get_method() == "GET" and "openrouter.ai/api/v1/models" in request.full_url:
            if self.catalogue_error is not None:
                raise self.catalogue_error
            return _Answer(json.dumps({"data": self.catalogue_rows}).encode("utf-8"))
        return _Answer(json.dumps(self.payloads.pop(0)).encode("utf-8"))

    @property
    def chat_requests(self):
        return [request for request in self.sent if getattr(request, "data", None)]

    def chat_body(self, index):
        return json.loads(self.chat_requests[index].data.decode("utf-8"))


def _tool_schema():
    return [{
        "type": "function",
        "function": {"name": "read.first", "parameters": {"type": "object"}},
    }]


def _chat_payload(text="ok", *, model="dots-studio/dots-3-note-preview:free"):
    return {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "model": model,
        "usage": {"cost": 0},
    }


def _catalogue_row(
    model,
    *,
    tools=True,
    input_modalities=("text",),
    output_modalities=("text",),
):
    return {
        "id": model,
        "pricing": {"prompt": "0", "completion": "0", "request": "0", "image": "0"},
        "architecture": {
            "input_modalities": list(input_modalities),
            "output_modalities": list(output_modalities),
        },
        "supported_parameters": ["tools"] if tools else [],
    }


def _tool_catalogue(*models):
    return [_catalogue_row(model) for model in models]


def test_openrouter_free_tool_turn_starts_with_tool_capable_free_model():
    wire = _Wire([_chat_payload()], catalogue_rows=_tool_catalogue(
        "dots-studio/dots-3-note-preview:free",
    ))

    result = model_router.route_chat(
        "openrouter/free",
        [{"role": "user", "content": "go"}],
        opener=wire,
        environ={"OPENROUTER_API_KEY": "fixture"},
        secrets_loader=lambda _: "",
        cloud_session={},
        free_only=True,
        tools=_tool_schema(),
    )

    body = wire.chat_body(0)
    assert result["ok"] is True
    assert body["model"] == "dots-studio/dots-3-note-preview:free"
    assert body["model"] != "openrouter/free"
    assert body["tools"] == _tool_schema()


def test_openrouter_free_tool_turn_rotates_after_429():
    sent = []

    catalogue = _tool_catalogue(
        "dots-studio/dots-3-note-preview:free",
        "cohere/north-mini-code:free",
    )

    def opener(request, timeout=None):
        if request.get_method() == "GET" and "openrouter.ai/api/v1/models" in request.full_url:
            return _Answer(json.dumps({"data": catalogue}).encode("utf-8"))
        sent.append(json.loads(request.data.decode("utf-8"))["model"])
        if len(sent) == 1:
            raise urllib.error.HTTPError(
                model_router.OPENROUTER_CHAT,
                429,
                "Too Many Requests",
                {},
                io.BytesIO(b'{"error":{"message":"rate limited","code":429}}'),
            )
        return _Answer(json.dumps(_chat_payload("second", model=sent[-1])).encode("utf-8"))

    result = model_router.route_chat(
        "openrouter/free",
        [{"role": "user", "content": "go"}],
        opener=opener,
        environ={"OPENROUTER_API_KEY": "fixture"},
        secrets_loader=lambda _: "",
        cloud_session={},
        free_only=True,
        tools=_tool_schema(),
    )

    assert result["text"] == "second"
    assert sent == [
        "dots-studio/dots-3-note-preview:free",
        "cohere/north-mini-code:free",
    ]


def test_openrouter_free_tool_turn_exhausts_once_after_three_failures():
    sent = []

    catalogue = _tool_catalogue(
        "dots-studio/dots-3-note-preview:free",
        "cohere/north-mini-code:free",
        "nvidia/nemotron-3.5-lightning:free",
    )

    def opener(request, timeout=None):
        if request.get_method() == "GET" and "openrouter.ai/api/v1/models" in request.full_url:
            return _Answer(json.dumps({"data": catalogue}).encode("utf-8"))
        sent.append(json.loads(request.data.decode("utf-8"))["model"])
        raise urllib.error.HTTPError(
            model_router.OPENROUTER_CHAT,
            429,
            "Too Many Requests",
            {},
            io.BytesIO(b'{"error":{"message":"rate limited","code":429}}'),
        )

    try:
        model_router.route_chat(
            "openrouter/free",
            [{"role": "user", "content": "go"}],
            opener=opener,
            environ={"OPENROUTER_API_KEY": "fixture"},
            secrets_loader=lambda _: "",
            cloud_session={},
            free_only=True,
            tools=_tool_schema(),
        )
    except model_router.ModelRouteRefused as exc:
        failure = exc
    else:
        raise AssertionError("expected free tool route exhaustion")

    assert failure.reason_code == "free_model_exhausted"
    assert sent == [
        "dots-studio/dots-3-note-preview:free",
        "cohere/north-mini-code:free",
        "nvidia/nemotron-3.5-lightning:free",
    ]


def test_openrouter_free_tool_turn_never_sends_tools_to_non_tool_model():
    wire = _Wire([], catalogue_rows=_tool_catalogue(
        "dots-studio/dots-3-note-preview:free",
    ))

    def opener(request, timeout=None):
        return wire(request, timeout=timeout)

    try:
        model_router.route_chat(
            "openrouter/liquid/lfm-2.5-2.6b:free",
            [{"role": "user", "content": "go"}],
            opener=opener,
            environ={"OPENROUTER_API_KEY": "fixture"},
            secrets_loader=lambda _: "",
            cloud_session={},
            free_only=True,
            tools=_tool_schema(),
        )
    except model_router.ModelRouteRefused as exc:
        failure = exc
    else:
        raise AssertionError("expected non-tool free model refusal")

    assert failure.reason_code == "non_chat_model"
    assert wire.chat_requests == []


def test_openrouter_free_tool_turn_empty_catalogue_refuses_without_dispatch():
    dispatched = []
    wire = _Wire([], catalogue_rows=[])

    with pytest.raises(model_router.ModelRouteRefused) as failure:
        model_router.route_chat(
            "openrouter/free",
            [{"role": "user", "content": "go"}],
            opener=wire,
            environ={"OPENROUTER_API_KEY": "fixture"},
            secrets_loader=lambda _: "",
            cloud_session={},
            free_only=True,
            tools=_tool_schema(),
            before_dispatch=lambda: dispatched.append(True),
        )

    assert failure.value.reason_code == "free_model_exhausted"
    assert wire.chat_requests == []
    assert dispatched == []


def test_openrouter_free_tool_turn_skips_default_model_decapabled_in_catalogue():
    wire = _Wire([_chat_payload(model="cohere/north-mini-code:free")], catalogue_rows=[
        _catalogue_row("dots-studio/dots-3-note-preview:free", tools=False),
        _catalogue_row("cohere/north-mini-code:free", tools=True),
    ])

    result = model_router.route_chat(
        "openrouter/free",
        [{"role": "user", "content": "go"}],
        opener=wire,
        environ={"OPENROUTER_API_KEY": "fixture"},
        secrets_loader=lambda _: "",
        cloud_session={},
        free_only=True,
        tools=_tool_schema(),
    )

    assert result["ok"] is True
    assert wire.chat_body(0)["model"] == "cohere/north-mini-code:free"


def test_openrouter_free_tool_turn_first_fetch_failure_without_cache_refuses_without_dispatch():
    dispatched = []
    wire = _Wire([_chat_payload()], catalogue_error=urllib.error.URLError("offline"))

    with pytest.raises(model_router.ModelRouteRefused) as failure:
        model_router.route_chat(
            "openrouter/free",
            [{"role": "user", "content": "go"}],
            opener=wire,
            environ={"OPENROUTER_API_KEY": "fixture"},
            secrets_loader=lambda _: "",
            cloud_session={},
            free_only=True,
            tools=_tool_schema(),
            before_dispatch=lambda: dispatched.append(True),
        )

    assert failure.value.reason_code == "free_model_exhausted"
    assert wire.chat_requests == []
    assert dispatched == []
