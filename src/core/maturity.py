"""Зрелость агента: измеримый порог «семя стоит раздавать».

Зачем это нужно
---------------
«Раздам семена, когда она начнёт развиваться» — правильное намерение, но
непроверяемое: момент «начала развития» нельзя опознать, значит его нельзя
и дождаться. Нужен порог, который считается из состояния агента и даёт
ответ «да/нет» с указанием, чего не хватает.

Что считается
-------------
Только то, что агент нажил **сам**, а не получил при рождении:

* прожитые циклы;
* концепции сверх родовых (bootstrap);
* концепции с уверенностью ≥ порога — глубина, а не только ширина;
* изменения ценностей через опыт;
* завершённые цели;
* действия с наблюдаемым результатом.

Порог намеренно не проходится на новорождённом: у свежего агента 0
циклов, 0 нажитых концепций, 0 завершённых целей и 0 результативных
действий. Если бы порог проходился сразу, он ничего бы не измерял.

Честность
---------
Модуль ничего не меняет: только читает и сравнивает. Он не может «помочь»
агенту стать зрелым и не влияет на его жизнь. Провал порога — не приговор:
агент продолжает жить, просто его семя ещё не стоит раздавать.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

# Уверенность, начиная с которой концепцию можно считать понятой.
CONFIDENT_THRESHOLD = 0.5


# ============================================================
# Порог
# ============================================================


@dataclass(frozen=True)
class MaturityCriteria:
    """Порог зрелости. Каждое поле — отдельный измеримый критерий.

    Значения по умолчанию подобраны так, чтобы порог требовал настоящей
    работы, но был достижим за несколько часов реального времени или за
    несколько минут в режиме «Лаборатория».
    """

    min_cycles: int = 500
    min_new_concepts: int = 20
    min_defined_concepts: int = 10
    min_value_changes: int = 1
    min_goals_completed: int = 1
    min_effective_ratio_pct: int = 50

    def as_dict(self) -> Dict[str, int]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "MaturityCriteria":
        """Собирает порог из словаря, игнорируя неизвестные ключи.

        Нужно для конфига и для чтения порога из семени: формат может
        меняться, а падать из-за лишнего ключа не должен.
        """
        if not isinstance(data, dict):
            return cls()
        known = cls.__dataclass_fields__
        values = {
            key: int(value)
            for key, value in data.items()
            if key in known and isinstance(value, (int, float))
        }
        return cls(**values)


# ============================================================
# Результат одного критерия
# ============================================================


@dataclass(frozen=True)
class CriterionResult:
    """Один критерий: сколько есть, сколько нужно, выполнен ли."""

    name: str
    label: str
    value: Optional[int]
    target: int
    detail: str = ""

    @property
    def met(self) -> bool:
        """Критерий выполнен. Неизвестное значение считается невыполненным."""
        if self.value is None:
            return False
        return self.value >= self.target

    def progress(self) -> float:
        """Доля выполнения 0..1 (для полоски в окне)."""
        if self.value is None:
            return 0.0
        if self.target <= 0:
            return 1.0
        return max(0.0, min(1.0, self.value / self.target))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "value": self.value,
            "target": self.target,
            "met": self.met,
            "detail": self.detail,
        }

    def describe(self) -> str:
        """Строка для человека: «Концепции сверх родовых 12/20»."""
        if self.value is None:
            return f"{self.label}: неизвестно (нужно {self.target})"
        mark = "✓" if self.met else "·"
        return f"{mark} {self.label}: {self.value}/{self.target}"


# ============================================================
# Отчёт
# ============================================================


@dataclass(frozen=True)
class MaturityReport:
    """Полная оценка зрелости."""

    agent_name: str
    criteria: List[CriterionResult]
    threshold: MaturityCriteria
    cycles_lived: int = 0
    birth_concepts_known: bool = True

    # ------------------------------------------------------------------
    # Сводка
    # ------------------------------------------------------------------

    @property
    def total(self) -> int:
        return len(self.criteria)

    @property
    def met_count(self) -> int:
        return sum(1 for item in self.criteria if item.met)

    @property
    def is_mature(self) -> bool:
        """Все критерии выполнены — семя стоит раздавать."""
        return self.met_count == self.total

    @property
    def ratio(self) -> float:
        return self.met_count / self.total if self.total else 0.0

    @property
    def blockers(self) -> List[CriterionResult]:
        """Что мешает. Пусто, если агент зрелый."""
        return [item for item in self.criteria if not item.met]

    # ------------------------------------------------------------------
    # Текст
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """Одна строка: «зрелость 3/6, не хватает: …»."""
        if self.is_mature:
            return f"зрелость {self.met_count}/{self.total} — порог пройден"
        missing = "; ".join(
            f"{item.label} {item.value if item.value is not None else '?'}"
            f"/{item.target}"
            for item in self.blockers
        )
        return (
            f"зрелость {self.met_count}/{self.total} — "
            f"не хватает: {missing}"
        )

    def describe(self) -> str:
        """Многострочный отчёт для консоли и логов."""
        lines = [
            f"Зрелость агента '{self.agent_name}': "
            f"{self.met_count}/{self.total}",
            f"Прожито циклов: {self.cycles_lived}",
            "",
        ]
        for item in self.criteria:
            lines.append("  " + item.describe())
            if item.detail:
                lines.append(f"      {item.detail}")
        lines.append("")
        lines.append(
            "ВЕРДИКТ: " + ("можно раздавать семя" if self.is_mature
                           else "порог не пройден")
        )
        if not self.birth_concepts_known:
            lines.append(
                "Внимание: нет отметки рождения (старый чекпоинт), "
                "число нажитых концепций неизвестно."
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Сериализация
    # ------------------------------------------------------------------

    def as_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "is_mature": self.is_mature,
            "met_count": self.met_count,
            "total": self.total,
            "ratio": round(self.ratio, 3),
            "cycles_lived": self.cycles_lived,
            "birth_concepts_known": self.birth_concepts_known,
            "summary": self.summary(),
            "threshold": self.threshold.as_dict(),
            "criteria": [item.as_dict() for item in self.criteria],
            "blockers": [item.name for item in self.blockers],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, indent=indent)


# ============================================================
# Измерение
# ============================================================


def _safe(callable_, default):
    """Вызывает счётчик, не позволяя одной поломке уронить весь отчёт.

    Оценка зрелости не должна падать из-за отсутствующей подсистемы: это
    диагностика, а не жизненный цикл.
    """
    try:
        return callable_()
    except Exception:
        return default


def _count_new_concepts(agent: Any) -> tuple:
    """Сколько концепций нажито сверх родовых.

    Returns:
        (значение или None, известно ли). ``None`` — нет отметки рождения,
        и придумывать число нельзя: неизвестное не должно выглядеть как
        ноль или как успех.
    """
    def _measure():
        mental_models = getattr(agent, "mental_models", None)
        concepts = getattr(mental_models, "concepts", None)
        if not isinstance(concepts, dict):
            return 0, True

        birth = getattr(agent, "_birth_concepts", None)
        if not isinstance(birth, int) or birth < 0:
            return None, False
        return max(0, len(concepts) - birth), True

    return _safe(_measure, (None, False))


def _count_defined_concepts(agent: Any) -> Optional[int]:
    """Концепции с собственной формулировкой, **сверх родовых**.

    Почему не «уверенность ≥ 0.5»: новая концепция приходит с уверенностью
    0.1 и растёт только от повторных встреч с сильной валентностью, поэтому
    такой порог практически недостижим и ничего не измерял бы.

    Собственная формулировка (``definition_hypothesis``) появляется, когда
    агент вернулся к теме и собрал определение из накопленного опыта. Это
    и есть освоение: не «видел слово», а «могу сказать, что это для меня
    значит».
    """
    mental_models = getattr(agent, "mental_models", None)
    concepts = getattr(mental_models, "concepts", None)
    if not isinstance(concepts, dict):
        return 0

    count = 0
    for node in concepts.values():
        try:
            definition = str(getattr(node, "definition_hypothesis", "") or "")
        except Exception:
            continue
        if len(definition) > 10:
            count += 1

    birth = getattr(agent, "_birth_defined", None)
    if not isinstance(birth, int) or birth < 0:
        return None
    return max(0, count - birth)


def _count_value_changes(agent: Any) -> int:
    """Сколько раз агент менял ценности через опыт."""
    registry = getattr(agent, "will_registry", None)
    if registry is None:
        return 0
    try:
        stats = registry.get_stats()
    except Exception:
        return 0
    by_type = (stats or {}).get("by_type") or {}
    try:
        return int(by_type.get("value_changes", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _count_effective_ratio_pct(agent: Any) -> int:
    """Доля продуктивных действий с наблюдаемым результатом, в процентах.

    Почему доля, а не «число разных действий»: агент естественно
    сосредотачивается на одном продуктивном действии, и требование трёх
    разных типов было бы недостижимо без искусственного принуждения к
    разнообразию. Доля же отвечает на важный вопрос: действует ли агент
    осмысленно или просто крутит счётчик.

    Считается по продуктивным действиям: отдых, рефлексия и ответ по
    памяти не меняют мир по своей природе, и их доля в знаменателе делала
    критерий недостижимым арифметически (замер: 28 % при 45 %
    действий-отдыха).
    """
    loop_closer = getattr(agent, "loop_closer", None)
    if loop_closer is None:
        return 0
    try:
        return int(round(loop_closer.effect_ratio() * 100))
    except Exception:
        return 0


def _count_cycles(agent: Any) -> int:
    try:
        return int(getattr(agent, "cycle_count", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _count_completed_goals(agent: Any) -> int:
    try:
        return int(getattr(agent, "completed_goals", 0) or 0)
    except (TypeError, ValueError):
        return 0


def assess(
    agent: Any,
    criteria: Optional[MaturityCriteria] = None,
) -> MaturityReport:
    """Оценивает зрелость агента по измеряемым критериям.

    Args:
        agent: ``DigitalBeing`` или совместимый объект.
        criteria: порог. По умолчанию ``MaturityCriteria()``.

    Returns:
        Отчёт с полным списком критериев и вердиктом.
    """
    threshold = criteria or MaturityCriteria()

    cycles = _safe(lambda: _count_cycles(agent), 0)
    new_concepts, birth_known = _count_new_concepts(agent)
    defined = _safe(lambda: _count_defined_concepts(agent), None)
    value_changes = _safe(lambda: _count_value_changes(agent), 0)
    goals = _safe(lambda: _count_completed_goals(agent), 0)
    effective_ratio = _safe(lambda: _count_effective_ratio_pct(agent), 0)

    results = [
        CriterionResult(
            name="cycles",
            label="Прожито циклов",
            value=cycles,
            target=threshold.min_cycles,
        ),
        CriterionResult(
            name="new_concepts",
            label="Концепций сверх родовых",
            value=new_concepts,
            target=threshold.min_new_concepts,
            detail=(
                "" if birth_known
                else "нет отметки рождения: число нажитых концепций неизвестно"
            ),
        ),
        CriterionResult(
            name="defined_concepts",
            label="Освоенных концепций",
            value=defined,
            target=threshold.min_defined_concepts,
            detail=(
                "есть своя формулировка, нажитая сверх родовых"
                if defined is not None
                else "нет отметки рождения: неизвестно, сколько освоено"
            ),
        ),
        CriterionResult(
            name="value_changes",
            label="Изменений ценностей",
            value=value_changes,
            target=threshold.min_value_changes,
            detail="ценность, добавленная или убранная через опыт",
        ),
        CriterionResult(
            name="goals_completed",
            label="Завершённых целей",
            value=goals,
            target=threshold.min_goals_completed,
        ),
        CriterionResult(
            name="effective_ratio",
            label="Доля продуктивных действий с результатом, %",
            value=effective_ratio,
            target=threshold.min_effective_ratio_pct,
            detail=(
                "действия, которые должны приносить знание и принесли его; "
                "отдых и ответ по памяти не в счёт"
            ),
        ),
    ]

    return MaturityReport(
        agent_name=str(getattr(agent, "name", "?")),
        criteria=results,
        threshold=threshold,
        cycles_lived=cycles,
        birth_concepts_known=birth_known,
    )


def load_criteria(path: Optional[str] = None) -> MaturityCriteria:
    """Порог из файла ``data/maturity.json``, если он есть.

    Файла может не быть — тогда действует порог по умолчанию. Так человек
    может поднять планку, не трогая код.
    """
    if not path:
        from src.core.paths import data_path

        path = data_path("maturity.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return MaturityCriteria()
    if isinstance(data, dict) and isinstance(data.get("criteria"), dict):
        data = data["criteria"]
    return MaturityCriteria.from_dict(data)


__all__ = [
    "CONFIDENT_THRESHOLD",
    "MaturityCriteria",
    "CriterionResult",
    "MaturityReport",
    "assess",
    "load_criteria",
]
