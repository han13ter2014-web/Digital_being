# Этап 7 — отчёт: Delamain-local, первый замкнутый контур

**Дата:** 2026-10-21.
**Статус:** вертикальный срез готов; интеграция с основным агентом — следующий этап.

## 1. Цель этапа

Превратить «богатую симуляцию познания» в проверяемый контур:

```text
задача → план → действие → наблюдение → запись опыта → результат
```

Ограничения этапа были сознательными:

* не пытаться сделать AGI или «сознание»;
* не требовать локальную LLM;
* не добавлять обязательных зависимостей;
* не давать агенту неограниченный доступ к файлам;
* не имитировать успех: ошибка должна останавливать план и попадать в память.

## 2. Что сделано

### 2.1. Новый пакет `src/delamain/`

| Файл | Назначение |
|---|---|
| `models.py` | dataclass-модели действий и результатов |
| `sandbox.py` | path-политика и файловые операции внутри workspace |
| `actions.py` | `Action`, `ActionError`, `ActionRegistry`, набор действий |
| `memory.py` | SQLite-память: эпизоды, факты, self-model, цели, навыки |
| `planner.py` | `HeuristicPlanner` для простых русских/английских команд |
| `runtime.py` | выполнение плана, остановка на ошибке, запись эпизодов |
| `__main__.py` | CLI-демо `python -m src.delamain` |

### 2.2. Sandbox

Реализована защитная политика путей:

* только относительные пути внутри workspace;
* запрет абсолютных, drive-relative и `..`-путей;
* проверка симлинков через `resolve()` и `commonpath`;
* лимит файла (по умолчанию 1 МБ);
* отказ от бинарных файлов при чтении;
* атомарная запись через временный файл и `os.replace`;
* исключение служебных каталогов (`.git`, `__pycache__`, `node_modules` и др.)
  из списков и поиска.

### 2.3. Действия

Реестр поддерживает:

`list_files`, `read_file`, `write_file`, `search_files`, `verify_file`,
`remember_fact`, `recall_facts`, `set_self_model`, `get_self_model`,
`save_goal`, `list_goals`.

`ActionRegistry.execute()` перехватывает ожидаемые и неожиданные ошибки и
возвращает `ActionResult(ok=False, error=...)`. Благодаря этому сбой остаётся
наблюдаемым, а не превращается в исключение, ломающее цикл.

### 2.4. Память

SQLite-схема:

* `episodes` — задача, шаг, аргументы, результат, ошибка, метаданные;
* `facts` + `facts_fts` — семантические факты и FTS5-поиск с fallback на
  `LIKE`;
* `self_model` — самоописание;
* `goals` — цели и статусы;
* `skills` — планы и счётчики успехов/неудач.

Runtime пишет `task.start` и `task.finish`, поэтому историю задачи можно
восстановить без внешнего лог-файла.

### 2.5. Runtime и planner

`DelamainRuntime.run_task()`:

* принимает готовый план или строит его через `HeuristicPlanner`;
* выполняет шаги последовательно;
* после каждого шага пишет эпизод;
* останавливается на первой ошибке;
* возвращает `TaskResult` с шагами и итогом.

`HeuristicPlanner` понимает базовые команды: список файлов, чтение, запись,
проверку, поиск, запоминание/воспоминание, создание цели. Это не замена LLM,
а гарантия работоспособности без модели и удобный тестовый дублёр.

### 2.6. CLI

```powershell
python -m src.delamain --root workspace --task "список файлов"
python -m src.delamain --root workspace --task "запиши в notes/a.txt: привет"
python -m src.delamain --root workspace --task "проверь notes/a.txt на привет"
```

CLI не импортирует основного агента и не требует `data/` проекта, если
передать `--db`.

## 3. Проверки

### 3.1. Целевые тесты

```text
python -m pytest tests/test_delamain_sandbox.py tests/test_delamain_memory.py tests/test_delamain_planner.py tests/test_delamain_runtime.py -q
21 passed in 0.40s
```

Покрыто:

* escape-попытки и лимиты sandbox;
* список/поиск и исключение служебных каталогов;
* эпизоды, факты, FTS, self-model, цели, навыки;
* последовательное выполнение и остановка на ошибке;
* `task.start` / `task.finish`;
* русские и английские команды planner;
* неизвестные действия и неизвестные задачи.

### 3.2. CLI-проверка

Вручную проверен полный цикл:

```text
запиши в notes/a.txt: привет  → write_file, ok=true
прочитай notes/a.txt          → read_file, text="привет"
```

### 3.3. Полный набор тестов

```text
python -m pytest -q
456 passed, 2 skipped in 840.96s (0:14:00)
```

Это на 21 тест больше, чем до этапа; регрессий в существующем наборе нет.

## 4. Что не сделано

* LLM-планировщик не подключён;
* автономный выбор целей не реализован;
* нет approval-политики для опасных действий;
* нет интеграции с `AgentRunner` / `DigitalBeing`;
* нет удаления файлов и запуска кода (сознательно);
* нет семантической проверки «правильности» результата, только явные
  проверки вроде `verify_file`;
* нет переиспользования `skills` в planning.

## 5. Следующий этап

1. Подключить `DelamainRuntime` как опциональную подсистему, не меняя
   поведение существующего агента по умолчанию.
2. Реализовать цикл цели: выбор → план → действие → проверка → обновление
   статуса.
3. Добавить интерфейс LLM-планировщика с JSON-схемой действий и fallback.
4. Ввести approval для записи/удаления/кода.
5. Начать использовать `skills` для повторного применения успешных планов.
6. Прогнать полный suite и зафиксировать этап.

## 6. Файлы этапа

Добавлены:

* `src/delamain/__init__.py`
* `src/delamain/models.py`
* `src/delamain/sandbox.py`
* `src/delamain/actions.py`
* `src/delamain/memory.py`
* `src/delamain/planner.py`
* `src/delamain/runtime.py`
* `src/delamain/__main__.py`
* `tests/test_delamain_sandbox.py`
* `tests/test_delamain_memory.py`
* `tests/test_delamain_planner.py`
* `tests/test_delamain_runtime.py`
* `docs/DELAMAIN_LOCAL.md`
* `docs/STAGE7_REPORT.md`

Изменены:

* `pyproject.toml` — пакет `src.delamain`;
* `docs/INDEX.md`, `README.md`, `CHANGELOG.md`.
