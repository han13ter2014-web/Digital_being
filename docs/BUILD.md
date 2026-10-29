# 🛠 Сборка Windows-установщика DigitalBeing.exe

Этот документ описывает, как собрать **один .exe файл**, который устанавливается
двойным кликом и запускает Digital Being в трее Windows.

---

## 🎯 Результат

После сборки получается:

```
dist/
└── DigitalBeing.exe    ~40-60 MB, onefile
```

Файл самодостаточен: PyInstaller включает интерпретатор Python и нужные
зависимости (pystray, plyer, Pillow, tkinter). Версия Python для исходного
проекта — `>=3.10`; конкретная версия внутри `.exe` определяется окружением
сборки.
Пользователю достаточно:

1. Скопировать `DigitalBeing.exe` на свой компьютер.
2. Двойной клик → агент поселяется в трее, открывается чат с приветствием.
3. Дать агенту имя (`/name <имя>`) или оставить временное.

---

## 🚀 One-command сборка

```bash
# 1. Установить pyinstaller (один раз)
pip install ".[build]"

# 2. Собрать .exe
python build.py             # ~1-3 мин
# или с очисткой предыдущей сборки:
python build.py --clean
```

После сборки:

```bash
dist/DigitalBeing.exe    # запуск двойным кликом
```

---

## 🔧 Что происходит под капотом

`build.py` выполняет:

1. **Проверка PyInstaller** — если не установлен, ставит автоматически.
2. **Проверка иконки** — если `assets/icon.ico` нет, генерирует заглушку через Pillow
   (тёмно-зелёный круг + буквы "DB"). Можно заменить на свою иконку 256×256.
3. **PyInstaller** запускает `digital_being.spec` с `--clean --noconfirm`.
4. **Результат** в `dist/DigitalBeing.exe`.

---

## 📁 Структура артефактов сборки

```
digital_being/
├── digital_being.spec       # ← спецификация PyInstaller
├── build.py                 # ← скрипт сборки
├── assets/
│   └── icon.ico             # ← 256×256, многобитная (16/32/48/64/128/256)
├── dist/
│   └── DigitalBeing.exe     # ← итоговый файл (НЕ коммитим в git)
├── build/                   # ← промежуточные файлы PyInstaller (НЕ коммитим)
└── tools/
    └── gen_icon.py          # ← генератор иконки через Pillow (fallback)
```

---

## 🧩 Содержимое `digital_being.spec`

Спецификация делает следующее:

| Параметр | Значение | Зачем |
|---|---|---|
| `datas` | `config/`, `data/knowledge_base.json` | Конфигурация и базовые знания внутри exe |
| `hiddenimports` | `pystray._win32`, `plyer.platforms.win.notification`, `tkinter.*` | Windows-специфичные модули, которые PyInstaller не находит автоматически |
| `excludes` | `matplotlib`, `numpy.tests`, `pytest`, `aiohttp` | Уменьшаем размер (они не нужны для tray-режима) |
| `console=False` | — | `--windowed`: без чёрной консоли при запуске |
| `icon='assets/icon.ico'` | — | Иконка приложения и трея |

---

## 🎨 Замена иконки

По умолчанию иконка генерируется программно (зелёный круг с "DB").
Чтобы поставить свою:

1. Создайте `assets/icon.ico` — многобитная иконка 256×256 (размеры 16/32/48/64/128/256).
2. Пересоберите: `python build.py --clean`.

Примеры программ для создания .ico:
- **GIMP** — File → Export As → `.ico`
- **IcoFX** (Windows)
- **ImageMagick**: `magick convert icon.png -define icon:auto-resize=256,128,64,48,32,16 icon.ico`

---

## 🐛 Типичные проблемы и решения

### `ModuleNotFoundError: No module named 'pystray._win32'`

PyInstaller не нашёл Windows-специфичный модуль pystray. Уже исправлено
в `digital_being.spec` через `hiddenimports`. Если всё же возникает —
добавьте явно:

```python
hiddenimports=['pystray._win32', 'pystray._base'],
```

### `ImportError: DLL load failed` при запуске .exe

Скорее всего не включены tcl/tk библиотеки. PyInstaller включает их
автоматически при импорте `tkinter`, но иногда нужно явно:

```python
hiddenimports=['tkinter', 'tkinter.ttk', 'tkinter.scrolledtext'],
```

### Иконка в трее не появляется на Windows 11

Известная проблема `pystray` с новой панелью задач. Решения:

1. Обновить pystray до последней версии: `pip install -U pystray`.
2. Использовать альтернативный backend — заменить в `src/ui/tray.py` на
   прямое WinAPI через `ctypes` (вне scope этого документа).

### SmartScreen блокирует запуск

Windows показывает предупреждение для неподписанных .exe. Решения:

1. Для разработки — нажать "Подробнее" → "Выполнить в любом случае".
2. Для распространения — купить сертификат подписи кода (~$70-200/год)
   и подписать .exe через `signtool`.

---

## 📦 Размеры и время

| Конфигурация | Размер | Время сборки | Время запуска |
|---|---|---|---|
| `--onefile` (по умолчанию) | 40-60 MB | 1-3 мин | 2-5 сек (распаковка) |
| `--onedir` (папка) | 30-50 MB (сумма файлов) | 30-60 сек | <1 сек |

`--onefile` удобнее для распространения (один файл). `--onedir` — для разработки.

Чтобы переключиться на `--onedir`, замените `EXE(...)` на:

```python
exe = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='DigitalBeing',
)
```

---

## 🧪 Smoke-тест после сборки

```bash
# Запустить в headless-режиме (без GUI) — проверить, что собирается корректно
dist/DigitalBeing.exe --headless --no-tray

# Или просто двойной клик на Windows
explorer dist/DigitalBeing.exe
```

В чате должно появиться приглашение NamingDialogue.

---

## 🔄 Альтернативы PyInstaller

| Инструмент | Плюсы | Минусы |
|---|---|---|
| **PyInstaller** ✅ | Зрелый, простой, well-documented | Большой размер exe (~50 MB) |
| **Nuitka** | Быстрее runtime, меньше размер | Сложнее настройка, дольше компиляция |
| **cx_Freeze** | Кросс-платформенный | Меньше фич для Windows |
| **py2exe** | Windows-only, давно существует | Устаревший, Python ≤3.10 |

Для Digital Being рекомендуем PyInstaller — он покрывает все наши требования
(tkinter, pystray, Pillow) и хорошо проверен в проде.

---

## 📝 Дополнительные улучшения (TODO)

- [ ] Подпись .exe сертификатом (для публичного распространения)
- [ ] Inno Setup скрипт для .msi с ярлыками и uninstall
- [ ] Автообновления через Squirrel.Windows
- [ ] Иконка-сплеш при первом запуске

См. также:
- [docs/USAGE.md](USAGE.md) — использование
- [docs/ARCHITECTURE.md](ARCHITECTURE.md) — архитектура проекта
- [main_tray.py](../main_tray.py) — точка входа