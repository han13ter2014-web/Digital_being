"""
build.py — one-command сборка DigitalBeing.exe.

Использование:
    python build.py            # собрать .exe
    python build.py --clean    # очистить build/ и dist/ перед сборкой

Требования:
    pip install pyinstaller

Результат:
    dist/DigitalBeing.exe   (~40-60 MB)
"""

# UTF-8 для Windows-консоли (эмодзи ✅ 🛠 и т.п.)
import io
import sys
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    except Exception:
        pass

import os
import shutil
import subprocess


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SPEC_FILE = os.path.join(PROJECT_ROOT, "digital_being.spec")
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")


def run(cmd: list[str], cwd: str | None = None) -> None:
    """Запускает команду и падает с понятной ошибкой."""
    print(f"\n>>> {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        print(f"❌ Команда упала с кодом {result.returncode}")
        sys.exit(result.returncode)


def ensure_pyinstaller() -> None:
    """Проверяет, что PyInstaller установлен."""
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("📦 PyInstaller не найден, устанавливаю...")
        run([sys.executable, "-m", "pip", "install", "pyinstaller>=6.0"])


def clean() -> None:
    """Очищает build/ и dist/."""
    for path in (BUILD_DIR, DIST_DIR):
        if os.path.isdir(path):
            print(f"🧹 Очищаю {path}/")
            shutil.rmtree(path, ignore_errors=True)
    # Также .pyc кэши и __pycache__
    for root, dirs, files in os.walk(PROJECT_ROOT):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                dirs.remove(d)


def check_icon() -> bool:
    """Проверяет наличие иконки. Если нет — генерирует заглушку через Pillow."""
    icon_path = os.path.join(PROJECT_ROOT, "assets", "icon.ico")
    if os.path.isfile(icon_path):
        print(f"✅ Иконка найдена: {icon_path}")
        return True
    print(f"⚠️  Иконка не найдена: {icon_path}")
    print("   Генерирую заглушку через Pillow...")
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("❌ Pillow не установлен. Установите: pip install Pillow")
        return False
    os.makedirs(os.path.dirname(icon_path), exist_ok=True)
    # Простая иконка 256×256 — тёмно-зелёный круг + "DB"
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Фон: тёмно-зелёный круг
    draw.ellipse([10, 10, size - 10, size - 10], fill=(46, 125, 50, 255))
    # Буквы "DB" (Digital Being)
    try:
        font = ImageFont.truetype("arial.ttf", 110)
    except OSError:
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", 110)
        except OSError:
            font = ImageFont.load_default()
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
    img.save(icon_path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48),
                                              (64, 64), (128, 128), (256, 256)])
    print(f"✅ Иконка создана: {icon_path}")
    return True


def build() -> None:
    """Сборка .exe."""
    if not os.path.isfile(SPEC_FILE):
        print(f"❌ Спецификация не найдена: {SPEC_FILE}")
        sys.exit(1)
    if not check_icon():
        print("⚠️  Сборка продолжится без кастомной иконки (--icon будет пропущен).")
    print("\n🚀 Собираю DigitalBeing.exe...")
    print("   Это займёт 1-3 минуты при первом запуске.")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        SPEC_FILE,
        "--clean",
        "--noconfirm",
    ]
    run(cmd)
    exe_path = os.path.join(DIST_DIR, "DigitalBeing.exe")
    if os.path.isfile(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print(f"\n✅ Готово! {exe_path} ({size_mb:.1f} MB)")
        print(f"   Двойной клик → агент поселяется в трее.")
    else:
        print(f"\n❌ Сборка прошла, но {exe_path} не найден.")
        sys.exit(1)


def main() -> None:
    if "--clean" in sys.argv:
        clean()
    ensure_pyinstaller()
    build()


if __name__ == "__main__":
    main()