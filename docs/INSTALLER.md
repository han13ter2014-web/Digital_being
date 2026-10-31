# 🪟 Создание Windows-установщика DigitalBeing_Setup.exe

Этот документ описывает, как собрать **полноценный Windows-установщик**
с визардом «Далее → Установить», который устанавливает Digital Being
как обычную программу (с ярлыками в меню Пуск, на рабочем столе,
возможностью удаления через «Программы и компоненты»).

---

## 🎯 Результат

После сборки получается:

```
installer_output/
└── DigitalBeing_Setup_v0.1.2.exe    ~50 MB
```

Это **самостоятельный installer**, который:

- 🪟 Показывает визард установки с лицензией и описанием.
- 📁 Устанавливает в `C:\Program Files\Digital Being\`.
- 🔗 Создаёт ярлык в меню «Пуск» и на рабочем столе (по выбору).
- 🚀 Создаёт запись в реестре для автозапуска (по выбору).
- 🗑️ Регистрирует себя в «Программы и компоненты» для удаления.
- 🌍 Поддерживает русский и английский языки.

**Пользователь** скачивает один файл, двойной клик → визард → готово.

---

## 🚀 One-command сборка

```bash
# 1. Установить Inno Setup (один раз)
#    Скачать: https://jrsoftware.org/isinfo.php
#    Стандартный путь: C:\Program Files (x86)\Inno Setup 6\ISCC.exe

# 2. Собрать всё (exe + installer)
python build_installer.py --rebuild

# Или по шагам:
python build.py                # dist/DigitalBeing.exe (30 MB)
python build_installer.py      # installer_output/DigitalBeing_Setup.exe (50 MB)
```

После сборки:

```bash
installer_output/DigitalBeing_Setup_v0.1.2.exe   # раздавать этот файл
```

Для публичной раздачи также публикуйте SHA-256 рядом с файлом. Подпись
сертификатом пока не выполняется, поэтому Windows SmartScreen может показать
предупреждение для независимого раннего релиза.

---

## 🔧 Что происходит под капотом

`build_installer.py` делает:

1. **Проверяет Inno Setup** — ищет `ISCC.exe` в стандартных путях.
2. **Проверяет `dist/DigitalBeing.exe`** — должен быть собран через `python build.py`.
3. **Запускает ISCC.exe** с файлом `inno_setup.iss`.
4. **Результат** — `installer_output/DigitalBeing_Setup_v0.1.2.exe`.

---

## 📁 Структура

```
digital_being/
├── inno_setup.iss                # ← Inno Setup скрипт (визард, файлы, реестр)
├── build_installer.py            # ← скрипт сборки (one-command)
├── installer/
│   ├── license.txt               # ← лицензия + этика использования
│   └── welcome.txt               # ← текст "Перед установкой"
├── dist/                         # ← артефакты PyInstaller (не в git)
│   └── DigitalBeing.exe
└── installer_output/             # ← артефакты Inno Setup (не в git)
    └── DigitalBeing_Setup_v0.1.2.exe
```

---

## 🎨 Содержимое `inno_setup.iss`

| Секция | Что делает |
|---|---|
| `[Setup]` | AppId (НЕ менять!), AppName, версия, путь установки, иконка, сжатие lzma2/ultra64, минимальная версия Win 10 |
| `[Languages]` | Русский и английский |
| `[Tasks]` | Чекбоксы: ярлык на рабочем столе, в меню Пуск, автозапуск |
| `[Files]` | Копирует `DigitalBeing.exe`, README, CHANGELOG, документацию |
| `[Icons]` | Создаёт ярлыки в меню Пуск и на рабочем столе |
| `[Registry]` | Записывает `HKCU\...\Run\DigitalBeing` для автозапуска |
| `[Run]` | После установки предлагает запустить агента сразу |
| `[UninstallDelete]` | Закомментировано — НЕ удаляем чекпоинты пользователя при деинсталляции |

---

## 🎁 Что пользователь получает после установки

```
C:\Program Files\Digital Being\
├── DigitalBeing.exe              # главный исполняемый файл
├── README.md
├── CHANGELOG.md
├── LICENSE.txt                   # лицензия + этика
└── docs\
    ├── USAGE.md
    ├── BUILD.md
    ├── WILL.md
    └── ARCHITECTURE.md
