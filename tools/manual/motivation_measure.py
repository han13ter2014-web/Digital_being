"""Замер мотивации через настоящий раннер.

Скрипт отвечает на вопрос «кто на самом деле выбирает действия»:
сколько кандидатов пришло от потребностей, сколько от драйвов, что
выбрал арбитр и чем это кончилось. Нужен, чтобы сравнивать поведение
до/после правок мотивации на одинаковых условиях.

Запуск (из корня проекта):

    python tools/manual/motivation_measure.py [циклов] [флаги]

Флаги:
    --hold-energy          держать энергию на максимуме: изолировать
                           мотивацию от телесной экономики;
    --hungry               начать с неудовлетворённых любопытства и связи;
    --exhausted            начать с нулевой энергии и высокой усталости;
    --seconds-per-cycle N  сколько «живых» секунд проживает цикл
                           (по умолчанию 5 — как в режиме live).

Данные пишутся во временную папку и не трогают ``data/`` рабочей копии.
Сеть отключается: замер не должен зависеть от Википедии.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from collections import Counter

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Изоляция данных ДО импорта src.core.paths.
_DATA_DIR = tempfile.mkdtemp(prefix="db_motivation_measure_")
os.environ["DIGITAL_BEING_DATA_DIR"] = _DATA_DIR
os.environ.setdefault("DIGITAL_BEING_TEST_MODE", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from src.core.agent import DigitalBeing  # noqa: E402
from src.core.agent_runner import AgentRunner  # noqa: E402
from src.core.event_bus import EventBus  # noqa: E402


class Measurement:
    def __init__(self) -> None:
        self.cycles = 0
        self.candidate_sources: Counter = Counter()
        self.candidate_actions: Counter = Counter()
        self.chosen: Counter = Counter()
        self.chosen_when_pressing: Counter = Counter()
        self.chosen_when_curiosity_hungry: Counter = Counter()
        self.chosen_when_can_ask: Counter = Counter()
        self.effects: Counter = Counter()
        self.pressing: Counter = Counter()
        self.active_drives: Counter = Counter()
        self.max_drive: Counter = Counter()
        self.need_levels_sum: Counter = Counter()
        self.goals_generated = 0
        self.no_candidates = 0
        self.asks_queued = 0
        self.asks_failed = 0
        self.ask_texts: Counter = Counter()
        self.denials: Counter = Counter()
        self.denied_actions: Counter = Counter()
        self.first_choices: list = []
        self.energy_curve: list = []
        self.fatigue_curve: list = []
        self.atp_curve: list = []
        self.rest_chosen = 0
        self.rest_when_tired = 0
        self.rest_after_work = 0
        self.work_after_rest = 0
        self._last_was_rest = None
        self.consolidations = 0
        self.definitions_formed = 0
        self.links_strengthened = 0
        self.definitions_refined = 0

    def observe(self, agent) -> None:
        self.cycles += 1
        motivation = agent.motivation_system
        status = motivation.get_status()

        self.pressing[len(status["pressing_needs"])] += 1
        self.active_drives[len(status["active_drives"])] += 1
        for name, need in status["needs"].items():
            self.need_levels_sum[name] += need["current_level"]

        strongest = max(
            motivation.drives.values(),
            key=lambda d: d.current_level,
            default=None,
        )
        if strongest is not None:
            self.max_drive[strongest.name] += 1

        chosen = (agent._last_arbitration or {}).get("action")
        if chosen:
            self.chosen[chosen] += 1
            if len(self.first_choices) < 12:
                self.first_choices.append(chosen)
            if status["pressing_needs"]:
                self.chosen_when_pressing[chosen] += 1
            curiosity = status["needs"]["curiosity"]
            if curiosity["pressing"]:
                self.chosen_when_curiosity_hungry[chosen] += 1
                if agent._is_action_available("ask_question"):
                    self.chosen_when_can_ask[chosen] += 1
        else:
            self.chosen["<нет выбора>"] += 1

        outcome = getattr(agent, "_last_action_outcome", None)
        if outcome is None:
            self.effects["<нет исхода>"] += 1
        else:
            self.effects["есть эффект" if outcome.had_effect else "без эффекта"] += 1

        if len(self.energy_curve) < 40:
            self.energy_curve.append(round(float(agent.energy), 1))

        intero = getattr(agent, "interoception", None)
        if intero is not None:
            state = intero.get_status()
            fatigue = float(state.get("fatigue", 0.0) or 0.0)
            if len(self.fatigue_curve) < 60:
                self.fatigue_curve.append(round(fatigue, 2))
                self.atp_curve.append(round(float(state.get("atp", 0.0)), 1))
            is_rest = chosen in ("rest", "deep_rest")
            if is_rest:
                self.rest_chosen += 1
                if fatigue >= 0.6:
                    self.rest_when_tired += 1
            if self._last_was_rest is not None:
                if is_rest and not self._last_was_rest:
                    self.rest_after_work += 1
                elif not is_rest and self._last_was_rest:
                    self.work_after_rest += 1
            self._last_was_rest = is_rest

        count = int(getattr(agent, "_consolidation_count", 0))
        if count > self.consolidations:
            self.consolidations = count
            last = getattr(agent, "_last_consolidation", {}) or {}
            self.definitions_formed += int(last.get("definitions", 0) or 0)
            self.links_strengthened += int(last.get("links", 0) or 0)
            self.definitions_refined += int(last.get("refined", 0) or 0)

    def _print_graph(self, agent) -> None:
        """Что осталось в памяти: формулировки, связи, уверенность."""
        print = self._emit  # noqa: A001  (строки должны попасть в отчёт)
        concepts = getattr(getattr(agent, "mental_models", None), "concepts", {}) or {}
        total = len(concepts)
        defined = sum(
            1
            for node in concepts.values()
            if len(str(getattr(node, "definition_hypothesis", "") or "")) > 10
        )
        weights = [
            float(weight)
            for node in concepts.values()
            for weight in (getattr(node, "connections", {}) or {}).values()
        ]
        strong = sum(1 for weight in weights if weight >= 0.3)
        mean_weight = sum(weights) / len(weights) if weights else 0.0
        experiences = sum(
            len(getattr(node, "experiences", []) or []) for node in concepts.values()
        )
        confidence = (
            sum(float(getattr(node, "confidence", 0.0) or 0.0) for node in concepts.values())
            / total
            if total
            else 0.0
        )
        print(
            f"Память: концепций {total}, с формулировкой {defined}, "
            f"опыта {experiences}"
        )
        print(
            f"Связи: всего {len(weights)}, сильных (≥0.3) {strong}, "
            f"средний вес {mean_weight:.3f}; средняя уверенность {confidence:.3f}"
        )
        print(
            f"Консолидаций: {self.consolidations} "
            f"(формулировок +{self.definitions_formed}, "
            f"уточнений {self.definitions_refined}, "
            f"связей +{self.links_strengthened})"
        )
        refined_examples = [
            f"{name}: {node.definition_hypothesis}"
            for name, node in concepts.items()
            if str(getattr(node, "definition_hypothesis", "")).startswith("По опыту")
            and "связано с" in str(node.definition_hypothesis)
        ][:3]
        for example in refined_examples:
            print(f"  {example[:160]}")
    def report(self, agent, candidate_samples) -> None:
        from src.core.motivation import unified_motivation as um

        self._lines = []
        print = self._emit  # noqa: A001  (собираем отчёт для файла)
        print("=" * 68)
        print(f"Модуль: {um.__file__} (pressure={hasattr(um.Need, 'pressure')})")
        print(f"Циклов: {self.cycles}")
        print(f"Типы действий (act): {dict(agent._action_type_counts)}")
        print(f"Выбрано арбитром: {dict(self.chosen.most_common())}")
        print(f"Выбрано при нажатой потребности: {dict(self.chosen_when_pressing.most_common())}")
        print(f"Выбрано при голодном любопытстве: {dict(self.chosen_when_curiosity_hungry.most_common())}")
        print(f"Выбрано, когда вопрос ВОЗМОЖЕН: {dict(self.chosen_when_can_ask.most_common())}")
        print(f"Исходы действий: {dict(self.effects)}")
        print(f"Нажатых потребностей за цикл: {dict(sorted(self.pressing.items()))}")
        print(f"Активных драйвов за цикл: {dict(sorted(self.active_drives.items()))}")
        print(f"Сильнейший драйв за цикл: {dict(self.max_drive.most_common())}")
        print(f"Кандидаты по источникам: {dict(self.candidate_sources)}")
        print(f"Кандидаты по действиям: {dict(self.candidate_actions.most_common(12))}")
        print(f"Сгенерировано целей: {self.goals_generated}")
        print(f"Циклов без кандидатов: {self.no_candidates}")
        print(
            f"Вопросов: поставлено в очередь {self.asks_queued}, "
            f"не удалось {self.asks_failed}"
        )
        print(f"Результаты вопросов: {dict(self.ask_texts.most_common(5))}")
        print(f"Отказы до выполнения: {dict(self.denials)} по действиям {dict(self.denied_actions.most_common(6))}")
        print(f"Первые выборы: {self.first_choices}")
        print(f"Энергия по циклам: {self.energy_curve}")
        print(f"Усталость по циклам: {self.fatigue_curve}")
        print(f"АТФ по циклам: {self.atp_curve}")
        print(
            f"Отдых выбран {self.rest_chosen} раз "
            f"(из них при усталости ≥0.6: {self.rest_when_tired}); "
            f"работа→отдых {self.rest_after_work}, отдых→работа {self.work_after_rest}"
        )
        self._print_graph(agent)
        if self.cycles:
            print("Средний уровень потребностей:")
            for name, total in sorted(self.need_levels_sum.items()):
                print(f"  {name:12s} {total / self.cycles:.3f}")
        print("Примеры кандидатов (последние 3 цикла):")
        for sample in candidate_samples[-3:]:
            print(f"  {sample}")
        print("=" * 68)

    def _emit(self, text: str = "") -> None:
        """Напечатать и запомнить строку отчёта (для записи в файл)."""
        if not hasattr(self, "_lines"):
            self._lines = []
        self._lines.append(str(text))
        print(text)

    def write_report(self, path: str) -> None:
        """Записать отчёт в UTF-8: консоль Windows искажает кириллицу."""
        lines = getattr(self, "_lines", [])
        if not lines:
            return
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")


async def main(
    cycles: int = 200,
    hold_energy: bool = False,
    seconds_per_cycle: float = 5.0,
    hungry: bool = False,
    exhausted: bool = False,
    report_path: str = "",
    consolidate: bool = True,
) -> int:
    agent = DigitalBeing(name="MotivationMeasure")
    # Замер без сети: поиск иначе ждёт rate-limit и искажает картину.
    searcher = getattr(agent, "web_searcher", None)
    if searcher is not None:
        searcher.toggle(False)

    if not consolidate:
        # Контрольная группа: тот же код, но сон не осмысляет накопленное.
        # Нужен, чтобы отделить вклад консолидации от вклада работы.
        from config.simulation_config import LR_CONFIG

        LR_CONFIG.CONSOLIDATION_ENABLED = False

    if hungry:
        # Сценарий «голодный агент»: любопытство и связь не удовлетворены
        # с самого начала. Нужен, чтобы увидеть выбор, а не ждать 20
        # тиков естественного затухания.
        for need_name in ("curiosity", "connection"):
            agent.motivation_system.needs[need_name].current_level = 0.05

    if exhausted:
        # Сценарий «тело на нуле»: ровно то состояние, в котором агент
        # раньше застревал навсегда — энергия 0, каждое действие
        # отклоняется, а отдых сам стоит энергии.
        agent.energy = 0.0
        agent.interoception.state.fatigue = 0.8
        agent.interoception.state.atp = 0.5

    bus = EventBus(max_queue_size=500, history_size=100)
    runner = AgentRunner(agent, bus, name="MeasureRunner")
    runner.set_speed("max")

    measurement = Measurement()
    samples = []

    original_candidates = agent.motivation_system.get_action_candidates

    def observed_candidates(context=None):
        result = original_candidates(context)
        measurement.candidate_sources.update(c.get("source", "?") for c in result)
        measurement.candidate_actions.update(c.get("action", "?") for c in result)
        for candidate in result:
            kind = candidate.get("type")
            if kind:
                measurement.candidate_sources[kind] += 1
        if not result:
            measurement.no_candidates += 1
        samples.append(
            [
                (c.get("action"), round(float(c.get("strength", 0)), 2),
                 c.get("type") or c.get("source"))
                for c in result
            ]
        )
        return result

    agent.motivation_system.get_action_candidates = observed_candidates

    # Считаем, чем на самом деле закончились вопросы: выбрано действие
    # «ask_question» и задан вопрос — разные вещи.
    original_ask_handler = getattr(agent, "_act_ask_user", None)
    if original_ask_handler is not None:
        def observed_ask():
            result = original_ask_handler() or {}
            text = str(result.get("text") or "")
            measurement.ask_texts[text[:60]] += 1
            if "ЗАПРОС" in text or "спросил человека" in text:
                measurement.asks_queued += 1
            else:
                measurement.asks_failed += 1
            return result

        agent._act_ask_user = observed_ask

    # Отказы (усталость/бюджет) считаем отдельно: выбранное действие и
    # выполненное действие — разные вещи.
    import src.core.agent as agent_module

    original_denied = agent_module.record_denied_outcome

    def observed_denied(obj, action_type, world_before, reason):
        measurement.denials[reason] += 1
        measurement.denied_actions[action_type] += 1
        return original_denied(obj, action_type, world_before, reason)

    agent_module.record_denied_outcome = observed_denied

    await runner.start()
    try:
        for _ in range(cycles):
            # В реальной жизни энергия восстанавливается по стенным
            # часам, а замер идёт в сотни раз быстрее. Без поправки
            # вторая половина прогона — это не мотивация, а голодный
            # отказ: act() не доходит до обработчиков. Поэтому каждый
            # цикл «проживает» те же 5 секунд, что и в режиме live.
            if hold_energy:
                agent.energy = 150
            else:
                runner.energy_policy.regenerate(seconds_per_cycle)
            goals_before = len(agent.motivation_system.goal_history)
            await runner.step_once()
            measurement.goals_generated += (
                len(agent.motivation_system.goal_history) - goals_before
            )
            measurement.observe(agent)
    finally:
        await runner.stop()

    measurement.report(agent, samples)
    print(f"Режим энергии: {'удерживается' if hold_energy else 'как в жизни'}")
    if report_path:
        measurement.write_report(report_path)
        print(f"Отчёт: {report_path}")
    print(f"Данные: {_DATA_DIR}")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    hold = "--hold-energy" in args
    hungry = "--hungry" in args
    exhausted = "--exhausted" in args
    consolidate = "--no-consolidation" not in args
    report = ""
    if "--report" in args:
        index = args.index("--report")
        report = args[index + 1]
        del args[index:index + 2]
    seconds = 5.0
    if "--seconds-per-cycle" in args:
        index = args.index("--seconds-per-cycle")
        seconds = float(args[index + 1])
        del args[index:index + 2]
    args = [a for a in args if not a.startswith("--")]
    count = int(args[0]) if args else 200
    raise SystemExit(
        asyncio.run(
            main(
                count,
                hold_energy=hold,
                seconds_per_cycle=seconds,
                hungry=hungry,
                exhausted=exhausted,
                report_path=report,
                consolidate=consolidate,
            )
        )
    )
