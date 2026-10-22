# Этап 13 — отчёт: безопасный authoring executable-payload для когнитивных целей

**Дата:** 2026-10-22.
**Статус:** готово; ручной `/goals exec` не требует отдельного флага, но
работает при включённом Delamain. Генерация proposal планировщиком
выключена по умолчанию (`DELAMAIN_GOAL_PROPOSAL_ENABLED=False`). Поведение
этапов 7–12 сохранено.

## 1. Цель этапа

После этапа 12 мост умел связать когнитивную цель с Delamain, но payload
приходилось задавать только из кода:

```python
agent.set_goal(
    "Написать отчёт",
    command="запиши в notes/report.txt: ready",
)
```

Из чата это было недоступно, а автоматически угадывать команду по названию
цели было бы нечестно и опасно. Этап 13 добавляет отдельный **authoring**
слой:

* пользователь может явно привязать команду к когнитивной цели;
* планировщик (эвристика или локальная LLM) может **предложить** план, но
  не исполняет его;
* proposal и решение сохраняются в metadata самой когнитивной цели;
* опасные шаги по-прежнему проходят через существующий approval;
* по умолчанию ничего не генерируется автоматически.

Этап не добавляет новых действий и не расширяет права агента. Он только
делает явное авторство payload удобным и наблюдаемым.

## 2. Что сделано

### 2.1. `GoalExecutionProposal`

Новый модуль `src/delamain/goal_authoring.py` содержит
`GoalExecutionProposal` — простое dataclass-описание предложения:

| Поле | Назначение |
|---|---|
| `command` | явная команда, если предложение ручное |
| `plan` | список шагов `{action, args}` |
| `success_predicate` | безопасная postcondition Stage 12 |
| `summary` | человекочитаемое описание плана |
| `files` | затронутые пути внутри workspace |
| `dangerous_actions` | шаги, помеченные `dangerous=True` |
| `requires_approval` | нужен ли approval при текущем режиме |
| `approval_mode` | `off`, `dangerous` или `all` на момент проверки |
| `source` | `manual`, `heuristic`, `planner` или `llm` |
| `planner_mode` | какой планировщик использовался |
| `status` | `pending`, `accepted`, `rejected` или `error` |
| `error` / `planner_error` | причина, если план не построен |
| `created_at` / `decided_at` | время создания и решения |
| `reason` | причина отклонения |

Proposal хранится в `goal["execution_proposal"]` как обычный dict, поэтому
переживает checkpoint без отдельной схемы. Решение хранится в
`goal["execution_decision"]`:

```json
{
  "accepted": true,
  "source": "manual",
  "proposal_source": "manual",
  "proposal_status": "accepted",
  "requires_approval": false,
  "dangerous_actions": ["write_file"],
  "decided_at": "..."
}
```

### 2.2. `GoalAuthoring`

`GoalAuthoring` — слой операций над `GoalSubsystem`:

* `build_manual()` — привязывает явную команду; proposal сразу получает
  статус `accepted`, потому что пользователь уже принял решение;
* `propose()` — просит настроенный planner построить план и сохраняет его
  как `pending`; ничего не привязывает и не исполняет;
* `accept()` — проверяет, что proposal всё ещё `pending`, повторно
  валидирует действия и привязывает payload;
* `reject()` — помечает proposal как `rejected`, не создавая execution.

Для ручного preview используется только `HeuristicPlanner`. Это делает
`/goals exec` быстрым и детерминированным и не вызывает LLM неожиданно.
Если эвристика не понимает команду, payload всё равно привязывается, но в
proposal сохраняется `planner_error`; реальный planner попробует разобрать
команду при выполнении. Если preview построил план с неизвестным действием,
payload **не** привязывается.

`propose()` использует настроенный runtime planner: эвристику или
`FallbackPlanner` с Ollama. Любой неизвестный action отклоняется до
`accept`, а опасные шаги вычисляются через
`ApprovalPolicy.dangerous_actions()` и `ApprovalPolicy.evaluate()`.

### 2.3. Команды чата

В `AgentRunner` добавлены подкоманды:

```text
/goals list
/goals show <id>
/goals exec <id> | <команда>
/goals exec <id> | <команда> | <success_predicate>
/goals propose <id>
/goals propose <id> | <задача>
/goals accept <id>
/goals reject <id> [причина]
```

`/goals` без подкоманды сохраняет прежний краткий вывод. `/goals list`
показывает все когнитивные цели и маркеры `exec`, `proposal=...`,
`delamain=#.../...`. `/goals show` показывает payload, predicate, proposal,
опасные действия, режим approval и связь с Delamain.

Пример ручного authoring:

