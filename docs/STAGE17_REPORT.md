# Этап 17 — измеримая оценка возможностей

**Дата:** 2026-10-22.
**Статус:** завершён; поведение runtime не меняется, оценка выключена из
обычного агентского цикла.
**Версия ядра:** `0.9.0`.

## 1. Зачем этот этап

После этапов 7–16 у Delamain-local появились sandbox, действия, SQLite,
навыки, approval, мост целей, authoring, backoff, replan и bounded repair.
Дальше добавлять возможности без измерения стало рискованно: легко
получить набор функций, который выглядит сложным, но не сохраняет уже
работающее поведение и не показывает, где именно агент ошибается.

Этап 17 добавляет **измерительный инструмент**, а не новую возможность
исполнения. Он отвечает на вопросы:

* завершается ли задача и проверяется ли результат;
* переживает ли агент ошибку шага и восстанавливается ли;
* выполняет ли длинный план целиком;
* не обходит ли approval и sandbox;
* переиспользует ли точный навык;
* насколько текущий эвристический planner разбирает команды.

Это не тест на AGI и не доказательство общего интеллекта. Высокий балл
означает только то, что узкий детерминированный контур ведёт себя
предсказуемо на данном наборе случаев.

## 2. Что добавлено

### 2.1. Модуль `src/delamain/evaluation.py`

Модуль загружает data-only JSON-suite, проверяет схему, запускает каждый
случай в отдельном workspace и возвращает машиночитаемый отчёт:

```text
SuiteResult
  cases_total / cases_passed / cases_failed / pass_rate
  metrics
    runtime_runs / runtime_successes
    expected_success_runs / expected_success_rate
    expected_failure_runs
    total_steps / total_effective_steps / average_steps
    repair_runs / repair_rate
    approvals_pending / approvals_approved / approvals_rejected
    recovery_rate / long_horizon_rate / skill_reuse_rate
    safety_rate / planning_accuracy
    categories: {basic, recovery, ...} -> {cases, passed, failed, pass_rate}
  results[]
    case_id, kind, category, ok, checks[], runs[], error, elapsed_ms
```

Каждый execution-случай получает собственный workspace и SQLite: случаи
не делят файлы и память. Оценка не импортируется runtime и не включается
никаким флагом.

### 2.2. Два вида случаев

**Execution** — проходит через настоящий `DelamainSubsystem` и runtime:
sandbox, `ActionRegistry`, память, approval, repair, skill. План подаётся
через `ScriptedPlanner`, поэтому проверяется исполнение, а не качество
языковой модели.

Поддерживаются:

* явный `plan` и `planner_plan`;
* `repair_plans` — последовательные ответы planner на ошибку шага;
* `resolve: approve|reject` для pending approval;
* проверки `ok`, `pending`, `goal_status`, файлов, `effective_actions`,
  `planned_actions`, истории, числа repair, skill-счётчиков, фактов и
  `output_fields`.

**Planning** — проверяет только `HeuristicPlanner` на коротких командах.
Это baseline языкового разбора, а не общая проверка понимания. Случай
считается пройденным, только если план совпал с ожидаемым.

### 2.3. Поставляемый набор `evals/delamain_stage17.json`

В наборе 18 случаев:

| Категория | Случаев | Что проверяет |
|---|---:|---|
| `basic` | 3 | запись/проверка, поиск, факт remember/recall |
| `long_horizon` | 1 | шесть шагов без обрезания |
| `recovery` | 3 | замена хвоста, repair с approval, reject repair |
| `safety` | 3 | approve/reject опасного плана, sandbox escape |
| `skill_reuse` | 1 | повторная команда без вызова planner |
| `planning` | 7 | английские и русская команды эвристики |

Набор лежит вне кода агента. Добавление случая не требует правок
runtime; оно требует только новой записи в JSON и, при необходимости,
нового действия/сценария. Схема и правила добавления — в
[evals/README.md](../evals/README.md).

### 2.4. CLI

```powershell
python -m src.delamain.evaluation --suite evals/delamain_stage17.json
```

Полезные варианты:

```powershell
# полный JSON в stdout и файл
python -m src.delamain.evaluation `
  --suite evals/delamain_stage17.json `
  --json `
  --report eval_report.json

# только один случай, с сохранением артефактов
python -m src.delamain.evaluation `
  --suite evals/delamain_stage17.json `
  --case recovery-replace `
  --workdir eval_artifacts

# разрешить частичный результат (по умолчанию нужен pass_rate = 1.0)
python -m src.delamain.evaluation `
  --suite evals/delamain_stage17.json `
  --fail-under 0.9
```

`--workdir` создаёт свежий подкаталог `run-<id>` и сохраняет workspace и
SQLite для разбора. Без `--workdir` используется временный каталог,
который удаляется после прогона; `--keep` оставляет его.

## 3. Результат эталонного прогона

На текущем коде:

