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
import inspect
import logging
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

    def __init__(self, max_queue_size: int = 1000, history_size: int = 200):
        """
        Args:
            max_queue_size: Максимум событий в очереди (защита от переполнения).
            history_size: Сколько последних событий хранить в истории (для отладки).
        """
        self._subscribers: Dict[str, List[Subscriber]] = defaultdict(list)
        self._queue: asyncio.Queue = None  # создаётся в start()
        self._max_queue_size = max_queue_size
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
        """Опубликовать событие.

        Если очередь переполнена — событие отбрасывается (но считается в статистике).
        Возвращает True, если событие добавлено в очередь.
        """
        if self._queue is None:
            logger.warning("EventBus.publish() до start() — событие отброшено")
            self._dropped_count += 1
            return False

        event = Event(
            name=name,
            data=data,
            source=source,
            priority=priority,
        )

        try:
            self._queue.put_nowait(event)
            self._stats[name] += 1
            return True
        except asyncio.QueueFull:
            self._dropped_count += 1
            logger.warning(f"EventBus переполнен, отброшено: {event}")
            return False

    def publish_sync(
        self,
        name: str,
        data: Any = None,
        source: str = "system",
        priority: int = 1,
    ) -> bool:
        """Синхронная публикация — для вызова из любого потока и контекста.

        Безопасно вызывать:
        - из coroutine (возвращает True/False без warning);
        - из синхронного кода внутри main loop (через call_soon_threadsafe);
        - из GUI-потока (Tkinter tray/chat) — если loop запущен в другом потоке,
          использует call_soon_threadsafe, иначе call_soon.

        Этап 2.5: была проблема — publish_sync из GUI-потока, когда loop ещё
        не стартовал, тихо ронял событие в _dropped_count без доставки.
        Теперь событие доставляется в любом случае, если EventBus.start() был
        вызван.
        """
        event = Event(name=name, data=data, source=source, priority=priority)

        # Всегда сохраняем в историю (для отладки) и инкрементируем счётчик.
        self._add_to_history(event)
        self._stats[name] += 1

        # Ищем запущенный loop в текущем потоке.
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is not None and running_loop.is_running():
            # Вызваны из корутины. Планируем put_nowait напрямую.
            try:
                running_loop.create_task(
                    self._enqueue_event(event),
                    name=f"publish:{name}",
                )
                return True
            except RuntimeError:
                pass

        # Цикл не в этом потоке (или его нет). Ищем глобальный loop.
        global_loop = getattr(self, "_global_loop", None)
        if global_loop is not None and not global_loop.is_closed():
            try:
                global_loop.call_soon_threadsafe(
                    self._enqueue_event_sync, event
                )
                return True
            except RuntimeError:
                pass

        # Последний шанс: сохраняем в историю и считаем как доставленное позже.
        # Если start() не был вызван, очередь не создана — тогда
        # создаём отложенный буфер.
        if self._queue is None:
            self._pending_pre_start.append(event)
            return True

        # Если loop есть, но недоступен — пробуем put_nowait из текущего потока.
        try:
            self._queue.put_nowait(event)
            return True
        except (asyncio.QueueFull, RuntimeError):
            self._dropped_count += 1
            return False

    async def _enqueue_event(self, event: Event) -> None:
        """Async-обёртка для _enqueue_event_sync (нужна для create_task)."""
        self._enqueue_event_sync(event)

    def _enqueue_event_sync(self, event: Event) -> None:
        """Синхронная версия enqueue — вызывается из call_soon_threadsafe."""
        if self._queue is None:
            # loop стартовал, но queue ещё нет — отложим.
            self._pending_pre_start.append(event)
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._dropped_count += 1

    def attach_loop(self, loop) -> None:
        """Привязать loop (вызывается из main_async() в main_tray.py).

        Этап 2.5: без этого call_soon_threadsafe не нашёл бы loop из других
        потоков. После attach_loop() publish_sync() работает из GUI-потоков.
        """
        self._global_loop = loop

    def drain_pre_start(self) -> int:
        """Слить отложенные события, накопленные до start().

        Вызывается сразу после start() в main_async() — все события, которые
        publish_sync сохранил пока loop ещё не работал, попадают в очередь.
        Возвращает количество доставленных.
        """
        if self._queue is None:
            return 0
        delivered = 0
        for ev in self._pending_pre_start:
            try:
                self._queue.put_nowait(ev)
                delivered += 1
            except asyncio.QueueFull:
                self._dropped_count += 1
        self._pending_pre_start = []
        return delivered

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
        self._add_to_history(event)
        subscribers = list(self._subscribers.get(event.name, []))
        # wildcard подписчики получают всё
        subscribers.extend(self._subscribers.get("*", []))

        if not subscribers:
            logger.debug(f"Нет подписчиков для {event.name}")
            return

        results = await asyncio.gather(
            *(self._safe_invoke(sub, event) for sub in subscribers),
            return_exceptions=False,
        )
        # results не используются, но gather не даёт исключениям убить цикл

    async def _safe_invoke(self, sub: Subscriber, event: Event) -> None:
        """Вызвать подписчика, не давая исключению сломать шину."""
        try:
            await sub(event)
        except Exception as e:
            logger.exception(f"Ошибка в подписчике {sub.__name__} для {event.name}: {e}")

    def _add_to_history(self, event: Event) -> None:
        """Сохранить событие в историю (с ограничением размера)."""
        self._history.append(event)
        if len(self._history) > self._history_max:
            self._history = self._history[-self._history_max:]

    # ============================================================
    # Наблюдение / отладка
    # ============================================================

    def get_history(self, last_n: int = 20, name_filter: Optional[str] = None) -> List[Event]:
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
    TICK = "tick"                    # Один внутренний цикл агента завершён
    TIMER_TICK = "timer_tick"        # Таймер сработал (каждые N секунд)

    # Пользователь
    USER_MESSAGE = "user_message"    # Сообщение от пользователя
    USER_OPENED_CHAT = "user_opened_chat"
    USER_CLOSED_CHAT = "user_closed_chat"
    USER_COMMAND = "user_command"    # /status, /goals и т.п.

    # Агент
    AGENT_THOUGHT = "agent_thought"  # Агент подумал (мысль)
    AGENT_ACTION = "agent_action"    # Агент совершил действие
    AGENT_EVOLVED = "agent_evolved"  # Интеллект вырос
    AGENT_WANTS_TO_SPEAK = "agent_wants_to_speak"  # Хочет сказать (→ уведомление)
    AGENT_QUESTION = "agent_question"  # Задаёт вопрос пользователю
    AGENT_MESSAGE = "agent_message"   # Просто сообщение (statement/reflection/etc.)
    AGENT_WEB_RESULT = "agent_web_result"  # Нашёл ответ в интернете (Wikipedia)

    # Состояние
    ENERGY_LOW = "energy_low"        # Энергия упала
    ENERGY_RECOVERED = "energy_recovered"
    GOAL_COMPLETED = "goal_completed"
    GOAL_ACTIVATED = "goal_activated"

    # Система
    PAUSE_REQUESTED = "pause_requested"
    RESUME_REQUESTED = "resume_requested"
    SHUTDOWN_REQUESTED = "shutdown_requested"
    SAVE_REQUESTED = "save_requested"
    SPEED_CHANGED = "speed_changed"      # Смена скорости жизни: live/fast/max
    STEP_REQUESTED = "step_requested"    # Один цикл по кнопке «Шаг»

    # === Жизнь и уход (через подтверждение человеком) ===
    # Окно только просит. Решение принимает LifeGuard: пауза + точная
    # фраза. См. src/core/life_guard.py и src/app/life_controller.py.
    LIFE_REQUEST = "life_request"        # Окно → ядро: «прошу сон/уход»
    LIFE_PROMPT = "life_prompt"          # Ядро → окно: «введи фразу»
    LIFE_CONFIRM = "life_confirm"        # Окно → ядро: «вот фраза»
    LIFE_CANCEL = "life_cancel"          # Окно → ядро: «отменить запрос»
    LIFE_WAKE = "life_wake"              # Окно → ядро: «разбудить»
    LIFE_RESULT = "life_result"          # Ядро → окно: итог решения
    CHAT_FOCUS_REQUESTED = "chat_focus_requested"  # Фокус на поле ввода