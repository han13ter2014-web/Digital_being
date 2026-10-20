"""
Subsystem — базовый класс для подсистем Digital Being и PluginRegistry.

Архитектурное решение:
Каждая подсистема (goals, knowledge, energy, sleep, soul...) наследуется от
Subsystem и автоматически регистрируется в PluginRegistry. Это даёт:

1. Единый жизненный цикл: setup() → tick() → teardown().
2. Возможность подключать плагины извне (внешние .py файлы) без правки ядра.
3. Единая точка для наблюдения: все подсистемы доступны через registry.
4. Безопасный shutdown — все зарегистрированные подсистемы получают teardown().

Этап 3.5: plugin-system. Раньше подсистемы инициализировались вручную в
DigitalBeing.__init__(). Теперь они могут подключаться декларативно:

    from src.core.subsystem_base import Subsystem, PluginRegistry

    class MyPlugin(Subsystem):
        name = "my_plugin"
        def tick(self, cycle, context): ...
        def status(self): return {"ok": True}

    registry = PluginRegistry.get_global()
    registry.register(MyPlugin())

Это не ломает существующий код — старые подсистемы продолжают работать как
атрибуты DigitalBeing, но дополнительно попадают в registry.
"""

import logging
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Optional, Type


logger = logging.getLogger(__name__)


