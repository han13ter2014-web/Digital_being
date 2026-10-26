"""Сводка отчётов memory_maturity_measure.py для проверки гипотезы глубины.

Запуск: python tools/manual/depth_sweep_summary.py КАТАЛОГ
Ожидает depth_<доля>_<зерно>.txt; отсутствующие метрики — ошибка, не ноль.
"""

import argparse
import re
from pathlib import Path
from statistics import mean


def parse_report(text: str) -> dict:
    def number(pattern: str, source: str = text) -> float:
        match = re.search(pattern, source)
        if match is None:
            raise ValueError(f"В отчёте нет метрики: {pattern}")
        return float(match.group(1))

    sample_lines = text.split("Итог:")[0].splitlines()
    if not sample_lines:
        raise ValueError("В отчёте нет срезов памяти")
    final_sample = sample_lines[-1]
    return {
        "depth": number(r"Доля углубления: ([0-9.]+)"),
        "seed": number(r"Зерно случайности: ([0-9]+)"),
        "own": number(r"своих +([0-9]+)", final_sample),
        "answerable": number(r"отвечаемых: [0-9]+ → ([0-9]+)"),
        "deep": number(r"дважды и более: ([0-9]+)"),
        "encounters": number(r"встреч на концепцию: ([0-9.]+)"),
        "confidence": number(r"средняя уверенность: [0-9.]+ → ([0-9.]+)"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    rows = []
    for path in sorted(args.directory.glob("depth_*_*.txt")):
        # Дополнительные диагностические отчёты не входят в сетку.
        if re.fullmatch(r"depth_[0-9.]+_[0-9]+[.]txt", path.name):
            rows.append(parse_report(path.read_text(encoding="utf-8")))
    if not rows:
        parser.error("Нет отчётов depth_<доля>_<зерно>.txt")
    groups = {}
    for row in rows:
        group = groups.setdefault(row["depth"], {})
        if row["seed"] in group:
            raise ValueError("Повторное зерно в одной группе")
        group[row["seed"]] = row
    seeds = set(next(iter(groups.values())))
    if any(set(group) != seeds for group in groups.values()):
        raise ValueError("Группы должны содержать одинаковые наборы зёрен")
    print("depth runs own answerable share deep encounters confidence")
    for depth, group in sorted(groups.items()):
        items = list(group.values())
        avg = lambda key: mean(item[key] for item in items)
        share = mean(item["answerable"] / item["own"] if item["own"] else 0.0 for item in items)
        print(f"{depth:.2f} {len(items)} {avg('own'):.1f} "
              f"{avg('answerable'):.1f} {share:.1%} {avg('deep'):.1f} "
              f"{avg('encounters'):.2f} {avg('confidence'):.3f}")
        print("  " + ", ".join(
            f"seed {seed:g}: {row['answerable']:g}/{row['own']:g}"
            for seed, row in sorted(group.items())
        ))


if __name__ == "__main__":
    main()
