"""Ручной, ограниченный Telegram Bot API sandbox для социальных каналов.

Модуль не содержит worker-а и ничего не запускает после restart. Токен читается
лениво по не-secret reference; checkpoint видит только reference и update cursor.
"""

from __future__ import annotations

import json
import socket
from typing import Any, Callable, Mapping, Optional
import urllib.error
import urllib.request

from src.core.external_credentials import (
    CredentialError,
    credential_target,
    provider_api_key,
)

TELEGRAM_PROVIDER = "telegram"
TELEGRAM_API_ROOT = "https://api.telegram.org"
TELEGRAM_CREDENTIAL_REF = credential_target(TELEGRAM_PROVIDER)
MAX_WIRE_BYTES = 256 * 1024
MAX_UPDATE_LIMIT = 32
MAX_TEXT_CHARS = 4000
_MAX_TELEGRAM_ID = 2**63 - 1


class TelegramChannelError(RuntimeError):
    """Безопасный код ошибки без URL, тела ответа, текста и секретов."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


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
            raise TelegramChannelError("unexpected_http_status")
        raw = response.read(MAX_WIRE_BYTES + 1)
    if len(raw) > MAX_WIRE_BYTES:
        raise TelegramChannelError("response_too_large")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise TelegramChannelError("invalid_response") from None
    if not isinstance(parsed, Mapping):
        raise TelegramChannelError("invalid_response")
    return parsed


def _load_telegram_token(reference: str) -> str:
    if reference != TELEGRAM_CREDENTIAL_REF:
        raise TelegramChannelError("invalid_credential_reference")
    try:
        return provider_api_key(TELEGRAM_PROVIDER)
    except CredentialError:
        raise TelegramChannelError("credential_unavailable") from None


def _integer(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int)


def _positive_id(value: Any) -> bool:
    return _integer(value) and 0 < value <= _MAX_TELEGRAM_ID


def _error_code(exc: urllib.error.HTTPError) -> str:
    if exc.code in {401, 403}:
        return "authentication_failed"
    if exc.code == 429:
        return "rate_limited"
    if 500 <= exc.code <= 599:
        return "provider_unavailable"
    if 300 <= exc.code <= 399:
        return "redirect_rejected"
    return "http_error"


class TelegramChannelAdapter:
    """Один manual getUpdates или sendMessage по явной команде владельца."""

    def __init__(
        self,
        *,
        credential_ref: str,
        account_id: str,
        timeout: float = 10.0,
        credential_loader: Callable[[str], str] = _load_telegram_token,
        transport: Optional[Callable[..., Mapping[str, Any]]] = None,
    ) -> None:
        if credential_ref != TELEGRAM_CREDENTIAL_REF:
            raise TelegramChannelError("invalid_credential_reference")
        if not isinstance(account_id, str) or not account_id.isdecimal():
            raise TelegramChannelError("invalid_account_id")
        if not _positive_id(int(account_id)):
            raise TelegramChannelError("invalid_account_id")
        if isinstance(timeout, bool) or not 1.0 <= float(timeout) <= 30.0:
            raise ValueError("timeout: expected a value from 1 to 30 seconds")
        self.credential_ref = credential_ref
        self.account_id = account_id
        self.timeout = float(timeout)
        self._credential_loader = credential_loader
        self._transport = transport or _urllib_transport

    def _call(self, method: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            token = self._credential_loader(self.credential_ref)
        except TelegramChannelError:
            raise
        except CredentialError:
            raise TelegramChannelError("credential_unavailable") from None
        except Exception:
            raise TelegramChannelError("credential_unavailable") from None
        if not isinstance(token, str) or not token.strip() or len(token) > 4096:
            raise TelegramChannelError("credential_unavailable")
        # Telegram требует token в path. Он никогда не попадает в журнал или error.
        url = f"{TELEGRAM_API_ROOT}/bot{token.strip()}/{method}"
        try:
            response = self._transport(
                url=url,
                payload=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "DigitalBeing/0.1 manual-social-sandbox",
                },
                timeout=self.timeout,
            )
        except TelegramChannelError:
            raise
        except urllib.error.HTTPError as exc:
            raise TelegramChannelError(_error_code(exc)) from None
        except (TimeoutError, socket.timeout):
            raise TelegramChannelError("timeout") from None
        except (urllib.error.URLError, OSError):
            raise TelegramChannelError("network_error") from None
        except Exception:
            raise TelegramChannelError("transport_failed") from None
        if not isinstance(response, Mapping):
            raise TelegramChannelError("invalid_response")
        if response.get("ok") is not True:
            error_code = response.get("error_code")
            if error_code in {401, 403}:
                raise TelegramChannelError("authentication_failed")
            if error_code == 429:
                raise TelegramChannelError("rate_limited")
            raise TelegramChannelError("provider_rejected")
        return response

    @staticmethod
    def _ignored(update_id: int, reason: str) -> dict:
        return {"update_id": update_id, "kind": "ignored", "reason": reason}

    def _normalize_update(self, raw: Any) -> dict:
        if not isinstance(raw, Mapping) or not _integer(raw.get("update_id")):
            raise TelegramChannelError("invalid_update")
        update_id = raw["update_id"]
        if not 0 <= update_id <= _MAX_TELEGRAM_ID:
            raise TelegramChannelError("invalid_update")
        if "message" not in raw:
            reason = "public_post" if "channel_post" in raw else "unsupported_update"
            return self._ignored(update_id, reason)
        message = raw.get("message")
        if not isinstance(message, Mapping):
            raise TelegramChannelError("invalid_update")
        chat = message.get("chat")
        if not isinstance(chat, Mapping) or not _integer(chat.get("id")):
            raise TelegramChannelError("invalid_update")
        chat_id = chat["id"]
        chat_type = chat.get("type")
        if chat_type != "private":
            reason = "public_post" if chat_type == "channel" else "group"
            return self._ignored(update_id, reason)
        if not _positive_id(chat_id):
            raise TelegramChannelError("invalid_update")
        if not isinstance(message.get("text"), str):
            return self._ignored(update_id, "non_text")
        text = message["text"]
        if not text.strip() or len(text) > MAX_TEXT_CHARS:
            raise TelegramChannelError("invalid_update")
        author = message.get("from")
        if not isinstance(author, Mapping) or not _positive_id(author.get("id")):
            raise TelegramChannelError("invalid_update")
        if not _positive_id(message.get("message_id")):
            raise TelegramChannelError("invalid_update")
        display_name = author.get("first_name") or author.get("username") or ""
        if not isinstance(display_name, str):
            raise TelegramChannelError("invalid_update")
        return {
            "update_id": update_id,
            "kind": "private_text",
            "conversation_id": str(chat_id),
            "author_id": str(author["id"]),
            "message_id": str(message["message_id"]),
            "text": text,
            "display_name": display_name.strip()[:40],
        }

    def get_updates(self, *, offset: Optional[int], limit: int = 16) -> list[dict]:
        """Прочитать один bounded batch; cursor подтверждает только manager."""
        if offset is not None and (
            not _integer(offset) or not 0 <= offset <= _MAX_TELEGRAM_ID
        ):
            raise TelegramChannelError("invalid_cursor")
        if not _integer(limit) or not 1 <= limit <= MAX_UPDATE_LIMIT:
            raise TelegramChannelError("invalid_limit")
        payload = {"limit": limit, "timeout": 0, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        response = self._call("getUpdates", payload)
        result = response.get("result")
        if not isinstance(result, list) or len(result) > limit:
            raise TelegramChannelError("invalid_response")
        return [self._normalize_update(item) for item in result]

    def send(
        self,
        *,
        channel_id: str,
        conversation_id: str,
        message_id: str,
        in_reply_to: str,
        text: str,
    ) -> dict:
        """Отправить exact owner-approved text и подтвердить точный receipt."""
        if not isinstance(conversation_id, str) or not conversation_id.isdecimal():
            raise TelegramChannelError("invalid_conversation")
        chat_id = int(conversation_id)
        if not _positive_id(chat_id):
            raise TelegramChannelError("invalid_conversation")
        reply_id = None
        if in_reply_to is not None:
            if not isinstance(in_reply_to, str) or not in_reply_to.isdecimal():
                raise TelegramChannelError("invalid_reply_target")
            reply_id = int(in_reply_to)
            if not _positive_id(reply_id):
                raise TelegramChannelError("invalid_reply_target")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
            raise TelegramChannelError("invalid_outgoing_text")
        payload = {"chat_id": chat_id, "text": text}
        if reply_id is not None:
            payload["reply_parameters"] = {
                "message_id": reply_id,
                "allow_sending_without_reply": False,
            }
        response = self._call("sendMessage", payload)
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise TelegramChannelError("invalid_response")
        chat = result.get("chat")
        author = result.get("from")
        if (
            not _positive_id(result.get("message_id"))
            or not isinstance(chat, Mapping)
            or chat.get("id") != chat_id
            or chat.get("type") != "private"
            or result.get("text") != text
            or not isinstance(author, Mapping)
            or author.get("id") != int(self.account_id)
            or author.get("is_bot") is not True
        ):
            raise TelegramChannelError("receipt_mismatch")
        return {
            "status": "sent",
            "channel_id": channel_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "external_message_id": str(result["message_id"]),
        }


def create_social_adapter(provider: str, **kwargs) -> TelegramChannelAdapter:
    """Единая фабрика 9D-1; произвольные provider и endpoint не поддержаны."""
    if str(provider or "").strip().lower() != TELEGRAM_PROVIDER:
        raise TelegramChannelError("unsupported_provider")
    return TelegramChannelAdapter(**kwargs)
