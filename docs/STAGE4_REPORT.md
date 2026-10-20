# Этап 4 — отчёт

Цель этапа: убрать мёртвый код и явный мусор, исправить мелкие реальные
баги. Без большого рефакторинга `agent.py` и без погони за покрытием.

## 1. Инструмент: `tools/hygiene_scan.py`

Чтобы не править «на глаз», добавлен AST-сканер. Он ищет:

| Тип | Что значит |
|---|---|
| `unused-import` | импорт, имя которого нигде не используется |
| `bare-except` | `except:` без типа (ловит и `KeyboardInterrupt`) |
| `mutable-default` | `def f(x=[])`, `def f(x={})`, `x=set()` |
| `duplicate-def` | второе определение функции/класса в той же области |
| `silent-except` | `except ...: pass` — ошибка исчезает |
| `todo` | `# TODO` / `# FIXME` |

Сканер понимает `__all__`, `__init__.py` (реэкспорт), `@property`-сеттеры,
`@overload`, `# noqa` и не считает проблемой `from __future__ import ...`.

```bash
python tools/hygiene_scan.py
python tools/hygiene_scan.py --path src --kind bare-except
python tools/hygiene_scan.py --json report.json
```

## 2. Что найдено и исправлено

### 2.1. Мёртвые импорты

До: **183** срабатывания `unused-import` (включая ложные на `__future__`).
Удалены неиспользуемые импорты в **74 файлах**: `typing`-имена, stdlib и
явный мусор вроде `flush_logs`/`UserPromptHandler`/`ContextAwareness` в
`agent.py`, `EventBus`/`Event` в `nursery_watcher.py`,
`ReflectionEngine` в `lifecycle_manager.py`.

После: **0** `unused-import` во всём проекте (140 файлов).

Импорт `numpy` в `voice.py` оставлен осознанно — он проверяет наличие
зависимости для распознавания речи, помечен `# noqa`.

### 2.2. Пустые модули

Удалены 6 файлов нулевого размера, на которые никто не ссылается:

* `src/action/output_generator.py`
* `src/cognition/reasoning_engine.py`
* `src/evolution/self_modification.py`
* `src/memory/knowledge_base.py`
* `src/perception/input_handler.py`
* `src/safety/guardrails.py`

### 2.3. Обработка ошибок

* `reflection_engine.save_reflection_report` — `except:` заменён на
  `(OSError, json.JSONDecodeError, TypeError)`. Битый JSON отчётов больше не
  маскирует `KeyboardInterrupt`.
* `internal_motivation._generate_goal_for_need` — `except:` заменён на
  `(KeyError, IndexError, ValueError)`: шаблон с неизвестным плейсхолдером
  не должен глотать всё подряд.
* `higher_cognition.Will.define_goal(values=[])` — изменяемое значение по
  умолчанию заменено на `None`.
* `agent.py`: подключение `NurseryWatcher` и `HealthDashboard`, лимит
  концепций и укрепление `core_self` больше не завершаются молчаливым
  `pass` — ошибка попадает в лог.

### 2.4. Реальный баг: локальный поиск зависел от текущей папки

`ThinkingPipeline._get_src_file_index()` обходил `src` относительно
`cwd` и глушил любые исключения. Если агент запускался не из корня
проекта (трей, инструменты, тесты), индекс оказывался пустым — локальный
поиск по коду молча не работал.

Теперь индекс строится от `project_root()` (через `src/core/paths.py`),
а `OSError` пишется в лог. Добавлен тест, который меняет `cwd` на
временную папку и проверяет, что индекс всё равно заполнен.

### 2.5. Тест, который проверял сам себя

`test_performance.test_save_knowledge_base_debounces` содержал копию
реализации `_save_knowledge_base` и проверял эту копию. Теперь тест
вызывает настоящий метод `DigitalBeing`, а результат проверяет по
изменению файла на диске.

## 3. Проверка

| Прогон | Результат |
|---|---|
| Полный suite | **421 passed, 2 skipped in 514,54 c (8:34)** |
| `compileall` (src/config/tests/tools/main) | OK |
| `git status data/` после прогонов | пусто |
| Сканер после правок | 0 unused-import, 0 bare-except, 0 mutable-default, 0 duplicate-def |

Новые тесты — `tests/test_stage4_hygiene.py` (7):

* сканер находит известные классы проблем на синтетическом файле;
* в `src`/`config` нет `except:` без типа;
* нет изменяемых значений по умолчанию;
* нет повторных определений;
* нет пустых модулей;
* битый JSON отчётов рефлексии не роняет агента;
* индекс `src` не зависит от `cwd`.

## 4. Что осознанно не трогали

* **56 `except ...: pass` в `src`** — в основном UI/трей и «лучше
  продолжить, чем упасть» (удаление временных файлов, публикация событий
  в GUI, необязательные подсистемы). Массовая замена на логирование
  добавила бы шум в лог, который этап 1 только что ограничил. Сканер их
  показывает; тесты на них не падают.
* **`agent.py`** — не разбирали на части: это отдельный большой этап.
* **Бенчмарки** — остаются медленными (основное время полного прогона).

## 5. Ограничения

* Сканер — не линтер: нет анализа потока данных, возможны ложные
  срабатывания на строковых аннотациях и динамическом доступе через
  `globals()`.
* `ruff`/`pyflakes` в проект не добавлены: лишняя зависимость ради этапа
  гигиены не нужна, AST-сканера достаточно для заявленных проверок.

## 6. Изменённые файлы

* `tools/hygiene_scan.py` — новый
* `tests/test_stage4_hygiene.py` — новый
* ~90 файлов — удалены мёртвые импорты и пустые модули, точечные правки
  обработки ошибок
* `src/cognition/thinking_pipeline.py` — индекс `src` от корня проекта
* `tests/test_performance.py` — тест debounce на реальном методе
* `README.md` — актуальное число тестов