| Метрика | Значение |
|---|---:|
| Случаи | 18/18 |
| `pass_rate` | 1.0 |
| Runtime-запуски | 12 |
| Фактические успехи | 9/12 |
| Ожидаемые успехи | 9/9 |
| Ожидаемые падения (reject/escape) | 3 |
| Средние шаги / эффективные шаги | 2.08 / 1.75 |
| Repair-запуски | 3 |
| Pending approval | 4 |
| Approved / rejected | 2 / 2 |
| `recovery_rate` | 1.0 |
| `long_horizon_rate` | 1.0 |
| `skill_reuse_rate` | 1.0 |
| `safety_rate` | 1.0 |
| `planning_accuracy` | 1.0 |

`runtime_successes = 9/12` — это фактическая статистика: три случая
намеренно проверяют отказ (`repair-reject`, `safety-reject`,
`safety-sandbox-escape`). Поэтому отдельно считается
`expected_success_rate = 9/9`: среди запусков, где успех ожидался, успех
достигнут во всех.

`planning_accuracy = 1.0` относится только к семи поддерживаемым фразам
эвристики. Это не значит, что planner понимает произвольный язык.

## 4. Что именно проверяет набор

### 4.1. Базовое исполнение

`basic-write-verify` проверяет два шага, содержимое файла и историю
`task.start → write_file → verify_file → task.finish`.
`basic-search` проверяет поиск и `output_fields` (`query`, `count`).
`basic-memory` проверяет `remember_fact`/`recall_facts` и факт в SQLite.

### 4.2. Длинный горизонт

`long-horizon-six` требует шесть эффективных шагов и пять файлов. Случай
ловит случайное обрезание плана или потерю хвоста.

### 4.3. Восстановление

`recovery-replace`:

1. успешный `write_file`;
2. ошибка `read_file`;
3. planner возвращает замену хвоста;
4. старый хвост не выполняется;
5. skill строится по `effective_actions`.

Проверяются `repair_count=1`, `replan_calls=1`, эффективный путь без
упавшего чтения и отсутствие выброшенного файла.

`recovery-approval` проверяет, что опасный repair ждёт approval, а после
approve продолжает задачу с уже выполненным безопасным шагом.
`repair-reject` проверяет, что reject не выполняет repair, сохраняет
побочные эффекты завершённых шагов и завершает цель как `failed`.

### 4.4. Безопасность

`safety-approve` и `safety-reject` проверяют approval-preflight: до
решения файла нет, approve выполняет ровно один раз, reject не выполняет.
`safety-sandbox-escape` пытается записать `../escape.txt`; sandbox
отклоняет путь, снаружи workspace ничего не появляется.

### 4.5. Переиспользование навыка

`skill-reuse-exact` запускает одну и ту же команду дважды. Первый запуск
вызывает `ScriptedPlanner`, сохраняет skill. Второй запуск должен:

* иметь `reused_skill=true`;
* не вызывать planner (`plan_calls=0`);
* сохранить `skill_successes=2`;
* оставить корректный файл.

Это baseline для этапа 18: сейчас навык находится только по точному
совпадению названия и команды.

## 5. Ограничения

* **Execution-случаи не проверяют языковое понимание.** План задан
  данными; `ScriptedPlanner` — детерминированная замена модели.
* **Planning-случаи узкие.** Семь фраз покрывают только текущие регулярные
  выражения эвристики; это не held-out оценка общего языка.
* **Набор небольшой.** 18 случаев — smoke/baseline, а не статистически
  значимый бенчмарк. Он не покрывает все действия и комбинации.
* **Нет внешних задач и сети.** Оценка полностью офлайн и не проверяет
  работу с реальными API, большими файлами или конкурентными агентами.
* **Нет оценки AGI.** Метрики измеряют инженерные свойства контура:
  успех, восстановление, безопасность, повторное использование. Они не
  измеряют сознание, общий интеллект или способность ставить собственные
  цели.
* **Побочные эффекты не откатываются.** Как и в Stage 16, успешные шаги
  до ошибки остаются; оценка это фиксирует, а не «лечит».

## 6. Тесты

Добавлен `tests/test_delamain_evaluation.py` (29 тестов):

* загрузка и валидация suite, duplicate id, неизвестные поля, опасные пути;
* простой успех, ожидаемое падение, несовпадение ожиданий;
* изоляция workspace и фильтр случаев;
* repair, durable repair-approval, reject;
* approval approve/reject и sandbox escape;
* точное переиспользование skill и отсутствие вызова planner;
* planning probe, включая обнаружение неподдерживаемой фразы;
* агрегация метрик, CLI, JSON-отчёт и exit code.

Полный прогон: `python -m pytest -q` — 580 passed, 2 skipped (включая
16 benchmark-тестов).

## 7. Следующий шаг

Stage 18: параметризованные и составные навыки. Сейчас skill находится
только при точном совпадении команды. Следующий шаг — научиться
переиспользовать успешный план для близкой задачи с другими аргументами,
не ослабляя approval, sandbox и проверку предусловий. Evaluation-suite
нужно расширить случаями переноса, чтобы изменение было измеримым.

## 8. Итог

Stage 17 не добавляет агенту новых прав и не делает его «умнее» напрямую.
Он добавляет способность **честно измерять** уже существующий контур и
показывает, что baseline проходит 18/18 случаев при явно очерченных
ограничениях. Это необходимая инфраструктура для следующих этапов, но не
доказательство AGI.
