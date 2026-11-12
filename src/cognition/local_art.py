"""Рисунок как отпечаток внутреннего состояния — артефакт, не декларация чувств.

Картина — это SVG-файл в той же песочнице, что и текстовые черновики.
Палитра рождается из доминирующей эмоции в момент начала работы и
хранится в работе: настроение картины не меняется задним числом, новое
настроение — новая картина. Редакция добавляет формы поверх прежних:
seed не содержит номера редакции, поэтому сцена воспроизводима, а
каждая редакция достраивает её, а не переписывает.

Дисциплина та же, что у черновиков: лимит редакций, «оставить работу»
только с причиной, чужие правки файла не затираются (проверка sha256).
"""

import hashlib
import random
from xml.sax.saxutils import escape
from uuid import uuid4

from src.core.activity_workspace import ActivityWorkspace


ART_LIMIT = 8  # редакций одной работы
MAX_ART = 32  # рисунков в папке (своя квота, отдельно от черновиков)

WIDTH, HEIGHT = 240, 160

# Палитра = (фон, [краски]). Эмоция задаёт колорит, не содержание.
PALETTES = {
    "fear": ("#0f0f1a", ["#1a1a2e", "#16213e", "#533483", "#7b2d8b"]),
    "sadness": ("#1c2733", ["#355070", "#6d597a", "#8e9aaf", "#b8bedd"]),
    "joy": ("#fff3d6", ["#ff9f45", "#ffd93d", "#ff6b6b", "#f9a826"]),
    "calm": ("#f2f0e6", ["#a3b18a", "#dad7cd", "#588157", "#3a5a40"]),
}

DEFAULT_THEMES = ("тишина", "дорога", "свет", "след", "вопрос", "берег")


def validate_art(state):
    if not isinstance(state, dict):
        raise ValueError("local_art: нужен словарь")
    identifier = state.get("id")
    if (
        not isinstance(identifier, str)
        or len(identifier) != 32
        or any(ch not in "0123456789abcdef" for ch in identifier)
    ):
        raise ValueError("local_art.id")
    if (
        type(state.get("revision")) is not int
        or not 1 <= state["revision"] <= ART_LIMIT
    ):
        raise ValueError("local_art.revision")
    if state.get("status", "active") not in {"active", "left"}:
        raise ValueError("local_art.status")
    if state.get("status") == "left" and (
        not isinstance(state.get("leave_reason"), str)
        or not state["leave_reason"].strip()
    ):
        raise ValueError("local_art.leave_reason")
    if state.get("palette") not in PALETTES:
        raise ValueError("local_art.palette")
    for key in ("theme", "sha256"):
        if not isinstance(state.get(key), str) or not state[key]:
            raise ValueError(f"local_art.{key}")


def leave_art(state, reason):
    validate_art(state)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Нужна причина оставить работу")
    if state.get("status") == "left":
        return dict(state)
    return {**state, "status": "left", "leave_reason": reason.strip()[:1000]}


def art_available(state=None, workspace=None):
    """Можно ли рисовать: активная работа с запасом редакций или место в папке."""
    if state is not None:
        validate_art(state)
        if state.get("status", "active") == "active" and state["revision"] < ART_LIMIT:
            return True
    workspace = workspace or ActivityWorkspace()
    svg = workspace.list("*.svg")
    return len(svg) < MAX_ART


