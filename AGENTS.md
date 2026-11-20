# Project Playbook

Краткие проверенные правила для повторяющейся работы с Digital Being. Не заменяет `body_plan.md` и проектную документацию.

## Commands

Все команды выполняются из `C:\Users\GamePK\digital_being` в проектной `.venv`.

- Один тест: `.venv/Scripts/python.exe -m pytest tests/<file>.py::<test> -q`
- Полный regression: `.venv/Scripts/python.exe -m pytest -q`
- CI static: `.venv/Scripts/python.exe -m ruff check src/ config/ tests/ main.py main_tray.py`
- CI format: `.venv/Scripts/python.exe -m ruff format --check src/ config/ tests/ main.py main_tray.py`
- Mypy: `.venv/Scripts/python.exe -m mypy --config-file pyproject.toml --explicit-package-bases --no-site-packages --follow-imports=skip main.py main_tray.py`
- Bandit: `.venv/Scripts/python.exe -m bandit -q -r src/ config/ main.py main_tray.py -ll --skip B101,B601`
- Syntax: `.venv/Scripts/python.exe -m compileall -q src/ config/ tests/ main.py main_tray.py`
- Evidence: verified locally, 2026-11-20; последний полный regression с branch coverage — 3940 passed, 2 skipped за 686,59 с, coverage 80,64 % (исправление коллизии ID SQLite-памяти).

## Conventions

- Для дефекта сначала падающее воспроизведение/regression-тест, затем минимальная правка, профильные и полные проверки.
- Не менять спорные эмоции, выборы, речь, цели и необычные проявления сущности без совместного разбора с владельцем.
- Не делать рефакторинг «заодно» и не превращать процент покрытия в самостоятельную цель.
- `body_plan.md` — авторитетный источник по органам и приоритетам; самовольно не расширять.
- Commit/push только по явному разрешению владельца на текущий набор изменений.
- Evidence: user-confirmed, 2026-11-12.

## Gotchas and protected areas

- Живые `data/` не изменять и живую сущность не запускать; тесты и воспроизведения только с `DIGITAL_BEING_DATA_DIR` во временной песочнице.
- Широкие `except` и необычное поведение — направления аудита, не автоматически баги.
- Legacy standalone JSON и managed UUID/SQLite — разные контуры; не переносить исправления между ними без проверки.
- Текущее состояние длительного аудита: `tmp/bug_hunt/state.md` (локальный ignored-файл).
- Evidence: user-confirmed и verified, 2026-11-12.

## Architecture decisions

- **Checkpoints прежде всего для внешнего наблюдения развития и диагностики.**
  - Причина: бесконечное самовосстановление может подорвать задуманные механики смертности и размножения сущности.
  - Scope: не развивать автономное самовосстановление или транзакционный `CheckpointSubsystem.load()` как способность сущности без отдельного разбора.
  - Сохранность файлов истории при записи остаётся важной и не противоречит этому решению.
  - Аудит вызовов 2026-11-12: автономный `checkpoint_now` только создаёт снимок; `attempt_recovery_from_checkpoint()` не имеет вызывающих мест; полная загрузка происходит при запуске/восстановлении профиля. Не добавлять автономный откат.
  - `check_death()` пишет «откат к более раннему целому», но откат не выполняет: это неточная наблюдаемость, не основание менять механику смерти.
  - Evidence: user-confirmed и verified by call-site inspection, 2026-11-12.

## Environment and recovery

- Windows installer: `.venv/Scripts/python.exe build_installer.py --rebuild`; PyInstaller 6.22.3 и `C:\Program Files (x86)\Inno Setup 6\ISCC.exe` доступны. Перед публикацией проверить архив на отсутствие живого `data/`, изолированный запуск и SHA-256.
- У PyInstaller windowed-сборки (`console=False`) может не быть консоли для `AttachConsole`; неудачная отправка Ctrl+C/Ctrl+Break в таком harness не доказывает дефект приложения, но и не засчитывается как проверка graceful shutdown.
- Baseline Git: `631e2c6`; полный regression — 2634 passed, 2 skipped, GitHub CI run `43722983480` — success, 8/8 jobs.
- Новые изменения после baseline коммитить и отправлять только по явному разрешению владельца.
- Evidence: verified, 2026-11-15.