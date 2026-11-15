"""Единый источник палитры, шрифтов и отступов для окна v1.

Стиль — «киберпанк»: графитовые поверхности, тонкие рамки и неоновые
акценты. Цвета описаны здесь один раз, чтобы их брали и окно, и карта жизни, и макет
(``tools/manual/render_life_map_mockup.py``). Не разбрасываем ``#hex`` по
виджетам: иначе палитра расползается и перестаёт быть единой.

Модуль чистый: только данные и маленькие функции, без Tk. Поэтому его
можно тестировать без экрана.
"""

from __future__ import annotations

import os

# --- Фон и поверхности: графит, а не чистый чёрный ---
BG_DEEP = "#07090C"
BG_CENTER = "#0B0E12"
SIDEBAR = "#0B0E12"
SURFACE = "#10141A"
BORDER = "#343C43"
EDGE = "#3A4650"
EDGE_ACTIVE = "#42E8FF"
GLOW_CYAN = "#123F47"
GLOW_VIOLET = "#332B52"
GLOW_AMBER = "#4A460B"
SELECTION = "#252A0C"
GRAPH_BG = "#0B1015"
GRID = "#15272E"
ORBIT = "#17333B"
ORBIT_VIOLET = "#27233A"

# --- Текст ---
TEXT = "#F3F1DF"
MUTED = "#9AA3AD"
DIMMED = "#65717B"

# --- Акценты киберпанк-макета ---
CYAN = "#42E8FF"
VIOLET = "#B49AFF"
GREEN = "#4ADE80"
AMBER = "#F2E600"
GREY = "#4B5563"
DANGER = "#FF5F56"

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
