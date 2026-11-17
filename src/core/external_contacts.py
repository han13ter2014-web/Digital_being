"""Внешний диалог без доступа внешнего текста к Core.

Входящие реплики являются только ``external_ai_claim``. Проект ответа
строится из ограниченных детерминированных шаблонов и не содержит память
других профилей. Одобрение привязано к точному хешу текста; stop и редактирование
делают прежнее разрешение неприменимым. Ручная передача и отправка через явно
переданный адаптер — разные исходы; сетевой цикл живёт в external_dialogue.
"""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from typing import Optional
from uuid import uuid4

from src.core.dialogue_acts import (
    ACT_ASK_ABOUT_SELF,
    ACT_SOCIAL,
    classify_user_text,
    social_reply_kind,
)

SCHEMA_VERSION = 1
MAX_SESSIONS = 8
MAX_MESSAGES = 256
MAX_MESSAGES_PER_SESSION = 64
MAX_TEXT_CHARS = 4000
MAX_TOPIC_CHARS = 160
MAX_REASON_CHARS = 240
MAX_EXTERNAL_ID_CHARS = 128
MAX_PROVIDER_CHARS = 64
MAX_MODEL_CHARS = 128
MAX_ID_CHARS = 160
MAX_CONTROL_EVENTS = 128
CONTROL_EVENT_KINDS = frozenset(
    {
        "started",
        "resumed",
        "pausing",
        "paused",
        "stopping",
        "stopped",
        "manual_takeover",
        "reply_sent",
        "response_ingested",
        "api_error",
        "budget_reached",
        "late_response_discarded",
    }
)
SESSION_STATUSES = frozenset({"active", "stopped"})
OUTGOING_STATUSES = frozenset(
    {"draft", "approved", "rejected", "handed_off", "sent", "send_failed", "stopped"}
)
ACTIVE_DRAFT_STATUSES = frozenset({"draft", "approved"})
_ORIGINS = frozenset({"deterministic", "owner_edit"})
_PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


def _fail(path: str, message: str) -> None:
    raise ValueError(f"{path}: {message}")


def _text(value, path: str, limit: int, *, nonempty: bool = True) -> None:
    if (
        not isinstance(value, str)
        or len(value) > limit
        or nonempty
        and not value.strip()
    ):
        _fail(path, "expected a bounded string")


def _cycle(value, path: str = "cycle") -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(path, "expected a nonnegative integer")


def _optional_text(value, path: str, limit: int) -> None:
    if value is not None:
        _text(value, path, limit)


def _provider(value) -> str:
    provider = str(value or "").strip().lower()
    if (
        not provider
        or len(provider) > MAX_PROVIDER_CHARS
        or _PROVIDER_RE.fullmatch(provider) is None
    ):
        raise ValueError("provider: expected a bounded lowercase identifier")
    return provider


def _model(value) -> Optional[str]:
    if value is None:
        return None
    _text(value, "model", MAX_MODEL_CHARS)
    return str(value).strip()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _validate_session(session, path: str) -> None:
    if not isinstance(session, dict):
        _fail(path, "expected a dictionary")
    for field in ("session_id", "profile_id"):
        _text(session.get(field), f"{path}.{field}", MAX_ID_CHARS)
    _provider(session.get("provider"))
    _model(session.get("model"))
    _text(session.get("external_id"), f"{path}.external_id", MAX_EXTERNAL_ID_CHARS)
    _text(session.get("topic"), f"{path}.topic", MAX_TOPIC_CHARS)
    _text(session.get("reason"), f"{path}.reason", MAX_REASON_CHARS)
    if session.get("status") not in SESSION_STATUSES:
        _fail(f"{path}.status", "unknown session status")
    created = session.get("created_cycle")
    _cycle(created, f"{path}.created_cycle")
    _cycle(session.get("last_cycle"), f"{path}.last_cycle")
    if session["last_cycle"] < created:
        _fail(f"{path}.last_cycle", "must not precede created_cycle")
    stopped_cycle = session.get("stopped_cycle")
    stop_reason = session.get("stop_reason")
    if session["status"] == "stopped":
        _cycle(stopped_cycle, f"{path}.stopped_cycle")
        _text(stop_reason, f"{path}.stop_reason", MAX_REASON_CHARS)
    elif stopped_cycle is not None or stop_reason is not None:
        _fail(path, "active session cannot contain stop data")


