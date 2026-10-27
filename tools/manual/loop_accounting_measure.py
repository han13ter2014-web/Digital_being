"""Замер бухгалтерии петли: дают ли действия результат и честно ли он считается.

Вопрос, на который отвечает скрипт: сколько действий реально меняют мир и
не наказывает ли метрика за то, что агент дышит.

Три числа, которые важны:

* **доля результативности по продуктивным действиям** — то, что считается
  теперь: работа, обещающая прирост знания;
* **доля по всем действиям** — то, что считалось раньше: отдых, рефлексия
  и отказы попадали в знаменатель;
* **тупики** — какие действия агент перестал выбирать и почему (отказ тела
  или «выполнял, мир не менялся»).

Запуск (из корня проекта):

    python tools/manual/loop_accounting_measure.py [циклов] [флаги]

Флаги:
    --hold-energy       держать энергию на максимуме: измерять работу, а
                        не отдых
    --seed N            зафиксировать зерно случайности
    --report PATH       записать отчёт в UTF-8 (консоль Windows искажает
                        кириллицу)

Данные пишутся во временную папку и не трогают ``data/`` рабочей копии.
Сеть выключена: замер не должен зависеть от Википедии.
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Изоляция данных ДО импорта src.core.paths.
_DATA_DIR = tempfile.mkdtemp(prefix="db_accounting_measure_")
os.environ["DIGITAL_BEING_DATA_DIR"] = _DATA_DIR
os.environ.setdefault("DIGITAL_BEING_TEST_MODE", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from src.core.agent import DigitalBeing  # noqa: E402
from src.core.agent_runner import AgentRunner  # noqa: E402
from src.core.event_bus import EventBus  # noqa: E402
from src.core.maturity import assess  # noqa: E402


MAINTENANCE_ACTIONS = {
    "rest",
    "deep_rest",
    "reflect",
    "self_reflect",
    "communicate",
    "know_answer",
}


class Tally:
    """Счётчик выборов и исходов по типу действия.

    За один цикл агент действует дважды: сначала автономный тик (арбитр),
    потом ответ на стимул. ``_last_action_outcome`` хранит только второй,
    поэтому исходы берутся из истории петли и дочитываются по одному.
    """

    def __init__(self) -> None:
        self.chosen: dict[str, int] = {}
        self.with_effect: dict[str, int] = {}
        self._last_seen = None

    def drain(self, closer) -> None:
        """Дочитать новые исходы из истории петли."""
        history = getattr(closer, "_history", None) or []
        if not history:
            return
        new = []
        found = False
        for outcome in reversed(history):
            if outcome is self._last_seen:
                found = True
                break
            new.append(outcome)
        if not found and self._last_seen is not None:
            # Историю обрезали быстрее, чем мы её прочитали. Для ручного
            # замера это допустимо: считаем всё, что видно.
            new = list(history)
        self._last_seen = history[-1]
        for outcome in reversed(new):
            self.add(outcome.action, outcome.had_effect)

    def add(self, action: str, had_effect: bool) -> None:
        if not action:
            return
        self.chosen[action] = self.chosen.get(action, 0) + 1
        if had_effect:
            self.with_effect[action] = self.with_effect.get(action, 0) + 1

    def rows(self) -> list[tuple[str, int, int]]:
        return sorted(
            (
                (action, count, self.with_effect.get(action, 0))
                for action, count in self.chosen.items()
            ),
            key=lambda row: -row[1],
        )


async def main(
    cycles: int = 300,
    hold_energy: bool = False,
    seed: int | None = None,
    report_path: str = "",
) -> int:
    if seed is not None:
        random.seed(seed)
        try:
            import numpy as np

            np.random.seed(seed)
        except Exception:
            pass

    agent = DigitalBeing(name="AccountingMeasure")
    searcher = getattr(agent, "web_searcher", None)
    if searcher is not None:
        searcher.toggle(False)

    bus = EventBus(max_queue_size=500, history_size=100)
    runner = AgentRunner(agent, bus, name="AccountingRunner")
    runner.set_speed("max")
    runner.set_stimulus_mode("pool")

    tally = Tally()
    max_unanswered = 0

    await runner.start()
    try:
        for _ in range(cycles):
            if hold_energy:
                agent.energy = 150.0
            else:
                runner.energy_policy.regenerate(5.0)
            await runner.step_once()

            tally.drain(agent.loop_closer)
            unanswered = sum(
                1
                for q in agent.get_open_questions()
                if not q.get("answered")
            )
            max_unanswered = max(max_unanswered, unanswered)
    finally:
        await runner.stop()

    status = agent.loop_closer.status()
    productive_total = int(status.get("productive_total", 0) or 0)
    productive_effect = int(status.get("productive_effect_total", 0) or 0)
    total_actions = int(status.get("total_actions", 0) or 0)
    total_effect = int(status.get("total_with_effect", 0) or 0)
    new_ratio = (productive_effect / productive_total) if productive_total else 0.0
    old_ratio = (total_effect / total_actions) if total_actions else 0.0

    maintenance = sum(
        count
        for action, count, _ in tally.rows()
        if action in MAINTENANCE_ACTIONS
    )
    chosen_total = sum(tally.chosen.values())

    stuck = list(status.get("stuck_actions", []) or [])
    stuck_by_denial = [a for a in stuck if agent.loop_closer.denied_streak(a)]
    stuck_by_emptiness = [a for a in stuck if a not in stuck_by_denial]

    maturity = assess(agent)

    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(
        "Режим: "
        + ("энергия удерживается (измеряется работа)" if hold_energy
           else "энергия как в жизни (включая отдых)")
    )
    lines.append(f"Циклов: {cycles}")
    if seed is not None:
        lines.append(f"Зерно случайности: {seed}")
    lines.append("")
    lines.append(
        f"Действия за {chosen_total} наблюдений "
        "(два за цикл: автономный тик + ответ на стимул):"
    )
    for action, count, effects in tally.rows():
        share = effects / count if count else 0.0
        mark = "обслуживание" if action in MAINTENANCE_ACTIONS else ""
        lines.append(
            f"  {action:<24} {count:4d}  {effects:4d}  ({share:.0%}) {mark}"
        )
    lines.append("")
    lines.append("Доля результативности:")
    lines.append(
        f"  по продуктивным (как считается теперь): {new_ratio:.0%} "
        f"({productive_effect}/{productive_total})"
    )
    lines.append(
        f"  по всем действиям (как считалось раньше): {old_ratio:.0%} "
        f"({total_effect}/{total_actions})"
    )
    lines.append(
        f"  обслуживание: {maintenance} из {chosen_total} выборов "
        f"({(maintenance / chosen_total if chosen_total else 0.0):.0%})"
    )
    lines.append("")
    lines.append(
        f"Тупики: {len(stuck)} — {stuck if stuck else 'нет'}"
    )
    if stuck:
        lines.append(f"  по отказу тела: {stuck_by_denial or 'нет'}")
        lines.append(f"  по «нет эффекта»: {stuck_by_emptiness or 'нет'}")
    lines.append("")
    lines.append(f"Очередь вопросов: максимум неотвеченных за прогон {max_unanswered}")
    lines.append("")
    lines.append(maturity.describe())
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
    report = ""
    if "--report" in args:
        index = args.index("--report")
        report = args[index + 1]
        del args[index:index + 2]
    seed = None
    if "--seed" in args:
        index = args.index("--seed")
        seed = int(args[index + 1])
        del args[index:index + 2]
    args = [a for a in args if not a.startswith("--")]
    count = int(args[0]) if args else 300
    raise SystemExit(
        asyncio.run(
            main(count, hold_energy=hold, seed=seed, report_path=report)
        )
    )
