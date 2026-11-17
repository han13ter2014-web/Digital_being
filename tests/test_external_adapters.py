"""Этап 8C: разрешённый каталог, сетевые ошибки и sanitized receipts."""

import json
import math
import urllib.error

import pytest

from src.core.external_adapters import (
    MAX_WIRE_BYTES,
    RUFP_ENDPOINT,
    ExternalAdapterError,
    ExternalChatAdapter,
    available_models,
)
from src.core.external_contacts import MAX_TEXT_CHARS


def _response(text="Привет! Рада знакомству.", **extra):
    return {
        "id": "chatcmpl-fixture",
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 7, "total_tokens": 27},
        "billing": {"cost_rub": 0.01, "authorization": "must-not-survive"},
        **extra,
    }


def _adapter(transport, **kwargs):
    kwargs.setdefault("model", "rufp/default")
    return ExternalChatAdapter(
        "rufp",
        credential_loader=lambda provider: "dummy-api-secret",
        transport=transport,
        **kwargs,
    )


def test_catalog_rejects_arbitrary_provider_model_and_limits():
    assert available_models("rufp") == ("rufp/default",)
    with pytest.raises(ExternalAdapterError, match="unsupported_provider"):
        available_models("example")
    with pytest.raises(ExternalAdapterError, match="unsupported_model"):
        _adapter(lambda **kwargs: _response(), model="https://example.invalid")
    with pytest.raises(ValueError):
        _adapter(lambda **kwargs: _response(), max_tokens=0)
    with pytest.raises(ValueError):
        _adapter(lambda **kwargs: _response(), timeout=0)


def test_fixed_endpoint_payload_and_sanitized_receipt():
    calls = []

    def transport(**kwargs):
        calls.append(kwargs)
        return _response()

    receipt = _adapter(transport, max_tokens=77).send(
        session_id="external-1", message_id="out-1", text="Привет"
    )

    assert receipt == {
        "status": "sent",
        "external_message_id": "chatcmpl-fixture",
        "response_text": "Привет! Рада знакомству.",
        "model": "rufp/default",
        "usage": {"prompt_tokens": 20, "completion_tokens": 7, "total_tokens": 27},
        "billing": {"cost_rub": 0.01},
    }
    request = calls[0]
    assert request["url"] == RUFP_ENDPOINT
    assert request["payload"]["model"] == "rufp/default"
    assert request["payload"]["stream"] is False
    assert request["payload"]["max_tokens"] == 77
    assert "tools" not in request["payload"]
    assert request["payload"]["messages"][-1] == {
        "role": "user",
        "content": "Привет",
    }
    assert request["headers"]["Authorization"] == "Bearer dummy-api-secret"


def test_history_is_bounded_and_never_shared_between_sessions():
    payloads = []

    def transport(**kwargs):
        payloads.append(kwargs["payload"])
        return _response()

    adapter = _adapter(transport)
    for index in range(8):
        adapter.send(
            session_id="session-a", message_id=f"out-{index}", text=f"Вопрос {index}"
        )
    adapter.send(session_id="session-b", message_id="out-b", text="Другой диалог")

    first_user_messages = [
        item for item in payloads[-2]["messages"] if item["role"] == "user"
    ]
    assert len(payloads[-2]["messages"]) == 14
    assert first_user_messages[0]["content"] == "Вопрос 1"
    assert payloads[-1]["messages"][-1]["content"] == "Другой диалог"
    assert all(
        item.get("content") != "Вопрос 7"
        for item in payloads[-1]["messages"]
        if item["role"] != "system"
    )


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "authentication_failed"),
        (403, "authentication_failed"),
        (429, "rate_limited"),
        (500, "provider_unavailable"),
        (503, "provider_unavailable"),
        (307, "redirect_rejected"),
        (400, "http_error"),
    ],
)
def test_http_errors_are_sanitized(status, code):
    def transport(**kwargs):
        raise urllib.error.HTTPError(
            url=kwargs["url"],
            code=status,
            msg="dummy-api-secret must not escape",
            hdrs=None,
            fp=None,
        )

    with pytest.raises(ExternalAdapterError) as caught:
        _adapter(transport).send(session_id="s", message_id="m", text="Текст")
    assert caught.value.code == code
    assert "dummy-api-secret" not in str(caught.value)