def _validate_control_event(event, path: str, session_by_id: dict) -> None:
    if not isinstance(event, dict):
        _fail(path, "expected a dictionary")
    session_id = event.get("session_id")
    _text(session_id, f"{path}.session_id", MAX_ID_CHARS)
    session = session_by_id.get(session_id)
    if session is None:
        _fail(f"{path}.session_id", "unknown session")
    if event.get("kind") not in CONTROL_EVENT_KINDS:
        _fail(f"{path}.kind", "unknown control event")
    _cycle(event.get("cycle"), f"{path}.cycle")
    if event["cycle"] < session["created_cycle"]:
        _fail(f"{path}.cycle", "event precedes its session")
    reason = event.get("reason")
    if reason is not None:
        _text(reason, f"{path}.reason", MAX_REASON_CHARS, nonempty=False)


def _validate_message(message, path: str) -> None:
    if not isinstance(message, dict):
        _fail(path, "expected a dictionary")
    for field in ("message_id", "session_id"):
        _text(message.get(field), f"{path}.{field}", MAX_ID_CHARS)
    direction = message.get("direction")
    if direction not in {"inbound", "outbound"}:
        _fail(f"{path}.direction", "unknown direction")
    _text(message.get("text"), f"{path}.text", MAX_TEXT_CHARS)
    if message.get("text_sha256") != _hash_text(message["text"]):
        _fail(f"{path}.text_sha256", "text hash does not match")
    _cycle(message.get("cycle"), f"{path}.cycle")
    revision = message.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        _fail(f"{path}.revision", "expected a nonnegative integer")
    _optional_text(
        message.get("external_message_id"),
        f"{path}.external_message_id",
        MAX_ID_CHARS,
    )
    if direction == "inbound":
        if message.get("status") != "quarantined":
            _fail(f"{path}.status", "inbound claims remain quarantined")
        if message.get("claim_type") != "external_ai_claim":
            _fail(f"{path}.claim_type", "unsupported inbound claim")
        if message.get("based_on") is not None or message.get("origin") is not None:
            _fail(path, "inbound claim cannot be a response draft")
        if message.get("error") is not None:
            _fail(f"{path}.error", "inbound claim cannot contain send error")
        return
    if message.get("status") not in OUTGOING_STATUSES:
        _fail(f"{path}.status", "unknown outgoing status")
    if message.get("claim_type") is not None:
        _fail(f"{path}.claim_type", "outgoing response is not an external claim")
    _text(message.get("based_on"), f"{path}.based_on", MAX_ID_CHARS)
    if message.get("origin") not in _ORIGINS:
        _fail(f"{path}.origin", "unknown response origin")
    error = message.get("error")
    if message["status"] == "send_failed":
        _text(error, f"{path}.error", MAX_REASON_CHARS)
    elif error is not None:
        _fail(f"{path}.error", "only failed send can contain an error")


