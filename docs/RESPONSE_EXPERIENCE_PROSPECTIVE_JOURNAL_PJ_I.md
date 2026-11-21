# RE-S1-PJ-I — production prospective journal, выключенный по умолчанию

Дата: 2026-11-21.

Базовая ревизия рабочего дерева: `977817f`. Изменения PJ-I не коммитировались и не
отправлялись. Контракт: `RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_TICKET.md`.
Предыдущая synthetic-проверка: `RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_PJ_V.md`.

Статус: **минимальный production writer реализован и выключен по умолчанию**.
Реальная жизнь не запускалась, флаг для неё не включался, живой `data/` не
использовался. Модель, веса, training runtime, advisor, речевая генерация и
candidate gate не создавались и не активировались. Естественные диалоги для
наполнения журнала не проводились. R0 readiness остаётся `insufficient_data`:
PJ-I создаёт возможность будущего наблюдения, но не добавляет реальных биографических
записей задним числом.

## 1. Разрешённая граница

Отдельное разрешение владельца покрывало только production writer, feature flag,
изолированные regression/resource-проверки и документацию. Оно не покрывало:

- включение журнала для реальной жизни и фазу PJ-A;
- запуск сущности или искусственные диалоги ради dataset;
- запись в живой `data/`;
- модель, обучение, advisor или влияние на выбор и речь;
- новые зависимости, сеть, commit или push.

Все созданные проверками SQLite находились в pytest `tmp_path` или отдельном
ignored-каталоге `tmp/response_experience_prospective/`.

## 2. Реализация

### 2.1. Writer и хранилище

Новый модуль `src/core/response_experience_journal.py` реализует синхронный
fail-open writer без сети, внешней очереди и фонового worker.

Writer открывается только при:

```text
DIGITAL_BEING_RESPONSE_JOURNAL=1
```

Без этого значения `AgentRunner` не открывает SQLite и не создаёт ни файл, ни
каталог журнала. Путь при включении:

```text
data/lives/<life_id>/response_experience_events.sqlite3
```

Зафиксированы:

- `journal_schema_version = 1`;
- `feature_contract_version = pj_structured_v1`;
- `writer_contract_version = pj_i_production_v1`;
- SQLite WAL, `synchronous=FULL`, `foreign_keys=ON`;
- `busy_timeout = 250 ms`;
- одна транзакция на событие и атомарное обновление `head`;
- монотонная per-life `event_sequence` и hash-chain;
- UPDATE/DELETE triggers для append-only `events`;
- проверка SQLite integrity, sequence, schema, life ID и hash-chain перед первым
  append после restart;
- sanitized runtime status без пути, текстов и payload.

Замороженные defaults:

| Бюджет | Значение |
|---|---:|
| События | 250 000 |
| Canonical payload | 16 KiB |
| Main DB + WAL | 64 MiB |

Для обычного события резервируется последний slot под `journal_gap`, чтобы event
budget не скрыл сам факт исчерпания. Storage budget проверяется **перед append** по
текущему размеру main DB + WAL. Это не абсолютный физический cap: один разрешённый
append может пересечь порог, после чего следующий append останавливается и writer
получает degraded/gap status. Автоматического pruning событий нет.

### 2.2. Только подтверждённые локальные переходы

`AgentRunner` записывает delivery только после непустого `message_id` и успешного
`ResponseExperience.register_delivery()` на существующих локальных путях
`send_reply` / `send_message`. Сам вызов `register_delivery()` универсальным
доказательством доставки не считается.

Не создают delivery:

- fallback `AGENT_THOUGHT`;
- отсутствие `message_id`;
- внешний session-scoped ответ;
- автономный tick без локальной доставки.

`_on_user_message()` получил тонкий wrapper: журнальные входы получают монотонные
`turn-1`, `turn-2`, …, а autonomous tick не расходует turn. `episode_id` и ID
событий детерминированы по life/profile/response. Exact retry возвращает прежнее
событие только при совпадении всей идентичности и payload; конфликт не перезаписывает
историю.

`ResponseExperience` получил runtime-only transition observer. Он вызывается после
фактических outcome, expiry и pruning, включая capacity-pruning в
`register_delivery()`. Observer не сериализуется и не добавляет полей в Core snapshot
или checkpoint. Ошибка наблюдателя не отменяет уже совершённый жизненный переход.

Шесть observed outcomes отделены от censored expiry:

- `answer`;
- `follow_up`;
- `unclassified_reply`;
- `ordinary_reply`;
- `explicit_support`;
- `explicit_opposition`.

`ttl_expired` получает `no_observed_reaction` и не становится observed outcome.
Orphan outcome получает `journal_gap` с `completeness=unverified`. Pruning ограничивает
текущее retained window, но не удаляет журнальный delivery/outcome.

