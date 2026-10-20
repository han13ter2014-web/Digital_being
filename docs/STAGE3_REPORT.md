# Этап 3 — отчёт

Цель этапа: тесты не должны писать в `data/` рабочей копии.

До этапа 3 запуск `pytest` мог изменить `data/knowledge_base.json`,
создать файлы в `data/memory`, `data/checkpoints`, `data/evolution`,
`data/cooperation`, `data/metrics` — тесты проверяли логику агента,
а побочным эффектом трогали данные пользователя.

## 1. Что сделано

### 1.1. Единая точка путей

Новый модуль `src/core/paths.py`:

```python
data_path("logs", "agent_log.txt")   # data/logs/agent_log.txt
data_dir()                           # учитывает DIGITAL_BEING_DATA_DIR
```

Переменная окружения `DIGITAL_BEING_DATA_DIR` перенаправляет **изменяемые**
данные. По умолчанию путь остался прежним (`data/`), поэтому поведение
обычного запуска не изменилось.

Чтение неизменяемых ресурсов (`data/initial_knowledge.json`,
`data/i18n/*.json`) осталось от корня проекта: это ассеты, а не данные
пользователя.

### 1.2. Куда проведён `data_path`

| Модуль | Что перенаправлено |
|---|---|
| `src/core/agent.py` | `knowledge_file`, каталоги `checkpoints`/`logs`, подсистемы, ментальные модели |
| `src/core/buffered_logger.py` | `agent_log.txt` |
| `src/core/agent_runner.py` | каталог чекпоинтов |
| `src/core/checkpoint_serializer.py` | каталог чекпоинтов (константа `DEFAULT_CHECKPOINT_DIR` оставлена для совместимости) |
| `src/core/subsystems/knowledge_base.py` | `knowledge_base.json` |
| `src/core/subsystems/checkpoint_manager.py` | каталог чекпоинтов |
| `src/core/subsystems/architecture_proposal.py` | предложения по самоизменению |
| `src/core/subsystems/mind_dream.py` | «Ясли» (`data/nursery`) |
| `src/memory/long_term_memory.py` | долговременная память |
| `src/cognition/agent_cooperation.py` | состояние кооперации |
| `src/cognition/reflection_engine.py` | отчёты рефлексии |
| `src/evolution/self_evolution_analyzer.py` | история самоизменений |
| `src/metrics/metrics_collector.py` | экспорт метрик |
| `config/settings.py` | `Settings.DATA_DIR` |
| `main_tray.py` | лог и каталоги трея |

### 1.3. Изоляция в тестах

`tests/conftest.py` при импорте:

1. создаёт временную папку `db_test_data_*`;
2. выставляет `DIGITAL_BEING_DATA_DIR`;
3. создаёт в ней подкаталоги (`logs`, `checkpoints`, `memory`, …);
4. удаляет папку после прогона.

Так как `conftest.py` загружается раньше тестовых модулей, все импорты
`src.*` видят уже подменённый путь.

Дополнительно `pytest_terminal_summary` сравнивает снимок `data/` до и
после прогона и печатает предупреждение, если тесты всё-таки что-то
изменили. Каталог `data/logs` исключён из проверки: там может писать
живой агент пользователя.

### 1.4. `test_tray_smoke.py`

Раньше это был скрипт с побочными эффектами на уровне модуля: он
запускался при сборе тестов, писал в `data/logs` рабочей копии и давал
`0 collected, exit code 5`.

Теперь это обычный pytest-тест:

* по умолчанию **пропускается** (поднимает GUI/трей);
* запускается явно: `RUN_TRAY_SMOKE=1 python -m pytest tests/test_tray_smoke.py`;
* агент стартует с изолированным `DIGITAL_BEING_DATA_DIR`;
* проверяется, что лог создан во временной папке и содержит путь к ней.

### 1.5. `test_performance.py`

Тест debounce писал в `data/test_kb_debounce.json`. Теперь использует
`tmp_path` и убирает за собой.

## 2. Проверка

| Прогон | Результат |
|---|---|
| Затронутые модули + интеграция | **358 passed, 2 skipped** (2:55) |
| `long_run` + dashboard + benchmarks | **48 passed** (14:18) |
| `git status data/` после прогонов | **пусто** |
| Smoke 300 циклов | 0 ошибок, 0 плохих декомпозиций, KB 36 |

Проверка изоляции — `tests/test_stage3_isolation.py` (9 тестов):

* `data_dir()` указывает на временную папку;
* `Settings.DATA_DIR`, `BufferedLogger`, `KnowledgeSubsystem`,
  `CheckpointSerializer` по умолчанию изолированы;
* сохранение KB не меняет `data/knowledge_base.json` рабочей копии;
* у живого `DigitalBeing` все пути (`knowledge_file`, чекпоинты, память)
  лежат внутри временной папки.

## 3. Как пользоваться

Отдельный профиль данных (не трогая `data/` проекта):

```powershell
$env:DIGITAL_BEING_DATA_DIR = "C:\digital_being_profiles\test"
python main.py
```

Тесты делают это автоматически.

## 4. Честные ограничения

* `tools/integration_smoke.py` и другие ручные инструменты по-прежнему
  работают с относительным `data/` — это осознанно: они запускаются
  человеком из корня проекта.
* Проверка утечек исключает `data/logs`, чтобы не конфликтовать с живым
  агентом. Сами тесты логи пишут во временную папку.
* Полный suite всё ещё медленный (отдельная задача этапа 4/5):
  benchmarks и dashboard-тесты занимают основное время.

## 5. Изменённые файлы

* `src/core/paths.py` — новый
* `tests/conftest.py` — изоляция данных и предупреждение об утечках
* `tests/test_stage3_isolation.py` — новый (9 тестов)
* `tests/test_tray_smoke.py` — переписан как pytest-тест
* `tests/test_performance.py` — `tmp_path` вместо `data/`
* `config/settings.py`, `main_tray.py` — поддержка `DIGITAL_BEING_DATA_DIR`
* перечисленные выше модули — пути через `data_path`

## 6. Что осталось

* Этап 4: гигиена кода (дубли, мёртвые импорты, `agent.py` как божественный
  объект — без большого рефакторинга).
