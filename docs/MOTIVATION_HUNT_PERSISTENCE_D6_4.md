# D6-4 — Фактическое сохранение hunt-следа после restart

Дата: 2026-11-21.

Основание: `MOTIVATION_HUNT_PERSISTENCE_TICKET_D6_4.md`, решение владельца
D6-4 в `MOTIVATION_DECISION_GATE_D6.md`.

Статус: **implementation завершён локально и проверен**. Commit/push не
выполнялись. Живая сущность не запускалась.

## 1. Что изменено

Checkpoint получил необязательное верхнеуровневое поле `hunt_misses` —
копию отображения `{тема: cycle_count}` из `_hunt_misses`.

Production-diff ограничен тремя согласованными файлами:

- `src/core/checkpoint_serializer.py` — копия при сохранении, staged-разбор и
  атомарное применение при restore; legacy без поля означает `{}` и очищает
  прежний след агента;
- `src/core/checkpoint_validation.py` — side-effect-free проверка непустых
  строковых тем, целых неотрицательных циклов, запрет `bool` и значений выше
  `cycle_count`;
- `src/core/agent_creation.py` — обновлён комментарий; новая жизнь по-прежнему
  начинается с пустым следа.

`SCHEMA_VERSION`, миграции, cooldown 200, граница `<200` / `==200`, кандидаты,
арбитр, needs, WorldDelta, valence, обработчик поиска, соседние следы, сеть и
LLM не менялись. `agent_handlers.py` не изменялся.

## 2. Доказательство дефекта до исправления

До production-правки новые проверки показали:

- отсутствие `hunt_misses` в `build_state_from_agent()`;
- сохранение предварительно существующего следа вместо его замены snapshot-ом;
- повторный вызов поисковика после restore до истечения cooldown;
- отсутствие отказа на невалидные значения.

Контрольный запуск `tests/test_hunt.py::HuntRestartTests` на старом поведении
дал **3 failed**: активный cooldown не восстанавливался, success терял след
другой темы, а независимый поиск не сохранял прежнюю запись.

## 3. Приёмочная матрица

| ID | Фактическая проверка | Результат |
|---|---|---|
| H-01 | Непустой round-trip и отсутствие разделяемой ссылки | Пройдено |
| H-02 | Пустой round-trip | Пройдено |
| H-03 | Legacy очищает предварительно непустой след | Пройдено |
| H-04 | Restore: miss 10, текущий цикл 209 | Cooldown, вызовов search 0 |
| H-05 | Тот же след в цикле 210 | Один вызов, новый miss 210 |
| H-06 | Success после restore | Очищена только выбранная тема, знание сохранено |
| H-07 | Другая тема | Не заблокирована чужим cooldown |
| H-08 | Невалидные контейнеры, ключи и значения | Отклонены с путем `hunt_misses` |
| H-09 | Ошибка restore | Нет частичных или вложенных мутаций; исходные ссылки сохранены |
| H-10 | Вторая жизнь | След, вопросы, цель, needs и история первой жизни не наследуются |
| H-11 | `_news_reads`, `_web_browses`, `_shared_topics` | Прежнее поведение сохранено |
| H-12 | `save_state(force=True) → CheckpointSerializer.load() → apply_state_to_agent()` | Файловый restart и cooldown пройдены в изолированном `tmp/` |

Основные проверки находятся в `tests/test_checkpoint_validation.py`,
`tests/test_checkpoint_serializer.py`, `tests/test_hunt.py` и
`tests/test_checkpoint_backend_integration.py`. Прямой `act()` используется как
контрольный вызов обработчика, а не как естественный арбитраж.

## 4. Differential до/после

Новый test-only инструмент: `tests/observations/d6_4_hunt_persistence.py`.
Старые D5 harness и отчёт не изменялись. Для исходной ревизии использована
изолированная копия `977817f3c0961c659a0c562981b6da9dd0eeb683`; все данные
записаны в новые песочницы `tmp/motivation_d6_4/`. Реальная сеть не использовалась.

Сырые результаты:

- `tmp/motivation_d6_4/differential_before.json`;
- `tmp/motivation_d6_4/differential_after.json`;
- проверенная сводка: `tmp/motivation_d6_4/differential_summary.json`.

Команды:

```bash
.venv/Scripts/python.exe tmp/motivation_d6_4/prepare_baseline.py
PYTHONPATH="C:\Users\GamePK\digital_being\tmp\motivation_d6_4\baseline" .venv/Scripts/python.exe tmp/motivation_d6_4/baseline/tests/observations/d6_4_hunt_persistence.py --label before --output tmp/motivation_d6_4/differential_before.json
.venv/Scripts/python.exe tests/observations/d6_4_hunt_persistence.py --label after --output tmp/motivation_d6_4/differential_after.json
.venv/Scripts/python.exe tmp/motivation_d6_4/summarize_differential.py
```

Наблюденные различия:

- D5-06: старая ревизия стёрла `{"память": 10}` и повторно вызвала поиск;
  новая восстановила след и вернула cooldown без вызова.
- Новый restart-сценарий: при разнице 199 старая ревизия вызвала поиск один
  раз, новая — ноль; при разнице 200 обе вызвали поиск один раз, новый miss
  стал 210.
- Legacy: старая ревизия оставила посторонний `{"stale": 1}`, новая применила
  пустой snapshot `{}`.

Наблюденная неизменность:

- без restart результаты и вызовы при 199/200 совпали;
- success, exception, disabled, denied и поиск другой темы совпали;
- вторая жизнь изолирована по всем контрольным полям;
- D5-07 сохранил разрешённый вызов: последний записанный miss остался в цикле
  0, естественный проход в цикле 200 не вызвал handler, поэтому restart+1
  соответствует разнице 201, а не активному cooldown.

## 5. Regression и статические проверки

Целевые проверки после исправления:

```bash
.venv/Scripts/python.exe -m pytest tests/test_checkpoint_validation.py tests/test_checkpoint_serializer.py tests/test_hunt.py tests/test_checkpoint_backend_integration.py -q
```

Результат: **139 passed in 1.44s**.

Обязательный профиль (повтор после финального форматирования):

```bash
.venv/Scripts/python.exe -m pytest tests/test_checkpoint_validation.py tests/test_checkpoint_serializer.py tests/test_checkpoint_subsystem.py tests/test_checkpoint_migrations.py tests/test_checkpoint_backend_integration.py tests/test_checkpoint_sqlite_mirror.py tests/test_hunt.py tests/test_loop_integration.py tests/test_web_search.py tests/test_unified_motivation.py -q
```

Результат: **244 passed in 4.23s**.

Полный regression:

```bash
.venv/Scripts/python.exe -m pytest -q
```

Результат: **4072 passed, 2 skipped in 548.04s (0:09:08)**.

Статические гейты:

```bash
.venv/Scripts/python.exe -m ruff check src/ config/ tests/ main.py main_tray.py
.venv/Scripts/python.exe -m ruff format --check src/ config/ tests/ main.py main_tray.py
.venv/Scripts/python.exe -m mypy --config-file pyproject.toml --explicit-package-bases --no-site-packages --follow-imports=skip main.py main_tray.py
.venv/Scripts/python.exe -m bandit -q -r src/ config/ main.py main_tray.py -ll --skip B101,B601
.venv/Scripts/python.exe -m compileall -q src/ config/ tests/ main.py main_tray.py
git diff --check
```

Все прошли: Ruff — `All checks passed`; format — `581 files already formatted`;
Mypy — `Success: no issues found in 2 source files`; Bandit завершился без
findings уровня `-ll` (выведены только предупреждения о `nosec`); compileall и
`git diff --check` завершились успешно. Изменённые файлы отдельно прошли
compileall, Ruff и Ruff format.

## 6. Граница и сохранность

Живой `data/`: 1278 файлов сопоставлены до/после по относительному пути,
размеру, `mtime_ns` и SHA-256. Manifest-файлы идентичны; SHA-256 обоих manifest:
`42f2c3b9880d411b4769b58e946a0e5a8a303e389f76f3e0d228e1fc8b3c5d4a`.
Живой профиль не изменён, реальная сеть в differential не использовалась.

D6-3 и D6-5 оставлены без ревизии по решению владельца. D7 и D8 завершены
2026-11-21 как документальные этапы; они не добавляли production-изменений к
этому implementation. Commit/push не выполнялись и требуют отдельного явного
разрешения.