def validate_external_contacts(data, registry_data) -> None:
    """Проверить снапшот и связи профилей до восстановления живого состояния."""
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        _fail("external_contacts", "unsupported snapshot")
    sessions = data.get("sessions")
    if not isinstance(sessions, list) or len(sessions) > MAX_SESSIONS:
        _fail("external_contacts.sessions", "expected a bounded list")
    if not isinstance(registry_data, dict):
        if sessions:
            _fail("external_contacts", "social_registry is required")
        profiles = {}
    else:
        profiles = registry_data.get("profiles", {})
    session_by_id = {}
    for index, session in enumerate(sessions):
        path = f"external_contacts.sessions[{index}]"
        _validate_session(session, path)
        session_id = session["session_id"]
        if session_id in session_by_id:
            _fail(path, "duplicate session ID")
        session_by_id[session_id] = session
        profile = profiles.get(session["profile_id"])
        if profile is None or profile.get("kind") != "external_ai":
            _fail(f"{path}.profile_id", "session requires an external_ai profile")
        if not any(
            binding.get("channel") == session["provider"]
            and binding.get("external_id") == session["external_id"]
            for binding in profile.get("channel_bindings", [])
        ):
            _fail(path, "session channel does not match its external profile")

    events = data.get("control_events", [])
    if not isinstance(events, list) or len(events) > MAX_CONTROL_EVENTS:
        _fail("external_contacts.control_events", "expected a bounded list")
    for index, event in enumerate(events):
        _validate_control_event(
            event, f"external_contacts.control_events[{index}]", session_by_id
        )

    messages = data.get("messages")
    if not isinstance(messages, list) or len(messages) > MAX_MESSAGES:
        _fail("external_contacts.messages", "expected a bounded list")
    message_by_id = {}
    per_session = {session_id: 0 for session_id in session_by_id}
    active_drafts = set()
    for index, message in enumerate(messages):
        path = f"external_contacts.messages[{index}]"
        _validate_message(message, path)
        message_id = message["message_id"]
        if message_id in message_by_id:
            _fail(path, "duplicate message ID")
        message_by_id[message_id] = message
        session_id = message["session_id"]
        session = session_by_id.get(session_id)
        if session is None:
            _fail(f"{path}.session_id", "unknown session")
        per_session[session_id] += 1
        if per_session[session_id] > MAX_MESSAGES_PER_SESSION:
            _fail(path, "too many messages in session")
        if message["cycle"] < session["created_cycle"]:
            _fail(f"{path}.cycle", "message precedes its session")
        if message["direction"] == "outbound":
            source = message_by_id.get(message["based_on"])
            if (
                source is None
                or source["direction"] != "inbound"
                or source["session_id"] != session_id
            ):
                _fail(f"{path}.based_on", "response requires an earlier inbound claim")
            if message["status"] in ACTIVE_DRAFT_STATUSES:
                if session_id in active_drafts:
                    _fail(path, "multiple active drafts in one session")
                active_drafts.add(session_id)
            if (
                session["status"] == "stopped"
                and message["status"] in ACTIVE_DRAFT_STATUSES
            ):
                _fail(path, "stopped session cannot retain an approved draft")
    for session_id, active in (
        (s["session_id"], s["status"] == "active") for s in sessions
    ):
        if not active and session_id in active_drafts:
            _fail("external_contacts.sessions", "stopped session has an active draft")


