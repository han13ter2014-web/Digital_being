"""main_tray.py — устаревшее имя точки входа.

Раньше это была отдельная программа со своим жизненным циклом: другой
цикл, другие пути, другая скорость (5 секунд на цикл против тысяч
циклов в секунду у консоли). Два файла — две разные жизни одного и
того же существа.

Теперь вход один — ``main.py``. Этот файл оставлен, чтобы не ломать
привычные команды и ярлыки:

    python main_tray.py                 → python main.py --ui tray
    python main_tray.py --headless      → python main.py --ui headless

Файл ничего не дублирует: он только переводит старые флаги в новые.
"""

import sys
import warnings

from main import main

_LEGACY_FLAGS = ("--headless", "--no-tray", "--no-chat", "--new", "--name")


def run() -> int:
    warnings.warn(
        "main_tray.py устарел: используйте `python main.py --ui tray`. "
        "Прежние флаги поддерживаются.",
        DeprecationWarning,
        stacklevel=2,
    )
    return main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(run())