`samples(outcome_before_sequence=...)` отдаёт только observed пары, доступные к
указанной границе sequence. Expired, orphan и ещё не наступивший относительно split
outcome в samples не попадают.

### 2.3. Repeat, профили и restore

Repeat origin вычисляется только по raw realization в текущем retained window в
памяти. В SQLite сохраняются лишь origin response ID и `retained_window`; raw text и
fingerprint не сохраняются. При pruning последующий repeat не объявляется первым в
жизни: недоступность более раннего origin остаётся ограничением evidence.

Временный `ResponseExperience` неактивного профиля при language consolidation
получает тот же observer, поэтому expiry/pruning неактивного профиля не теряются.
Вторая жизнь имеет отдельный файл, sequence и repeat graph.

После успешного `apply_state_to_agent()` вызывается `note_core_restore()`. Журнал не
откатывается и исходы не переписываются; расхождение фиксируется как
`core_restore_divergence` с `completeness=unverified`. Новых checkpoint-полей нет.

### 2.4. Privacy whitelist

Delivery payload содержит frozen structured features: намерение, контекст, источник,
ожидание, uncertainty flags, языковые категории, realization rule/act/kind, buckets
длины и ссылок, provenance flag, borrowed category и repeat metadata.

Production borrowed levels ограничены `situational` и `habit`. Динамические значения
схлопываются в `other`/`missing`.

В журнал не попадают:

- сырой вход или текст ответа;
- `observed_input`, `base_text` и borrowed expression;
- fingerprints и text hashes;
- reference IDs;
- динамические source/context/категории вне whitelist.

## 3. Ошибки, restart и конкуренция

Writer fail-open относительно жизни: ошибка append, payload/storage/event budget или
SQLite не отменяет доставку, память, сон и остановку. При этом полнота не скрывается:
status становится `degraded` или `quarantine`, создаётся gap, если он ещё доступен,
и увеличивается `dropped_events`.

`writer_leases(writer_id, process_id)` различает активный concurrent writer и прошлый
crash. Активный PID не считается unclean shutdown. Stale lease при новом открытии даёт
`previous_shutdown_unclean`; последний штатно закрывшийся writer выставляет
`clean_shutdown=1`.

При restart журнал продолжает проверенную sequence/hash. Повреждение обнаруживается до
append; `AgentRunner` получает unavailable writer в quarantine, а исходные строки не
исправляются и не заменяются новым пустым журналом. Жизнь и фактическая доставка
продолжаются.

`AgentRunner.stop()` закрывает observer/writer в `finally`, включая ранний return или
ошибку основной остановки. Повторный stop не создаёт второй `journal_stopped`; после
последнего close WAL/SHM закрываются, integrity подтверждается.

Exactly-once между внешней доставкой и SQLite **не заявляется**. Crash после внешней
доставки, но до commit журнала остаётся возможным окном потери; оно обозначается
unclean/gap, а не скрывается.

## 4. Приёмочная матрица

Новый `tests/test_response_experience_journal.py` содержит **27 passed** с учётом
шести parametrized outcome-кейсов.

| ID | Фактическое доказательство | Результат |
|---|---|---|
| PJ-01 | Подтверждённый `message_id`; missing ID/thought не создают delivery | PASS |
| PJ-02 | Шесть реальных observe transitions и отдельный censored expiry | PASS |
| PJ-03 | External session-scoped registration не создаёт локальное событие | PASS |
| PJ-04 | Реальные turn-1/turn-2, исходный episode и observation turn | PASS |
| PJ-05 | Atomic sequence/head, exact retry, concurrent writers | PASS |
| PJ-06 | `outcome_before_sequence` исключает поздний исход из прошлого | PASS |
| PJ-07 | Outcome не изменяет immutable delivery | PASS |
| PJ-08 | SQLite после WAL checkpoint не содержит секретных текстов/IDs/fingerprints | PASS |
| PJ-09 | Origin точен в retained window и ограничен pruning | PASS |
| PJ-10 | Consolidation pruning не удаляет журнальные outcomes | PASS |
| PJ-11 | Crash window и orphan получают unverified/degraded; samples пусты | PASS |
| PJ-12 | Injected failure и hard budgets не отменяют доставку/память | PASS |
| PJ-13 | Clean/unclean restart продолжает цепочку и обозначает gap | PASS |
| PJ-14 | Hash corruption quarantined до append; реальная доставка продолжается | PASS |
| PJ-15 | Вторая жизнь изолирована по файлу, sequence и repeat graph | PASS |
| PJ-16 | Core restore добавляет gap, не откатывает журнал/исход | PASS |
| PJ-17 | Disabled/enabled full-state и bus differential без различий | PASS |
| PJ-18 | Controlled artifact/RAM/write-pair resource budgets | PASS; ограничения в разделе 6 |
| PJ-19 | Idempotent stop, закрытый writer/WAL и `integrity_check=ok` | PASS |
| PJ-20 | Default-off; нет модели, advisor, речи или candidate gate | PASS |

