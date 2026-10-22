# Этап 12 — отчёт: мост когнитивных целей и Delamain

**Дата:** 2026-10-22.
**Статус:** готово; мост выключен по умолчанию
(`DELAMAIN_BRIDGE_ENABLED=False`), поведение этапов 7–11 сохранено.

## 1. Цель этапа

До этого этапа в проекте жили две независимые модели целей:

* `GoalSubsystem` — когнитивные цели вида «выучить Python», «собрать
  факты», «написать отчёт»;
* таблица `goals` в SQLite Delamain — исполняемые цели с `command` или
  явным `plan`.

Агент мог думать о цели, но не мог автоматически превратить её в
действие. Нужен был мост, который:

* связывает **активную** когнитивную цель не более чем с одной
  исполняемой целью Delamain;
* не угадывает команду из естественно-языкового названия;
* переживает повторные `tick`, перезапуск и потерю in-memory ссылки;
* различает ожидание approval, выполнение, успех и провал;
* проверяет явный success predicate после выполнения;
* не ломает существующее поведение по умолчанию;
* показывает связь в `/delamain goals`, `/goals`, `/status` и
  `/delamain status`.

Этап не добавляет новых опасных действий. Он только связывает уже
существующий исполняемый слой с уже существующей когнитивной моделью.

## 2. Что сделано

### 2.1. Опциональный `GoalBridge`

Новый модуль `src/delamain/goal_bridge.py` содержит:

* `GoalBridge` — синхронизацию активной цели и очереди Delamain;
* `derive_bridge_status()` — вывод статуса моста из строки SQLite;
* `bridge_summary()` — счётчики для общего статуса;
* `evaluate_success_predicate()` — безопасную проверку postcondition.

Мост включается только при одновременном выполнении условий:

1. `DelamainSubsystem` включена (`DELAMAIN_ENABLED=1`, config или
   `/delamain on`);
2. `DELAMAIN_BRIDGE_ENABLED=1` (или `bridge_enabled=True` в конструкторе).

По умолчанию оба флага выключены. Без явного включения импорт и создание
подсистемы не открывают SQLite и не создают целей.

### 2.2. Явный executable-payload

Связь не выводится из названия цели. Когнитивная цель должна явно
содержать `goal["execution"]`:

```python
agent.set_goal(
    "Написать отчёт",
    command="запиши в notes/report.txt: ready",
    success_predicate="file_contains:notes/report.txt:ready",
)
```

Поддерживаются формы:

* `execution = {"command": "...", "success_predicate": "..."}`;
* `execution = {"plan": [ActionRequest, ...]}`;
* строка как `command`;
* список как явный `plan`;
* совместимые ключи `delamain_command` / `delamain_plan`.

`GoalSubsystem.set_goal()` расширен необязательными keyword-only
параметрами `command`, `plan`, `success_predicate`. Для уже созданной
цели есть `GoalSubsystem.attach_execution(goal_id, ...)`, который по
умолчанию не перезаписывает существующий payload.

Если payload нет, мост ничего не делает: чисто когнитивная цель остаётся
когнитивной.

### 2.3. Одна когнитивная цель → одна исполняемая цель

При первом `tick` мост:

1. берёт только `GoalSubsystem.active_goal`;
2. проверяет наличие executable-payload;
3. ищет уже существующую Delamain-цель по metadata:
   `bridge_source=goal_subsystem`, `cognitive_goal_id`, `cognitive_agent`;
4. создаёт новую цель только если не нашёл ни одной;
5. записывает `delamain_goal_id` и `delamain_bridge` обратно в словарь
   когнитивной цели.

Повторные `tick` не создают дублей. Если in-memory ссылка потеряна
(например, старый checkpoint), мост находит цель в SQLite по metadata и
привязывается к ней. Если найдено несколько старых целей, выбирается
последняя; новая не создаётся.

### 2.4. Статусы моста

Delamain хранит только `pending/done/failed`. Мост добавляет два
наблюдаемых состояния:

| Статус | Значение |
|---|---|
| `pending` | цель создана, но ещё не выполнялась |
| `in_progress` | выполнение началось, есть попытка или approval уже одобрен |
| `waiting_approval` | план ждёт `/delamain approve` или `/delamain reject` |
| `done` | действие выполнено и success predicate пройден |
| `failed` | reject, ошибка действия или невыполненный predicate |

`waiting_approval` **не** считается провалом когнитивной цели. Цель
остаётся активной, progress поднимается до промежуточного значения, а
повторные `tick` не создают второй approval.

Статус хранится в двух местах:

* `cognitive_goal["delamain_bridge"]` — для `/goals` и checkpoint;
* `goals.metadata["bridge_status"]` в SQLite — чтобы пережить перезапуск
  и показать predicate-failure в `/delamain goals`.

### 2.5. Approve и reject

После `sub.approve()` и `sub.reject()` мост синхронизируется сразу, не
ожидая следующего `tick`.

```text
cognitive goal
      │  executable payload
      ▼
Delamain goal (pending)
      │
      ├── approval не нужен → run → done
      ├── нужен approval → waiting_approval
      │        ├── approve → run → done
      │        └── reject  → failed (без skill-failure)
      └── ошибка действия → failed (skill-failure пишет Delamain)
```

Reject переводит когнитивную цель в `failed` с понятной причиной
(`approval rejected: <причина>`), но не пишет failure в `skills`, потому
что ни одно действие не выполнялось.

### 2.6. Success predicate

После успешного выполнения Delamain-цели мост проверяет
`success_predicate`. Поддержан маленький детерминированный словарь:

| Predicate | Проверка |
|---|---|
| пусто, `ok`, `execution_ok` | задача Delamain завершилась успешно |
| `file_exists:<path>` | файл существует внутри workspace |
| `file_contains:<path>:<text>` | файл содержит подстроку |

Неизвестный predicate **fail-closed**: мост не вызывает `eval`, не
исполняет код и помечает связь как `failed` с причиной
`unsupported success predicate`.

Если действие выполнено, а predicate не пройден:

* Delamain-цель остаётся `done`;
* skill success сохраняется — действие действительно выполнилось;
* bridge-статус становится `failed`;
* когнитивная цель становится `failed`, чтобы агент перешёл к следующей,
  а не завис на недостигнутой цели.

### 2.7. Прогресс и следующая цель

Мост обновляет `_goal_progress`:

* `pending` → 10%;
* `waiting_approval` → 25%;
* `in_progress` → 60%;
* `done` → 100%.

Успех вызывает обычный `agent.complete_goal()`, поэтому начисляется
reward, обновляется `completed_goals` и активируется следующая
`pending`-цель. Провал вызывает новый
`GoalSubsystem.fail_goal(goal_id, reason)`: цель получает статус
`failed`, `failed_at` и `failure_reason`, счётчик завершённых не растёт,
активируется следующая цель.

На следующем `tick` мост видит новую активную цель и, если у неё есть
payload, создаёт для неё ровно одну исполняемую цель. Так замыкается
контур «цель → действие → память → следующая цель».

### 2.8. Отображение

* `/delamain goals` показывает `cognitive=#<id>/<bridge_status>` и
  ожидающий approval;
* `/delamain status` показывает `linked`, `waiting`, `done`, `failed` и
  последнюю ошибку моста;
* `/goals` показывает Delamain-цель активной когнитивной цели;
* `/status` показывает сводку моста, если он включён.

## 3. Изменённые файлы

| Файл | Изменение |
|---|---|
| `src/delamain/goal_bridge.py` | новый мост, статусы, predicate, дедупликация |
| `src/delamain/subsystem.py` | `bridge_enabled`, metadata в `queue_goal`, синхронизация в `tick`/`approve`/`reject`, `get_goal`, статус |
| `src/core/subsystems/goal_manager.py` | executable-payload, `attach_execution`, `fail_goal`, счётчик failed |
| `src/core/agent.py` | проброс `command/plan/success_predicate` через `set_goal` |
| `src/core/agent_runner.py` | отображение связи в `/delamain goals`, `/goals`, `/status`, логах |
| `config/simulation_config.py` | `DELAMAIN_BRIDGE_ENABLED=False` |
| `src/delamain/__init__.py` | экспорт bridge API |
| `tests/test_delamain_goal_bridge.py` | 13 тестов этапа |

