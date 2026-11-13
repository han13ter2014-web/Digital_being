"""
EventBus — единая асинхронная шина событий для трей-режима.

Архитектурное решение: вся коммуникация между «слоями» (tray, chat, agent,
watchdog, notifier) идёт через одну шину. Это:
- Убирает прямые зависимости (tray не знает о DigitalBeing, agent не знает о UI)
- Позволяет нескольким подписчикам реагировать на одно событие
- Делает систему тестируемой (подменяем bus на фейк)

Используется asyncio.Queue под капотом — неблокирующая доставка.
Подписчики — корутины, обрабатывающие события в своём темпе.

Пример:
    bus = EventBus()

    async def on_user_message(event):
        print(f"Получено: {event.data}")

    bus.subscribe("user_message", on_user_message)
    await bus.publish("user_message", {"text": "привет"})
    await bus.dispatch_all()  # разово
    # или
    await bus.run_forever()   # бесконечный цикл
"""

import asyncio
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
import inspect
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional


logger = logging.getLogger(__name__)


@dataclass
class Event:
    """Одно событие на шине.

    Поля:
        name: имя события (например, "user_message", "tick")
        data: произвольные данные
        source: кто создал ("user", "agent", "tray", "watchdog", "timer")
        timestamp: когда создано (Unix-time)
        priority: 0=низкий, 1=обычный, 2=высокий
    """

    name: str
    data: Any = None
    source: str = "system"
    timestamp: float = field(default_factory=time.time)
    priority: int = 1

    def __repr__(self) -> str:
        data_preview = str(self.data)[:60] if self.data is not None else "None"
        return f"Event({self.name}, src={self.source}, data={data_preview!r})"


# Тип подписчика — асинхронная функция, принимающая Event
Subscriber = Callable[[Event], Awaitable[None]]