@pytest.mark.parametrize("error", [TimeoutError(), urllib.error.URLError("offline")])
def test_timeout_and_network_errors_are_sanitized(error):
    def transport(**kwargs):
        raise error

    with pytest.raises(ExternalAdapterError) as caught:
        _adapter(transport).send(session_id="s", message_id="m", text="Текст")
    assert caught.value.code in {"timeout", "network_error"}
    assert "offline" not in str(caught.value)


@pytest.mark.parametrize(
    ("response", "code"),
    [
        ({}, "empty_response"),
        ({"choices": []}, "empty_response"),
        ({"choices": [{"message": {"content": ""}}]}, "empty_response"),
        ({"choices": [{"message": {"content": None}}]}, "empty_response"),
        (
            {"choices": [{"message": {"content": "x" * (MAX_TEXT_CHARS + 1)}}]},
            "response_too_long",
        ),
    ],
)
def test_malformed_empty_and_long_responses_are_rejected(response, code):
    with pytest.raises(ExternalAdapterError) as caught:
        _adapter(lambda **kwargs: response).send(
            session_id="s", message_id="m", text="Текст"
        )
    assert caught.value.code == code


def test_unexpected_transport_exception_does_not_expose_details():
    def transport(**kwargs):
        raise RuntimeError("dummy-api-secret")

    with pytest.raises(ExternalAdapterError, match="transport_failed") as caught:
        _adapter(transport).send(session_id="s", message_id="m", text="Текст")
    assert "dummy-api-secret" not in str(caught.value)


def test_usage_and_billing_drop_invalid_or_secret_values():
    response = _response(
        usage={"prompt_tokens": -1, "completion_tokens": True, "total_tokens": 9},
        billing={
            "finite": 1.5,
            "infinite": math.inf,
            "nested": {"token": "hidden", "ok": 2},
        },
    )
    receipt = _adapter(lambda **kwargs: response).send(
        session_id="s", message_id="m", text="Текст"
    )
    assert receipt["usage"] == {"total_tokens": 9}
    assert receipt["billing"] == {"finite": 1.5, "nested": {"ok": 2}}


def test_default_wire_parser_rejects_invalid_json_and_oversize(monkeypatch):
    from src.core import external_adapters as module

    class Response:
        status = 200

        def __init__(self, raw):
            self.raw = raw

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return self.raw

    class Opener:
        def __init__(self, raw):
            self.raw = raw

        def open(self, request, timeout):
            return Response(self.raw)

    monkeypatch.setattr(
        module.urllib.request, "build_opener", lambda *args: Opener(b"not-json")
    )
    with pytest.raises(ExternalAdapterError, match="invalid_response"):
        module._urllib_transport(url=RUFP_ENDPOINT, payload={}, headers={}, timeout=1.0)

    monkeypatch.setattr(
        module.urllib.request,
        "build_opener",
        lambda *args: Opener(b"x" * (MAX_WIRE_BYTES + 1)),
    )
    with pytest.raises(ExternalAdapterError, match="response_too_large"):
        module._urllib_transport(url=RUFP_ENDPOINT, payload={}, headers={}, timeout=1.0)


def test_no_redirect_handler_is_installed(monkeypatch):
    from src.core import external_adapters as module

    seen = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return json.dumps(_response()).encode("utf-8")

    class Opener:
        def open(self, request, timeout):
            return Response()

    def build_opener(*handlers):
        seen.extend(handlers)
        return Opener()

    monkeypatch.setattr(module.urllib.request, "build_opener", build_opener)
    result = module._urllib_transport(
        url=RUFP_ENDPOINT, payload={}, headers={}, timeout=1.0
    )
    assert result["choices"]
    assert len(seen) == 1
    assert isinstance(seen[0], module._NoRedirectHandler)
    assert seen[0].redirect_request(None, None, 307, "", {}, "https://evil") is None


def test_request_token_upper_bound_matches_wire_payload_without_mutation():
    calls = []

    def transport(**kwargs):
        calls.append(kwargs)
        return _response()

    adapter = _adapter(transport, max_tokens=77)
    bound = adapter.request_token_upper_bound(session_id="external-1", text="Привет")

    assert adapter._histories == {}
    assert calls == []
    adapter.send(session_id="external-1", message_id="out-1", text="Привет")
    wire_bytes = json.dumps(calls[0]["payload"], ensure_ascii=False).encode("utf-8")
    assert bound == len(wire_bytes) + 77
