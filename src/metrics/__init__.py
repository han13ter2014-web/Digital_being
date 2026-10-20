"""
Метрики и расширения Digital Being (Этап 3.6, 3.7, 3.8, 3.2).

- metrics_collector.py — MetricsCollector с time-series историей (3.6)
- i18n.py — менеджер локализаций (3.7)
- webhooks.py — Telegram/Discord интеграции (3.8)
- voice.py — TTS/STT (3.2)
"""

from src.metrics.metrics_collector import MetricsCollector, DEFAULT_CHANNELS
from src.metrics.i18n import I18n, get_i18n, set_language, t, reset_i18n
from src.metrics.webhooks import (
    Webhook, TelegramWebhook, DiscordWebhook,
    WebhookManager, create_default_manager,
)
from src.metrics.voice import (
    VoiceEngine, ConsoleVoiceEngine, PyttsxVoiceEngine,
    WhisperSTTEngine, VoiceRouter, create_default_router,
)

__all__ = [
    # Метрики (3.6)
    "MetricsCollector", "DEFAULT_CHANNELS",
    # i18n (3.7)
    "I18n", "get_i18n", "set_language", "t", "reset_i18n",
    # Webhooks (3.8)
    "Webhook", "TelegramWebhook", "DiscordWebhook",
    "WebhookManager", "create_default_manager",
    # Voice (3.2)
    "VoiceEngine", "ConsoleVoiceEngine", "PyttsxVoiceEngine",
    "WhisperSTTEngine", "VoiceRouter", "create_default_router",
]