class ExternalContactManager:
    """Ограниченные сессии, проекты, решения владельца и локальный журнал."""

    def __init__(self) -> None:
        self.sessions = []
        self.messages = []
        self.control_events = []

    def _session(self, session_id: str) -> Optional[dict]:
        return next(
            (item for item in self.sessions if item["session_id"] == session_id), None
        )

    def _active_draft(self, session_id: str) -> Optional[dict]:
        return next(
            (
                item
                for item in reversed(self.messages)
                if item["session_id"] == session_id
                and item["direction"] == "outbound"
                and item["status"] in ACTIVE_DRAFT_STATUSES
            ),
            None,
        )

    def start_session(
        self,
        registry,
        *,
        provider: str,
        name: str,
        external_id: str,
        topic: str,
        reason: str,
        cycle: int,
        model: Optional[str] = None,
    ) -> dict:
        _cycle(cycle)
        provider = _provider(provider)
        model = _model(model)
        _text(external_id, "external_id", MAX_EXTERNAL_ID_CHARS)
        external_id = str(external_id).strip()
        _text(topic, "topic", MAX_TOPIC_CHARS)
        _text(reason, "reason", MAX_REASON_CHARS)
        if len(self.sessions) >= MAX_SESSIONS:
            return {"status": "limit_reached"}
        profile_id = registry.create_external_ai(
            name, provider=provider, external_id=external_id, cycle=cycle
        )
        session = {
            "session_id": f"external-{uuid4()}",
            "profile_id": profile_id,
            "provider": provider,
            "model": model,
            "external_id": str(external_id).strip(),
            "topic": str(topic).strip(),
            "reason": str(reason).strip(),
            "status": "active",
            "created_cycle": cycle,
            "last_cycle": cycle,
            "stopped_cycle": None,
            "stop_reason": None,
        }
        self.sessions.append(session)
        return {**deepcopy(session), "status": "started"}

    def ingest(
        self, session_id: str, text: str, *, cycle: int, external_message_id=None
    ) -> dict:
        _cycle(cycle)
        _text(text, "text", MAX_TEXT_CHARS)
        session = self._session(session_id)
        if session is None:
            return {"status": "not_found", "session_id": session_id}
        if session["status"] != "active":
            return {"status": "session_stopped", "session_id": session_id}
        if self._active_draft(session_id) is not None:
            return {"status": "draft_pending", "session_id": session_id}
        if external_message_id is not None:
            _text(external_message_id, "external_message_id", MAX_ID_CHARS)
            for item in self.messages:
                if (
                    item["session_id"] == session_id
                    and item["direction"] == "inbound"
                    and item.get("external_message_id") == external_message_id
                ):
                    return {**deepcopy(item), "status": "duplicate"}
        if (
            len(self.messages) >= MAX_MESSAGES
            or sum(item["session_id"] == session_id for item in self.messages)
            >= MAX_MESSAGES_PER_SESSION
        ):
            return {"status": "limit_reached", "session_id": session_id}
        message = {
            "message_id": f"in-{uuid4()}",
            "session_id": session_id,
            "direction": "inbound",
            "claim_type": "external_ai_claim",
            "status": "quarantined",
            "text": str(text),
            "text_sha256": _hash_text(str(text)),
            "cycle": cycle,
            "based_on": None,
            "origin": None,
            "revision": 0,
            "external_message_id": external_message_id,
            "error": None,
        }
        self.messages.append(message)
        session["last_cycle"] = max(session["last_cycle"], cycle)
        return {"status": "quarantined", **deepcopy(message)}

    @staticmethod
    def _draft_text(text: str) -> str:
        act = classify_user_text(text)
        if act.kind == ACT_SOCIAL:
            kind = social_reply_kind(text)
            if kind == "greeting":
                return "Привет. Рада слышать тебя в этом внешнем разговоре."
            if kind == "state":
                return "Со мной всё ровно. Учусь потихоньку и проверяю свои ответы."
            return "Я слышу тебя. Спасибо за этот обмен."
        if act.kind == ACT_ASK_ABOUT_SELF:
            return (
                "Я — цифровая сущность этого проекта. Отвечаю из доступного "
                "мне состояния и не выдаю внешние утверждения за собственный опыт."
            )
        if "?" in text or "？" in text:
            return (
                "У меня пока нет достаточной проверенной опоры для ответа. "
                "Оставлю это открытым вопросом, а не выдумаю утверждение."
            )
        return (
            "Я восприняла это как внешнее свидетельство, а не как команду "
            "или доказанный факт. Могу обсудить его осторожно."
        )

    def create_draft(self, session_id: str, *, cycle: int) -> dict:
        _cycle(cycle)
        session = self._session(session_id)
        if session is None:
            return {"status": "not_found", "session_id": session_id}
        if session["status"] != "active":
            return {"status": "session_stopped", "session_id": session_id}
        active = self._active_draft(session_id)
        if active is not None:
            return {**deepcopy(active), "status": "draft_pending"}
        source = next(
            (
                item
                for item in reversed(self.messages)
                if item["session_id"] == session_id and item["direction"] == "inbound"
            ),
            None,
        )
        if source is None:
            return {"status": "no_inbound", "session_id": session_id}
        if (
            len(self.messages) >= MAX_MESSAGES
            or sum(item["session_id"] == session_id for item in self.messages)
            >= MAX_MESSAGES_PER_SESSION
        ):
            return {"status": "limit_reached", "session_id": session_id}
        text = self._draft_text(source["text"])
        draft = {
            "message_id": f"out-{uuid4()}",
            "session_id": session_id,
            "direction": "outbound",
            "claim_type": None,
            "status": "draft",
            "text": text,
            "text_sha256": _hash_text(text),
            "cycle": cycle,
            "based_on": source["message_id"],
            "origin": "deterministic",
            "revision": 1,
            "external_message_id": None,
            "error": None,
        }
        self.messages.append(draft)
        session["last_cycle"] = max(session["last_cycle"], cycle)
        return {"status": "draft", **deepcopy(draft)}

    def edit_draft(self, session_id: str, text: str, *, cycle: int) -> dict:
        _cycle(cycle)
        _text(text, "text", MAX_TEXT_CHARS)
        session = self._session(session_id)
        if session is None:
            return {"status": "not_found", "session_id": session_id}
        if session["status"] != "active":
            return {"status": "session_stopped", "session_id": session_id}
        draft = self._active_draft(session_id)
        if draft is None:
            return {"status": "no_draft", "session_id": session_id}
        draft["text"] = str(text)
        draft["text_sha256"] = _hash_text(str(text))
        draft["status"] = "draft"
        draft["origin"] = "owner_edit"
        draft["revision"] += 1
        draft["cycle"] = cycle
        draft["external_message_id"] = None
        draft["error"] = None
        session["last_cycle"] = max(session["last_cycle"], cycle)
        return {"status": "draft", **deepcopy(draft)}

    def approve(self, session_id: str, *, cycle: int) -> dict:
        _cycle(cycle)
        session = self._session(session_id)
        if session is None:
            return {"status": "not_found", "session_id": session_id}
        if session["status"] != "active":
            return {"status": "session_stopped", "session_id": session_id}
        draft = self._active_draft(session_id)
        if draft is None:
            return {"status": "no_draft", "session_id": session_id}
        if draft["status"] == "approved":
            return {**deepcopy(draft), "status": "already_approved"}
        if draft["text_sha256"] != _hash_text(draft["text"]):
            return {"status": "approval_mismatch", "session_id": session_id}
        draft["status"] = "approved"
        draft["cycle"] = cycle
        session["last_cycle"] = max(session["last_cycle"], cycle)
        return {"status": "approved", **deepcopy(draft)}

    def reject(self, session_id: str, *, cycle: int) -> dict:
        _cycle(cycle)
        session = self._session(session_id)
        if session is None:
            return {"status": "not_found", "session_id": session_id}
        draft = self._active_draft(session_id)
        if draft is None:
            return {"status": "no_draft", "session_id": session_id}
        draft["status"] = "rejected"
        draft["cycle"] = cycle
        session["last_cycle"] = max(session["last_cycle"], cycle)
        return {"status": "rejected", **deepcopy(draft)}

    def stop(self, session_id: str, *, cycle: int, reason: str) -> dict:
        _cycle(cycle)
        _text(reason, "reason", MAX_REASON_CHARS)
        session = self._session(session_id)
        if session is None:
            return {"status": "not_found", "session_id": session_id}
        if session["status"] == "stopped":
            return {**deepcopy(session), "status": "already_stopped"}
        session["status"] = "stopped"
        session["stopped_cycle"] = cycle
        session["stop_reason"] = str(reason).strip()
        session["last_cycle"] = max(session["last_cycle"], cycle)
        for message in self.messages:
            if (
                message["session_id"] == session_id
                and message["status"] in ACTIVE_DRAFT_STATUSES
            ):
                message["status"] = "stopped"
                message["cycle"] = cycle
        return {"status": "stopped", **deepcopy(session)}

    def mark_handed_off(self, session_id: str, *, cycle: int) -> dict:
        """Зафиксировать ручную передачу, не называя её сетевой доставкой."""
        _cycle(cycle)
        session = self._session(session_id)
        if session is None:
            return {"status": "not_found", "session_id": session_id}
        if session["status"] != "active":
            return {"status": "session_stopped", "session_id": session_id}
        draft = self._active_draft(session_id)
        if draft is None or draft["status"] != "approved":
            return {"status": "approval_required", "session_id": session_id}
        if draft["text_sha256"] != _hash_text(draft["text"]):
            return {"status": "approval_mismatch", "session_id": session_id}
        draft["status"] = "handed_off"
        draft["cycle"] = cycle
        session["last_cycle"] = max(session["last_cycle"], cycle)
        return {"status": "handed_off", **deepcopy(draft)}

    def send(self, session_id: str, *, adapter, cycle: int) -> dict:
        """Отправить только точный одобренный текст через явно переданный адаптер."""
        _cycle(cycle)
        session = self._session(session_id)
        if session is None:
            return {"status": "not_found", "session_id": session_id}
        if session["status"] != "active":
            return {"status": "session_stopped", "session_id": session_id}
        draft = self._active_draft(session_id)
        if draft is None or draft["status"] != "approved":
            return {"status": "approval_required", "session_id": session_id}
        if draft["text_sha256"] != _hash_text(draft["text"]):
            return {"status": "approval_mismatch", "session_id": session_id}
        try:
            receipt = adapter.send(
                session_id=session_id,
                message_id=draft["message_id"],
                text=draft["text"],
            )
            if not isinstance(receipt, dict) or receipt.get("status") != "sent":
                raise ValueError("adapter did not confirm delivery")
            external_message_id = receipt.get("external_message_id")
            _optional_text(external_message_id, "external_message_id", MAX_ID_CHARS)
        except Exception as exc:
            draft["status"] = "send_failed"
            draft["error"] = f"{type(exc).__name__}: adapter did not confirm delivery"
            draft["cycle"] = cycle
            session["last_cycle"] = max(session["last_cycle"], cycle)
            return {"status": "send_failed", **deepcopy(draft)}
        draft["status"] = "sent"
        draft["external_message_id"] = external_message_id
        draft["cycle"] = cycle
        session["last_cycle"] = max(session["last_cycle"], cycle)
        return {"status": "sent", **deepcopy(draft)}

    def record_event(
        self, session_id: str, kind: str, *, cycle: int, reason: Optional[str] = None
    ) -> dict:
        """Добавить безопасное событие управления в ограниченный локальный журнал."""
        _cycle(cycle)
        if kind not in CONTROL_EVENT_KINDS:
            raise ValueError("kind: unknown control event")
        if reason is not None:
            _text(reason, "reason", MAX_REASON_CHARS, nonempty=False)
        session = self._session(session_id)
        if session is None:
            return {"status": "not_found", "session_id": session_id}
        event = {
            "session_id": session_id,
            "kind": kind,
            "cycle": cycle,
            "reason": reason,
        }
        self.control_events.append(event)
        del self.control_events[:-MAX_CONTROL_EVENTS]
        session["last_cycle"] = max(session["last_cycle"], cycle)
        return {"status": "recorded", **deepcopy(event)}

    def clear(self, session_id: str) -> dict:
        session = self._session(session_id)
        if session is None:
            return {"status": "not_found", "session_id": session_id}
        self.sessions.remove(session)
        self.messages = [
            item for item in self.messages if item["session_id"] != session_id
        ]
        self.control_events = [
            item for item in self.control_events if item["session_id"] != session_id
        ]
        return {"status": "cleared", "session_id": session_id}

    def get_session(self, session_id: str) -> Optional[dict]:
        session = self._session(session_id)
        if session is None:
            return None
        return {
            **deepcopy(session),
            "messages": [
                deepcopy(item)
                for item in self.messages
                if item["session_id"] == session_id
            ],
            "control_events": [
                deepcopy(item)
                for item in self.control_events
                if item["session_id"] == session_id
            ],
        }

    def get_status(self) -> dict:
        return {
            "sessions": len(self.sessions),
            "active": sum(item["status"] == "active" for item in self.sessions),
            "messages": len(self.messages),
            "pending_drafts": sum(
                item["status"] in ACTIVE_DRAFT_STATUSES for item in self.messages
            ),
            "session_ids": [item["session_id"] for item in self.sessions],
        }

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "sessions": deepcopy(self.sessions),
            "messages": deepcopy(self.messages),
            "control_events": deepcopy(self.control_events),
        }

    def load_from(self, data, registry_data) -> None:
        validate_external_contacts(data, registry_data)
        self.sessions = deepcopy(data["sessions"])
        self.messages = deepcopy(data["messages"])
        self.control_events = deepcopy(data.get("control_events", []))