class Subsystem:
    """Базовый класс для подсистем Digital Being.

    Контракт:
    - name (str|class attr) — уникальное имя. Используется в registry и логах.
    - enabled (bool)         — флаг «включено». Если False — tick() не вызывается.
    - setup(context)         — вызывается один раз после attach.
    - tick(cycle, context)   — главный цикл подсистемы. context — общий dict
                               со ссылками на агента, состояние и т.п.
    - status()               — возвращает JSON-сериализуемый dict для dashboard.
    - teardown()             — вызывается при остановке. Освобождает ресурсы.

    Подсистема может переопределить ТОЛЬКО нужные методы — у базового класса
    все они no-op с защитой от исключений.
    """

    # Уникальное имя подсистемы. Если не задано — берётся из имени класса.
    name: str = ""

    # Включена ли по умолчанию. Подсистема может переопределить через set_enabled().
    enabled: bool = True

    # Приоритет tick(): меньше = раньше. По умолчанию 100 (нейтрально).
    priority: int = 100

    # Версия (для UI/diagnostics).
    version: str = "0.1.0"

    def __init__(self, agent_name: str = "unknown", **kwargs: Any) -> None:
        self.agent_name = agent_name
        # Локальные метрики — для self-diagnostics и dashboard.
        self._tick_count: int = 0
        self._last_tick_ts: float = 0.0
        self._last_error: Optional[str] = None
        self._error_count: int = 0
        self._setup_done: bool = False
        # Контекст, переданный в setup().
        self._context: Dict[str, Any] = {}

        # Если имя не задано — берём из имени класса (lowercase).
        if not self.name:
            self.name = type(self).__name__.lower()

    # ----------------------------------------------------------------
    # Жизненный цикл
    # ----------------------------------------------------------------

    def setup(self, context: Dict[str, Any]) -> None:
        """Однократная инициализация после attach.

        context содержит ключи:
        - agent_name: str
        - registry: PluginRegistry
        - agent: DigitalBeing (может быть None, если подсистема standalone)
        """
        self._context = dict(context) if context else {}
        self._setup_done = True
        logger.debug(f"[{self.name}] setup() done (agent={self.agent_name})")

    def tick(self, cycle: int, context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Главный цикл. Должен быть идемпотентным и быстрым.

        Возвращает dict с событиями для шины (опционально) или None.
        Базовая реализация — no-op. Подсистема может вернуть:
            {"events": [{"name": "...", "data": ...}, ...]}
        """
        self._tick_count += 1
        self._last_tick_ts = time.time()
        return None

    def teardown(self) -> None:
        """Вызывается один раз при остановке. Освобождает ресурсы."""
        self._setup_done = False
        logger.debug(f"[{self.name}] teardown() done")

    # ----------------------------------------------------------------
    # Управление состоянием
    # ----------------------------------------------------------------

    def set_enabled(self, enabled: bool) -> None:
        """Включить/выключить подсистему (tick() не вызывается если выключена)."""
        self.enabled = bool(enabled)

    def is_enabled(self) -> bool:
        return self.enabled

    # ----------------------------------------------------------------
    # Диагностика
    # ----------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        """Возвращает JSON-сериализуемый статус (для dashboard и логов)."""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "priority": self.priority,
            "version": self.version,
            "tick_count": self._tick_count,
            "error_count": self._error_count,
            "last_error": self._last_error,
            "last_tick_ts": self._last_tick_ts,
        }

    # ----------------------------------------------------------------
    # Внутренние хелперы для подклассов
    # ----------------------------------------------------------------

    def _record_error(self, exc: BaseException) -> None:
        """Записать ошибку (используется обёрткой в registry)."""
        self._error_count += 1
        self._last_error = f"{type(exc).__name__}: {exc}"
        # Логируем стек только первый раз, дальше — только счётчик.
        if self._error_count <= 3:
            logger.warning(
                f"[{self.name}] ошибка #{self._error_count}: {self._last_error}\n"
                f"{traceback.format_exc()}"
            )

    def __repr__(self) -> str:
        return f"<Subsystem {self.name} enabled={self.enabled} ticks={self._tick_count}>"


# ============================================================
# PluginRegistry — реестр всех подсистем
# ============================================================

# Тип фабрики: может быть классом (тогда registry сам инстанциирует)
# или уже готовым экземпляром.
Factory = Callable[[], Subsystem]


class PluginRegistry:
    """Реестр подсистем/плагинов.

    Особенности:
    - Singleton: get_global() возвращает один и тот же реестр на процесс.
    - Регистрация: register(instance) или register_class(cls).
    - Тики: tick_all(cycle, context) — последовательно по priority.
    - Безопасный tick: ошибка одной подсистемы не валит остальные.
    - Status: status_all() — снимок всех для dashboard.
    - Teardown: teardown_all() — для graceful shutdown.

    Использование:
        registry = PluginRegistry.get_global()
        registry.register(MyPlugin())

        # В главном цикле:
        registry.tick_all(cycle, {"agent": agent, ...})

        # При остановке:
        registry.teardown_all()
    """

    _global: Optional["PluginRegistry"] = None
    _global_lock = threading.Lock()

    def __init__(self) -> None:
        self._items: Dict[str, Subsystem] = {}
        self._classes: Dict[str, Type[Subsystem]] = {}
        self._lock = threading.RLock()
        # История последних тиков (для dashboard/SSE-ленты).
        self._max_history: int = 200
        self._history: List[Dict[str, Any]] = []
        # Подписчики на события реестра (для UI/тестов).
        self._listeners: List[Callable[[str, Dict[str, Any]], None]] = []

    # ----------------------------------------------------------------
    # Singleton
    # ----------------------------------------------------------------

    @classmethod
    def get_global(cls) -> "PluginRegistry":
        """Ленивая инициализация глобального реестра (thread-safe)."""
        if cls._global is None:
            with cls._global_lock:
                if cls._global is None:
                    cls._global = cls()
        return cls._global

    @classmethod
    def reset_global(cls) -> None:
        """Сбросить глобальный реестр (для тестов)."""
        with cls._global_lock:
            cls._global = None

    # ----------------------------------------------------------------
    # Регистрация
    # ----------------------------------------------------------------

    def register(self, instance: Subsystem, *, replace: bool = False) -> bool:
        """Зарегистрировать экземпляр подсистемы.

        Возвращает True, если зарегистрирована. False — если уже есть и replace=False.
        """
        if not isinstance(instance, Subsystem):
            raise TypeError(
                f"PluginRegistry.register ожидает Subsystem, получено: {type(instance).__name__}"
            )
        with self._lock:
            name = instance.name
            if name in self._items and not replace:
                logger.debug(f"[registry] '{name}' уже зарегистрирована, пропускаю")
                return False
            self._items[name] = instance
            if not replace:
                self._emit("registered", {"name": name, "version": instance.version})
                logger.debug(f"[registry] зарегистрирована: {name} (v{instance.version})")
            else:
                self._emit("replaced", {"name": name, "version": instance.version})
            return True

    def register_class(self, cls: Type[Subsystem], *, agent_name: str = "unknown",
                        replace: bool = False) -> bool:
        """Зарегистрировать класс (будет инстанциирован при первом запросе).

        Полезно для декларативной регистрации плагинов из конфига.
        """
        if not (isinstance(cls, type) and issubclass(cls, Subsystem)):
            raise TypeError(f"register_class ожидает подкласс Subsystem, получено: {cls!r}")
        with self._lock:
            # Имя берём из класса, если у него не задан class-attr name.
            name = getattr(cls, "name", "") or cls.__name__.lower()
            if name in self._classes and not replace:
                return False
            self._classes[name] = cls
            # Сохраняем agent_name — пригодится при инстанциировании.
            self._classes[f"__{name}__agent__"] = cls  # type: ignore[assignment]
            logger.debug(f"[registry] зарегистрирован класс: {name}")
            return True

    def get(self, name: str) -> Optional[Subsystem]:
        """Получить подсистему по имени. Если зарегистрирован только класс —
        инстанциировать (lazy)."""
        with self._lock:
            if name in self._items:
                return self._items[name]
            if name in self._classes:
                cls = self._classes[name]
                instance = cls(agent_name="unknown")
                self._items[name] = instance
                return instance
            return None

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._items or name in self._classes

    def unregister(self, name: str) -> bool:
        """Удалить подсистему из реестра (с teardown)."""
        with self._lock:
            instance = self._items.pop(name, None)
            self._classes.pop(name, None)
            if instance is not None:
                try:
                    instance.teardown()
                except Exception as e:
                    logger.warning(f"[registry] ошибка teardown {name}: {e}")
                self._emit("unregistered", {"name": name})
                return True
            return False

    # ----------------------------------------------------------------
    # Lifecycle hooks (массовые)
    # ----------------------------------------------------------------

    def setup_all(self, context: Optional[Dict[str, Any]] = None) -> int:
        """Вызвать setup() для всех зарегистрированных. Возвращает кол-во успешных."""
        ctx = dict(context or {})
        count = 0
        with self._lock:
            instances = list(self._items.values())
        for inst in instances:
            try:
                inst.setup(ctx)
                count += 1
            except Exception as e:
                inst._record_error(e)
                logger.warning(f"[registry] setup {inst.name} упал: {e}")
        return count

    def tick_all(self, cycle: int, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Вызвать tick() для всех enabled подсистем по priority.

        Возвращает сводный отчёт:
            {
                "cycle": int,
                "ok": [name, ...],
                "failed": [{"name": ..., "error": ...}, ...],
                "results": {name: result_dict_or_None, ...},
                "elapsed_ms": float,
            }
        """
        ctx = dict(context or {})
        t0 = time.perf_counter()
        ok: List[str] = []
        failed: List[Dict[str, Any]] = []
        results: Dict[str, Any] = {}

        with self._lock:
            # Сортируем по priority. Стабильная сортировка сохраняет порядок регистрации.
            ordered = sorted(
                (i for i in self._items.values() if i.enabled),
                key=lambda x: (x.priority, x.name),
            )

        for inst in ordered:
            try:
                res = inst.tick(cycle, ctx)
                ok.append(inst.name)
                results[inst.name] = res
                if isinstance(res, dict) and "events" in res:
                    self._emit(f"events:{inst.name}", res["events"])
            except Exception as e:
                inst._record_error(e)
                failed.append({"name": inst.name, "error": str(e)})
                results[inst.name] = None

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        report = {
            "cycle": cycle,
            "ok": ok,
            "failed": failed,
            "results": results,
            "elapsed_ms": round(elapsed_ms, 3),
        }
        self._push_history(report)
        self._emit("tick_report", report)
        return report

    def teardown_all(self) -> int:
        """Вызвать teardown() для всех. Возвращает кол-во успешных."""
        count = 0
        with self._lock:
            instances = list(self._items.values())
        for inst in instances:
            try:
                inst.teardown()
                count += 1
            except Exception as e:
                logger.warning(f"[registry] teardown {inst.name} упал: {e}")
        return count

    # ----------------------------------------------------------------
    # Наблюдение
    # ----------------------------------------------------------------

    def status_all(self) -> Dict[str, Any]:
        """Снимок всех подсистем (для dashboard)."""
        with self._lock:
            snapshot = [inst.status() for inst in self._items.values()]
        return {
            "subsystem_count": len(snapshot),
            "enabled_count": sum(1 for s in snapshot if s.get("enabled")),
            "subsystems": snapshot,
            "total_ticks": sum(s.get("tick_count", 0) for s in snapshot),
            "total_errors": sum(s.get("error_count", 0) for s in snapshot),
            "registered_classes": list(self._classes.keys()),
        }

    def list_names(self) -> List[str]:
        """Список имён всех зарегистрированных подсистем."""
        with self._lock:
            return sorted(set(self._items.keys()) | set(self._classes.keys()))

    # ----------------------------------------------------------------
    # История тиков (для SSE-ленты дашборда)
    # ----------------------------------------------------------------

    def _push_history(self, report: Dict[str, Any]) -> None:
        with self._lock:
            self._history.append({
                "cycle": report.get("cycle"),
                "ok_count": len(report.get("ok", [])),
                "failed_count": len(report.get("failed", [])),
                "elapsed_ms": report.get("elapsed_ms"),
                "timestamp": time.time(),
            })
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

    def get_history(self, last_n: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._history[-last_n:])

    # ----------------------------------------------------------------
    # Подписчики (для UI)
    # ----------------------------------------------------------------

    def subscribe(self, callback: Callable[[str, Dict[str, Any]], None]) -> None:
        """Подписаться на события реестра (registered, tick_report, ...)."""
        with self._lock:
            self._listeners.append(callback)

    def _emit(self, event_name: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(event_name, payload)
            except Exception as e:
                logger.debug(f"[registry] listener ошибка: {e}")

    # ----------------------------------------------------------------
    # Утилиты для тестов
    # ----------------------------------------------------------------

    def clear(self) -> None:
        """Очистить реестр (только для тестов). teardown не вызывается."""
        with self._lock:
            self._items.clear()
            self._classes.clear()
            self._history.clear()


# ============================================================
# Хелперы для регистрации в DigitalBeing
# ============================================================

def attach_existing_subsystem(agent: Any, attr_name: str, *,
                              registry: Optional[PluginRegistry] = None,
                              priority: int = 100) -> Optional[Subsystem]:
    """Обернуть существующую подсистему агента в Subsystem-адаптер
    и зарегистрировать в registry.

    Используется в DigitalBeing для того, чтобы старые подсистемы
    (которые не наследуют Subsystem) попали в реестр.

    Args:
        agent: экземпляр DigitalBeing.
        attr_name: имя атрибута агента (например, "sleep_cycle").
        registry: реестр. По умолчанию — глобальный.
        priority: priority подсистемы (меньше = раньше).

    Returns:
        Зарегистрированный адаптер или None, если атрибут не найден.
    """
    if registry is None:
        registry = PluginRegistry.get_global()
    sub = getattr(agent, attr_name, None)
    if sub is None:
        return None
    adapter = LegacySubsystemAdapter(
        name=attr_name,
        wrapped=sub,
        agent=agent,
        priority=priority,
        agent_name=getattr(agent, "name", "unknown"),
    )
    registry.register(adapter)
    return adapter


class LegacySubsystemAdapter(Subsystem):
    """Адаптер для существующих подсистем, которые НЕ наследуют Subsystem.

    Делегирует status() и teardown() в обёрнутый объект, если они там есть.
    tick() — no-op по умолчанию (агент сам вызывает свои методы в evolve()).
    """

    def __init__(self, name: str, wrapped: Any, agent: Any, *,
                 priority: int = 100, agent_name: str = "unknown") -> None:
        super().__init__(agent_name=agent_name)
        self.name = name
        self.priority = priority
        self.wrapped = wrapped
        self._agent = agent

    def status(self) -> Dict[str, Any]:
        base = super().status()
        # Если у обёртки есть get_status() — используем.
        if hasattr(self.wrapped, "get_status"):
            try:
                base["wrapped_status"] = self.wrapped.get_status()
            except Exception as e:
                base["wrapped_status_error"] = str(e)
        # Если есть state (или вызываемый state()) — добавим (для дашборда).
        wrapped_state = getattr(self.wrapped, "state", None)
        if callable(wrapped_state):
            try:
                base["state"] = wrapped_state()
            except Exception:
                pass
        elif wrapped_state is not None and not callable(wrapped_state):
            base["state"] = wrapped_state
        return base

    def teardown(self) -> None:
        # Не ломаем обёртку — просто фиксируем.
        super().teardown()