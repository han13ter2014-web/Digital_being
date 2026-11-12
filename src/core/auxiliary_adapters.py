"""Per-instance метрики и разрешённые владельцем внешние адаптеры."""

from __future__ import annotations

import os
from typing import Dict

from src.cognition.agent_cooperation import AgentCooperationHub
from src.core.buffered_logger import get_logger
from src.metrics.i18n import I18n
from src.metrics.metrics_collector import MetricsCollector
from src.metrics.voice import create_default_router
from src.metrics.webhooks import create_default_manager


def initialize_auxiliary_adapters(agent) -> None:
    agent.metrics = MetricsCollector(agent_name=agent.name, persist_dir=None)
    agent.cooperation_hub = AgentCooperationHub()
    agent.cooperation_hub.register_agent(agent)
    # Голос разрешён владельцем. Реальные TTS/STT используются, если их
    # зависимости установлены; console остаётся детерминированным fallback.
    # Тесты не инициализируют аудиоустройства и не загружают модели.
    test_mode = os.environ.get("DIGITAL_BEING_TEST_MODE") == "1"
    agent.voice_router = create_default_router(
        enabled=True,
        allow_pyttsx3=not test_mode,
        allow_whisper=not test_mode,
    )
    # Worker нужен только при реально настроенных Telegram/Discord endpoint-ах.
    agent.webhooks = create_default_manager()
    if agent.webhooks.list_webhooks():
        agent.webhooks.start()
    agent.i18n = I18n()


def tick_auxiliary_adapters(agent, cycle: int) -> Dict:
    hub = getattr(agent, "cooperation_hub", None)
    if hub is None:
        return {}
    try:
        return {"cooperation": hub.tick(agent.life_id)}
    except Exception as exc:
        get_logger().log(f"[COOPERATION] tick error: {exc}")
        return {"cooperation": {"error": str(exc)}}


def auxiliary_status(agent) -> Dict:
    metrics = getattr(agent, "metrics", None)
    voice = getattr(agent, "voice_router", None)
    webhooks = getattr(agent, "webhooks", None)
    i18n = getattr(agent, "i18n", None)
    hub = getattr(agent, "cooperation_hub", None)
    return {
        "metrics": {
            "mode": "ephemeral",
            "channels": metrics.list_channels() if metrics is not None else [],
        },
        "cooperation": (
            hub.get_agent_statistics(agent.life_id) if hub is not None else {}
        ),
        "voice": voice.status() if voice is not None else {},
        "webhooks": webhooks.status() if webhooks is not None else {},
        "i18n": {
            "language": i18n.get_language() if i18n is not None else None,
            "loaded_languages": i18n.list_languages() if i18n is not None else [],
        },
    }


def capture_cooperation(agent) -> Dict:
    hub = getattr(agent, "cooperation_hub", None)
    return hub.to_checkpoint() if hub is not None else {}


def restore_cooperation(agent, staged: AgentCooperationHub) -> None:
    agent.cooperation_hub = staged
    life_id = getattr(agent, "life_id", None)
    # Старые минимальные checkpoint-объекты могут не иметь identity. Их
    # состояние восстанавливается локально, но в кооперацию они не входят.
    if isinstance(life_id, str) and life_id.strip():
        staged.register_agent(agent)


__all__ = [
    "initialize_auxiliary_adapters", "tick_auxiliary_adapters",
    "auxiliary_status", "capture_cooperation", "restore_cooperation",
]
