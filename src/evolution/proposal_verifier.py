"""proposal_verifier — проба: изолированная проверка предложения до подачи.

«Эволюция-1» (2026-11-03). Перед тем как предложить изменение человеку,
существо честно проверяет его в песочнице: отдельный процесс Python с
временной папкой данных (DIGITAL_BEING_DATA_DIR), где конфигурация
патчится, создаётся пробный агент и проживает несколько тактов эволюции.
Рабочие данные и живой стенд проба не касается.

Вердикт честный: «пройдена» — только если рабочий процесс отработал без
ошибок и напечатал VERIFY_OK. Любой сбой (исключение, таймаут, неизвестный
атрибут) — «не пройдена», и это тоже записывается в предложение.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from typing import Dict

from src.core.paths import DATA_DIR_ENV, project_root

VERIFY_CYCLES = 5
VERIFY_TIMEOUT_SEC = 120
SPEC_ENV = "EVOLVE_VERIFY_SPEC"
LOG_TAIL_CHARS = 800


def verify_config_change(
    attr: str,
    value: object,
    cycles: int = VERIFY_CYCLES,
    timeout: int = VERIFY_TIMEOUT_SEC,
) -> Dict:
    """Проверяет изменение конфигурации в изолированном подпроцессе.

    Возвращает словарь с честным исходом пробы:
    ``ran`` — проба реально запускалась; ``passed`` — рабочий процесс
    завершился без ошибок; ``cycles`` — сколько тактов прожито;
    ``log_tail`` — хвост вывода для человека.
    """
    spec = {"attr": attr, "value": value, "cycles": cycles}
    tmp = tempfile.mkdtemp(prefix="evolve_verify_")
    env = dict(os.environ)
    env[DATA_DIR_ENV] = tmp
    env[SPEC_ENV] = json.dumps(spec, ensure_ascii=False)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "src.evolution._verify_worker"],
            cwd=project_root(),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "ran": True,
            "passed": False,
            "cycles": cycles,
            "log_tail": f"проба не уложилась в {timeout} с",
        }
    except OSError as exc:
        return {
            "ran": False,
            "passed": False,
            "cycles": 0,
            "log_tail": f"пробу не удалось запустить: {exc}",
        }

    tail = (proc.stdout or "") + (proc.stderr or "")
    return {
        "ran": True,
        "passed": proc.returncode == 0 and "VERIFY_OK" in (proc.stdout or ""),
        "cycles": cycles,
        "log_tail": tail[-LOG_TAIL_CHARS:].strip(),
    }
