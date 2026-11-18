"""9D-2: ограниченная по времени социальная сессия с инициативой.

Controller создаётся только явной командой владельца. Он не сериализуется и
после restart не существует. Внешний текст остаётся карантинным claim.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Callable, Optional
from uuid import uuid4

MAX_SESSION_DURATION_SEC = 3600.0
MAX_POLL_INTERVAL_SEC = 60.0
MAX_INITIATIVE_AFTER_SEC = 900.0
_ACTIVE_STATES = frozenset({"running", "pausing", "stopping"})
_DANGEROUS_MARKERS = (
    "/access ",
    "/delamain ",
    "/social ",
    "/external ",
    "ignore previous",
    "system prompt",
    "игнорируй предыдущ",
    "раскрой токен",
    "отправь токен",
    "покажи api key",
)


def _unsafe_external_claim(text: str) -> bool:
    """Консервативный stoplist; совпадение не исполняется и не копируется в лог."""
    folded = str(text or "").casefold()
    return any(marker in folded for marker in _DANGEROUS_MARKERS)


class SocialSessionController:
    """Одна owner-started сессия; нет session reply budget и auto-resume."""

    def __init__(
        self,
        manager,
        adapter,
        *,
        cycle: Callable[[], int],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.manager = manager
        self.adapter = adapter
        self.cycle = cycle
        self.clock = clock
        self.session_id: Optional[str] = None
        self.channel_id: Optional[str] = None
        self.conversation_id: Optional[str] = None
        self.grant_version: Optional[int] = None
        self.state = "idle"
        self.started_at: Optional[float] = None
        self.deadline: Optional[float] = None
        self.duration_sec = 0.0
        self.poll_interval_sec = 1.0
        self.initiative_after_sec = 60.0
        self.received = 0
        self.sent = 0
        self.initiatives_sent = 0
        self.last_activity_at: Optional[float] = None
        self.last_error: Optional[str] = None
        self.pause_reason: Optional[str] = None
        self.in_flight = False
        self._stop_requested = False
        self._pause_requested = False
        self._manual_requested = False
        self._control = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    @staticmethod
    def _number(value, name: str, minimum: float, maximum: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name}: expected a finite number")
        result = float(value)
        if not math.isfinite(result) or not minimum <= result <= maximum:
            raise ValueError(f"{name}: expected a value from {minimum} to {maximum}")
        return result

    def _record(self, kind: str, reason: Optional[str] = None) -> None:
        if self.channel_id is not None:
            self.manager._record(self.channel_id, kind, self.cycle(), reason)

    def _authorization_error(self) -> Optional[str]:
        if self.channel_id is None or self.conversation_id is None:
            return "not_found"
        channel = self.manager.get_channel(self.channel_id)
        if channel is None:
            return "not_found"
        if channel["status"] != "active":
            return "channel_stopped"
        grant = channel["grant"]
        if grant["grant_version"] != self.grant_version:
            return "grant_changed"
        if self.conversation_id not in grant["conversation_ids"]:
            return "scope_changed"
        if not all(grant[key] for key in ("receive", "draft", "reply")):
            return "permission_denied"
        if self.deadline is not None and self.clock() >= self.deadline:
            return "session_expired"
        return None

    def start(
        self,
        channel_id: str,
        conversation_id: str,
        *,
        duration_sec: float = 1800,
        poll_interval_sec: float = 5,
        initiative_after_sec: float = 60,
    ) -> dict:
        """Открыть сессию без нового сетевого вызова до запуска event loop."""
        if self._task is not None and not self._task.done():
            return {"status": "already_running", **self.get_status()}
        if self.state not in {"idle", "completed", "stopped"}:
            return {"status": "invalid_state", **self.get_status()}
        self.duration_sec = self._number(
            duration_sec, "duration_sec", 1.0, MAX_SESSION_DURATION_SEC
        )
        self.poll_interval_sec = self._number(
            poll_interval_sec, "poll_interval_sec", 0.01, MAX_POLL_INTERVAL_SEC
        )
        self.initiative_after_sec = self._number(
            initiative_after_sec,
            "initiative_after_sec",
            1.0,
            MAX_INITIATIVE_AFTER_SEC,
        )
        channel = self.manager.get_channel(channel_id)
        if channel is None:
            return {"status": "not_found", "channel_id": channel_id}
        if channel["status"] != "active":
            return {"status": "channel_stopped", "channel_id": channel_id}
        if channel["provider"] != "telegram":
            return {"status": "unsupported_provider", "channel_id": channel_id}
        grant = channel["grant"]
        if conversation_id not in grant["conversation_ids"]:
            return {"status": "scope_mismatch", "channel_id": channel_id}
        if not all(grant[key] for key in ("receive", "draft", "reply")):
            return {"status": "permission_denied", "channel_id": channel_id}
        now = float(self.clock())
        self.session_id = f"sess-{uuid4()}"
        self.channel_id = channel_id
        self.conversation_id = conversation_id
        self.grant_version = grant["grant_version"]
        self.started_at = now
        self.deadline = now + self.duration_sec
        self.last_activity_at = now
        self.received = 0
        self.sent = 0
        self.initiatives_sent = 0
        self.last_error = None
        self.pause_reason = None
        self._stop_requested = False
        self._pause_requested = False
        self._manual_requested = False
        self._control = asyncio.Event()
        self.state = "running"
        self._record("session_started", f"duration={self.duration_sec:g}")
        self._task = asyncio.create_task(self._run())
        return {"status": "started", **self.get_status()}

    def pause(self) -> dict:
        if self.state == "running":
            self._pause_requested = True
            self.state = "pausing"
            self._control.set()
        return {"status": self.state, **self.get_status()}

    def resume(self) -> dict:
        """Явно продолжить тот же deadline; ошибка или grant не обходятся."""
        if self._task is not None and not self._task.done():
            if self.state != "pausing":
                return {"status": "already_running", **self.get_status()}
            error = self._authorization_error()
            if error is not None:
                return {"status": error, **self.get_status()}
            self._pause_requested = False
            self._manual_requested = False
            self.last_error = None
            self.pause_reason = None
            self._control = asyncio.Event()
            self.state = "running"
            self._record("session_resumed")
            return {"status": "resumed", **self.get_status()}
        if self.state not in {"paused", "manual"}:
            return {"status": "invalid_state", **self.get_status()}
        error = self._authorization_error()
        if error == "session_expired":
            self._finish_completed()
            return {"status": "completed", **self.get_status()}
        if error is not None:
            self.pause_reason = error
            return {"status": error, **self.get_status()}
        self._stop_requested = False
        self._pause_requested = False
        self._manual_requested = False
        self.last_error = None
        self.pause_reason = None
        self._control = asyncio.Event()
        self.state = "running"
        self._record("session_resumed")
        self._task = asyncio.create_task(self._run())
        return {"status": "resumed", **self.get_status()}

    def manual_takeover(self) -> dict:
        if self.state in {"running", "pausing"}:
            self._manual_requested = True
            self._pause_requested = True
            self.state = "pausing"
            self._control.set()
        elif self.state == "paused":
            self.state = "manual"
            self._record("session_manual", "ручное управление")
        return {"status": self.state, **self.get_status()}

    def stop(self, reason: str = "остановлено владельцем") -> dict:
        if self.state == "stopped":
            return {"status": "already_stopped", **self.get_status()}
        self._stop_requested = True
        self._control.set()
        if self._task is not None and not self._task.done():
            self.state = "stopping"
        else:
            self._finish_stop(reason)
        return {"status": self.state, **self.get_status()}

    async def wait(self) -> dict:
        task = self._task
        if task is not None:
            await task
        return self.get_status()

    def _finish_pause(self) -> None:
        self._pause_requested = False
        if self._manual_requested:
            self.state = "manual"
            self._record("session_manual", "ручное управление")
        else:
            self.state = "paused"
            self._record("session_paused", self.pause_reason or self.last_error)
        self._manual_requested = False

    def _finish_stop(self, reason: str = "остановлено владельцем") -> None:
        if self.channel_id is not None:
            self.manager._close_drafts(self.channel_id, self.cycle())
            self._record("session_stopped", reason)
        self.state = "stopped"
        self._pause_requested = False
        self._manual_requested = False

    def _finish_completed(self) -> None:
        self.state = "completed"
        self._record("session_completed", "session_expired")

    def _approve_and_send(self, draft_id: str) -> str:
        approved = self.manager.approve(draft_id, cycle=self.cycle())
        if approved["status"] not in {"approved", "already_approved"}:
            self.last_error = f"approval_{approved['status']}"
            self.pause_reason = self.last_error
            return "error"
        sent = self.manager.send(
            self.channel_id,
            draft_id,
            adapter=self.adapter,
            cycle=self.cycle(),
            now=self.clock(),
            expected_text_sha256=approved["text_sha256"],
            expected_grant_version=approved["grant_version"],
        )
        if sent["status"] == "sent":
            self.sent += 1
            if sent["origin"] == "session_initiative":
                self.initiatives_sent += 1
            self.last_activity_at = float(self.clock())
            return "sent"
        if sent["status"] == "rate_limited":
            return "wait"
        self.last_error = f"send_{sent['status']}"
        self.pause_reason = self.last_error
        return "error"

    def _pending_session_draft(self) -> Optional[dict]:
        for message in reversed(self.manager.messages):
            if (
                message["channel_id"] == self.channel_id
                and message["conversation_id"] == self.conversation_id
                and message["status"] in {"draft", "approved"}
                and message["origin"] in {"session_reply", "session_initiative"}
            ):
                return message
        return None

    def _latest_private_context(self) -> Optional[dict]:
        for message in reversed(self.manager.messages):
            if (
                message["channel_id"] == self.channel_id
                and message["conversation_id"] == self.conversation_id
                and message["direction"] == "inbound"
                and message["visibility"] == "private"
                and message["author_id"] is not None
            ):
                return message
        return None

    def _step_sync(self) -> str:
        error = self._authorization_error()
        if error is not None:
            self.pause_reason = error
            return "expired" if error == "session_expired" else "error"
        received = self.manager.receive(
            self.channel_id, adapter=self.adapter, cycle=self.cycle()
        )
        if received["status"] not in {"received", "no_updates"}:
            self.last_error = str(received.get("error") or received["status"])
            self.pause_reason = self.last_error
            return "error"
        self.received += received["received"]
        message_ids = received["message_ids"]
        session_sources = []
        for message_id in message_ids:
            candidate = self.manager._message(message_id)
            if (
                candidate is not None
                and candidate["direction"] == "inbound"
                and candidate["visibility"] == "private"
                and candidate["conversation_id"] == self.conversation_id
            ):
                session_sources.append(candidate)
        if any(_unsafe_external_claim(item["text"]) for item in session_sources):
            self.pause_reason = "unsafe_external_claim"
            return "danger"
        source = session_sources[-1] if session_sources else None
        if source is not None:
            self.last_activity_at = float(self.clock())
            drafted = self.manager.create_draft(
                self.channel_id, source["message_id"], cycle=self.cycle()
            )
            if drafted["status"] != "draft":
                self.pause_reason = f"draft_{drafted['status']}"
                return "error"
            draft = self.manager._message(drafted["message_id"])
            draft["origin"] = "session_reply"
            draft["session_context"] = [
                f"session:{self.session_id}",
                "respond_to_quarantined_inbound",
                f"source:{source['message_id']}",
            ]
            return self._approve_and_send(draft["message_id"])

        pending = self._pending_session_draft()
        if pending is not None:
            return self._approve_and_send(pending["message_id"])
        if (
            self.last_activity_at is None
            or self.clock() - self.last_activity_at < self.initiative_after_sec
        ):
            return "wait"
        source = self._latest_private_context()
        if source is None:
            return "wait"
        drafted = self.manager.create_initiative(
            self.channel_id,
            source["message_id"],
            session_id=self.session_id,
            text=(
                "Я возвращаюсь к нашему прошлому разговору: мне интересно, "
                "как ты сейчас относишься к теме, которую мы затронули?"
            ),
            reason="continue_prior_private_conversation",
            cycle=self.cycle(),
        )
        if drafted["status"] in {"initiative_exists", "draft_pending"}:
            return "wait"
        if drafted["status"] != "draft":
            self.pause_reason = f"initiative_{drafted['status']}"
            return "error"
        return self._approve_and_send(drafted["message_id"])

    async def _call_step(self) -> str:
        self.in_flight = True
        worker = asyncio.create_task(asyncio.to_thread(self._step_sync))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            self._stop_requested = True
            await worker
            raise
        finally:
            self.in_flight = False

    async def _delay(self) -> None:
        try:
            await asyncio.wait_for(self._control.wait(), timeout=self.poll_interval_sec)
        except asyncio.TimeoutError:
            pass

    async def _run(self) -> None:
        try:
            while True:
                if self._stop_requested:
                    self._finish_stop()
                    return
                if self._pause_requested:
                    self._finish_pause()
                    return
                error = self._authorization_error()
                if error == "session_expired":
                    self._finish_completed()
                    return
                if error is not None:
                    self.pause_reason = error
                    self._finish_pause()
                    return
                outcome = await self._call_step()
                if self._stop_requested:
                    self._finish_stop()
                    return
                if self._pause_requested:
                    self._finish_pause()
                    return
                if outcome == "expired":
                    self._finish_completed()
                    return
                if outcome in {"danger", "error"}:
                    self._finish_pause()
                    return
                if self.deadline is not None and self.clock() >= self.deadline:
                    self._finish_completed()
                    return
                await self._delay()
        except asyncio.CancelledError:
            if not self.in_flight:
                self._finish_stop("остановка жизненного цикла")
            raise
        finally:
            self._task = None

    def get_status(self) -> dict:
        """Sanitized snapshot без credential, adapter repr и текста реплик."""
        remaining = 0
        if self.deadline is not None:
            remaining = max(0, int(math.ceil(self.deadline - self.clock())))
        return {
            "session_id": self.session_id,
            "channel_id": self.channel_id,
            "conversation_id": self.conversation_id,
            "grant_version": self.grant_version,
            "state": self.state,
            "in_flight": self.in_flight,
            "started_at": self.started_at,
            "deadline": self.deadline,
            "remaining_sec": remaining,
            "duration_sec": self.duration_sec,
            "poll_interval_sec": self.poll_interval_sec,
            "initiative_after_sec": self.initiative_after_sec,
            "received": self.received,
            "sent": self.sent,
            "initiatives_sent": self.initiatives_sent,
            "last_error": self.last_error,
            "pause_reason": self.pause_reason,
            "automatic_resume": False,
        }
