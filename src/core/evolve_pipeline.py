"""
evolve_pipeline.py — Middleware-пайплайн для DigitalBeing.evolve().

Проблема:
    `DigitalBeing.evolve()` (≈106 строк) делает 7 разных вещей:
        1. Такт кеша ментальных моделей
        2. Мотивация
        3. Душа (с интервалом)
        4. Привязанность
        5. Лимит концепций
        6. Принудительное забывание
        7. Рост интеллекта
    Добавить новую фазу = править ядро, тестировать заново.

Решение:
    Пайплайн middleware-классов. Каждое middleware — простой callable:
        def my_middleware(agent, cycle, context) -> MiddlewareResult
    context — общий dict (пробрасывается между фазами).
    MiddlewareResult.skip: True → пропустить остальные фазы (используется в soul_tick).

Зачем:
    - Декомпозиция God Module (рекомендация #1 из AUDIT_REPORT).
    - Плагины могут добавлять свои фазы (например, "EnergyHistoryMiddleware",
      "VulnerabilityMiddleware") без правки ядра.
    - Каждое middleware можно тестировать изолированно.

Использование:
    pipeline = default_evolve_pipeline()
    result = pipeline.run(agent, cycle=42)
    # result.phases — список имён выполненных фаз
    # result.context — общий контекст, модифицированный middleware
    # result.skip_requested — True если какой-то middleware попросил stop

Обратная совместимость:
    `DigitalBeing.evolve()` продолжает работать как раньше: использует
    встроенный `default_evolve_pipeline()` если не переопределён. Все
    существующие тесты должны проходить без изменений.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# =====================================================================
# Базовые структуры
# =====================================================================

@dataclass
class MiddlewareResult:
    """Результат работы одного middleware.

    Attributes:
        skip: Если True — следующие middleware не выполняются (используется,
            когда фаза не должна запускаться в этом цикле, например soul_tick
            раз в 10 циклов).
        data: Произвольные данные, которые middleware хочет вернуть. Полезно
            для логирования, метрик и отладки. Не влияют на пайплайн.
    """

    skip: bool = False
    data: Dict[str, Any] = field(default_factory=dict)


# Тип middleware: принимает (agent, cycle, context) и возвращает MiddlewareResult.
MiddlewareFn = Callable[[Any, int, Dict[str, Any]], MiddlewareResult]


@dataclass
class PipelineResult:
    """Сводный результат прогона пайплайна."""

    cycle: int
    phases: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    skip_requested: bool = False
    errors: List[str] = field(default_factory=list)


# =====================================================================
# Класс пайплайна
# =====================================================================

class EvolvePipeline:
    """Middleware-пайплайн для `DigitalBeing.evolve()`.

    Middleware выполняются в порядке регистрации. Каждое может:
        1. Прочитать/изменить context (dict).
        2. Вернуть MiddlewareResult с .skip=True (остановить пайплайн).
        3. Бросить исключение → логируется, пайплайн продолжается
           (изоляция ошибок — middleware не должны ломать эволюцию).
    """

    def __init__(self, name: str = "evolve"):
        self.name = name
        self._middlewares: List[tuple] = []  # (name, fn)

    def use(self, name: str, fn: MiddlewareFn) -> "EvolvePipeline":
        """Регистрирует middleware. Возвращает self для chaining.

        Args:
            name: Уникальное имя фазы (для логов и тестов).
            fn: Callable (agent, cycle, context) -> MiddlewareResult.
        """
        if not callable(fn):
            raise TypeError(f"Middleware '{name}' must be callable, got {type(fn)}")
        self._middlewares.append((name, fn))
        return self

    def run(self, agent: Any, cycle: int, context: Optional[Dict[str, Any]] = None) -> PipelineResult:
        """Запускает все middleware по порядку.

        Args:
            agent: DigitalBeing (или совместимый объект).
            cycle: Номер текущего цикла (int).
            context: Начальный контекст (dict). Если None — создаётся пустой.

        Returns:
            PipelineResult с фазами, контекстом и списком ошибок.
        """
        if context is None:
            context = {}
        result = PipelineResult(cycle=cycle, context=context)

        for name, fn in self._middlewares:
            if result.skip_requested:
                logger.debug("[%s] Пропуск '%s' — skip_requested", self.name, name)
                continue

            result.phases.append(name)
            try:
                mw_result = fn(agent, cycle, context)
            except Exception as exc:
                # Изоляция ошибок: один сломанный middleware не должен
                # ломать всю эволюцию. Логируем и идём дальше.
                logger.exception(
                    "[%s] Ошибка в middleware '%s': %s", self.name, name, exc,
                )
                result.errors.append(f"{name}: {exc}")
                continue

            if isinstance(mw_result, MiddlewareResult):
                if mw_result.skip:
                    result.skip_requested = True
                # Мерджим data в общий контекст (если есть)
                if mw_result.data:
                    context.update(mw_result.data)
            elif mw_result is not None:
                # Legacy-стиль: middleware вернул просто dict.
                if isinstance(mw_result, dict):
                    context.update(mw_result)

        return result

    def __len__(self) -> int:
        return len(self._middlewares)

    def __contains__(self, name: str) -> bool:
        return any(n == name for n, _ in self._middlewares)


# =====================================================================
# Базовые middleware (вынесены из DigitalBeing.evolve())
# =====================================================================

def make_mental_models_tick() -> MiddlewareFn:
    """Middleware: такт кеша ментальных моделей (Шаг 4 оптимизации)."""

    def middleware(agent, cycle, context):
        if hasattr(agent, "mental_models") and hasattr(agent.mental_models, "tick_cycle"):
            agent.mental_models.tick_cycle()
        return MiddlewareResult()

    return middleware


def make_motivation_tick() -> MiddlewareFn:
    """Middleware: обновляет потребности и проверяет новые драйвы."""

    def middleware(agent, cycle, context):
        # Single source of truth: UnifiedMotivationSystem (P0.6-P0.10).
        # Legacy MotivationController kept only as fallback.
        motivation = getattr(agent, "motivation_system", None) or getattr(agent, "motivation", None)
        if motivation is None or (hasattr(motivation, "available") and not motivation.available):
            return MiddlewareResult()

        # Потребности уже тикнули в autonomous_tick этого же цикла.
        # Второй тик удваивал бы затухание и незаметно ускорял «голод»
        # относительно остальных часов агента.
        if getattr(motivation, "last_tick_cycle", None) == cycle:
            return MiddlewareResult()

        motivation_state = motivation.tick({
            "unknown_concepts": [
                name for name, node in agent.mental_models.concepts.items()
                if node.confidence < 0.4
            ],
            "novel_areas": list(agent.mental_models.concepts.keys())[:5],
            "weak_areas": ["reasoning", "metacognition"],
        })
        if motivation_state.get("new_goals"):
            logger.info(
                "🎯 Мотивация добавила %d новых целей",
                len(motivation_state["new_goals"]),
            )
        return MiddlewareResult(data={"motivation": motivation_state})

    return middleware


def make_soul_tick(interval_attr: str = "SOUL_TICK_INTERVAL") -> MiddlewareFn:
    """Middleware: душа (с интервалом) + watchdog.should_run_heavy_tick.

    Args:
        interval_attr: имя атрибута в LR_CONFIG с интервалом тиков.
    """

    def middleware(agent, cycle, context):
        from src.core.watchdog import get_watchdog
        wd = context.get("watchdog") or get_watchdog()
        run_heavy = wd.should_run_heavy_tick()

        soul_interval = getattr(LR_CONFIG, interval_attr, 10)
        if (
            hasattr(agent, "soul")
            and (cycle % max(1, soul_interval) == 0)
            and run_heavy
        ):
            soul_report = agent.tick_soul(cycle)
            # Логируем квесты и сигналы
            if soul_report["soul"].get("systems", {}).get("meaning", {}).get("new_quest"):
                quest = soul_report["soul"]["systems"]["meaning"]["new_quest"]
                logger.info("🌌 Новый экзистенциальный квест: %s", quest[:60])
            if soul_report["embodiment"].get("state") in ("exhausted", "tired"):
                logger.info(
                    "😴 Embodiment: %s (fatigue=%.2f)",
                    soul_report["embodiment"]["state"],
                    soul_report["embodiment"]["fatigue"],
                )
            if soul_report["mortality"].get("phase") in ("autumn", "finale"):
                logger.info(
                    "⏳ Mortality: фаза %s (anxiety=%.2f)",
                    soul_report["mortality"]["phase"],
                    soul_report["mortality"]["mortality_anxiety"],
                )
            return MiddlewareResult(data={"soul_report": soul_report})
        return MiddlewareResult()

    return middleware


def make_attachment_tick() -> MiddlewareFn:
    """Middleware: записывает взаимодействие с пользователем."""

    def middleware(agent, cycle, context):
        if hasattr(agent, "attachment") and hasattr(agent, "user_interaction"):
            ui = agent.user_interaction
            if ui and ui.pending_questions:
                agent.attachment.record_interaction(
                    name="user",
                    was_helpful=True,
                    was_substantial=True,
                )
        return MiddlewareResult()

    return middleware


def make_concept_limit(interval: int = 50) -> MiddlewareFn:
    """Middleware: лимит ментальных моделей (периодически).

    Args:
        interval: как часто проверять лимит (в циклах).
    """

    def middleware(agent, cycle, context):
        if cycle % interval != 0:
            return MiddlewareResult()
        try:
            forgotten = agent.mental_models.apply_concept_limit()
            if forgotten > 0:
                logger.info("🧹 Лимит ментальных моделей: -%d слабых концепций", forgotten)
            return MiddlewareResult(data={"concepts_forgotten": forgotten})
        except Exception as exc:
            logger.debug("concept_limit: %s", exc)
            return MiddlewareResult()

    return middleware


def make_force_forget_under_pressure() -> MiddlewareFn:
    """Middleware: принудительное забывание под давлением памяти."""

    def middleware(agent, cycle, context):
        from src.core.watchdog import get_watchdog
        wd = context.get("watchdog") or get_watchdog()
        if wd.should_force_forget():
            forgotten = agent.mental_models.apply_concept_limit()
            wd.mark_forced_forget(forgotten)
            return MiddlewareResult(data={"forced_forget": forgotten})
        return MiddlewareResult()

    return middleware


def make_intelligence_growth() -> MiddlewareFn:
    """Middleware: рост интеллекта при достаточном успехе.

    Это «главная» фаза: если интеллект повысился — увеличиваем энергию,
    сохраняем БЗ, ставим новую цель, укрепляем идентичность.
    """

    def middleware(agent, cycle, context):
        evolution_threshold = 3 + (agent.intelligence - 1) * 2
        old_intelligence = agent.intelligence
        evolved = False

        if (
            agent.success_streak >= evolution_threshold
            or agent.completed_goals >= agent.intelligence * 2
        ):
            agent.intelligence += 1
            agent.success_streak = 0
            agent.energy += 20
            logger.info(
                "ЭВОЛЮЦИЯ! Интеллект %d -> %d", old_intelligence, agent.intelligence,
            )
            logger.info("[%s] ИНТЕЛЛЕКТ ПОВЫШЕН! Уровень: %d", agent.name, agent.intelligence)
            agent._save_knowledge_base()
            evolved = True

            if agent.intelligence % 2 == 0:
                agent.set_goal(
                    f"Достичь уровня {agent.intelligence + 1}",
                    difficulty=agent.intelligence,
                )

            # Удовлетворяем потребности при росте интеллекта
            if hasattr(agent, "motivation") and agent.motivation.available:
                agent.motivation.satisfy_need("competence", amount=0.2)
                agent.motivation.satisfy_need("self_improvement", amount=0.15)

            # Укрепляем идентичность
            if hasattr(agent, "soul") and agent.soul.is_available("self"):
                try:
                    core = agent.soul.get("self")
                    core.identity_stability_score = min(
                        1.0, core.identity_stability_score + 0.05
                    )
                except Exception:
                    pass

        return MiddlewareResult(data={"evolved": evolved, "intelligence": agent.intelligence})

    return middleware


# =====================================================================
# Стандартный пайплайн
# =====================================================================

# Импорт LR_CONFIG здесь, чтобы не было циклической зависимости при загрузке.
from config.simulation_config import LR_CONFIG  # noqa: E402


def default_evolve_pipeline() -> EvolvePipeline:
    """Возвращает стандартный пайплайн эволюции.

    Порядок фаз соответствует оригинальному `DigitalBeing.evolve()` —
    это гарантирует, что новая реализация даёт тот же результат, что и старая.
    """
    return (
        EvolvePipeline(name="evolve")
        .use("mental_models_tick", make_mental_models_tick())
        .use("motivation", make_motivation_tick())
        .use("soul", make_soul_tick())
        .use("attachment", make_attachment_tick())
        .use("concept_limit", make_concept_limit(interval=50))
        .use("force_forget", make_force_forget_under_pressure())
        .use("intelligence_growth", make_intelligence_growth())
    )


# Глобальный синглтон — переиспользуется между вызовами.
_default_pipeline: Optional[EvolvePipeline] = None


def get_default_pipeline() -> EvolvePipeline:
    """Получает (лениво создаёт) стандартный пайплайн эволюции."""
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = default_evolve_pipeline()
    return _default_pipeline


def reset_default_pipeline() -> None:
    """Сбрасывает кеш пайплайна (для тестов с monkey-patch)."""
    global _default_pipeline
    _default_pipeline = None