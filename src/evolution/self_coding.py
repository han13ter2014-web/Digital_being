"""self_coding — рука самоэволюции: повторный сигнал → предложение config_change.

«Эволюция-1» (2026-11-03). Существо не пишет свободный код: канон это
запрещает. Вместо этого она собирает предложение
из проверенных заготовок: белый список безопасных рычагов конфигурации,
честный diff с реальным текущим значением и обоснование из её собственных
метрик. Это тот же принцип, что её рисунки (local_art): композиция из
проверенных частей, а не выдумка.

Границы:
- рычаги ТОЛЬКО из SAFE_TUNABLES (WILL_CONFIG, watchdog, защита от
  жестокости и жизненный цикл сюда не попадают и попасть не могут);
- категории без безопасного рычага (goal_management, learning_strategy)
  честно не дают черновика — «нет рычага» тоже ответ;
- SignalTracker живёт в памяти и не сериализуется: сон стирает след
  накопленных сигналов, как след неудачной охоты.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

from config.simulation_config import LR_CONFIG


@dataclass(frozen=True)
class Tunable:
    """Безопасный рычаг: атрибут LR_CONFIG, кандидат и обоснование."""

    attr: str
    candidate: object
    rationale: str


# Белый список рычагов. Каждый — параметр темпа/гигиены, не затрагивающий
# волю, ценности, защиту и жизненный цикл существа.
SAFE_TUNABLES: Dict[str, Tunable] = {
    "energy_efficiency": Tunable(
        attr="REST_FATIGUE_THRESHOLD",
        candidate=0.55,
        rationale=(
            "Отдыхать чуть раньше: меньше действий на истощении, "
            "меньше провалов и потраченной впустую энергии."
        ),
    ),
    "memory_management": Tunable(
        attr="FORGETTING_INTERVAL",
        candidate=400,
        rationale=(
            "Чаще отпускать слабые концепции: память остаётся лёгкой, "
            "а уверенные знания не трогаются."
        ),
    ),
    "concept_quality": Tunable(
        attr="MIN_CONFIDENCE_FOR_RETENTION",
        candidate=0.15,
        rationale=(
            "Держать в памяти более уверенные концепции: слабые "
            "быстрее отпускаются, качество выше."
        ),
    ),
}

_MISSING = object()


class SignalTracker:
    """Считает подряд идущие повторы сигнала.

    Один анализ за тик; категория «дозревает» до предложения только если
    повторяется ``threshold`` раз подряд. Серия любой другой категории
    сбрасывает её счётчик — сигнал должен быть устойчивым, а не случайным.
    """

    def __init__(self, threshold: int = 3):
        self.threshold = max(1, threshold)
        self._streaks: Dict[str, int] = {}

    def observe(self, categories: Iterable[str]) -> Optional[str]:
        """Записывает категории сигналов тика.

        Возвращает категорию, достигшую порога (и сбрасывает её счётчик,
        чтобы следующее предложение собирало стрик заново), иначе None.
        Категории вне белого списка наблюдаются, но никогда не дозревают:
        для них нет безопасного рычага.
        """
        seen = set(categories)
        ripe: Optional[str] = None
        for category in SAFE_TUNABLES:
            if category in seen:
                self._streaks[category] = self._streaks.get(category, 0) + 1
                if ripe is None and self._streaks[category] >= self.threshold:
                    ripe = category
            else:
                self._streaks[category] = 0
        if ripe is not None:
            self._streaks[ripe] = 0
        return ripe

    def streak(self, category: str) -> int:
        return self._streaks.get(category, 0)


def draft_config_change(category: str) -> Optional[Dict]:
    """Собирает честный черновик изменения конфигурации.

    Текущее значение читается из живого LR_CONFIG — diff никогда не
    выдумывает «старое» значение. Если рычага нет, атрибут отсутствует
    или уже равен кандидату — черновика нет.
    """
    tunable = SAFE_TUNABLES.get(category)
    if tunable is None:
        return None
    old = getattr(LR_CONFIG, tunable.attr, _MISSING)
    if old is _MISSING or old == tunable.candidate:
        return None
    diff = (
        "--- a/config/simulation_config.py\n"
        "+++ b/config/simulation_config.py\n"
        "@@\n"
        f"-    {tunable.attr} = {old!r}\n"
        f"+    {tunable.attr} = {tunable.candidate!r}\n"
    )
    return {
        "category": category,
        "attr": tunable.attr,
        "old": old,
        "new": tunable.candidate,
        "diff": diff,
        "rationale": tunable.rationale,
        "title": f"{tunable.attr}: {old!r} → {tunable.candidate!r}",
    }


# === Разбор решения человека (дверь диалога) ===

_APPROVE_WORDS = ("одобри", "одобряю", "принимаю", "прими")
_REJECT_WORDS = ("отклони", "отклоняю", "отвергаю", "отвергни")
_ID_RE = re.compile(r"\b(prop_[\w-]+)\b")


def parse_proposal_decision(text: str) -> Optional[Tuple[str, Optional[str]]]:
    """Распознаёт решение человека о предложении.

    Возвращает ("approve"|"reject", proposal_id|None) или None, если
    реплика не про решение. id может отсутствовать — тогда имеется в
    виду последнее ожидающее предложение.
    """
    lowered = text.strip().lower()
    first = lowered.split(maxsplit=1)[0] if lowered else ""
    decision: Optional[str] = None
    if first in _APPROVE_WORDS:
        decision = "approve"
    elif first in _REJECT_WORDS:
        decision = "reject"
    if decision is None:
        return None
    match = _ID_RE.search(text)
    return decision, (match.group(1) if match else None)
