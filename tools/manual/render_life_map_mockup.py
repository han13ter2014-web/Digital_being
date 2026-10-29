"""Макет карты жизни: рисуем тем же способом, что и настоящий Canvas-граф.

Это не продукт, а превью визуального языка: палитра «биолюминесцентный
неон», типы узлов (цвет + форма), свечение активного узла, карточка деталей.
Запуск: python tools/manual/render_life_map_mockup.py
"""

from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1600, 900

BG_CENTER = (20, 24, 33)
BG_EDGE = (10, 12, 17)
SIDEBAR = (17, 21, 29)
SURFACE = (20, 24, 33)
TEXT = (230, 233, 239)
MUTED = (139, 147, 167)
CYAN = (34, 211, 238)
VIOLET = (167, 139, 250)
GREEN = (74, 222, 128)
AMBER = (251, 191, 36)
GREY = (75, 85, 99)

FONT_DIR = r"C:\Windows\Fonts"


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(f"{FONT_DIR}\\{name}", size)
    except OSError:
        return ImageFont.load_default()


REG = lambda s: _font("segoeui.ttf", s)  # noqa: E731
BOLD = lambda s: _font("segoeuib.ttf", s)  # noqa: E731
MONO = lambda s: _font("consola.ttf", s)  # noqa: E731


# (x, y, тип, подпись, размер)
NODES = [
    (760, 430, "concept", "память", 46),
    (520, 260, "concept", "внимание", 34),
    (1040, 300, "concept", "энергия", 34),
    (980, 620, "concept", "время", 32),
    (540, 640, "concept", "игра", 36),
    (760, 200, "intention", "исследовать память", 26),
    (300, 420, "intention", "черновик «Тишина»", 26),
    (1180, 500, "intention", "новая партия", 24),
    (660, 790, "activity", "исследование", 30),
    (300, 640, "activity", "творчество", 28),
    (1260, 240, "activity", "отдых", 28),
    (900, 500, "activity", "общение", 26),
    (200, 240, "value", "знание", 28),
    (1340, 700, "value", "автономия", 26),
    (440, 480, "value", "забота", 24),
    (880, 760, "topic", "источник: человек", 18),
    (400, 150, "topic", "гипотеза", 18),
    (1120, 750, "topic", "документ", 18),
    (620, 360, "forgotten", "старый вопрос", 20),
    (220, 780, "forgotten", "оставленный путь", 20),
]

# связи: только реальные типы (ассоциация, породило намерение, продолжение)
EDGES = [
    (0, 1), (0, 2), (0, 3), (0, 4), (0, 12),
    (5, 0), (5, 8), (6, 9), (6, 0), (7, 11),
    (1, 16), (2, 13), (3, 17), (12, 14), (4, 8),
    (19, 6), (18, 0), (10, 2), (13, 7), (14, 9),
]


def radial_background() -> Image.Image:
    image = Image.new("RGB", (W, H), BG_EDGE)
    pixels = image.load()
    cx, cy = W * 0.52, H * 0.5
    largest = math.hypot(max(cx, W - cx), max(cy, H - cy))
    for y in range(H):
        for x in range(0, W, 2):
            ratio = min(1.0, math.hypot(x - cx, y - cy) / largest)
            color = tuple(
                int(BG_CENTER[i] + (BG_EDGE[i] - BG_CENTER[i]) * ratio ** 0.8)
                for i in range(3)
            )
            pixels[x, y] = color
            if x + 1 < W:
                pixels[x + 1, y] = color
    return image


def node_color(kind: str):
    return {"concept": CYAN, "intention": VIOLET, "value": GREEN,
            "activity": AMBER, "topic": CYAN, "forgotten": GREY}[kind]


def node_alpha(kind: str) -> int:
    return 90 if kind == "forgotten" else 255


def draw_node(draw: ImageDraw.ImageDraw, x, y, kind, size, *, crisp: bool):
    color = node_color(kind)
    if kind == "forgotten":
        color = GREY
    if kind == "concept":
        draw.ellipse([x - size, y - size, x + size, y + size], fill=color)
    elif kind == "intention":
        draw.polygon([(x, y - size), (x + size, y), (x, y + size), (x - size, y)], fill=color)
    elif kind == "value":
        points = [(x + size * math.cos(math.radians(a)), y + size * math.sin(math.radians(a)))
                  for a in range(-90, 270, 60)]
        draw.polygon(points, fill=color)
    elif kind == "activity":
        draw.ellipse([x - size, y - size, x + size, y + size], fill=color)
        ring = size + 7
        draw.ellipse([x - ring, y - ring, x + ring, y + ring], outline=color, width=3)
    elif kind == "topic":
        draw.ellipse([x - size * 0.5, y - size * 0.5, x + size * 0.5, y + size * 0.5], fill=color)
    else:
        draw.ellipse([x - size, y - size, x + size, y + size], outline=color, width=3)