```text
/goals exec 2 | запиши в notes/report.txt: ready | file_contains:notes/report.txt:ready
```

Пример безопасного proposal:

```text
/goals propose 2
/goals show 2
/goals accept 2
```

### 2.4. Ограничения и защита

* `/goals exec` не требует `DELAMAIN_GOAL_PROPOSAL_ENABLED`, но требует
  включённого Delamain: это явное действие пользователя, а не
  автоматическая генерация.
* `/goals propose` при выключенном флаге возвращает ошибку и ничего не
  сохраняет.
* Proposal не исполняется сам. До `accept` в SQLite Delamain не создаётся
  ни одной цели.
* Повторный `exec`/`accept` не перезаписывает существующий payload.
* При наличии pending proposal ручной `exec` просит сначала принять или
  отклонить его, чтобы не потерять решение.
* `accept` заново проверяет actions по живому `ActionRegistry` и обновляет
  `requires_approval` по текущей политике.
* `dangerous_actions` сохраняются даже при `approval_mode=off`; чат
  предупреждает, что принятие payload означает согласие на опасные действия
  без отдельного запроса.
* При `approval_mode=dangerous` или `all` выполнение по-прежнему
  останавливается до `/delamain approve <id>`.
* Для реального исполнения нужны `DELAMAIN_ENABLED=1` и
  `DELAMAIN_BRIDGE_ENABLED=1`; `/delamain on` включает runtime, но не мост.

## 3. Поток

```text
/goals propose <id>
        │
        ▼
GoalAuthoring.propose()
        │  planner (heuristic / LLM)
        ▼
GoalExecutionProposal(status=pending)
        │  сохраняется в goal["execution_proposal"]
        ├── /goals reject → status=rejected, execution не создаётся
        └── /goals accept
                │  повторная валидация actions
                ▼
        GoalSubsystem.attach_execution()
                │
                ▼
        GoalBridge (DELAMAIN_BRIDGE_ENABLED=1)
                │
                ▼
        Delamain approval → run → predicate → память
```

Ручной поток короче:

```text
/goals exec <id> | <команда>
        │
        ▼
GoalAuthoring.build_manual()
        │  heuristic preview + dangerous actions
        ▼
execution + proposal(status=accepted) + decision
        │
        ▼
GoalBridge → Delamain
```

## 4. Конфигурация

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DELAMAIN_GOAL_PROPOSAL_ENABLED` | `0` | разрешить `/goals propose`; ручной `exec` работает без этого флага при включённом Delamain |

Флаг также доступен как `DELAMAIN_GOAL_PROPOSAL_ENABLED` в
`config/simulation_config.py`. Env имеет приоритет. `GoalAuthoring.status()`
попадает в `/delamain status` строкой
`Authoring: on|off, proposals=on|off`.

## 5. Тесты

Новый файл `tests/test_delamain_goal_authoring.py` содержит 15 тестов:

* ручной attach, accepted-proposal, decision и фактическое выполнение;
* отказ от authoring при выключенном Delamain, без создания runtime;
* запрет повторного payload;
* pending proposal не исполняется до `accept`;
* reject не создаёт execution и не запускает действие;
* proposal выключен по умолчанию;
* неизвестное действие в LLM-плане отклоняется до attach;
* неизвестное действие в ручном preview отклоняется до attach;
* опасный proposal проходит существующий approval;
* естественно-языковой заголовок не угадывается эвристикой;
* LLM-подобный план остаётся proposal до `accept`;
* команды `/goals exec`, `list`, `show`;
* команды `/goals propose`, `accept`, `reject` и reason в решении;
* predicate в `/goals exec`;
* статус authoring в `/delamain status`.

Целевой прогон:

```text
28 passed
```

(15 новых тестов + 13 тестов Stage 12.)

Полный suite проекта:

```text
524 passed, 2 skipped in 949.61s (0:15:49, включая benchmarks)
```

## 6. Что не сделано

* Нет автоматического предложения payload для каждой новой когнитивной
  цели. Proposal создаётся только по явной команде.
* Нет отдельного UI-редактора плана: принять можно только proposal целиком.
* Нет семантического сопоставления названия цели с действиями. Эвристика
  по-прежнему понимает только явные команды, а LLM может ошибаться.
* Нет автоматического перепланирования после ошибки выполнения.
* Approval остаётся preflight-барьером, а не полноценной ОС-песочницей.

## 7. Итог

Stage 13 закрывает разрыв между «у агента есть когнитивная цель» и «есть
явный, проверяемый executable-payload». Ручной путь удобен и предсказуем,
LLM-путь ограничен предложением и явным принятием, а опасные действия
по-прежнему проходят через approval. Ядро работает без модели.
