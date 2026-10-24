"""LifeController — связывает окно с защитой жизни.

Окно живёт в потоке Tk и не должно напрямую менять состояние агента.
Оно публикует события (``LIFE_REQUEST``, ``LIFE_CONFIRM``, ...), а
контроллер выполняет их в потоке asyncio, где живёт агент.

Разделение важно по двум причинам:

1. **Потокобезопасность.** Все изменения агента происходят в одном
   потоке — том же, где идут циклы жизни.
2. **Проверяемость.** Логику можно протестировать без Tk: контроллер
   принимает события и возвращает события.

Контроллер ничего не решает сам про уход. Он лишь вызывает методы
агента, которые упираются в ``LifeGuard`` (пауза + точная фраза).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.core.event_bus import EventBus, Events

logger = logging.getLogger(__name__)


class LifeController:
    """Обрабатывает запросы окна о сне, уходе и пробуждении."""

    def __init__(self, agent: Any, bus: EventBus) -> None:
        self.agent = agent
        self.bus = bus
        self._subscribe()

    def _subscribe(self) -> None:
        self.bus.subscribe(Events.LIFE_REQUEST, self._on_request)
        self.bus.subscribe(Events.LIFE_CONFIRM, self._on_confirm)
        self.bus.subscribe(Events.LIFE_CANCEL, self._on_cancel)
        self.bus.subscribe(Events.LIFE_WAKE, self._on_wake)

    # ------------------------------------------------------------------
    # Обработчики
    # ------------------------------------------------------------------

    async def _on_request(self, event) -> None:
        """Человек нажал «Сон» или «Уйти». Создаём запрос, не меняя жизнь."""
        data = event.data or {}
        kind = str(data.get("kind", "dream"))
        reason = str(data.get("reason", "") or "запрос из окна")

        if kind == "dream":
            result = self.agent.request_dream(reason)
        elif kind == "terminate":
            result = self.agent.request_termination(reason)
        else:
            await self._publish_result(
                False, f"Неизвестный вид ухода: {kind}", state=None
            )
            return

        if result.get("status") != "pending":
            await self._publish_result(
                False,
                str(result.get("reason", "Запрос отклонён")),
                state=None,
            )
            return

        logger.info(
            f"[LifeController] Запрос {kind}: {result.get('request_id')}"
        )
        await self.bus.publish(
            Events.LIFE_PROMPT,
            {
                "request_id": result.get("request_id"),
                "kind": kind,
                "phrase": result.get("phrase"),
                "cooldown_sec": result.get("cooldown_sec"),
                "expires_in_sec": result.get("expires_in_sec"),
                "description": result.get("description"),
                "reversible": result.get("reversible", kind == "dream"),
            },
            source="life_controller",
            priority=1,
        )

    async def _on_confirm(self, event) -> None:
        """Человек ввёл фразу. Решает LifeGuard, не контроллер."""
        data = event.data or {}
        request_id = str(data.get("request_id", ""))
        phrase = str(data.get("phrase", ""))

        request = self._get_request(request_id)
        if request is None:
            await self._publish_result(
                False, "Запрос не найден или истёк.", state=None
            )
            return

        if request.kind == "dream":
            result = self.agent.confirm_dream(request_id, phrase)
        else:
            result = self.agent.confirm_termination(request_id, phrase)

        status = str(result.get("status", ""))
        if status == "rejected":
            await self._publish_result(
                False, str(result.get("reason", "Отклонено")), state=None
            )
            return

        if status == "dreaming":
            message = (
                "Агент уснул. Семя сохранено в Яслях: "
                f"{result.get('seed_folder')}"
            )
        elif status == "terminated":
            message = (
                "Агент прекратил существование. "
                "Снимок данных создан перед уходом."
            )
        else:
            message = "Готово."

        logger.info(f"[LifeController] Подтверждено: {status}")
        await self._publish_result(
            True, message, state=result.get("state")
        )

    async def _on_cancel(self, event) -> None:
        """Отмена работает всегда и ничего не требует."""
        data = event.data or {}
        request_id = str(data.get("request_id", ""))
        result = self.agent.cancel_life_request(request_id)
        cancelled = result.get("status") == "cancelled"
        await self._publish_result(
            cancelled,
            "Запрос отменён. Агент продолжает жить."
            if cancelled
            else "Запрос не найден.",
            state=None,
        )

    async def _on_wake(self, event) -> None:
        """Пробуждение из глубокого сна."""
        result = self.agent.wake_from_sleep()
        if result.get("status") == "denied":
            await self._publish_result(
                False, str(result.get("reason", "Не удалось разбудить")),
                state=None,
            )
            return
        await self._publish_result(
            True, "Агент вернулся к жизни.", state=result.get("state")
        )

    # ------------------------------------------------------------------
    # Вспомогательное
    # ------------------------------------------------------------------

    def _get_request(self, request_id: str):
        guard = getattr(self.agent, "life_guard", None)
        if guard is None:
            return None
        try:
            return guard.get_request(request_id)
        except Exception:
            return None

    async def _publish_result(
        self,
        ok: bool,
        message: str,
        *,
        state: Optional[str],
    ) -> None:
        payload: Dict[str, Any] = {"ok": bool(ok), "message": message}
        if state is not None:
            payload["state"] = state
        await self.bus.publish(
            Events.LIFE_RESULT,
            payload,
            source="life_controller",
            priority=1,
        )


__all__ = ["LifeController"]