def _scene_shapes(theme, palette, count):
    """Детерминированная сцена: seed не содержит редакцию, поэтому
    редакция N повторяет сцену N-1 и добавляет свои формы в конец."""
    seed = hashlib.sha256(f"{theme}|{palette}".encode("utf-8")).hexdigest()
    rng = random.Random(seed)
    _bg, colors = PALETTES[palette]
    shapes = []
    for index in range(count):
        kind = rng.choice(("circle", "rect", "line"))
        color = colors[rng.randrange(len(colors))]
        opacity = round(rng.uniform(0.35, 0.9), 2)
        if kind == "circle":
            shapes.append(
                f'<circle cx="{rng.randrange(10, WIDTH - 10)}" '
                f'cy="{rng.randrange(10, HEIGHT - 10)}" '
                f'r="{rng.randrange(4, 26)}" fill="{color}" '
                f'fill-opacity="{opacity}" />'
            )
        elif kind == "rect":
            shapes.append(
                f'<rect x="{rng.randrange(0, WIDTH - 30)}" '
                f'y="{rng.randrange(0, HEIGHT - 20)}" '
                f'width="{rng.randrange(8, 30)}" height="{rng.randrange(6, 20)}" '
                f'fill="{color}" fill-opacity="{opacity}" />'
            )
        else:
            shapes.append(
                f'<line x1="{rng.randrange(0, WIDTH)}" y1="{rng.randrange(0, HEIGHT)}" '
                f'x2="{rng.randrange(0, WIDTH)}" y2="{rng.randrange(0, HEIGHT)}" '
                f'stroke="{color}" stroke-opacity="{opacity}" '
                f'stroke-width="{rng.randrange(1, 4)}" />'
            )
    return shapes


def render_svg(theme, palette, richness, revision):
    """Собрать SVG: фон палитры + формы. richness — густота мазков."""
    richness = max(1, min(9, int(richness)))
    count = richness + 2 * (revision - 1)
    background, _colors = PALETTES[palette]
    shapes = _scene_shapes(theme, palette, count)
    title = escape(theme)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" '
        f'height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        f"<title>{title} — редакция {revision}</title>",
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{background}" />',
        *shapes,
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


def art_thumbnail(state):
    """ASCII-миниатюра работы для текстового ответа (24×8).

    Тени той же детерминированной сцены: формы оставляют след на сетке,
    глубина следа — от порядка формы.
    """
    validate_art(state)
    seed = hashlib.sha256(
        f"{state['theme']}|{state['palette']}".encode("utf-8")
    ).hexdigest()
    rng = random.Random(seed)
    count = 5 + 2 * (state["revision"] - 1)
    grid = [[" "] * 24 for _ in range(8)]
    marks = ".:+*#"
    for index in range(min(count, 30)):
        x = rng.randrange(24)
        y = rng.randrange(8)
        mark = marks[min(len(marks) - 1, index // 6)]
        if grid[y][x] == " " or mark > grid[y][x]:
            grid[y][x] = mark
    return "\n".join("".join(row) for row in grid)


def art_step(state=None, *, palette="calm", theme=None, richness=5, workspace=None):
    """Одна редакция рисунка: новая работа или новый слой поверх."""
    workspace = workspace or ActivityWorkspace()
    sandbox = workspace.sandbox
    if state is not None:
        validate_art(state)
    if state is None or state["revision"] >= ART_LIMIT or state.get("status") == "left":
        if len(workspace.list("*.svg")) >= MAX_ART:
            raise ValueError("Папка рисунков заполнена; новые файлы не создаются")
        identifier = uuid4().hex
        if palette not in PALETTES:
            raise ValueError(f"local_art: неизвестная палитра {palette!r}")
        theme = (theme or "").strip() or random.choice(DEFAULT_THEMES)
        revision = 1
    else:
        identifier, theme, palette = state["id"], state["theme"], state["palette"]
        # Прежняя редакция может остаться в общем корне до перехода (5C):
        # копируем её в каталог жизни, оригинал не трогаем.
        workspace.ensure_from_legacy(f"{identifier}.svg")
        previous = sandbox.read_text(f"{identifier}.svg")
        if hashlib.sha256(previous.encode("utf-8")).hexdigest() != state["sha256"]:
            raise ValueError(
                "Рисунок изменён извне; автоматическая перезапись отменена"
            )
        revision = state["revision"] + 1
    content = render_svg(theme, palette, richness, revision)
    workspace.write(
        f"{identifier}.svg",
        content,
        overwrite=revision > 1,
        kind="creative",
        metadata={"activity": "art", "work_id": identifier, "revision": revision},
    )
    if sandbox.read_text(f"{identifier}.svg") != content:
        raise IOError("Не совпало обратное чтение рисунка")
    return {
        "id": identifier,
        "theme": theme,
        "palette": palette,
        "revision": revision,
        "status": "active",
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }
