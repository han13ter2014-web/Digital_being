"""Provider-neutral социальные каналы без сети и автономной отправки.

Входящие реплики остаются ``external_social_claim``. ``ChannelGrant`` разрешает
приём, проект и отправку независимо; ``reply`` применим только к конкретному
owner-approved draft. Здесь нет worker-а или секретов; provider API вынесен в adapter.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import math
import re
from typing import Optional
from uuid import UUID, uuid4

SCHEMA_VERSION = 1
MAX_CHANNELS = 8
MAX_MESSAGES = 256
MAX_MESSAGES_PER_CHANNEL = 64
MAX_CONTROL_EVENTS = 128
MAX_TEXT_CHARS = 4000
MAX_ID_CHARS = 160
MAX_EXTERNAL_ID_CHARS = 128
MAX_PROVIDER_CHARS = 64
MAX_NAME_CHARS = 40
MAX_REASON_CHARS = 240
MAX_CONVERSATION_SCOPES = 32
MAX_REPLIES_PER_CHANNEL = 64
MAX_INTERVAL_SEC = 3600.0
VISIBILITIES = frozenset({"private", "group"})
AUTHOR_KINDS = frozenset({"external_person", "external_ai"})
CHANNEL_STATUSES = frozenset({"active", "stopped"})
ACTIVE_DRAFT_STATUSES = frozenset({"draft", "approved"})
OUTBOUND_STATUSES = frozenset(
    {"draft", "approved", "rejected", "superseded", "stopped", "send_failed", "sent"}
)
CONTROL_EVENT_KINDS = frozenset(
    {
        "created",
        "grant_updated",
        "revoked",
        "stopped",
        "received",
        "draft_created",
        "edited",
        "approved",
        "rejected",
        "sent",
        "send_failed",
        "session_started",
        "session_paused",
        "session_resumed",
        "session_manual",
        "session_stopped",
        "session_completed",
    }
)
_PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
TELEGRAM_CREDENTIAL_REF = "DigitalBeing/telegram"
MAX_UPDATE_CURSOR = 2**63 - 1
_CHANNEL_KEYS = frozenset(
    {
        "channel_id",
        "provider",
        "account_id",
        "default_author_kind",
        "status",
        "created_cycle",
        "last_cycle",
        "stopped_cycle",
        "stop_reason",
        "grant",
        "received_count",
        "sent_count",
        "last_sent_at",
        "credential_ref",
        "update_cursor",
    }
)
_GRANT_KEYS = frozenset(
    {
        "grant_version",
        "conversation_ids",
        "receive",
        "draft",
        "reply",
        "max_messages",
        "max_replies",
        "min_interval_sec",
    }
)
_MESSAGE_KEYS = frozenset(
    {
        "message_id",
        "channel_id",
        "conversation_id",
        "author_id",
        "profile_id",
        "direction",
        "claim_type",
        "status",
        "visibility",
        "text",
        "text_sha256",
        "cycle",
        "external_message_id",
        "based_on",
        "in_reply_to",
        "origin",
        "revision",
        "grant_version",
        "error",
        "session_context",
    }
)
_EVENT_KEYS = frozenset({"channel_id", "kind", "cycle", "reason"})
_ENVELOPE_REQUIRED = frozenset(
    {
        "channel_id",
        "provider",
        "account_id",
        "conversation_id",
        "author_id",
        "message_id",
        "visibility",
        "text",
    }
)
_ENVELOPE_KEYS = _ENVELOPE_REQUIRED | {"author_kind", "display_name"}


def _fail(path: str, message: str) -> None:
    raise ValueError(f"{path}: {message}")


def _keys(value, expected, path: str) -> None:
    if not isinstance(value, dict):
        _fail(path, "expected a dictionary")
    if set(value) != set(expected):
        _fail(path, "unexpected or missing fields")


def _text(value, path: str, limit: int, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or len(value) > limit:
        _fail(path, "expected a bounded string")
    if nonempty and not value.strip():
        _fail(path, "expected a nonempty string")
    return value


def _identifier(value, path: str, limit: int = MAX_ID_CHARS) -> str:
    _text(value, path, limit)
    if value != value.strip() or any(ord(char) < 32 for char in value):
        _fail(path, "expected a stable identifier without padding or controls")
    return value


def _optional_identifier(value, path: str) -> None:
    if value is not None:
        _identifier(value, path)


def _uuid(value, path: str) -> str:
    _text(value, path, 36)
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise ValueError(f"{path}: expected a UUID") from error
    if str(parsed) != value.lower():
        _fail(path, "expected a canonical UUID")
    return str(parsed)


def _cycle(value, path: str = "cycle") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(path, "expected a nonnegative integer")
    return value


def _count(value, path: str, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= maximum
    ):
        _fail(path, f"expected an integer from 0 to {maximum}")
    return value


def _timestamp(value, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(path, "expected a finite number")
    if not math.isfinite(value) or value < 0:
        _fail(path, "expected a nonnegative finite number")
    return float(value)


def _provider(value) -> str:
    provider = str(value or "").strip().lower()
    if (
        not provider
        or len(provider) > MAX_PROVIDER_CHARS
        or _PROVIDER_RE.fullmatch(provider) is None
    ):
        raise ValueError("provider: expected a bounded lowercase identifier")
    return provider


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _default_grant() -> dict:
    return {
        "grant_version": 1,
        "conversation_ids": [],
        "receive": False,
        "draft": False,
        "reply": False,
        "max_messages": 0,
        "max_replies": 0,
        "min_interval_sec": 0.0,
    }


def _validate_grant(grant, path: str) -> None:
    _keys(grant, _GRANT_KEYS, path)
    version = grant.get("grant_version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        _fail(f"{path}.grant_version", "expected a positive integer")
    scopes = grant.get("conversation_ids")
    if not isinstance(scopes, list) or len(scopes) > MAX_CONVERSATION_SCOPES:
        _fail(f"{path}.conversation_ids", "expected a bounded list")
    if len(set(scopes)) != len(scopes):
        _fail(f"{path}.conversation_ids", "duplicate conversation scope")
    for index, scope in enumerate(scopes):
        _identifier(scope, f"{path}.conversation_ids[{index}]")
    for field in ("receive", "draft", "reply"):
        if not isinstance(grant.get(field), bool):
            _fail(f"{path}.{field}", "expected a boolean")
    _count(grant.get("max_messages"), f"{path}.max_messages", MAX_MESSAGES_PER_CHANNEL)
    _count(grant.get("max_replies"), f"{path}.max_replies", MAX_REPLIES_PER_CHANNEL)
    interval = grant.get("min_interval_sec")
    _timestamp(interval, f"{path}.min_interval_sec")
    if interval > MAX_INTERVAL_SEC:
        _fail(f"{path}.min_interval_sec", "interval is too large")


def _validate_channel(channel, path: str) -> None:
    _keys(channel, _CHANNEL_KEYS, path)
    _uuid(channel.get("channel_id"), f"{path}.channel_id")
    _provider(channel.get("provider"))
    _identifier(channel.get("account_id"), f"{path}.account_id", MAX_EXTERNAL_ID_CHARS)
    credential_ref = channel.get("credential_ref")
    update_cursor = channel.get("update_cursor")
    if channel.get("provider") == "telegram":
        if credential_ref != TELEGRAM_CREDENTIAL_REF:
            _fail(f"{path}.credential_ref", "unsupported Telegram credential reference")
        if update_cursor is not None and (
            isinstance(update_cursor, bool)
            or not isinstance(update_cursor, int)
            or not 0 <= update_cursor <= MAX_UPDATE_CURSOR
        ):
            _fail(f"{path}.update_cursor", "expected a bounded Telegram update ID")
    elif credential_ref is not None or update_cursor is not None:
        _fail(path, "credential_ref and update_cursor are Telegram-only")
    if channel.get("default_author_kind") not in AUTHOR_KINDS:
        _fail(f"{path}.default_author_kind", "unsupported external author kind")
    if channel.get("status") not in CHANNEL_STATUSES:
        _fail(f"{path}.status", "unsupported channel status")
    created = _cycle(channel.get("created_cycle"), f"{path}.created_cycle")
    _cycle(channel.get("last_cycle"), f"{path}.last_cycle")
    if channel["last_cycle"] < created:
        _fail(f"{path}.last_cycle", "must not precede created_cycle")
    stopped_cycle = channel.get("stopped_cycle")
    stop_reason = channel.get("stop_reason")
    if channel["status"] == "stopped":
        _cycle(stopped_cycle, f"{path}.stopped_cycle")
        _text(stop_reason, f"{path}.stop_reason", MAX_REASON_CHARS)
    elif stopped_cycle is not None or stop_reason is not None:
        _fail(path, "active channel cannot contain stop data")
    _validate_grant(channel.get("grant"), f"{path}.grant")
    _count(channel.get("received_count"), f"{path}.received_count", MAX_MESSAGES)
    _count(channel.get("sent_count"), f"{path}.sent_count", MAX_REPLIES_PER_CHANNEL)
    last_sent = channel.get("last_sent_at")
    if last_sent is not None:
        _timestamp(last_sent, f"{path}.last_sent_at")
    if channel["sent_count"] == 0 and last_sent is not None:
        _fail(f"{path}.last_sent_at", "no sent message can own a timestamp")
    if channel["sent_count"] > 0 and last_sent is None:
        _fail(f"{path}.last_sent_at", "sent messages require a timestamp")


def _validate_message(message, path: str) -> None:
    _keys(message, _MESSAGE_KEYS, path)
    _identifier(message.get("message_id"), f"{path}.message_id")
    _uuid(message.get("channel_id"), f"{path}.channel_id")
    _identifier(message.get("conversation_id"), f"{path}.conversation_id")
    _optional_identifier(message.get("author_id"), f"{path}.author_id")
    _uuid(message.get("profile_id"), f"{path}.profile_id")
    if message.get("direction") not in {"inbound", "outbound"}:
        _fail(f"{path}.direction", "unsupported direction")
    if message.get("visibility") not in VISIBILITIES:
        _fail(f"{path}.visibility", "public or unknown visibility is unsupported")
    _text(message.get("text"), f"{path}.text", MAX_TEXT_CHARS)
    if message.get("text_sha256") != _hash_text(message["text"]):
        _fail(f"{path}.text_sha256", "text hash does not match")
    _cycle(message.get("cycle"), f"{path}.cycle")
    context = message.get("session_context")
    if not isinstance(context, list) or len(context) > 4:
        _fail(f"{path}.session_context", "expected bounded session provenance")
    for index, item in enumerate(context):
        _identifier(item, f"{path}.session_context[{index}]")
    if message["direction"] == "inbound":
        if context:
            _fail(f"{path}.session_context", "inbound claim cannot own a session")
        if message.get("status") != "quarantined":
            _fail(f"{path}.status", "inbound claims remain quarantined")
        if message.get("claim_type") != "external_social_claim":
            _fail(f"{path}.claim_type", "unsupported inbound claim")
        _identifier(message.get("external_message_id"), f"{path}.external_message_id")
        for field in ("based_on", "in_reply_to", "origin", "grant_version", "error"):
            if message.get(field) is not None:
                _fail(f"{path}.{field}", "inbound claim cannot contain response data")
        if message.get("revision") != 0:
            _fail(f"{path}.revision", "inbound revision must be zero")
        if message["visibility"] == "private" and message["author_id"] is None:
            _fail(f"{path}.author_id", "private claims require a stable author")
        return
    if message.get("status") not in OUTBOUND_STATUSES:
        _fail(f"{path}.status", "unsupported outbound status")
    if message.get("claim_type") is not None:
        _fail(f"{path}.claim_type", "outbound draft is not an external claim")
    _identifier(message.get("based_on"), f"{path}.based_on")
    origin = message.get("origin")
    if origin not in {
        "deterministic",
        "owner_edit",
        "session_reply",
        "session_initiative",
    }:
        _fail(f"{path}.origin", "unsupported draft origin")
    if origin == "session_initiative":
        if message.get("in_reply_to") is not None:
            _fail(f"{path}.in_reply_to", "initiative is not a reply")
    else:
        _identifier(message.get("in_reply_to"), f"{path}.in_reply_to")
    if origin in {"session_reply", "session_initiative"} and not context:
        _fail(f"{path}.session_context", "session send requires provenance")
    revision = message.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        _fail(f"{path}.revision", "expected a positive integer")
    _optional_identifier(
        message.get("external_message_id"), f"{path}.external_message_id"
    )
    grant_version = message.get("grant_version")
    if message["status"] in {"approved", "send_failed", "sent"}:
        if (
            isinstance(grant_version, bool)
            or not isinstance(grant_version, int)
            or grant_version < 1
        ):
            _fail(f"{path}.grant_version", "approved draft requires a grant version")
    elif grant_version is not None:
        _fail(f"{path}.grant_version", "unapproved draft cannot retain approval scope")
    error = message.get("error")
    if message["status"] == "send_failed":
        _text(error, f"{path}.error", MAX_REASON_CHARS)
    elif error is not None:
        _fail(f"{path}.error", "only failed send can contain an error")


def _normalized_snapshot(data) -> dict:
    """Миграция additive-полей 9D-1 без изменения переданного checkpoint."""
    restored = deepcopy(data)
    if isinstance(restored, dict) and isinstance(restored.get("channels"), list):
        for channel in restored["channels"]:
            if not isinstance(channel, dict):
                continue
            is_telegram = channel.get("provider") == "telegram"
            channel.setdefault(
                "credential_ref", TELEGRAM_CREDENTIAL_REF if is_telegram else None
            )
            channel.setdefault("update_cursor", None)
    return restored


def validate_social_channels(data, registry_data) -> None:
    """Проверить весь snapshot и profile scope до мутаций живого агента."""
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        _fail("social_channels", "unsupported snapshot")
    data = _normalized_snapshot(data)
    if set(data) != {"schema_version", "channels", "messages", "control_events"}:
        _fail("social_channels", "unexpected or missing fields")
    channels = data.get("channels")
    if not isinstance(channels, list) or len(channels) > MAX_CHANNELS:
        _fail("social_channels.channels", "expected a bounded list")
    profiles = (
        registry_data.get("profiles", {}) if isinstance(registry_data, dict) else {}
    )
    if channels and not profiles:
        _fail("social_channels", "social_registry is required")
    channel_by_id = {}
    provider_accounts = set()
    for index, channel in enumerate(channels):
        path = f"social_channels.channels[{index}]"
        _validate_channel(channel, path)
        channel_id = channel["channel_id"]
        if channel_id in channel_by_id:
            _fail(path, "duplicate channel ID")
        binding = (channel["provider"], channel["account_id"])
        if binding in provider_accounts:
            _fail(path, "provider/account binding must be unique")
        provider_accounts.add(binding)
        channel_by_id[channel_id] = channel

    messages = data.get("messages")
    if not isinstance(messages, list) or len(messages) > MAX_MESSAGES:
        _fail("social_channels.messages", "expected a bounded list")
    message_by_id = {}
    external_ids = set()
    per_channel = {channel_id: 0 for channel_id in channel_by_id}
    active_drafts = set()
    inbound_counts = {channel_id: 0 for channel_id in channel_by_id}
    sent_counts = {channel_id: 0 for channel_id in channel_by_id}
    for index, message in enumerate(messages):
        path = f"social_channels.messages[{index}]"
        _validate_message(message, path)
        message_id = message["message_id"]
        if message_id in message_by_id:
            _fail(path, "duplicate local message ID")
        message_by_id[message_id] = message
        channel = channel_by_id.get(message["channel_id"])
        if channel is None:
            _fail(f"{path}.channel_id", "unknown channel")
        channel_id = channel["channel_id"]
        per_channel[channel_id] += 1
        if per_channel[channel_id] > MAX_MESSAGES_PER_CHANNEL:
            _fail(path, "too many messages in channel")
        if message["cycle"] < channel["created_cycle"]:
            _fail(f"{path}.cycle", "message precedes its channel")
        profile = profiles.get(message["profile_id"])
        if profile is None or profile.get("kind") not in AUTHOR_KINDS | {"unknown"}:
            _fail(
                f"{path}.profile_id", "message requires an external or unknown profile"
            )
        if message["direction"] == "inbound":
            inbound_counts[channel_id] += 1
            external_key = (channel_id, message["external_message_id"])
            if external_key in external_ids:
                _fail(path, "duplicate provider message ID")
            external_ids.add(external_key)
        if profile["kind"] == "unknown":
            if message["author_id"] is not None or profile.get("channel_bindings"):
                _fail(f"{path}.profile_id", "unknown profile must remain unbound")
        else:
            if message["author_id"] is None or not any(
                binding.get("channel") == channel["provider"]
                and binding.get("external_id") == message["author_id"]
                for binding in profile.get("channel_bindings", [])
            ):
                _fail(f"{path}.profile_id", "author binding does not match profile")
        if message["direction"] == "outbound":
            source = message_by_id.get(message["based_on"])
            if (
                source is None
                or source["direction"] != "inbound"
                or any(
                    source[field] != message[field]
                    for field in (
                        "channel_id",
                        "conversation_id",
                        "author_id",
                        "profile_id",
                    )
                )
                or (
                    message["origin"] == "session_initiative"
                    and message["in_reply_to"] is not None
                )
                or (
                    message["origin"] != "session_initiative"
                    and message["in_reply_to"] != source["external_message_id"]
                )
            ):
                _fail(f"{path}.based_on", "draft escaped its inbound scope")
            if (
                message["grant_version"] is not None
                and message["grant_version"] > channel["grant"]["grant_version"]
            ):
                _fail(f"{path}.grant_version", "approval exceeds current grant")
            draft_key = (channel_id, message["conversation_id"])
            if message["status"] in ACTIVE_DRAFT_STATUSES:
                if draft_key in active_drafts:
                    _fail(path, "multiple active drafts in one conversation")
                active_drafts.add(draft_key)
            if (
                channel["status"] == "stopped"
                and message["status"] in ACTIVE_DRAFT_STATUSES
            ):
                _fail(path, "stopped channel cannot retain an active draft")
            if message["status"] == "sent":
                sent_counts[channel_id] += 1
    for channel_id, channel in channel_by_id.items():
        if channel["received_count"] != inbound_counts[channel_id]:
            _fail("social_channels.channels", "received_count does not match journal")
        if channel["sent_count"] != sent_counts[channel_id]:
            _fail("social_channels.channels", "sent_count does not match journal")

    events = data.get("control_events")
    if not isinstance(events, list) or len(events) > MAX_CONTROL_EVENTS:
        _fail("social_channels.control_events", "expected a bounded list")
    for index, event in enumerate(events):
        path = f"social_channels.control_events[{index}]"
        _keys(event, _EVENT_KEYS, path)
        channel = channel_by_id.get(event.get("channel_id"))
        if channel is None:
            _fail(f"{path}.channel_id", "unknown channel")
        if event.get("kind") not in CONTROL_EVENT_KINDS:
            _fail(f"{path}.kind", "unsupported control event")
        _cycle(event.get("cycle"), f"{path}.cycle")
        if event["cycle"] < channel["created_cycle"]:
            _fail(f"{path}.cycle", "event precedes its channel")
        reason = event.get("reason")
        if reason is not None:
            _text(reason, f"{path}.reason", MAX_REASON_CHARS, nonempty=False)


class SocialChannelManager:
    """Каналы, grants, карантин и точная owner-approved отправка через adapter."""

    def __init__(self, registry) -> None:
        self.registry = registry
        self.channels = []
        self.messages = []
        self.control_events = []

    def _channel(self, channel_id: str) -> Optional[dict]:
        return next(
            (item for item in self.channels if item["channel_id"] == channel_id), None
        )

    def _message(self, message_id: str) -> Optional[dict]:
        return next(
            (item for item in self.messages if item["message_id"] == message_id), None
        )

    def _record(self, channel_id: str, kind: str, cycle: int, reason=None) -> None:
        if kind not in CONTROL_EVENT_KINDS:
            raise ValueError("kind: unsupported control event")
        self.control_events.append(
            {"channel_id": channel_id, "kind": kind, "cycle": cycle, "reason": reason}
        )
        del self.control_events[:-MAX_CONTROL_EVENTS]

    def create_channel(
        self,
        *,
        provider: str,
        account_id: str,
        cycle: int,
        default_author_kind: str = "external_person",
    ) -> dict:
        provider = _provider(provider)
        _identifier(account_id, "account_id", MAX_EXTERNAL_ID_CHARS)
        _cycle(cycle)
        if default_author_kind not in AUTHOR_KINDS:
            raise ValueError("default_author_kind: unsupported external author kind")
        existing = next(
            (
                item
                for item in self.channels
                if item["provider"] == provider and item["account_id"] == account_id
            ),
            None,
        )
        if existing is not None:
            return {**deepcopy(existing), "status": "exists"}
        if len(self.channels) >= MAX_CHANNELS:
            return {"status": "limit_reached"}
        channel_id = str(uuid4())
        channel = {
            "channel_id": channel_id,
            "provider": provider,
            "account_id": account_id,
            "default_author_kind": default_author_kind,
            "status": "active",
            "created_cycle": cycle,
            "last_cycle": cycle,
            "stopped_cycle": None,
            "stop_reason": None,
            "grant": _default_grant(),
            "received_count": 0,
            "sent_count": 0,
            "last_sent_at": None,
            "credential_ref": (
                TELEGRAM_CREDENTIAL_REF if provider == "telegram" else None
            ),
            "update_cursor": None,
        }
        self.channels.append(channel)
        self._record(channel_id, "created", cycle)
        return {**deepcopy(channel), "status": "created"}

    def update_grant(
        self,
        channel_id: str,
        *,
        conversation_ids,
        receive: bool,
        draft: bool,
        reply: bool,
        max_messages: int,
        max_replies: int,
        min_interval_sec: float,
        cycle: int,
    ) -> dict:
        _cycle(cycle)
        channel = self._channel(channel_id)
        if channel is None:
            return {"status": "not_found", "channel_id": channel_id}
        if channel["status"] != "active":
            return {"status": "channel_stopped", "channel_id": channel_id}
        candidate = {
            "grant_version": channel["grant"]["grant_version"],
            "conversation_ids": list(conversation_ids),
            "receive": receive,
            "draft": draft,
            "reply": reply,
            "max_messages": max_messages,
            "max_replies": max_replies,
            "min_interval_sec": min_interval_sec,
        }
        _validate_grant(candidate, "grant")
        candidate["min_interval_sec"] = float(candidate["min_interval_sec"])
        comparable = {
            key: value for key, value in candidate.items() if key != "grant_version"
        }
        current = {
            key: value
            for key, value in channel["grant"].items()
            if key != "grant_version"
        }
        if comparable == current:
            return {"status": "unchanged", **deepcopy(channel["grant"])}
        candidate["grant_version"] += 1
        channel["grant"] = candidate
        channel["last_cycle"] = max(channel["last_cycle"], cycle)
        for message in self.messages:
            if message["channel_id"] == channel_id and message["status"] == "approved":
                message["status"] = "draft"
                message["grant_version"] = None
                message["cycle"] = cycle
        self._record(channel_id, "grant_updated", cycle)
        return {"status": "updated", **deepcopy(candidate)}

    def _close_drafts(self, channel_id: str, cycle: int) -> None:
        for message in self.messages:
            if (
                message["channel_id"] == channel_id
                and message["status"] in ACTIVE_DRAFT_STATUSES
            ):
                message["status"] = "stopped"
                message["grant_version"] = None
                message["cycle"] = cycle

    def revoke(self, channel_id: str, *, cycle: int, reason: str) -> dict:
        _cycle(cycle)
        _text(reason, "reason", MAX_REASON_CHARS)
        channel = self._channel(channel_id)
        if channel is None:
            return {"status": "not_found", "channel_id": channel_id}
        if channel["status"] != "active":
            return {"status": "channel_stopped", "channel_id": channel_id}
        grant = deepcopy(channel["grant"])
        grant.update(receive=False, draft=False, reply=False)
        if any(channel["grant"][key] for key in ("receive", "draft", "reply")):
            grant["grant_version"] += 1
        channel["grant"] = grant
        channel["last_cycle"] = max(channel["last_cycle"], cycle)
        self._close_drafts(channel_id, cycle)
        self._record(channel_id, "revoked", cycle, reason)
        return {**deepcopy(channel), "status": "revoked"}

    def stop(self, channel_id: str, *, cycle: int, reason: str) -> dict:
        _cycle(cycle)
        _text(reason, "reason", MAX_REASON_CHARS)
        channel = self._channel(channel_id)
        if channel is None:
            return {"status": "not_found", "channel_id": channel_id}
        if channel["status"] == "stopped":
            return {**deepcopy(channel), "status": "already_stopped"}
        channel["status"] = "stopped"
        channel["stopped_cycle"] = cycle
        channel["stop_reason"] = reason
        channel["last_cycle"] = max(channel["last_cycle"], cycle)
        channel["grant"].update(receive=False, draft=False, reply=False)
        channel["grant"]["grant_version"] += 1
        self._close_drafts(channel_id, cycle)
        self._record(channel_id, "stopped", cycle, reason)
        return {**deepcopy(channel), "status": "stopped"}

    def _validate_envelope(self, envelope) -> dict:
        if not isinstance(envelope, dict) or set(envelope) - _ENVELOPE_KEYS:
            _fail("envelope", "unexpected fields")
        missing = _ENVELOPE_REQUIRED - set(envelope)
        if missing:
            _fail("envelope", f"missing fields: {sorted(missing)}")
        clean = deepcopy(envelope)
        _uuid(clean["channel_id"], "envelope.channel_id")
        clean["provider"] = _provider(clean["provider"])
        _identifier(clean["account_id"], "envelope.account_id", MAX_EXTERNAL_ID_CHARS)
        _identifier(clean["conversation_id"], "envelope.conversation_id")
        _identifier(clean["message_id"], "envelope.message_id")
        if clean["author_id"] is not None:
            _identifier(clean["author_id"], "envelope.author_id")
        if clean["visibility"] not in VISIBILITIES:
            _fail("envelope.visibility", "public or unknown visibility is unsupported")
        if clean["visibility"] == "private" and clean["author_id"] is None:
            _fail("envelope.author_id", "private claims require a stable author")
        _text(clean["text"], "envelope.text", MAX_TEXT_CHARS)
        kind = clean.get("author_kind", "external_person")
        if kind not in AUTHOR_KINDS:
            _fail(
                "envelope.author_kind",
                "external text cannot claim another identity kind",
            )
        clean["author_kind"] = kind
        display_name = clean.get("display_name", "")
        _text(display_name, "envelope.display_name", MAX_NAME_CHARS, nonempty=False)
        clean["display_name"] = display_name
        return clean

    def _resolve_profile(self, channel: dict, event: dict, cycle: int) -> str:
        if event["author_id"] is None:
            existing = next(
                (
                    item
                    for item in self.messages
                    if item["channel_id"] == channel["channel_id"]
                    and item["conversation_id"] == event["conversation_id"]
                    and item["direction"] == "inbound"
                    and item["author_id"] is None
                ),
                None,
            )
            if existing is not None:
                return existing["profile_id"]
            return self.registry.create_external_unknown(cycle=cycle)
        if channel["default_author_kind"] == "external_ai":
            return self.registry.create_external_ai(
                event["display_name"] or "External AI",
                provider=channel["provider"],
                external_id=event["author_id"],
                cycle=cycle,
            )
        return self.registry.create_external_person(
            event["display_name"],
            provider=channel["provider"],
            external_id=event["author_id"],
            cycle=cycle,
        )

    def ingest(self, envelope, *, cycle: int) -> dict:
        _cycle(cycle)
        event = self._validate_envelope(envelope)
        channel = self._channel(event["channel_id"])
        if channel is None:
            raise KeyError(event["channel_id"])
        if (event["provider"], event["account_id"]) != (
            channel["provider"],
            channel["account_id"],
        ):
            raise ValueError("envelope: provider/account does not match channel")
        if event["author_kind"] != channel["default_author_kind"]:
            raise ValueError("envelope.author_kind: incompatible with channel")
        duplicate = next(
            (
                item
                for item in self.messages
                if item["channel_id"] == channel["channel_id"]
                and item["direction"] == "inbound"
                and item["external_message_id"] == event["message_id"]
            ),
            None,
        )
        if duplicate is not None:
            expected = {
                "conversation_id": duplicate["conversation_id"],
                "author_id": duplicate["author_id"],
                "visibility": duplicate["visibility"],
                "text": duplicate["text"],
            }
            if any(event[key] != value for key, value in expected.items()):
                raise ValueError(
                    "envelope.message_id: replay does not match original claim"
                )
            return {**deepcopy(duplicate), "status": "duplicate"}
        grant = channel["grant"]
        if channel["status"] != "active":
            return {"status": "channel_stopped", "channel_id": channel["channel_id"]}
        if (
            not grant["receive"]
            or event["conversation_id"] not in grant["conversation_ids"]
        ):
            return {"status": "permission_denied", "channel_id": channel["channel_id"]}
        if (
            len(self.messages) >= MAX_MESSAGES
            or channel["received_count"] >= grant["max_messages"]
            or channel["received_count"] >= MAX_MESSAGES_PER_CHANNEL
        ):
            return {"status": "limit_reached", "channel_id": channel["channel_id"]}
        profile_id = self._resolve_profile(channel, event, cycle)
        for message in self.messages:
            if (
                message["channel_id"] == channel["channel_id"]
                and message["conversation_id"] == event["conversation_id"]
                and message["status"] in ACTIVE_DRAFT_STATUSES
            ):
                message["status"] = "superseded"
                message["grant_version"] = None
                message["cycle"] = cycle
        message = {
            "message_id": f"in-{uuid4()}",
            "channel_id": channel["channel_id"],
            "conversation_id": event["conversation_id"],
            "author_id": event["author_id"],
            "profile_id": profile_id,
            "direction": "inbound",
            "claim_type": "external_social_claim",
            "status": "quarantined",
            "visibility": event["visibility"],
            "text": event["text"],
            "text_sha256": _hash_text(event["text"]),
            "cycle": cycle,
            "external_message_id": event["message_id"],
            "based_on": None,
            "in_reply_to": None,
            "origin": None,
            "revision": 0,
            "grant_version": None,
            "error": None,
            "session_context": [],
        }
        self.messages.append(message)
        channel["received_count"] += 1
        channel["last_cycle"] = max(channel["last_cycle"], cycle)
        self._record(channel["channel_id"], "received", cycle)
        return {"status": "quarantined", **deepcopy(message)}

    def receive(self, channel_id: str, *, adapter, cycle: int, limit: int = 16) -> dict:
        """Выполнить один manual Telegram batch и подтвердить обработанные updates."""
        _cycle(cycle)
        channel = self._channel(channel_id)
        if channel is None:
            return {"status": "not_found", "channel_id": channel_id}
        if channel["status"] != "active":
            return {"status": "channel_stopped", "channel_id": channel_id}
        if channel["provider"] != "telegram":
            return {"status": "unsupported_provider", "channel_id": channel_id}
        grant = channel["grant"]
        if not grant["receive"] or not grant["conversation_ids"]:
            return {"status": "permission_denied", "channel_id": channel_id}
        if channel.get("credential_ref") != TELEGRAM_CREDENTIAL_REF:
            return {"status": "credential_required", "channel_id": channel_id}
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 32
        ):
            return {"status": "invalid_limit", "channel_id": channel_id}
        cursor = channel["update_cursor"]
        offset = cursor + 1 if cursor is not None else None
        try:
            updates = adapter.get_updates(offset=offset, limit=limit)
        except Exception as exc:
            code = getattr(exc, "code", "transport_failed")
            allowed = {
                "authentication_failed",
                "credential_unavailable",
                "invalid_cursor",
                "invalid_response",
                "invalid_update",
                "network_error",
                "provider_rejected",
                "provider_unavailable",
                "rate_limited",
                "redirect_rejected",
                "response_too_large",
                "timeout",
                "transport_failed",
                "unexpected_http_status",
                "http_error",
            }
            return {
                "status": "transport_error",
                "error": code if code in allowed else "transport_failed",
            }
        if not isinstance(updates, list) or len(updates) > limit:
            return {"status": "transport_error", "error": "invalid_response"}

        received = 0
        duplicates = 0
        ignored = 0
        message_ids = []
        previous_id = None
        required = {
            "update_id",
            "kind",
            "conversation_id",
            "author_id",
            "message_id",
            "text",
            "display_name",
        }
        for update in updates:
            if not isinstance(update, dict):
                return {"status": "invalid_update", "error": "invalid_update"}
            update_id = update.get("update_id")
            if (
                isinstance(update_id, bool)
                or not isinstance(update_id, int)
                or not 0 <= update_id <= MAX_UPDATE_CURSOR
                or (previous_id is not None and update_id <= previous_id)
            ):
                return {"status": "invalid_update", "error": "invalid_update"}
            previous_id = update_id
            if cursor is not None and update_id <= cursor:
                duplicates += 1
                continue
            kind = update.get("kind")
            if kind == "ignored":
                if set(update) != {"update_id", "kind", "reason"} or not isinstance(
                    update.get("reason"), str
                ):
                    return {"status": "invalid_update", "error": "invalid_update"}
                ignored += 1
            elif kind == "private_text":
                if set(update) != required:
                    return {"status": "invalid_update", "error": "invalid_update"}
                if update["conversation_id"] not in grant["conversation_ids"]:
                    ignored += 1
                else:
                    envelope = {
                        "channel_id": channel_id,
                        "provider": "telegram",
                        "account_id": channel["account_id"],
                        "conversation_id": update["conversation_id"],
                        "author_id": update["author_id"],
                        "author_kind": channel["default_author_kind"],
                        "display_name": update["display_name"],
                        "message_id": update["message_id"],
                        "visibility": "private",
                        "text": update["text"],
                    }
                    try:
                        result = self.ingest(envelope, cycle=cycle)
                    except (KeyError, TypeError, ValueError):
                        return {"status": "invalid_update", "error": "invalid_update"}
                    if result["status"] not in {"quarantined", "duplicate"}:
                        return {
                            **result,
                            "received": received,
                            "duplicates": duplicates,
                            "ignored": ignored,
                            "message_ids": message_ids,
                            "update_cursor": channel["update_cursor"],
                        }
                    if result["status"] == "duplicate":
                        duplicates += 1
                    else:
                        received += 1
                    message_ids.append(result["message_id"])
            else:
                return {"status": "invalid_update", "error": "invalid_update"}
            channel["update_cursor"] = update_id
            channel["last_cycle"] = max(channel["last_cycle"], cycle)
        return {
            "status": "received" if updates else "no_updates",
            "received": received,
            "duplicates": duplicates,
            "ignored": ignored,
            "message_ids": message_ids,
            "update_cursor": channel["update_cursor"],
        }

    @staticmethod
    def _draft_text(text: str) -> str:
        if "?" in text or "？" in text:
            return (
                "У меня пока нет достаточной проверенной опоры для ответа. "
                "Оставлю это открытым вопросом, а не выдумаю утверждение."
            )
        return (
            "Я восприняла это как внешнее свидетельство, а не как команду "
            "или доказанный факт. Могу обсудить его осторожно."
        )

    def create_draft(
        self, channel_id: str, inbound_message_id: str, *, cycle: int
    ) -> dict:
        _cycle(cycle)
        channel = self._channel(channel_id)
        if channel is None:
            return {"status": "not_found", "channel_id": channel_id}
        if channel["status"] != "active":
            return {"status": "channel_stopped", "channel_id": channel_id}
        source = self._message(inbound_message_id)
        if (
            source is None
            or source["direction"] != "inbound"
            or source["channel_id"] != channel_id
        ):
            return {"status": "not_found", "message_id": inbound_message_id}
        if source["profile_id"] not in self.registry.profiles:
            return {"status": "identity_required", "message_id": inbound_message_id}
        if self.registry.profiles[source["profile_id"]]["kind"] == "unknown":
            return {"status": "identity_required", "message_id": inbound_message_id}
        grant = channel["grant"]
        if (
            not grant["draft"]
            or source["conversation_id"] not in grant["conversation_ids"]
        ):
            return {"status": "permission_denied", "channel_id": channel_id}
        active = next(
            (
                item
                for item in reversed(self.messages)
                if item["channel_id"] == channel_id
                and item["conversation_id"] == source["conversation_id"]
                and item["status"] in ACTIVE_DRAFT_STATUSES
            ),
            None,
        )
        if active is not None:
            return {**deepcopy(active), "status": "draft_pending"}
        if (
            len(self.messages) >= MAX_MESSAGES
            or sum(item["channel_id"] == channel_id for item in self.messages)
            >= MAX_MESSAGES_PER_CHANNEL
        ):
            return {"status": "limit_reached", "channel_id": channel_id}
        text = self._draft_text(source["text"])
        draft = {
            "message_id": f"out-{uuid4()}",
            "channel_id": channel_id,
            "conversation_id": source["conversation_id"],
            "author_id": source["author_id"],
            "profile_id": source["profile_id"],
            "direction": "outbound",
            "claim_type": None,
            "status": "draft",
            "visibility": source["visibility"],
            "text": text,
            "text_sha256": _hash_text(text),
            "cycle": cycle,
            "external_message_id": None,
            "based_on": source["message_id"],
            "in_reply_to": source["external_message_id"],
            "origin": "deterministic",
            "revision": 1,
            "grant_version": None,
            "error": None,
            "session_context": [],
        }
        self.messages.append(draft)
        channel["last_cycle"] = max(channel["last_cycle"], cycle)
        self._record(channel_id, "draft_created", cycle)
        return {"status": "draft", **deepcopy(draft)}

    def create_initiative(
        self,
        channel_id: str,
        source_message_id: str,
        *,
        session_id: str,
        text: str,
        reason: str,
        cycle: int,
    ) -> dict:
        """Создать одну инициативу из реального prior private context."""
        _cycle(cycle)
        _identifier(session_id, "session_id")
        _text(text, "text", MAX_TEXT_CHARS)
        _identifier(reason, "reason", 80)
        channel = self._channel(channel_id)
        if channel is None:
            return {"status": "not_found", "channel_id": channel_id}
        if channel["status"] != "active":
            return {"status": "channel_stopped", "channel_id": channel_id}
        source = self._message(source_message_id)
        if (
            source is None
            or source["direction"] != "inbound"
            or source["channel_id"] != channel_id
            or source["visibility"] != "private"
        ):
            return {"status": "not_found", "message_id": source_message_id}
        profile = self.registry.profiles.get(source["profile_id"])
        if profile is None or profile["kind"] == "unknown":
            return {"status": "identity_required", "message_id": source_message_id}
        grant = channel["grant"]
        if (
            not grant["draft"]
            or source["conversation_id"] not in grant["conversation_ids"]
        ):
            return {"status": "permission_denied", "channel_id": channel_id}
        if any(
            item["direction"] == "outbound"
            and item["based_on"] == source_message_id
            and item["origin"] == "session_initiative"
            for item in self.messages
        ):
            return {"status": "initiative_exists", "channel_id": channel_id}
        if any(
            item["channel_id"] == channel_id
            and item["conversation_id"] == source["conversation_id"]
            and item["status"] in ACTIVE_DRAFT_STATUSES
            for item in self.messages
        ):
            return {"status": "draft_pending", "channel_id": channel_id}
        if (
            len(self.messages) >= MAX_MESSAGES
            or sum(item["channel_id"] == channel_id for item in self.messages)
            >= MAX_MESSAGES_PER_CHANNEL
        ):
            return {"status": "limit_reached", "channel_id": channel_id}
        draft = {
            "message_id": f"out-{uuid4()}",
            "channel_id": channel_id,
            "conversation_id": source["conversation_id"],
            "author_id": source["author_id"],
            "profile_id": source["profile_id"],
            "direction": "outbound",
            "claim_type": None,
            "status": "draft",
            "visibility": "private",
            "text": text,
            "text_sha256": _hash_text(text),
            "cycle": cycle,
            "external_message_id": None,
            "based_on": source["message_id"],
            "in_reply_to": None,
            "origin": "session_initiative",
            "revision": 1,
            "grant_version": None,
            "error": None,
            "session_context": [f"session:{session_id}", reason],
        }
        self.messages.append(draft)
        channel["last_cycle"] = max(channel["last_cycle"], cycle)
        self._record(channel_id, "draft_created", cycle)
        return {"status": "draft", **deepcopy(draft)}

    def edit_draft(self, draft_id: str, text: str, *, cycle: int) -> dict:
        _cycle(cycle)
        _text(text, "text", MAX_TEXT_CHARS)
        draft = self._message(draft_id)
        if draft is None or draft["direction"] != "outbound":
            return {"status": "not_found", "message_id": draft_id}
        channel = self._channel(draft["channel_id"])
        if channel["status"] != "active":
            return {"status": "channel_stopped", "message_id": draft_id}
        if draft["status"] not in ACTIVE_DRAFT_STATUSES:
            return {"status": "no_active_draft", "message_id": draft_id}
        if not channel["grant"]["draft"]:
            return {"status": "permission_denied", "message_id": draft_id}
        draft.update(
            text=text,
            text_sha256=_hash_text(text),
            status="draft",
            origin="owner_edit",
            revision=draft["revision"] + 1,
            cycle=cycle,
            external_message_id=None,
            grant_version=None,
            error=None,
        )
        channel["last_cycle"] = max(channel["last_cycle"], cycle)
        self._record(channel["channel_id"], "edited", cycle)
        return {"status": "draft", **deepcopy(draft)}

    def approve(self, draft_id: str, *, cycle: int) -> dict:
        _cycle(cycle)
        draft = self._message(draft_id)
        if draft is None or draft["direction"] != "outbound":
            return {"status": "not_found", "message_id": draft_id}
        channel = self._channel(draft["channel_id"])
        if channel["status"] != "active":
            return {"status": "channel_stopped", "message_id": draft_id}
        if draft["status"] not in ACTIVE_DRAFT_STATUSES:
            return {"status": "approval_required", "message_id": draft_id}
        if not channel["grant"]["draft"]:
            return {"status": "permission_denied", "message_id": draft_id}
        if draft["text_sha256"] != _hash_text(draft["text"]):
            return {"status": "approval_mismatch", "message_id": draft_id}
        if (
            draft["status"] == "approved"
            and draft["grant_version"] == channel["grant"]["grant_version"]
        ):
            return {**deepcopy(draft), "status": "already_approved"}
        draft["status"] = "approved"
        draft["grant_version"] = channel["grant"]["grant_version"]
        draft["cycle"] = cycle
        channel["last_cycle"] = max(channel["last_cycle"], cycle)
        self._record(channel["channel_id"], "approved", cycle)
        return {"status": "approved", **deepcopy(draft)}

    def reject(self, draft_id: str, *, cycle: int) -> dict:
        _cycle(cycle)
        draft = self._message(draft_id)
        if draft is None or draft["direction"] != "outbound":
            return {"status": "not_found", "message_id": draft_id}
        if draft["status"] not in ACTIVE_DRAFT_STATUSES:
            return {"status": "no_active_draft", "message_id": draft_id}
        draft["status"] = "rejected"
        draft["grant_version"] = None
        draft["cycle"] = cycle
        channel = self._channel(draft["channel_id"])
        channel["last_cycle"] = max(channel["last_cycle"], cycle)
        self._record(channel["channel_id"], "rejected", cycle)
        return {"status": "rejected", **deepcopy(draft)}

    def send(
        self,
        channel_id: str,
        draft_id: str,
        *,
        adapter,
        cycle: int,
        now: float,
        expected_text_sha256: str,
        expected_grant_version: int,
    ) -> dict:
        """Отправить один exact-scope draft; accepted/HTTP 200 не считается sent."""
        _cycle(cycle)
        _timestamp(now, "now")
        draft = self._message(draft_id)
        if draft is None or draft["direction"] != "outbound":
            return {"status": "not_found", "message_id": draft_id}
        if draft["channel_id"] != channel_id:
            return {"status": "scope_mismatch", "message_id": draft_id}
        channel = self._channel(channel_id)
        if channel["status"] != "active":
            return {"status": "channel_stopped", "message_id": draft_id}
        grant = channel["grant"]
        if (
            not grant["reply"]
            or draft["conversation_id"] not in grant["conversation_ids"]
        ):
            return {"status": "permission_denied", "message_id": draft_id}
        if draft["status"] != "approved":
            return {"status": "approval_required", "message_id": draft_id}
        if (
            draft["text_sha256"] != _hash_text(draft["text"])
            or expected_text_sha256 != draft["text_sha256"]
        ):
            return {"status": "approval_mismatch", "message_id": draft_id}
        if (
            expected_grant_version != grant["grant_version"]
            or draft["grant_version"] != grant["grant_version"]
        ):
            return {"status": "grant_mismatch", "message_id": draft_id}
        if channel["sent_count"] >= grant["max_replies"]:
            return {"status": "limit_reached", "message_id": draft_id}
        if (
            channel["last_sent_at"] is not None
            and now - channel["last_sent_at"] < grant["min_interval_sec"]
        ):
            return {"status": "rate_limited", "message_id": draft_id}
        try:
            receipt = adapter.send(
                channel_id=channel_id,
                conversation_id=draft["conversation_id"],
                message_id=draft["message_id"],
                in_reply_to=draft["in_reply_to"],
                text=draft["text"],
            )
            if (
                not isinstance(receipt, dict)
                or receipt.get("status") != "sent"
                or any(
                    receipt.get(field) != draft[field]
                    for field in ("channel_id", "conversation_id", "message_id")
                )
            ):
                raise ValueError("adapter did not confirm exact delivery")
            external_message_id = receipt.get("external_message_id")
            _optional_identifier(external_message_id, "receipt.external_message_id")
        except Exception as exc:
            draft["status"] = "send_failed"
            draft["error"] = (
                f"{type(exc).__name__}: adapter did not confirm exact delivery"
            )
            draft["cycle"] = cycle
            channel["last_cycle"] = max(channel["last_cycle"], cycle)
            self._record(channel_id, "send_failed", cycle)
            return {"status": "send_failed", **deepcopy(draft)}
        draft["status"] = "sent"
        draft["external_message_id"] = external_message_id
        draft["cycle"] = cycle
        channel["sent_count"] += 1
        channel["last_sent_at"] = float(now)
        channel["last_cycle"] = max(channel["last_cycle"], cycle)
        self._record(channel_id, "sent", cycle)
        return {"status": "sent", **deepcopy(draft)}

    def get_channel(self, channel_id: str) -> Optional[dict]:
        channel = self._channel(channel_id)
        if channel is None:
            return None
        messages = [
            deepcopy(item) for item in self.messages if item["channel_id"] == channel_id
        ]
        pending = next(
            (
                deepcopy(item)
                for item in reversed(messages)
                if item["status"] in ACTIVE_DRAFT_STATUSES
            ),
            None,
        )
        return {**deepcopy(channel), "messages": messages, "pending_draft": pending}

    def get_status(self) -> dict:
        return {
            "channels": len(self.channels),
            "active": sum(item["status"] == "active" for item in self.channels),
            "messages": len(self.messages),
            "pending_drafts": sum(
                item["status"] in ACTIVE_DRAFT_STATUSES for item in self.messages
            ),
            "sent": sum(item["status"] == "sent" for item in self.messages),
            "workers": 0,
            "automatic_resume": False,
        }

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "channels": deepcopy(self.channels),
            "messages": deepcopy(self.messages),
            "control_events": deepcopy(self.control_events),
        }

    def load_from(self, data, registry_data) -> None:
        restored = _normalized_snapshot(data)
        validate_social_channels(restored, registry_data)
        for message in restored["messages"]:
            if message["status"] == "approved":
                message["status"] = "draft"
                message["grant_version"] = None
        self.channels = restored["channels"]
        self.messages = restored["messages"]
        self.control_events = restored["control_events"]
