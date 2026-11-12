# Статические проверки

## Единые версии

CI, локальная `.venv` и pre-commit используют одинаковые версии инструментов:

- **ruff 0.5.7** — lint и форматирование;
- **mypy 1.11.2** — проверка публичных entry points;
- **bandit 1.7.8** — поиск проблем безопасности средней и высокой severity.

Версии закреплены одновременно в `.pre-commit-config.yaml` и группах `dev`/`all`
в `pyproject.toml`. Мета-тест `tests/test_static_pin.py` блокирует рассинхрон.
При обновлении инструмента оба файла меняются в одном коммите.

## Обязательные команды

```bash
python -m ruff check src/ config/ tests/ main.py main_tray.py
python -m ruff format --check src/ config/ tests/ main.py main_tray.py
python -m mypy --config-file pyproject.toml --explicit-package-bases --no-site-packages --follow-imports=skip main.py main_tray.py
python -m bandit -r src/ config/ main.py main_tray.py -ll --skip B101,B601
```

На Windows в проектной среде команды начинаются с
`.venv/Scripts/python.exe`, на Unix — с `.venv/bin/python`.

Ruff заменил прежний необязательный `pyflakes`: результат проверки блокирует CI.
Форматирование выполняется командой `python -m ruff format ...` (без `--check`).

## Граница mypy

Mypy обязателен только для `main.py` и `main_tray.py` — публичных входных API.
Это не утверждение, что весь репозиторий типизирован. Флаги
`--explicit-package-bases` и `--follow-imports=skip` устраняют конфликт
одноимённых пакетов и ограничивают gate заданной областью;
`--no-site-packages` исключает несовместимые сторонние stubs. Расширять область
следует постепенно, после устранения реальных ошибок типов, а не ослаблением
проверки до формально зелёного состояния.

Pre-commit использует ту же команду: `always_run: true` и
`pass_filenames: false`, поэтому hook не подменяет entry-point gate проверкой
только изменённых файлов.

## Исключения Bandit

`B101` отключён для assert в тестах, `B601` — для проверенного запуска shell в
существующих изолированных сценариях. Другие правила глобально не ослабляются.
Локальные `# nosec Bxxx` допустимы только после аудита конкретного места:
например, для константного списка SQL-колонок или заранее проверенного URL.
Новые динамические SQL-идентификаторы следует цитировать, а значения всегда
передавать параметрами.
