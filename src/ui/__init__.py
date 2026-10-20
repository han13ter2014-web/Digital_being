"""
UI-подсистемы Digital Being.

- tray.py              — pystray-иконка в системном трее (v2).
- chat_window.py       — tkinter-окно чата.
- notifier.py          — OS-уведомления (plyer).
- web_dashboard.py     — aiohttp веб-дашборд (Этап 3.1).
"""

from src.ui.web_dashboard import (
    WebDashboard,
    SharedState,
    AIOHTTP_AVAILABLE,
)

__all__ = [
    "WebDashboard",
    "SharedState",
    "AIOHTTP_AVAILABLE",
]