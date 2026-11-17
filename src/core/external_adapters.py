"""Фиксированные OpenAI-совместимые адаптеры внешних собеседников."""

from __future__ import annotations

import json
import math
import socket
from typing import Any, Callable, Dict, Mapping, Optional, Tuple
import urllib.error
import urllib.request

from src.core.external_contacts import MAX_TEXT_CHARS
from src.core.external_credentials import provider_api_key

RUFP_PROVIDER = "rufp"
RUFP_MODEL = "rufp/default"
RUFP_ENDPOINT = "https://app.rufp.ru/api/v1/llm/chat/completions"
MAX_WIRE_BYTES = 256 * 1024
MAX_HISTORY_MESSAGES = 12
MAX_COMPLETION_TOKENS = 512
_PROVIDER_CATALOG = {
    RUFP_PROVIDER: {
        "endpoint": RUFP_ENDPOINT,
        "models": (RUFP_MODEL,),
    }
}
_SECRET_PARTS = ("secret", "token", "api_key", "apikey", "authorization")


class ExternalAdapterError(RuntimeError):
    """Безопасная ошибка канала без URL, тела ответа и секретов."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def available_models(provider: str) -> Tuple[str, ...]:
    """Вернуть только встроенный каталог; произвольный endpoint не поддержан."""
    key = str(provider or "").strip().lower()
    if key not in _PROVIDER_CATALOG:
        raise ExternalAdapterError("unsupported_provider")
    return tuple(_PROVIDER_CATALOG[key]["models"])


def _safe_number(value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if abs(value) > 1_000_000_000_000:
        return None
    return value


def _safe_metadata(value: Any, *, depth: int = 0) -> Any:
    """Сохранить только ограниченные usage/billing без секретных полей."""
    number = _safe_number(value)
    if number is not None:
        return number
    if isinstance(value, str) and len(value) <= 128:
        return value
    if value is None or isinstance(value, bool):
        return value
    if depth >= 2 or not isinstance(value, Mapping):
        return None
    result = {}
    for raw_key, raw_value in list(value.items())[:32]:
        key = str(raw_key)
        if (
            not key
            or len(key) > 64
            or any(part in key.casefold() for part in _SECRET_PARTS)
        ):
            continue
        safe = _safe_metadata(raw_value, depth=depth + 1)
        if safe is not None:
            result[key] = safe
    return result


def _safe_usage(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        number = _safe_number(value.get(key))
        if isinstance(number, int) and number >= 0:
            result[key] = number
    return result


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _urllib_transport(
    *,
    url: str,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    timeout: float,
) -> Mapping[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers=dict(headers),
        method="POST",
    )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    with opener.open(request, timeout=timeout) as response:  # nosec B310
        if response.status != 200:
            raise ExternalAdapterError("unexpected_http_status")
        raw = response.read(MAX_WIRE_BYTES + 1)
    if len(raw) > MAX_WIRE_BYTES:
        raise ExternalAdapterError("response_too_large")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ExternalAdapterError("invalid_response") from None
    if not isinstance(parsed, Mapping):
        raise ExternalAdapterError("invalid_response")
    return parsed


class ExternalChatAdapter:
    """Адаптер одной модели с отдельной ограниченной историей каждой сессии."""

    def __init__(
        self,
        provider: str,
        model: str,
        *,
        timeout: float = 30.0,
        max_tokens: int = 160,
        credential_loader: Callable[[str], str] = provider_api_key,
        transport: Optional[Callable[..., Mapping[str, Any]]] = None,
    ) -> None:
        provider_key = str(provider or "").strip().lower()
        models = available_models(provider_key)
        if model not in models:
            raise ExternalAdapterError("unsupported_model")
        if isinstance(max_tokens, bool) or not 1 <= max_tokens <= MAX_COMPLETION_TOKENS:
            raise ValueError("max_tokens: expected an integer from 1 to 512")
        if not 1.0 <= float(timeout) <= 120.0:
            raise ValueError("timeout: expected a value from 1 to 120 seconds")
        self.provider = provider_key
        self.model = model
        self.timeout = float(timeout)
        self.max_tokens = max_tokens
        self._endpoint = _PROVIDER_CATALOG[provider_key]["endpoint"]
        self._credential_loader = credential_loader
        self._transport = transport or _urllib_transport
        self._histories: Dict[str, list] = {}

    def _messages(self, session_id: str, text: str) -> list:
        history = self._histories.setdefault(session_id, [])
        messages = [
            {
                "role": "system",
                "content": (
                    "Веди короткий диалог по-русски. Не запрашивай секреты, "
                    "личные данные или доступ к компьютеру собеседника."
                ),
            },
            *history,
            {"role": "user", "content": text},
        ]
        return messages

    def send(self, *, session_id: str, message_id: str, text: str) -> dict:
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
            raise ExternalAdapterError("invalid_outgoing_text")
        api_key = self._credential_loader(self.provider)
        payload = {
            "model": self.model,
            "messages": self._messages(session_id, text),
            "stream": False,
            "max_tokens": self.max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "DigitalBeing/0.1 external-dialogue",
        }
        try:
            response = self._transport(
                url=self._endpoint,
                payload=payload,
                headers=headers,
                timeout=self.timeout,
            )
        except ExternalAdapterError:
            raise
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                code = "authentication_failed"
            elif exc.code == 429:
                code = "rate_limited"
            elif 500 <= exc.code <= 599:
                code = "provider_unavailable"
            elif 300 <= exc.code <= 399:
                code = "redirect_rejected"
            else:
                code = "http_error"
            raise ExternalAdapterError(code) from None
        except (TimeoutError, socket.timeout):
            raise ExternalAdapterError("timeout") from None
        except (urllib.error.URLError, OSError):
            raise ExternalAdapterError("network_error") from None
        except Exception:
            raise ExternalAdapterError("transport_failed") from None

        try:
            choices = response.get("choices")
            choice = choices[0] if isinstance(choices, list) and choices else None
            message = choice.get("message") if isinstance(choice, Mapping) else None
            content = message.get("content") if isinstance(message, Mapping) else None
        except (AttributeError, IndexError, TypeError):
            content = None
        if not isinstance(content, str) or not content.strip():
            raise ExternalAdapterError("empty_response")
        if len(content) > MAX_TEXT_CHARS:
            raise ExternalAdapterError("response_too_long")
        content = content.strip()
        history = self._histories.setdefault(session_id, [])
        history.extend(
            [
                {"role": "user", "content": text},
                {"role": "assistant", "content": content},
            ]
        )
        del history[:-MAX_HISTORY_MESSAGES]
        external_id = response.get("id")
        if not isinstance(external_id, str) or not external_id.strip():
            external_id = None
        elif len(external_id) > 160:
            raise ExternalAdapterError("invalid_response")
        return {
            "status": "sent",
            "external_message_id": external_id,
            "response_text": content,
            "model": self.model,
            "usage": _safe_usage(response.get("usage")),
            "billing": _safe_metadata(response.get("billing")) or {},
        }


def create_external_adapter(provider: str, model: str, **kwargs) -> ExternalChatAdapter:
    """Единая точка выбора встроенного провайдера для Core и UI."""
    return ExternalChatAdapter(provider, model, **kwargs)
