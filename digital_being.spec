# -*- mode: python ; coding: utf-8 -*-
"""
digital_being.spec — PyInstaller spec для Digital Being (Windows).

Собирает один .exe файл, который включает Python 3.14 + все зависимости
(pystray, plyer, Pillow, tkinter). Запуск — двойным кликом.

Сборка:
    pip install pyinstaller
    pyinstaller digital_being.spec --clean --noconfirm

Результат:
    dist/DigitalBeing.exe   (~40-60 MB, onefile)

Аргументы PyInstaller, вынесенные в .spec:
    --onefile   — один файл (не папка)
    --windowed  --noconsole  — без чёрной консоли
    --icon assets/icon.ico   — иконка приложения
"""

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None


# ============================================================
# Анализ исходников
# ============================================================
a = Analysis(
    ['main_tray.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Конфигурация (LR_CONFIG и пр.)
        ('config', 'config'),
        # Знания агента по умолчанию: чистый стартовый сид, а НЕ живой
        # runtime-файл data/knowledge_base.json (в dev data/ — рабочий каталог
        # агента, в него попадают следы самообучения; bootstrap.py при первом
        # запуске копирует бандлный сид в каталог данных пользователя).
        ('data_bootstrap/knowledge_base.json', 'data'),
        ('data/initial_knowledge.json', 'data'),
        # Локализации (i18n: src/metrics/i18n.py грузит data/i18n/{lang}.json)
        ('data/i18n', 'data/i18n'),
        # База знаний (каталог может отсутствовать в свежем clone; данные
        # загружаются через knowledge_base.json, поэтому не делаем его
        # обязательным source для PyInstaller.)
        # Иконка приложения (используется pystray при старте)
        ('assets/icon.ico', 'assets'),
    ],
    hiddenimports=[
        # pystray Windows backend
        'pystray._win32',
        # plyer Windows backend для нотификаций
        'plyer.platforms.win.notification',
        # tkinter (для чата)
        'tkinter',
        'tkinter.ttk',
        'tkinter.scrolledtext',
        'tkinter.font',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Не тянем лишнее (уменьшает размер)
        'matplotlib',
        'numpy.tests',
        'pytest',
        'pytest_asyncio',
        'aiohttp',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Подтянуть все submodules pystray (иногда требуется)
hiddenimports_pystray = collect_submodules('pystray')
a.hiddenimports += hiddenimports_pystray


# ============================================================
# PyInstaller Analysis
# ============================================================
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)


# ============================================================
# EXE (onefile)
# ============================================================
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='DigitalBeing',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                    # сжимаем UPX (если установлен)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,               # --windowed: без чёрной консоли
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',      # иконка приложения (256x256, многобитная)
)