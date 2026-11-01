"""
build_installer.py — one-command сборка Windows-установщика через Inno Setup.

Использование:
    python build_installer.py            # собрать installer (если dist/DigitalBeing.exe уже есть)
    python build_installer.py --rebuild  # пересобрать .exe + installer
    python build_installer.py --clean    # очистить installer_output/

Требования:
    - Inno Setup 6.x (https://jrsoftware.org/isinfo.php)
    - dist/DigitalBeing.exe (собран через `python build.py`)

Результат:
    installer_output/DigitalBeing_Setup_v0.1.3.exe (~50 MB)
"""

import io
import os
import shutil
import subprocess
import sys


# UTF-8 для Windows-консоли
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    except Exception:
        pass


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
ISS_FILE = os.path.join(PROJECT_ROOT, "inno_setup.iss")
INSTALLER_OUTPUT = os.path.join(PROJECT_ROOT, "installer_output")
DIST_EXE = os.path.join(PROJECT_ROOT, "dist", "DigitalBeing.exe")


def read_version() -> str:
    """Достаёт MyAppVersion из inno_setup.iss."""
    with open(ISS_FILE, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped.startswith("#define MyAppVersion"):
                parts = stripped.split('"')
                if len(parts) >= 2 and parts[1]:
                    return parts[1]
    print(f"❌ Не нашёл #define MyAppVersion в {ISS_FILE}")
    sys.exit(1)


def find_iscc() -> str | None:
    """Ищет ISCC.exe (Inno Setup Command Line Compiler) в стандартных путях."""
    candidates = [
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
        r"C:\Program Files\Inno Setup 5\ISCC.exe",
        # Chocolatey
        r"C:\ProgramData\chocolatey\bin\ISCC.exe",
        # Scoop
        os.path.expanduser(r"~\scoop\apps\inno-setup\current\ISCC.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def run(cmd: list[str], cwd: str | None = None) -> None:
    """Запускает команду и падает с понятной ошибкой."""
    print(f"\n>>> {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        print(f"❌ Команда упала с кодом {result.returncode}")
        sys.exit(result.returncode)


def check_exe_exists() -> None:
    """Проверяет, что dist/DigitalBeing.exe уже собран."""
    if not os.path.isfile(DIST_EXE):
        print(f"❌ Не найден {DIST_EXE}")
        print("   Сначала соберите .exe через `python build.py` или передайте --rebuild.")
        sys.exit(1)


def clean() -> None:
    """Очищает installer_output/."""
    if os.path.isdir(INSTALLER_OUTPUT):
        print(f"🧹 Очищаю {INSTALLER_OUTPUT}/")
        shutil.rmtree(INSTALLER_OUTPUT, ignore_errors=True)


def build() -> None:
    """Компилирует inno_setup.iss в setup.exe."""
    iscc = find_iscc()
    if not iscc:
        print("❌ Inno Setup (ISCC.exe) не найден.")
        print("   Скачайте и установите: https://jrsoftware.org/isinfo.php")
        print("   Стандартные пути:")
        print("     • C:\\Program Files (x86)\\Inno Setup 6\\ISCC.exe")
        print("     • C:\\Program Files\\Inno Setup 6\\ISCC.exe")
        sys.exit(1)

    if not os.path.isfile(ISS_FILE):
        print(f"❌ Не найден {ISS_FILE}")
        sys.exit(1)

    check_exe_exists()
    print(f"📦 Использую ISCC: {iscc}")
    print("🚀 Компилирую installer (~30 сек)...")

    os.makedirs(INSTALLER_OUTPUT, exist_ok=True)
    run([iscc, ISS_FILE])

    # Имя файла задаётся в .iss через OutputBaseFilename с версией
    version = read_version()
    setup_exe = os.path.join(INSTALLER_OUTPUT, f"DigitalBeing_Setup_v{version}.exe")
    if not os.path.isfile(setup_exe):
        print(f"\n❌ Сборка прошла, но {setup_exe} не найден в {INSTALLER_OUTPUT}/")
        sys.exit(1)
    size_mb = os.path.getsize(setup_exe) / (1024 * 1024)
    print(f"\n✅ Готово! {setup_exe} ({size_mb:.1f} MB)")
    print(f"   Раздавайте этот файл — пользователи получат визард установки.")
    print(f"   Двойной клик на setup.exe → мастер установки → ярлык на рабочем столе.")


def main() -> None:
    if "--clean" in sys.argv:
        clean()

    if "--rebuild" in sys.argv:
        # Сначала пересобираем .exe
        print("🔄 Шаг 1/2: пересобираем DigitalBeing.exe...")
        run([sys.executable, "build.py", "--clean"])
        print("\n📦 Шаг 2/2: собираем installer...")

    build()


if __name__ == "__main__":
    main()