"""LoopCloser — замыкание петли «действие → результат» и выход из тупика.

Две задачи
----------
1. **Учёт результата.** После каждого действия сравнивает подпись мира
   (``src/core/world_delta.py``) и говорит, дало ли действие наблюдаемый
   эффект.
2. **Выход из зацикливания.** Если одно и то же действие повторяется без
   эффекта, оно перестаёт считаться рабочим. Раньше агент бесконечно
   выбирал ``explore``, потому что ничто не мешало: действие «выполнялось»
   и не оставляло следов, а причина сменить его не появлялась.

Почему не наказание, а переключение
-----------------------------------
Штраф за бесполезное действие только уменьшил бы энергию и ничего не
изменил в выборе. Здесь другая логика: действие, не дающее эффекта
``max_no_effect`` раз подряд, помечается как «тупиковое», и арбитр его не
выбирает, пока не появятся новые условия. Это ближе к тому, как ведёт себя
живое существо: если стучаться в стену бесполезно — перестают стучаться,
а не стучатся слабее.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence

from src.core.world_delta import WorldDelta, WorldSignature, between, capture


# Действия, которые по смыслу должны приводить к приросту знания.
# Остальные (отдых, рефлексия, общение) — обслуживание, а не прогресс:
# «нет новых знаний» для них нормально.
DEFAULT_PRODUCTIVE_ACTIONS: FrozenSet[str] = frozenset(
    {
        "explore",
        "synthesis",
        "decomposition",
        "hypothesis",
        "web_search",
        "know_answer",
    }
)


@dataclass(frozen=True)
class ActionOutcome:
    """Результат одного действия с точки зрения изменений в мире."""

    action: str
    delta: WorldDelta
    topic: str = ""
    credited: bool = False
    reason: str = ""

    @property
    def had_effect(self) -> bool:
        return not self.delta.is_empty

    def as_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "topic": self.topic,
            "had_effect": self.had_effect,
            "credited": self.credited,
            "reason": self.reason,
            "delta": self.delta.as_dict(),
            "summary": self.delta.summary(),
        }


@dataclass
class LoopCloser:
    """Следит за тем, чтобы действия приводили к наблюдаемому результату.

    Args:
        max_no_effect: сколько раз подряд действие может не дать эффекта,
            прежде чем считаться тупиковым.
        history_size: сколько последних исходов помнить (для диагностики).
        productive_actions: действия, которые обещают прирост знания.
            Только они могут стать «тупиковыми». Отдых, рефлексия и
            общение не добавляют знаний по своей природе — считать их
            бесполезными было бы ошибкой и привело бы к их отключению.
    """

    max_no_effect: int = 3
    history_size: int = 50
    productive_actions: FrozenSet[str] = field(
        default_factory=lambda: DEFAULT_PRODUCTIVE_ACTIONS
    )

    _no_effect_streak: Dict[str, int] = field(default_factory=dict, repr=False)
    _effect_count: Dict[str, int] = field(default_factory=dict, repr=False)
    _history: List[ActionOutcome] = field(default_factory=list, repr=False)
    _last: Optional[ActionOutcome] = None

    # ------------------------------------------------------------------
    # Классификация действий
    # ------------------------------------------------------------------

    def is_productive(self, action: str) -> bool:
        """Обещает ли действие прирост знания.

        Для непродуктивных действий «нет эффекта» — норма, а не тупик.
        """
        return str(action) in self.productive_actions

    # ------------------------------------------------------------------
    # Учёт
    # ------------------------------------------------------------------

    def observe(
        self,
        action: str,
        before: WorldSignature,
        after: WorldSignature,
        *,
        topic: str = "",
        reason: str = "",
    ) -> ActionOutcome:
        """Регистрирует исход действия.

        Returns:
            ``ActionOutcome`` с признаком ``had_effect``.
        """
        delta = between(before, after)
        outcome = ActionOutcome(
            action=str(action),
            delta=delta,
            topic=str(topic or ""),
            reason=str(reason or ""),
        )

        key = str(action)
        if delta.is_empty:
            self._no_effect_streak[key] = self._no_effect_streak.get(key, 0) + 1
        else:
            self._no_effect_streak[key] = 0
            self._effect_count[key] = self._effect_count.get(key, 0) + 1

        self._last = outcome
        self._history.append(outcome)
        if len(self._history) > max(1, self.history_size):
            del self._history[: len(self._history) - self.history_size]

        return outcome

    def observe_agent_action(
        self,
        agent: Any,
        action: str,
        before: WorldSignature,
        *,
        topic: str = "",
        reason: str = "",
    ) -> ActionOutcome:
        """Удобная обёртка: снимает подпись после действия сама."""
        return self.observe(
            action,
            before,
            capture(agent),
            topic=topic,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Состояние
    # ------------------------------------------------------------------

    @property
    def last_outcome(self) -> Optional[ActionOutcome]:
        return self._last

    def no_effect_streak(self, action: str) -> int:
        """Сколько раз подряд действие не давало эффекта."""
        return int(self._no_effect_streak.get(str(action), 0))

    def is_stuck(self, action: str) -> bool:
        """Действие повторяется без эффекта слишком долго.

        Непродуктивные действия (отдых, рефлексия, общение) тупиковыми не
        бывают: они и не должны добавлять знаний.
        """
        if not self.is_productive(action):
            return False
        return self.no_effect_streak(action) >= max(1, int(self.max_no_effect))

    def has_effect_history(self, action: str) -> bool:
        """Действие хотя бы раз давало наблюдаемый эффект."""
        return int(self._effect_count.get(str(action), 0)) > 0

    def effective_actions(self) -> List[str]:
        """Действия, которые в этой жизни давали эффект."""
        return sorted(self._effect_count)

    def stuck_actions(self) -> List[str]:
        """Действия, которые сейчас в тупике."""
        return sorted(
            action
            for action in self._no_effect_streak
            if self.is_stuck(action)
        )

    def reset(self, action: Optional[str] = None) -> None:
        """Сбрасывает счётчики (одного действия или все).

        Нужно, когда условия изменились: например, включился web-поиск и
        действие, ранее бесполезное, снова может дать результат.
        """
        if action is None:
            self._no_effect_streak.clear()
            return
        self._no_effect_streak.pop(str(action), None)

    # ------------------------------------------------------------------
    # Выбор действия
    # ------------------------------------------------------------------

    def choose(
        self,
        candidates: Sequence[Dict[str, Any]],
        *,
        fallback: Optional[str] = None,
        normalize: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Выбирает первого кандидата, который не в тупике.

        Args:
            candidates: список кандидатов ``{"action": ..., ...}``,
                обычно уже отсортированный по силе.
            fallback: действие на случай, когда все кандидаты тупиковые.
                Должно быть заведомо результативным (например,
                ``think_decompose``), иначе цикл снова замрёт.
            normalize: функция приведения имени к типу действия. Имена у
                источников разные («exploration» и «explore»), а счётчики
                общие — без приведения проверка смотрела бы не туда.

        Returns:
            Выбранный кандидат. Если все тупиковые — синтетический
            кандидат с ``fallback`` и пометкой ``reason="all_stuck"``.
        """
        to_type = normalize or (lambda name: str(name))

        for candidate in candidates:
            action = str(candidate.get("action", ""))
            if not action:
                continue
            if not self.is_stuck(to_type(action)):
                return dict(candidate)

        if fallback:
            return {
                "action": str(fallback),
                "source": "loop_closer",
                "strength": 0.5,
                "params": {},
                "reason": "all_stuck",
            }
        return {
            "action": "wait",
            "source": "loop_closer",
            "strength": 0.0,
            "params": {},
            "reason": "all_stuck",
        }

    def describe_candidates(
        self, candidates: Iterable[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Диагностика: какие кандидаты тупиковые и почему."""
        result = []
        for candidate in candidates:
            action = str(candidate.get("action", ""))
            result.append(
                {
                    "action": action,
                    "stuck": self.is_stuck(action),
                    "no_effect_streak": self.no_effect_streak(action),
                    "had_effect_before": self.has_effect_history(action),
                }
            )
        return result

    # ------------------------------------------------------------------
    # Сериализация
    # ------------------------------------------------------------------

    def to_checkpoint_dict(self) -> Dict[str, Any]:
        """Сохраняет счётчики: тупики не должны исчезать после рестарта."""
        return {
            "no_effect_streak": dict(self._no_effect_streak),
            "effect_count": dict(self._effect_count),
        }

    def restore_from_checkpoint(self, state: Optional[Dict[str, Any]]) -> None:
        """Восстанавливает счётчики из чекпоинта."""
        if not isinstance(state, dict):
            return
        streak = state.get("no_effect_streak")
        if isinstance(streak, dict):
            self._no_effect_streak = {
                str(key): int(value)
                for key, value in streak.items()
                if isinstance(value, (int, float))
            }
        counts = state.get("effect_count")
        if isinstance(counts, dict):
            self._effect_count = {
                str(key): int(value)
                for key, value in counts.items()
                if isinstance(value, (int, float))
            }

    def status(self) -> Dict[str, Any]:
        """Состояние для окна и дашборда."""
        return {
            "last_action": self._last.action if self._last else None,
            "last_effect": self._last.had_effect if self._last else None,
            "last_summary": self._last.delta.summary() if self._last else "",
            "stuck_actions": self.stuck_actions(),
            "effective_actions": self.effective_actions(),
            "max_no_effect": self.max_no_effect,
        }


__all__ = ["ActionOutcome", "LoopCloser"]