## 5. Выполненные проверки

### 5.1. Новые и профильные regressions

```text
.venv/Scripts/python.exe -m pytest tests/test_response_experience_journal.py -q
27 passed in 2.33s
```

После усиления corruption-теста реальной доставкой через Runner:

```text
.venv/Scripts/python.exe -m pytest tests/test_response_experience_journal.py tests/test_response_experience.py tests/test_language_consolidation.py tests/test_external_response.py tests/test_response_experience_shadow_baseline.py tests/test_checkpoint_serializer.py tests/test_checkpoint_validation.py tests/test_checkpoint_backend_integration.py -q
228 passed in 5.23s
```

Отдельный resource-тест: `1 passed in 0.72s`. Случайный seed не использовался;
ID и сценарии детерминированы.

### 5.2. Полный regression

Первый полный прогон выявил реальный integration-дефект:

```text
.venv/Scripts/python.exe -m pytest -q
14 failed, 4095 passed, 2 skipped in 538.49s
```

Тринадцать падений имели общую причину: narrow unit-tests создают `AgentRunner` через
`__new__` без `__init__`, а journal wrapper обращался к отсутствующему атрибуту
напрямую. Ещё один static dispatch-тест читал прежний метод после выделения тонкого
wrapper. Production-совместимость исправлена через `getattr(..., None)` без создания
writer; static-тест теперь проверяет неизменную canonical chain в
`_on_user_message_impl`, а не ослабляет порядок.

Повтор ранее упавших файлов вместе с новым journal suite:

```text
92 passed in 2.85s
```

Повтор профильного набора после исправления: **228 passed in 4.55s**.

Финальный полный regression после исправления:

```text
.venv/Scripts/python.exe -m pytest -q
4109 passed, 2 skipped in 538.62s (0:08:58)
```

Все 14 исходных падений устранены; новых пропусков и падений не добавлено.

### 5.3. Статические гейты

Выполнены после финальных production/test-изменений:

```text
.venv/Scripts/python.exe -m ruff check src/ config/ tests/ main.py main_tray.py
.venv/Scripts/python.exe -m ruff format --check src/ config/ tests/ main.py main_tray.py
.venv/Scripts/python.exe -m mypy --config-file pyproject.toml --explicit-package-bases --no-site-packages --follow-imports=skip main.py main_tray.py
.venv/Scripts/python.exe -m bandit -q -r src/ config/ main.py main_tray.py -ll --skip B101,B601
.venv/Scripts/python.exe -m compileall -q src/ config/ tests/ main.py main_tray.py
```

Фактические результаты:

- Ruff check — passed;
- Ruff format — `585 files already formatted`;
- mypy — `Success: no issues found in 2 source files`;
- Bandit — failed tests нет; остались существующие nosec warnings B113/B608;
- compileall — passed.

Mypy остаётся public entry-point gate, а не полной типизацией всех модулей.

## 6. Controlled resource measurement

Команда:

```text
.venv/Scripts/python.exe tmp/response_experience_prospective/pj_i_resource_measure.py
```

Изолированный Windows probe: 40 deliveries / 82 события, включая start/stop.

| Метрика | Факт | Test budget |
|---|---:|---:|
| Elapsed | 0,100033 с | < 30 с |
| Mean delivery+outcome pair | 2,202 мс | — |
| p95 delivery+outcome pair | 2,566 мс | < 250 мс |
| Max delivery+outcome pair | 3,229 мс | < 1000 мс |
| Artifact после close | 159 744 байта | < 4 MiB |
| tracemalloc current | 91 989 байт | — |
| tracemalloc peak | 99 555 байт | < 16 MiB |

`integrity_check=["ok"]`, `data_root_is_tmp=true`.

Это controlled measurement синхронного writer, а не гарантия latency реальной жизни.
Полный autonomous tick и реальный UI отдельно не профилировались; writer не создаёт
фоновых tick-задач, но синхронные delivery/expiry/pruning всё равно должны быть
измерены на выбранной жизни перед более широким использованием. Tick impact и ресурсы
остаются обязательной частью наблюдения при отдельно разрешённой PJ-A.

## 7. Итог и следующая граница

PJ-I доказывает наличие изолированного production writer и controlled regressions,
но не качество будущей модели, не полноту реальной биографии и не готовность candidate
gate. Нулевой R0 не переносится в журнал. Новые записи появятся только после отдельной
активации и будущих фактических локальных доставок.

Следующая фаза PJ-A требует нового явного разрешения: включить флаг только для одной
выбранной жизни, запустить её обычным контуром владельца и наблюдать естественные
события, gaps и ресурсы. PJ-R, baselines, модель и advisor этим отчётом не разрешаются.
