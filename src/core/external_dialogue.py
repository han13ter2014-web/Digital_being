"""Явно запущенный и ограниченный автономный обмен с внешним ИИ."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import math
from typing import Callable, Optional

MAX_AUTONOMOUS_REPLIES = 8
MAX_TOTAL_TOKENS = 256_000
MAX_INTERVAL_SEC = 60.0
_RUNNING_STATES = frozenset({"running", "pausing", "stopping"})


class _ReceiptCapture:
    """Сохранить sanitized receipt, который ручной manager намеренно игнорирует."""

    def __init__(self, adapter):
        self.adapter = adapter
        self.receipt = None

    def send(self, **kwargs):
        self.receipt = self.adapter.send(**kwargs)
        return self.receipt


class ExternalDialogueController:
    """Одна сессия; restart создаёт новый idle-контроллер без автозапуска."""

    def __init__(self, manager, adapter, *, cycle: Callable[[], int]) -> None:
        self.manager = manager
        self.adapter = adapter
        self.cycle = cycle
        self.session_id: Optional[str] = None
        self.state = "idle"
        self.last_error: Optional[str] = None
        self.pause_reason: Optional[str] = None
        self.max_replies = 0
        self.max_total_tokens = 0
        self.min_interval_sec = 0.0
        self.replies_sent = 0
        self.tokens_used = 0
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.tokens_estimated = False
        self.billing_receipts = []
        self.in_flight = False
        self._stop_requested = False
        self._pause_requested = False
        self._manual_requested = False
        self._control = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    def _record(self, kind: str, reason: Optional[str] = None) -> None:
        if self.session_id is not None:
            self.manager.record_event(
                self.session_id, kind, cycle=self.cycle(), reason=reason
            )

    def _session(self) -> Optional[dict]:
        if self.session_id is None:
            return None
        return self.manager.get_session(self.session_id)

    def _validate_limits(
        self, max_replies: int, max_total_tokens: int, min_interval_sec: float
    ) -> None:
        if (
            isinstance(max_replies, bool)
            or not isinstance(max_replies, int)
            or not 1 <= max_replies <= MAX_AUTONOMOUS_REPLIES
        ):
            raise ValueError("max_replies: expected an integer from 1 to 8")
        if (
            isinstance(max_total_tokens, bool)
            or not isinstance(max_total_tokens, int)
            or not 1 <= max_total_tokens <= MAX_TOTAL_TOKENS
        ):
            raise ValueError("max_total_tokens: expected an integer from 1 to 256000")
        if not 0.0 <= float(min_interval_sec) <= MAX_INTERVAL_SEC:
            raise ValueError("min_interval_sec: expected a value from 0 to 60")

    def start(
        self,
        session_id: str,
        *,
        max_replies: int = 3,
        max_total_tokens: int = 1200,
        min_interval_sec: float = 2.0,
    ) -> dict:
        """Начать новый бюджет только по явному вызову владельца."""
        if self._task is not None and not self._task.done():
            return {"status": "already_running", **self.get_status()}
        if self.state not in {"idle", "completed"}:
            return {"status": "invalid_state", **self.get_status()}
        self._validate_limits(max_replies, max_total_tokens, min_interval_sec)
        session = self.manager.get_session(session_id)
        if session is None:
            return {"status": "not_found", "session_id": session_id}
        if session["status"] != "active":
            return {"status": "session_stopped", "session_id": session_id}
        if (
            session["provider"] != self.adapter.provider
            or session.get("model") != self.adapter.model
        ):
            return {"status": "model_mismatch", "session_id": session_id}
        self.session_id = session_id
        self.max_replies = max_replies
        self.max_total_tokens = max_total_tokens
        self.min_interval_sec = float(min_interval_sec)
        self.replies_sent = 0
        self.tokens_used = 0
        self.tokens_estimated = False
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.billing_receipts = []
        self.last_error = None
        self.pause_reason = None
        self._stop_requested = False
        self._pause_requested = False
        self._manual_requested = False
        self._control = asyncio.Event()
        self.state = "running"
        self._record("started", f"replies={max_replies}; tokens={max_total_tokens}")
        self._task = asyncio.create_task(self._run())
        return {"status": "started", **self.get_status()}

    def resume(self) -> dict:
        """Продолжить тот же бюджет после паузы; budget_reached требует start."""
        if self._task is not None and not self._task.done():
            return {"status": "already_running", **self.get_status()}
        if self.state not in {"paused", "manual"}:
            return {"status": "invalid_state", **self.get_status()}
        session = self._session()
        if session is None or session["status"] != "active":
            return {"status": "session_stopped", **self.get_status()}
        self._pause_requested = False
        self._manual_requested = False
        self._stop_requested = False
        self.last_error = None
        self.pause_reason = None
        self._control = asyncio.Event()
        self.state = "running"
        self._record("resumed")
        self._task = asyncio.create_task(self._run())
        return {"status": "resumed", **self.get_status()}

    def pause(self) -> dict:
        if self.state == "running":
            self._pause_requested = True
            self.state = "pausing"
            if not self.in_flight:
                self._record("pausing")
            self._control.set()
        return {"status": self.state, **self.get_status()}

    def manual_takeover(self) -> dict:
        """После текущего неотменяемого запроса оставить следующий ответ вручную."""
        if self.state in {"running", "pausing"}:
            self._manual_requested = True
            self._pause_requested = True
            self.state = "pausing"
            if not self.in_flight:
                self._record("manual_takeover")
            self._control.set()
        elif self.state == "paused":
            self._manual_requested = True
            self._record("manual_takeover")
            self.state = "manual"
        return {"status": self.state, **self.get_status()}

    def stop(self, reason: str = "остановлено владельцем") -> dict:
        """Не начинать новый запрос; текущий HTTP завершается без позднего ingest."""
        if self.state == "stopped":
            return {"status": "already_stopped", **self.get_status()}
        self._stop_requested = True
        self._control.set()
        if self._task is not None and not self._task.done():
            self.state = "stopping"
            if not self.in_flight:
                self._record("stopping", reason)
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
            self._record("paused", "ручное управление следующим ответом")
        else:
            self.state = "paused"
            self._record("paused", self.last_error)
        self._manual_requested = False

    def _finish_stop(self, reason: str = "остановлено владельцем") -> None:
        if self.session_id is not None:
            session = self.manager.get_session(self.session_id)
            if session is not None and session["status"] == "active":
                self.manager.stop(self.session_id, cycle=self.cycle(), reason=reason)
            self._record("stopped", reason)
        self.state = "stopped"
        self._pause_requested = False
        self._manual_requested = False

    def _finish_budget(self) -> None:
        self.state = "completed"
        self._record(
            "budget_reached",
            f"replies={self.replies_sent}; tokens={self.tokens_used}",
        )

    def _account_usage(self, receipt: dict, outgoing_text: str) -> None:
        usage = receipt.get("usage") if isinstance(receipt, dict) else {}
        usage = usage if isinstance(usage, dict) else {}
        for key in self.usage:
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                self.usage[key] += value
        total = usage.get("total_tokens")
        if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
            self.tokens_used += total
        else:
            self.tokens_estimated = True
            self.tokens_used += (
                math.ceil(len(outgoing_text) / 4) + self.adapter.max_tokens
            )
        billing = receipt.get("billing") if isinstance(receipt, dict) else None
        if isinstance(billing, dict) and billing:
            self.billing_receipts.append(deepcopy(billing))
            del self.billing_receipts[:-MAX_AUTONOMOUS_REPLIES]

    async def _send(self):
        capture = _ReceiptCapture(self.adapter)
        self.in_flight = True
        worker = asyncio.create_task(
            asyncio.to_thread(
                self.manager.send,
                self.session_id,
                adapter=capture,
                cycle=self.cycle(),
            )
        )
        try:
            result = await asyncio.shield(worker)
            return result, capture.receipt
        except asyncio.CancelledError:
            # shield оставляет HTTP в worker; дожидаемся его и переводим отмену
            # в обычный stop, чтобы поздний ответ не прошёл через ingest.
            self._stop_requested = True
            result = await worker
            return result, capture.receipt
        finally:
            self.in_flight = False

    def _request_token_upper_bound(self, text: str):
        try:
            bound = self.adapter.request_token_upper_bound(
                session_id=self.session_id, text=text
            )
        except Exception:
            self.last_error = "budget_estimate_failed"
            return None
        if isinstance(bound, bool) or not isinstance(bound, int) or bound < 1:
            self.last_error = "budget_estimate_failed"
            return None
        return bound

    async def _step(self) -> str:
        draft = self.manager.create_draft(self.session_id, cycle=self.cycle())
        if draft["status"] != "draft":
            self.last_error = f"draft_{draft['status']}"
            self._record("api_error", self.last_error)
            return "error"
        upper_bound = self._request_token_upper_bound(draft["text"])
        if upper_bound is None:
            self._record("api_error", self.last_error)
            return "error"
        if self.tokens_used + upper_bound > self.max_total_tokens:
            return "budget"
        approved = self.manager.approve(self.session_id, cycle=self.cycle())
        if approved["status"] not in {"approved", "already_approved"}:
            self.last_error = f"approval_{approved['status']}"
            self._record("api_error", self.last_error)
            return "error"
        sent, receipt = await self._send()
        if sent["status"] != "sent" or not isinstance(receipt, dict):
            self.last_error = sent.get("error") or "adapter_did_not_confirm"
            self._record("api_error", self.last_error)
            return "error"
        self.replies_sent += 1
        self._account_usage(receipt, sent["text"])
        self._record("reply_sent", sent["message_id"])
        if self._stop_requested:
            self._record("late_response_discarded", sent["message_id"])
            return "stopped"
        response_text = receipt.get("response_text")
        external_id = receipt.get("external_message_id")
        try:
            incoming = self.manager.ingest(
                self.session_id,
                response_text,
                cycle=self.cycle(),
                external_message_id=external_id,
            )
        except (TypeError, ValueError):
            self.last_error = "invalid_adapter_receipt"
            self._record("api_error", self.last_error)
            return "error"
        if incoming["status"] != "quarantined":
            self.last_error = f"ingest_{incoming['status']}"
            self._record("api_error", self.last_error)
            return "error"
        self._record("response_ingested", incoming["message_id"])
        if self.tokens_used > self.max_total_tokens:
            self.pause_reason = "provider_budget_exceeded"
            self._record(
                "provider_budget_exceeded",
                f"tokens={self.tokens_used}; limit={self.max_total_tokens}",
            )
            return "provider_budget_exceeded"
        reason = self.manager.empty_exchange_reason(self.session_id)
        if reason is not None:
            self.pause_reason = reason
            self._record("empty_exchange", reason)
            return "empty_exchange"
        return "sent"

    async def _delay(self) -> None:
        if self.min_interval_sec <= 0:
            await asyncio.sleep(0)
            return
        try:
            await asyncio.wait_for(self._control.wait(), timeout=self.min_interval_sec)
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
                if (
                    self.replies_sent >= self.max_replies
                    or self.tokens_used >= self.max_total_tokens
                ):
                    self._finish_budget()
                    return
                outcome = await self._step()
                if outcome == "stopped" or self._stop_requested:
                    self._finish_stop()
                    return
                if outcome == "budget":
                    self._finish_budget()
                    return
                if outcome == "error":
                    if self._pause_requested:
                        self._finish_pause()
                    else:
                        self.state = "paused"
                        self._record("paused", self.last_error)
                    return
                if outcome in {"empty_exchange", "provider_budget_exceeded"}:
                    if not self._pause_requested:
                        self.state = "paused"
                        self._record("paused", self.pause_reason)
                        return
                if self._pause_requested:
                    self._finish_pause()
                    return
                if (
                    self.replies_sent >= self.max_replies
                    or self.tokens_used >= self.max_total_tokens
                ):
                    self._finish_budget()
                    return
                await self._delay()
        except asyncio.CancelledError:
            # Отмена task не отменяет уже запущенный urllib в worker-потоке.
            # Публичный stop ждёт этот request и потому не создаёт поздних записей.
            if not self.in_flight:
                self._finish_stop("остановка жизненного цикла")
            raise
        finally:
            self._task = None

    def get_status(self) -> dict:
        """Снимок без ключа, adapter repr, response_text и секретов провайдера."""
        return {
            "session_id": self.session_id,
            "state": self.state,
            "in_flight": self.in_flight,
            "replies_sent": self.replies_sent,
            "max_replies": self.max_replies,
            "tokens_used": self.tokens_used,
            "max_total_tokens": self.max_total_tokens,
            "min_interval_sec": self.min_interval_sec,
            "usage": dict(self.usage),
            "tokens_estimated": self.tokens_estimated,
            "billing_receipts": deepcopy(self.billing_receipts),
            "last_error": self.last_error,
            "pause_reason": self.pause_reason,
            "automatic_resume": False,
        }
