"""
Генерация иконки assets/icon.ico для Digital Being.

Запуск: python tools/gen_icon.py

Используется как fallback в build.py, если иконка не найдена.
"""
import os
import sys

# Force UTF-8 stdout (Windows)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow не установлен: pip install Pillow")
    sys.exit(1)


def find_font() -> ImageFont.FreeTypeFont:
    """Ищет жирный шрифт из нескольких стандартных путей Windows."""
    candidates = [
        ("arial.ttf", 110),
        ("C:/Windows/Fonts/arialbd.ttf", 110),
        ("C:/Windows/Fonts/arial.ttf", 110),
        ("C:/Windows/Fonts/segoeui.ttf", 100),
        ("DejaVuSans-Bold.ttf", 110),
    ]
    for name, size in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main():
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Тёмно-зелёный круг (как nature/life)
    draw.ellipse([10, 10, size - 10, size - 10], fill=(46, 125, 50, 255))

    # Буквы "DB"
    font = find_font()
    text = "DB"
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
    except AttributeError:
        text_w, text_h = draw.textsize(text, font=font)
    x = (size - text_w) // 2
    y = (size - text_h) // 2 - 10
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)

    out_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "icon.ico")
    img.save(
        out_path,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Иконка сохранена: {out_path} ({os.path.getsize(out_path)} bytes)")


if __name__ == "__main__":
    main()