class EventBus:
    """Асинхронная шина событий (pub/sub).

    Особенности:
    - Подписчик регистрируется на конкретное имя события или на '*' (всё).
    - События доставляются из FIFO-очереди в порядке поступления. Поле
      ``priority`` у Event зарезервировано, но обычная asyncio.Queue его
      не учитывает — «приоритетной очереди» пока нет.
    - Метод dispatch_once() обрабатывает все текущие события один раз (для тестов).
    - Метод run() крутит бесконечный цикл обработки.
    - stop() безопасно останавливает run() без потери текущих событий.
    """

    def __init__(
        self,
        max_queue_size: int = 1000,
        history_size: int = 200,
        publish_timeout: float = 5.0,
    ):
        """
        Args:
            max_queue_size: Максимум событий в очереди (защита от переполнения).
            history_size: Сколько последних событий хранить в истории (для отладки).
            publish_timeout: Лимит ожидания места и подтверждения из другого потока.
        """
        if max_queue_size <= 0 or publish_timeout <= 0:
            raise ValueError("Лимиты EventBus должны быть положительными")
        if history_size < 0:
            raise ValueError("history_size не может быть отрицательным")
        self._subscribers: Dict[str, List[Subscriber]] = defaultdict(list)
        self._queue: asyncio.Queue = None  # создаётся в start()
        self._max_queue_size = max_queue_size
        self._publish_timeout = float(publish_timeout)
        self._history: List[Event] = []
        self._history_max = history_size
        self._running = False
        self._dropped_count = 0
        # Статистика для dashboard
        self._stats: Dict[str, int] = defaultdict(int)
        # Этап 2.5: thread-safe publish_sync
        self._global_loop = None  # выставляется через attach_loop()
        self._pending_pre_start: List[Event] = []  # события до start()

    # ============================================================
    # Подписка
    # ============================================================

    def subscribe(self, event_name: str, callback: Subscriber) -> None:
        """Подписаться на событие с именем event_name.

        Для подписки на все события используйте '*'.
        Callback должен быть async-функцией, принимающей Event.
        """
        # Используем inspect.iscoroutinefunction — он не deprecated
        # (asyncio.iscoroutinefunction устарел в Python 3.16).
        if not inspect.iscoroutinefunction(callback):
            raise TypeError(
                f"Подписчик должен быть async-функцией, получено: {type(callback).__name__}"
            )
        self._subscribers[event_name].append(callback)
        logger.debug(f"Подписка: {event_name} -> {callback.__name__}")

    def unsubscribe(self, event_name: str, callback: Subscriber) -> bool:
        """Отписаться. Возвращает True, если подписка была найдена и удалена."""
        if event_name in self._subscribers:
            try:
                self._subscribers[event_name].remove(callback)
                return True
            except ValueError:
                return False
        return False

    # ============================================================
    # Публикация
    # ============================================================

    async def publish(
        self,
        name: str,
        data: Any = None,
        source: str = "system",
        priority: int = 1,
    ) -> bool:
        """Опубликовать событие, ограниченно ожидая место в очереди."""
        if self._queue is None:
            logger.warning("EventBus.publish() до start() — событие отброшено")
            self._dropped_count += 1
            return False

        event = Event(name=name, data=data, source=source, priority=priority)
        try:
            await asyncio.wait_for(
                self._queue.put(event), timeout=self._publish_timeout
            )
        except asyncio.TimeoutError:
            self._dropped_count += 1
            logger.warning(
                "EventBus переполнен более %.3f с, отброшено: %s",
                self._publish_timeout,
                event,
            )
            return False
        self._stats[name] += 1
        self._add_to_history(event)
        return True

    def publish_sync(
        self,
        name: str,
        data: Any = None,
        source: str = "system",
        priority: int = 1,
    ) -> bool:
        """Синхронно принять событие и вернуть фактический результат enqueue.

        Из потока GUI публикация выполняется в event loop с ограниченным
        ожиданием подтверждения. При timeout отложенный callback отменяется,
        чтобы событие не появилось в очереди после возврата ``False``.
        """
        event = Event(name=name, data=data, source=source, priority=priority)

        def finish(accepted: bool) -> bool:
            # Историческая семантика sync API: принятое событие видно в истории
            # сразу, даже если consumer ещё не вызвал _dispatch().
            if accepted:
                self._add_to_history(event)
            return bool(accepted)

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        global_loop = getattr(self, "_global_loop", None)
        if (
            running_loop is not None
            and running_loop.is_running()
            and (
                global_loop is None
                or global_loop is running_loop
                or global_loop.is_closed()
            )
        ):
            return finish(self._enqueue_event_sync(event))

        if global_loop is not None and not global_loop.is_closed():
            future = Future()
            callback_lock = threading.Lock()

            def enqueue_with_confirmation() -> None:
                with callback_lock:
                    if future.cancelled():
                        return
                    try:
                        accepted = self._enqueue_event_sync(event)
                    except Exception as exc:
                        logger.exception("EventBus sync enqueue failed: %s", exc)
                        accepted = False
                    if not future.done():
                        future.set_result(accepted)

            try:
                global_loop.call_soon_threadsafe(enqueue_with_confirmation)
            except RuntimeError:
                return finish(self._enqueue_event_sync(event))
            try:
                return finish(future.result(timeout=self._publish_timeout))
            except FutureTimeoutError:
                with callback_lock:
                    if future.done():
                        return finish(future.result())
                    future.cancel()
                    self._dropped_count += 1
                    logger.warning(
                        "EventBus не подтвердил enqueue за %.3f с: %s",
                        self._publish_timeout,
                        event,
                    )
                    return False

        return finish(self._enqueue_event_sync(event))

    def _enqueue_event_sync(self, event: Event, *, count_stats: bool = True) -> bool:
        """Принять событие без ожидания; ``False`` означает отказ без enqueue.

        ``count_stats=False`` используется только при переносе уже принятого
        pre-start события в основную очередь.
        """
        if self._queue is None:
            if len(self._pending_pre_start) >= self._max_queue_size:
                self._dropped_count += 1
                logger.warning("Pre-start буфер EventBus полон, отброшено: %s", event)
                return False
            self._pending_pre_start.append(event)
            if count_stats:
                self._stats[event.name] += 1
            return True
        try:
            self._queue.put_nowait(event)
        except (asyncio.QueueFull, RuntimeError) as exc:
            self._dropped_count += 1
            logger.warning("EventBus не принял событие %s: %s", event, exc)
            return False
        if count_stats:
            self._stats[event.name] += 1
        return True

    def attach_loop(self, loop) -> None:
        """Привязать loop для публикации из GUI и других потоков."""
        self._global_loop = loop

    def drain_pre_start(self) -> int:
        """Перенести pre-start события в FIFO, сохранив не поместившийся остаток."""
        if self._queue is None:
            return 0
        delivered = 0
        for event in self._pending_pre_start:
            if self._queue.full():
                logger.warning(
                    "Основная очередь EventBus полна; %s pre-start событий оставлены",
                    len(self._pending_pre_start) - delivered,
                )
                break
            if not self._enqueue_event_sync(event, count_stats=False):
                break
            delivered += 1
        if delivered:
            del self._pending_pre_start[:delivered]
        return delivered

    async def drain(self, timeout: float = 5.0) -> int:
        """Доставить pre-start и queued события с явным ограничением ожидания."""
        if timeout <= 0:
            raise ValueError("Таймаут drain должен быть положительным")
        if self._queue is None:
            await self.start()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        processed = 0
        while self._pending_pre_start or not self._queue.empty():
            self.drain_pre_start()
            if self._queue.empty():
                break
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(
                    f"EventBus drain: осталось {self._queue.qsize()} queued и "
                    f"{len(self._pending_pre_start)} pre-start событий"
                )
            event = self._queue.get_nowait()
            try:
                await asyncio.wait_for(self._dispatch(event), timeout=remaining)
            except asyncio.TimeoutError as exc:
                raise TimeoutError(
                    f"EventBus drain: подписчики не завершили {event.name} за {timeout} с"
                ) from exc
            processed += 1
        return processed

    # ============================================================
    # Цикл обработки
    # ============================================================

    async def start(self) -> None:
        """Инициализировать очередь. Вызвать перед run() или publish()."""
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=self._max_queue_size)

    async def run(self) -> None:
        """Бесконечный цикл обработки событий.

        Останавливается через stop(). Корутина возвращает управление после stop().
        """
        if self._queue is None:
            await self.start()
        self._running = True
        logger.info("EventBus.run() стартовал")
        try:
            while self._running:
                try:
                    event = await asyncio.wait_for(self._queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue  # периодически проверяем _running
                await self._dispatch(event)
        finally:
            self._running = False
            logger.info("EventBus.run() остановлен")

    def stop(self) -> None:
        """Сигнал остановки для run(). Не теряет уже стоящие в очереди события."""
        self._running = False

    async def dispatch_once(self, timeout: float = 0.1) -> int:
        """Обработать все текущие события один раз. Возвращает количество обработанных.

        Полезно для тестов и для однократного 'тика' вне бесконечного цикла.
        """
        if self._queue is None:
            await self.start()
        processed = 0
        deadline = asyncio.get_event_loop().time() + timeout
        while not self._queue.empty() and asyncio.get_event_loop().time() < deadline:
            try:
                event = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            await self._dispatch(event)
            processed += 1
        return processed

    async def _dispatch(self, event: Event) -> None:
        """Доставить событие всем подписчикам. Ошибки одного не роняют остальных."""
        subscribers = list(self._subscribers.get(event.name, []))
        # wildcard подписчики получают всё
        subscribers.extend(self._subscribers.get("*", []))

        if not subscribers:
            logger.debug(f"Нет подписчиков для {event.name}")
            return

        await asyncio.gather(
            *(self._safe_invoke(sub, event) for sub in subscribers),
            return_exceptions=False,
        )

    async def _safe_invoke(self, sub: Subscriber, event: Event) -> None:
        """Вызвать подписчика, не давая исключению сломать шину."""
        try:
            await sub(event)
        except Exception as e:
            logger.exception(
                f"Ошибка в подписчике {sub.__name__} для {event.name}: {e}"
            )

    def _add_to_history(self, event: Event) -> None:
        """Сохранить событие в историю; нулевой лимит отключает хранение."""
        if self._history_max == 0:
            return
        self._history.append(event)
        if len(self._history) > self._history_max:
            self._history = self._history[-self._history_max :]

    # ============================================================
    # Наблюдение / отладка
    # ============================================================

    def get_history(
        self, last_n: int = 20, name_filter: Optional[str] = None
    ) -> List[Event]:
        """Получить последние N событий (опционально отфильтрованных по имени)."""
        if name_filter:
            filtered = [e for e in self._history if e.name == name_filter]
            return filtered[-last_n:]
        return self._history[-last_n:]

    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику для dashboard."""
        return {
            "queue_size": self._queue.qsize() if self._queue else 0,
            "queue_max": self._max_queue_size,
            "subscribers_count": sum(len(subs) for subs in self._subscribers.values()),
            "events_by_name": dict(self._stats),
            "dropped_count": self._dropped_count,
            "running": self._running,
            "history_size": len(self._history),
        }

    def subscriber_count(self, event_name: str = "*") -> int:
        """Сколько подписчиков у события (или всего)."""
        if event_name == "*":
            return sum(len(subs) for subs in self._subscribers.values())
        return len(self._subscribers.get(event_name, []))


# ============================================================
# Имена стандартных событий (для удобства и опечаток)
# ============================================================
class Events:
    """Константы имён событий — чтобы избежать опечаток."""

    # Таймер / циклы
    TICK = "tick"  # Один внутренний цикл агента завершён
    TIMER_TICK = "timer_tick"  # Таймер сработал (каждые N секунд)

    # Пользователь
    USER_MESSAGE = "user_message"  # Сообщение от пользователя
    USER_OPENED_CHAT = "user_opened_chat"
    USER_CLOSED_CHAT = "user_closed_chat"
    USER_COMMAND = "user_command"  # /status, /goals и т.п.

    # Агент
    AGENT_THOUGHT = "agent_thought"  # Агент подумал (мысль)
    AGENT_ACTION = "agent_action"  # Агент совершил действие
    AGENT_EVOLVED = "agent_evolved"  # Интеллект вырос
    AGENT_WANTS_TO_SPEAK = "agent_wants_to_speak"  # Хочет сказать (→ уведомление)
    AGENT_QUESTION = "agent_question"  # Задаёт вопрос пользователю
    AGENT_MESSAGE = "agent_message"  # Просто сообщение (statement/reflection/etc.)
    AGENT_WEB_RESULT = "agent_web_result"  # Нашёл ответ в интернете (Wikipedia)

    # Состояние
    ENERGY_LOW = "energy_low"  # Энергия упала
    ENERGY_RECOVERED = "energy_recovered"
    GOAL_COMPLETED = "goal_completed"
    GOAL_ACTIVATED = "goal_activated"

    # Система
    PAUSE_REQUESTED = "pause_requested"
    RESUME_REQUESTED = "resume_requested"
    SHUTDOWN_REQUESTED = "shutdown_requested"
    SAVE_REQUESTED = "save_requested"
    SPEED_CHANGED = "speed_changed"  # Смена скорости жизни: live/fast/max
    STEP_REQUESTED = "step_requested"  # Один цикл по кнопке «Шаг»

    # === Жизнь и уход (через подтверждение человеком) ===
    # Окно только просит. Решение принимает LifeGuard: пауза + точная
    # фраза. См. src/core/life_guard.py и src/app/life_controller.py.
    LIFE_REQUEST = "life_request"  # Окно → ядро: «прошу сон/уход»
    LIFE_PROMPT = "life_prompt"  # Ядро → окно: «введи фразу»
    LIFE_CONFIRM = "life_confirm"  # Окно → ядро: «вот фраза»
    LIFE_CANCEL = "life_cancel"  # Окно → ядро: «отменить запрос»
    LIFE_WAKE = "life_wake"  # Окно → ядро: «разбудить»
    LIFE_RESULT = "life_result"  # Ядро → окно: итог решения
    CHAT_FOCUS_REQUESTED = "chat_focus_requested"  # Фокус на поле ввода