def main() -> str:
    base = radial_background()
    draw = ImageDraw.Draw(base, "RGBA")

    # сайдбар
    draw.rectangle([0, 0, 230, H], fill=SIDEBAR + (255,))
    draw.line([230, 0, 230, H], fill=(35, 42, 56, 255), width=2)
    draw.text((28, 34), "Ядро", font=BOLD(24), fill=TEXT)
    draw.text((28, 66), "живая карта", font=REG(15), fill=MUTED)
    for i, item in enumerate(["Сейчас", "Карта жизни", "Дневник", "Занятия", "Доступы"]):
        y = 130 + i * 46
        active = item == "Карта жизни"
        if active:
            draw.rounded_rectangle([16, y - 8, 214, y + 28], 10, fill=CYAN + (36,))
            draw.rounded_rectangle([16, y - 8, 22, y + 28], 3, fill=CYAN + (255,))
        draw.text((40, y), item, font=BOLD(17) if active else REG(17),
                  fill=TEXT if active else MUTED)

    # свечение: связи и ореолы
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    for a, b in EDGES:
        xa, ya = NODES[a][0], NODES[a][1]
        xb, yb = NODES[b][0], NODES[b][1]
        gdraw.line([xa, ya, xb, yb], fill=CYAN + (36,), width=2)
    for x, y, kind, _, size in NODES:
        color = node_color(kind)
        halo = size + 22
        for step in range(3):
            r = halo - step * 7
            gdraw.ellipse([x - r, y - r, x + r, y + r], fill=color + (26,))
    glow = glow.filter(ImageFilter.GaussianBlur(9))
    base = Image.alpha_composite(base.convert("RGBA"), glow).convert("RGB")
    draw = ImageDraw.Draw(base, "RGBA")

    # чёткие связи поверх свечения
    for a, b in EDGES:
        xa, ya = NODES[a][0], NODES[a][1]
        xb, yb = NODES[b][0], NODES[b][1]
        draw.line([xa, ya, xb, yb], fill=(90, 200, 220, 110), width=1)

    # узлы
    for x, y, kind, label, size in NODES:
        draw_node(draw, x, y, kind, size, crisp=True)

    # активный узел пульсирует: внешнее кольцо
    ax, ay, asize = NODES[0][0], NODES[0][1], NODES[0][4]
    draw.ellipse([ax - asize - 16, ay - asize - 16, ax + asize + 16, ay + asize + 16],
                 outline=CYAN + (120,), width=2)

    # подписи узлов
    label_font = REG(15)
    for x, y, kind, label, size in NODES:
        if kind in {"concept", "activity", "value", "intention"}:
            draw.text((x + size + 12, y - 9), label, font=BOLD(15) if kind != "topic" else REG(13),
                      fill=TEXT if kind != "forgotten" else MUTED)

    # легенда
    lx, ly = 270, 812
    draw.rounded_rectangle([lx, ly, lx + 900, ly + 52], 12, fill=SURFACE + (220,),
                           outline=(40, 48, 64, 255), width=1)
    legend = [("концепции", CYAN, "круг"), ("намерения", VIOLET, "ромб"),
              ("ценности", GREEN, "шестиугольник"), ("занятия", AMBER, "кольцо"),
              ("забытое", GREY, "тихий контур")]
    ox = lx + 24
    for text, color, shape in legend:
        draw.ellipse([ox, ly + 20, ox + 14, ly + 34], fill=color if shape != "забытое" else None,
                     outline=color if shape == "забытое" else None, width=2)
        draw.text((ox + 22, ly + 17), text, font=REG(14), fill=MUTED)
        ox += 175

    # карточка деталей
    cx0, cy0, cx1, cy1 = 1120, 120, 1560, 470
    draw.rounded_rectangle([cx0, cy0, cx1, cy1], 16, fill=SURFACE + (235,),
                           outline=CYAN + (90,), width=1)
    draw.ellipse([cx0 + 28, cy0 + 30, cx0 + 66, cy0 + 68], fill=CYAN)
    draw.text((cx0 + 84, cy0 + 32), "память", font=BOLD(24), fill=TEXT)
    draw.text((cx0 + 84, cy0 + 62), "концепция · собственный опыт", font=REG(14), fill=MUTED)
    stats = [("Свидетельств", "3"), ("Уверенность", "0.62"),
             ("Источников", "2"), ("Влияла на выбор", "да, 4 раза")]
    sy = cy0 + 108
    for name, value in stats:
        draw.text((cx0 + 28, sy), name, font=REG(15), fill=MUTED)
        draw.text((cx1 - 190, sy), value, font=MONO(15), fill=TEXT)
        sy += 38
    draw.line([cx0 + 28, sy + 4, cx1 - 28, sy + 4], fill=(45, 53, 70, 255), width=1)
    draw.text((cx0 + 28, sy + 20), "Откуда известно", font=REG(13), fill=MUTED)
    draw.text((cx0 + 28, sy + 44), "собственное действие rest,", font=REG(14), fill=TEXT)
    draw.text((cx0 + 28, sy + 66), "ответ человека · цикл 214", font=REG(14), fill=TEXT)

    # заголовок
    draw.text((262, 40), "Карта жизни", font=BOLD(30), fill=TEXT)
    draw.text((262, 80), "узлы — то, что существо знает, хочет и пережило; связи — только реально записанные",
              font=REG(15), fill=MUTED)

    out = r"C:\digital_being\docs\mockups\life_map_hybrid.png"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    base.save(out)
    return out


if __name__ == "__main__":
    print(main())