```

**Ярлыки**:
- 🪟 Меню «Пуск» → Digital Being
- 🖥️ Рабочий стол → Digital Being (если выбрано при установке)
- 🚀 Автозапуск при входе в Windows (если выбрано)

**В реестре**:
- `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\DigitalBeing` (если выбран автозапуск)

**В «Программы и компоненты»**:
- Digital Being v0.1.2 → кнопка «Удалить»

---

## 🔄 Обновление приложения

**Важно**: при обновлении версии **не меняйте `AppId`** в `inno_setup.iss`.
Этот GUID связывает старую и новую версии — Inno Setup автоматически
обновит программу, сохранив данные пользователя.

Что менять при релизе:
- `MyAppVersion` (например `"0.2.0"`)
- Содержимое `dist/DigitalBeing.exe`
- Файлы в `docs\`

---

## 🐛 Типичные проблемы

### `ISCC.exe не найден`

Скачайте Inno Setup: https://jrsoftware.org/isinfo.php
И положите в один из стандартных путей:

```
C:\Program Files (x86)\Inno Setup 6\ISCC.exe
C:\Program Files\Inno Setup 6\ISCC.exe
```

Или добавьте в `PATH`.

### `Cannot find dist\DigitalBeing.exe`

Сначала соберите .exe:

```bash
python build.py
```

### `SetupIconFile 'assets\icon.ico' not found`

Сначала создайте иконку:

```bash
python tools/gen_icon.py
```

### SmartScreen блокирует установщик

Как и с DigitalBeing.exe — для неподписанных файлов нужно нажать
«Подробнее» → «Выполнить в любом случае». Для публичного распространения
нужен сертификат подписи кода.

### Агент не запускается автоматически после установки

Проверьте, что при установке был выбран чекбокс «Запускать при входе в Windows»
(опция `autostart` в `inno_setup.iss`). Или запустите вручную через ярлык.

---

## 🔄 Альтернативы Inno Setup

| Инструмент | Плюсы | Минусы |
|---|---|---|
| **Inno Setup** ✅ | Стандарт для open-source Windows, бесплатный, скриптовый | Windows-only |
| **NSIS** | Очень гибкий, малый размер | Сложный скриптовый язык |
| **WiX Toolset** | XML-based, интеграция с MSBuild | Сложный для open-source |
| **Inno Setup Plus** | Расширенная версия Inno | Менее известен |

Для Digital Being рекомендуем **Inno Setup** — стандарт в open-source мире,
бесплатный, легко автоматизируется.

---

## 📦 Размеры

| Компонент | Размер |
|---|---|
| `DigitalBeing.exe` (PyInstaller onefile) | ~30 MB |
| Документация (5 файлов .md) | ~200 KB |
| `DigitalBeing_Setup.exe` (LZMA2 ultra64) | ~30 MB (сжатие ~1%) |
| После установки на диске | ~60 MB |

LZMA2 ultra64 даёт почти идеальное сжатие для уже упакованного `.exe`.

---

## 🧪 Тест после сборки

1. **Чистая установка**: запустите `DigitalBeing_Setup.exe` на компьютере
   без Digital Being. Должен появиться визард установки.
2. **Проверка компонентов**:
   - Ярлык в меню «Пуск» работает → открывает агента в трее.
   - Ярлык на рабочем столе работает (если выбран).
   - В «Программы и компоненты» есть Digital Being с кнопкой «Удалить».
   - Если выбран автозапуск — после перезагрузки агент стартует с Windows.
3. **Деинсталляция**: через «Программы и компоненты» → «Удалить» → всё
   корректно чистится (ярлыки, реестр, файлы), но **данные пользователя
   (data/) сохраняются**.

---

## 📝 Что НЕ входит в этот план

- ❌ **Подпись installer сертификатом** — для распространения нужно купить
  сертификат (~70-200 USD/год) и подписать через `signtool`.
- ❌ **Автообновления** — потребует Squirrel.Windows или собственный механизм.
- ❌ **MSIX-пакет** — для Windows Store, требует Microsoft-аккаунт и сертификацию.
- ❌ **Многоязычные файлы .isl** — кастомные переводы, нужно делать вручную.

---

## 🔗 Связанные документы

- [docs/BUILD.md](BUILD.md) — сборка `DigitalBeing.exe` через PyInstaller
- [docs/USAGE.md](USAGE.md) — использование агента
- [README.md](../README.md) — главная страница проекта
- [GitHub](https://github.com/han13ter2014-web/Digital_being) — публичный репозиторий