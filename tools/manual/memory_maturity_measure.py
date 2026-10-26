"""Замер зрелости памяти: становится ли агенту легче отвечать.

Вопрос, на который отвечает скрипт: растёт ли доля концепций, о которых
агент «может ответить» (``MentalModel.can_answer_about``: уверенность
выше 0.4, минимум две встречи, собственная формулировка), и даёт ли сну
это что-то по сравнению с работой без сна.

Родовые знания исключаются: агент рождается с готовым набором концепций,
и засчитывать их как освоенное — значит измерять не его жизнь, а семя.

Запуск (из корня проекта):

    python tools/manual/memory_maturity_measure.py [циклов] [флаги]

Флаги:
    --no-consolidation  контрольная группа: сон не осмысливает накопленное
    --hold-energy       держать энергию на максимуме (иначе прогон
                        превращается в измерение отдыха)
    --seed N            зафиксировать зерно случайности: без него два
                        прогона — разные траектории, и разницу между ними
                        нельзя приписать консолидации
    --depth N           доля исследований, идущих на углубление уже
                        встреченной темы (0..1); по умолчанию — из конфига
    --sample-every N    как часто снимать срез памяти (по умолчанию 50)
    --report PATH       записать отчёт в UTF-8 (консоль Windows искажает
                        кириллицу)

Данные пишутся во временную папку и не трогают ``data/`` рабочей копии.
Сеть выключена: замер не должен зависеть от Википедии.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Изоляция данных ДО импорта src.core.paths.
_DATA_DIR = tempfile.mkdtemp(prefix="db_memory_measure_")
os.environ["DIGITAL_BEING_DATA_DIR"] = _DATA_DIR
os.environ.setdefault("DIGITAL_BEING_TEST_MODE", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from src.core.agent import DigitalBeing  # noqa: E402
from src.core.agent_runner import AgentRunner  # noqa: E402
from src.core.event_bus import EventBus  # noqa: E402


class Sample:
    """Срез памяти в один момент жизни."""

    def __init__(self, cycle: int, snapshot: dict) -> None:
        self.cycle = cycle
        self.snapshot = snapshot

    def line(self) -> str:
        s = self.snapshot
        return (
            f"  цикл {self.cycle:4d}: концепций {s['concepts']:3d} "
            f"(своих {s['own']:3d}), с формулировкой {s['defined']:3d}, "
            f"отвечаемых {s['answerable']:3d} ({s['answerable_share']:.0%}), "
            f"отвечает из памяти {s['definable']:3d}, "
            f"встреч на концепцию {s['mean_experiences']:.1f}, "
            f"ср. уверенность {s['mean_confidence']:.3f}, "
            f"связей {s['links']:4d}, консолидаций {s['consolidations']:3d}"
        )


def snapshot(agent) -> dict:
    """Снять срез памяти: что освоено, о чём можно ответить."""
    model = agent.mental_models
    concepts = model.concepts
    birth = int(getattr(agent, "_birth_concepts", 0) or 0)
    # Родовые концепции определяем по имени из снимка рождения, а не по
    # количеству: часть из них могла быть забыта, и тогда «свои» считались
    # бы неверно.
    born = set(getattr(agent, "_birth_concept_names", set()) or set())
    own = [name for name in concepts if name not in born]

    defined = 0
    answerable = 0
    definable = 0
    confidence_sum = 0.0
    links = 0
    encounters = 0
    deep = 0
    no_evidence = 0
    low_confidence = 0
    evidence_strength = 0.0
    for name in own:
        node = concepts[name]
        text = str(getattr(node, "definition_hypothesis", "") or "")
        if len(text) > 10:
            defined += 1
        if model.can_answer_about(name):
            answerable += 1
        # «Отвечает из памяти» — это условие ветки [Ментальная модель] в
        # thinking_pipeline: уверенность выше 0.5 и формулировка.
        if float(getattr(node, "confidence", 0.0) or 0.0) > 0.5 and len(text) > 10:
            definable += 1
        confidence_sum += float(getattr(node, "confidence", 0.0) or 0.0)
        links += len(getattr(node, "connections", {}) or {})
        experiences = len(getattr(node, "experiences", []) or [])
        encounters += experiences
        # Повторные встречи — охват в глубину, но не обязательно знания:
        # нейтральная регистрация темы не добавляет свидетельств.
        if experiences >= 2:
            deep += 1
        strength, _ = node.evidence()
        evidence_strength += strength
        if strength == 0:
            no_evidence += 1
        if node.confidence <= 0.4:
            low_confidence += 1

    own_count = len(own)
    return {
        "concepts": len(concepts),
        "own": own_count,
        "birth": birth,
        "defined": defined,
        "answerable": answerable,
        "answerable_share": (answerable / own_count) if own_count else 0.0,
        "definable": definable,
        "deep": deep,
        "deep_share": (deep / own_count) if own_count else 0.0,
        "encounters": encounters,
        "no_evidence": no_evidence,
        "low_confidence": low_confidence,
        "evidence_strength": evidence_strength,
        "mean_experiences": (encounters / own_count) if own_count else 0.0,
        "mean_confidence": (confidence_sum / own_count) if own_count else 0.0,
        "links": links,
        "consolidations": int(getattr(agent, "_consolidation_count", 0)),
    }


async def main(
    cycles: int = 500,
    consolidate: bool = True,
    hold_energy: bool = False,
    report_path: str = "",
    sample_every: int = 50,
    seed: int | None = None,
    depth_ratio: float | None = None,
) -> int:
    if seed is not None:
        # Без фиксации зерна два прогона — разные случайные траектории
        # (ε-greedy, выбор темы), и разницу между ними нельзя приписать
        # консолидации. Зерно делает сравнение воспроизводимым.
        import random

        import numpy as np

        random.seed(seed)
        np.random.seed(seed)

    agent = DigitalBeing(name="MemoryMeasure")
    searcher = getattr(agent, "web_searcher", None)
    if searcher is not None:
        searcher.toggle(False)

    from config.simulation_config import LR_CONFIG

    if not consolidate:
        LR_CONFIG.CONSOLIDATION_ENABLED = False
    if depth_ratio is not None:
        # Доля исследований, идущих на углубление уже встреченной темы.
        # Флаг нужен, чтобы сравнивать значения на одной траектории, не
        # правя конфиг между прогонами.
        LR_CONFIG.EXPLORATION_DEPTH_RATIO = float(depth_ratio)

    # Имена родовых концепций фиксируем ДО первого действия: иначе
    # «своими» окажутся и те, что агент только что изучил.
    agent._birth_concept_names = set(agent.mental_models.concepts)

    bus = EventBus(max_queue_size=500, history_size=100)
    runner = AgentRunner(agent, bus, name="MemoryRunner")
    runner.set_speed("max")

    samples = [Sample(0, snapshot(agent))]
    actions = {}

    await runner.start()
    try:
        for step in range(1, cycles + 1):
            if hold_energy:
                agent.energy = 150.0
            else:
                runner.energy_policy.regenerate(5.0)
            await runner.step_once()

            chosen = (agent._last_arbitration or {}).get("action")
            if chosen:
                actions[chosen] = actions.get(chosen, 0) + 1

            if step % sample_every == 0 or step == cycles:
                samples.append(Sample(step, snapshot(agent)))
    finally:
        await runner.stop()

    final = samples[-1].snapshot
    first = samples[0].snapshot

    lines = []
    lines.append("=" * 72)
    lines.append(
        "Режим: "
        + ("сон осмысляет накопленное" if consolidate else "сон выключен")
        + (", энергия удерживается" if hold_energy else ", энергия как в жизни")
    )
    lines.append(f"Циклов: {cycles}")
    if seed is not None:
        lines.append(f"Зерно случайности: {seed}")
    lines.append(
        f"Доля углубления: {getattr(LR_CONFIG, 'EXPLORATION_DEPTH_RATIO', '?')}"
    )
    lines.append(f"Действия: {actions}")
    lines.append("Динамика памяти (только свои концепции, без родовых):")
    lines.extend(sample.line() for sample in samples)
    lines.append("Итог:")
    lines.append(
        f"  отвечаемых: {first['answerable']} → {final['answerable']} "
        f"({first['answerable_share']:.0%} → {final['answerable_share']:.0%})"
    )
    lines.append(
        f"  встречались дважды и более: {final['deep']} "
        f"({final['deep_share']:.0%} своих)"
    )
    lines.append(
        f"  встреч на концепцию: {final['mean_experiences']:.2f}"
    )
    lines.append(
        f"  без свидетельств: {final['no_evidence']}, "
        f"с низкой уверенностью: {final['low_confidence']}, "
        f"суммарная сила свидетельств: {final['evidence_strength']:.2f}"
    )
    lines.append(
        f"  отвечает из памяти: {first['definable']} → {final['definable']}"
    )
    lines.append(
        f"  с формулировкой: {first['defined']} → {final['defined']}"
    )
    lines.append(
        f"  средняя уверенность: {first['mean_confidence']:.3f} → "
        f"{final['mean_confidence']:.3f}"
    )
    lines.append(
        f"  связей: {first['links']} → {final['links']}, "
        f"консолидаций: {final['consolidations']}"
    )

    # Почему концепции НЕ отвечаемы: это важнее доли.
    model = agent.mental_models
    born = set(getattr(agent, "_birth_concept_names", set()) or set())
    reasons = {"мало встреч": 0, "нет формулировки": 0, "низкая уверенность": 0}
    for name, node in model.concepts.items():
        if name in born or model.can_answer_about(name):
            continue
        if len(node.experiences) < 2:
            reasons["мало встреч"] += 1
        elif len(str(node.definition_hypothesis or "")) <= 10:
            reasons["нет формулировки"] += 1
        else:
            reasons["низкая уверенность"] += 1
    lines.append(f"Почему не отвечаем: {reasons}")
    lines.append("=" * 72)

    text = "\n".join(lines)
    print(text)
    if report_path:
        with open(report_path, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        print(f"Отчёт: {report_path}")
    print(f"Данные: {_DATA_DIR}")
    return 0


if __name__ == "__main__":
    args = list(sys.argv[1:])
    hold = "--hold-energy" in args
    consolidate = "--no-consolidation" not in args
    report = ""
    if "--report" in args:
        index = args.index("--report")
        report = args[index + 1]
        del args[index:index + 2]
    sample_every = 50
    if "--sample-every" in args:
        index = args.index("--sample-every")
        sample_every = int(args[index + 1])
        del args[index:index + 2]
    seed = None
    if "--seed" in args:
        index = args.index("--seed")
        seed = int(args[index + 1])
        del args[index:index + 2]
    depth = None
    if "--depth" in args:
        index = args.index("--depth")
        depth = float(args[index + 1])
        del args[index:index + 2]
    args = [a for a in args if not a.startswith("--")]
    count = int(args[0]) if args else 500
    raise SystemExit(
        asyncio.run(
            main(
                count,
                consolidate=consolidate,
                hold_energy=hold,
                report_path=report,
                sample_every=sample_every,
                seed=seed,
                depth_ratio=depth,
            )
        )
    )
