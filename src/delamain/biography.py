"""Непрерывность автобиографии между запусками процесса.

Маркер — обычный эпизод ``MemoryStore``, а не сообщение интерфейса. Журнал
запуска нужен только для доказуемой причины разрыва: отсутствие записи о
штатном завершении не превращается в выдуманное событие внутри разрыва.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional


def _memory(agent: Any) -> Any:
    subsystem = getattr(agent, "delamain", None)
    if subsystem is None:
        return None
    runtime = getattr(subsystem, "runtime", None)
    if runtime is None:
        ensure = getattr(subsystem, "_ensure_runtime", None)
        if not callable(ensure):
            return None
        runtime = ensure()
    return getattr(runtime, "memory", None)


def begin_biography_run(
    agent: Any, *, run_id: Optional[str] = None, started_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Открыть журнал нового запуска и при необходимости записать один разрыв."""
    memory = _memory(agent)
    actual_run_id = str(run_id or uuid.uuid4())
    if memory is None:
        return {"run_id": actual_run_id, "status": "unavailable", "marker_created": False}
    return memory.begin_biography_run(
        life_id=str(agent.life_id), run_id=actual_run_id, started_at=started_at,
    )


def record_graceful_shutdown(
    agent: Any, *, run_id: Optional[str], ended_at: Optional[str] = None,
) -> bool:
    """Записать только фактически выполненное штатное завершение."""
    if not run_id:
        return False
    memory = _memory(agent)
    if memory is None:
        return False
    return bool(memory.record_graceful_shutdown(
        life_id=str(agent.life_id), run_id=str(run_id), ended_at=ended_at,
    ))
