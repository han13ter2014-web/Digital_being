"""Единый источник палитры, шрифтов и отступов для окна v1.

Стиль — «биолюминесцентный неон»: тёмная бездна и светящиеся узлы. Цвета
описаны здесь один раз, чтобы их брали и окно, и карта жизни, и макет
(``tools/manual/render_life_map_mockup.py``). Не разбрасываем ``#hex`` по
виджетам: иначе палитра расползается и перестаёт быть единой.

Модуль чистый: только данные и маленькие функции, без Tk. Поэтому его
можно тестировать без экрана.
"""

from __future__ import annotations

import os

# --- Фон и поверхности ---
BG_DEEP = "#0A0C11"
BG_CENTER = "#141821"
SIDEBAR = "#11151D"
SURFACE = "#141821"
BORDER = "#232A38"
EDGE = "#2E4057"
EDGE_ACTIVE = "#5B8FA8"
GLOW_CYAN = "#164A59"
GLOW_VIOLET = "#40326B"
GLOW_AMBER = "#604B1D"

# --- Текст ---
TEXT = "#E6E9EF"
MUTED = "#8B93A7"
DIMMED = "#5B6274"

# --- Акценты ---
CYAN = "#22D3EE"
VIOLET = "#A78BFA"
GREEN = "#4ADE80"
AMBER = "#FBBF24"
GREY = "#4B5563"
DANGER = "#F87171"

# Типы узлов карты жизни. Цвет + форма вместе: карта должна читаться и при
# дальтонизме, поэтому форма дублирует цвет.
NODE_COLORS = {
    "concept": CYAN,
    "intention": VIOLET,
    "value": GREEN,
    "activity": AMBER,
    "topic": CYAN,
    "forgotten": GREY,
}

NODE_SHAPES = {
    "concept": "circle",
    "intention": "diamond",
    "value": "hexagon",
    "activity": "ring",
    "topic": "dot",
    "forgotten": "outline",
}

# Отступы (шаг сетки). Держим небольшим набором, чтобы вёрстка была ровной.
SPACING = {"xs": 4, "sm": 8, "md": 14, "lg": 20}


def node_color(kind: str) -> str:
    """Цвет узла по типу; неизвестный тип — приглушённый серый."""
    return NODE_COLORS.get(str(kind), GREY)


def node_shape(kind: str) -> str:
    """Форма узла по типу; неизвестный тип — тихий контур."""
    return NODE_SHAPES.get(str(kind), "outline")


def font_family() -> str:
    """Семейство основного шрифта для текущей ОС."""
    return "Segoe UI" if os.name == "nt" else "Helvetica"


def mono_family() -> str:
    """Моноширинный шрифт — только для технических подробностей."""
    return "Consolas" if os.name == "nt" else "Menlo"
