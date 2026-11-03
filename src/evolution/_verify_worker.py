"""_verify_worker — рабочий процесс пробы предложения.

Запускается ТОЛЬКО из `proposal_verifier.verify_config_change`:
применяет патч конфигурации (из переменной окружения EVOLVE_VERIFY_SPEC),
создаёт пробного агента во временной папке данных (DIGITAL_BEING_DATA_DIR
уже выставлена вызывающим) и проживает несколько тактов эволюции.

Успех — печать VERIFY_OK и нулевой код выхода. Любая ошибка — ненулевой
код; верификатор прочитает хвост вывода и честно запишет «не пройдена».
"""

from __future__ import annotations

import json
import os
import sys
import traceback


def main() -> int:
    raw = os.environ.get("EVOLVE_VERIFY_SPEC")
    if not raw:
        print("нет спецификации пробы", file=sys.stderr)
        return 2
    try:
        spec = json.loads(raw)
        attr = str(spec["attr"])
        value = spec["value"]
        cycles = int(spec.get("cycles", 5))
    except (KeyError, TypeError, ValueError) as exc:
        print(f"битая спецификация пробы: {exc}", file=sys.stderr)
        return 2

    from config.simulation_config import LR_CONFIG

    if not hasattr(LR_CONFIG, attr):
        print(f"неизвестный рычаг: {attr}", file=sys.stderr)
        return 2
    setattr(LR_CONFIG, attr, value)

    try:
        from src.core.agent import DigitalBeing

        agent = DigitalBeing(name="__probe__")
        for _ in range(cycles):
            agent.evolve()
    except Exception:
        traceback.print_exc()
        return 1

    print("VERIFY_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