## 4. Тесты

Новый набор `tests/test_delamain_goal_bridge.py` — **13 тестов**:

1. выключенный мост не создаёт цель и не пишет файл;
2. повторные `tick` создают ровно одну Delamain-цель;
3. успех завершает когнитивную цель и ставит progress 100%;
4. pending approval оставляет когнитивную цель активной и не дублируется;
5. approve выполняет план и завершает когнитивную цель;
6. reject даёт понятную причину, но не пишет skill-failure;
7. невыполненный success predicate даёт bridge `failed`, сохраняя
   успех действия в `skills`;
8. потерянная in-memory ссылка переиспользует существующую цель;
9. цель без payload игнорируется;
10. сводка моста и статус цели видны в `subsystem.status()`;
11. `/delamain goals`, `/goals` и `/status` показывают связь;
12. после завершения первой цели мост связывает следующую;
13. predicate fail-closed и не поддерживает `eval`-подобные выражения.

Целевые прогоны:

```text
tests/test_delamain_goal_bridge.py                         13 passed
Delamain suite (8 файлов)                                  74 passed
integration + stage5 + checkpoint + bridge                 79 passed
```

Полный прогон:

```text
python -m pytest -q
509 passed, 2 skipped in 1193.76s (0:19:53, включая benchmarks)
```

## 5. Ограничения и не-цели

* Мост не переводит естественный язык в команды. Название цели без
  payload ничего не запускает.
* Мост не является новым планировщиком: он использует существующие
  `HeuristicPlanner`, `OllamaPlanner` и `ActionRegistry`.
* `in_progress` — наблюдаемое состояние, а не отдельный фоновый процесс.
  Runtime синхронный, поэтому «в процессе» означает попытку/одобренный
  approval, а не параллельное выполнение.
* Проваленная когнитивная цель не перезапускается автоматически. Для
  повторной попытки нужна новая цель или явное действие пользователя.
* Success predicate намеренно маленький. Расширение словаря должно
  оставаться явным и безопасным, без `eval`.
* Связь привязана к `agent_name`; переименование агента может потребовать
  повторной привязки.
* Флаг моста читается при создании подсистемы. Отдельной команды
  `/delamain bridge on` нет; `/delamain on` включает только runtime.
* Мост не отменяет sandbox и approval. Он лишь вызывает уже существующий
  исполняемый слой.

## 6. Совместимость

* По умолчанию мост выключен, Delamain-поведение этапов 7–11 не меняется.
* `GoalSubsystem.set_goal(title, difficulty)` и
  `agent.set_goal(title, difficulty, activate)` работают как раньше;
  новые параметры keyword-only.
* `get_status()` получил дополнительный ключ `failed`; существующие
  ключи не изменены.
* `queue_goal()` получил необязательный `metadata`; старые вызовы
  работают без изменений.
* `list_goals()` для bridge-целей дополняется `bridge_status` и
  `cognitive_goal_id`, не меняя статусы SQLite.

## 7. Следующий этап

1. Добавить пользовательскую команду, которая прикрепляет executable-payload
   к существующей когнитивной цели, не требуя Python API.
2. Добавить backoff и перепланирование после ошибки действия, не создавая
   дублей когнитивной цели.
3. Расширить безопасный словарь success predicate (например, проверка
   нескольких файлов или JSON-поля) без перехода к `eval`.
4. Показать историю bridge-переходов в веб-дашборде.
5. Разрешить LLM предлагать executable-payload, но только через явное
   подтверждение пользователя и существующий approval.
6. Прогнать полный набор и зафиксировать этап в CHANGELOG.
