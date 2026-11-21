# RE-S1-R0 — Sanitized read-only инвентаризация реальной биографии

Дата подготовки: 2026-11-21.

Орган: **Собственная пластичная кора** по `body_plan.md`. Это подготовительный
контур к `RESPONSE_EXPERIENCE_SHADOW_TICKET.md`, а не новый орган и не фаза 2.

Статус: **тикет подготовлен; выполнение не авторизовано**. Реальное содержимое
`data/` не читалось, sanitized-копии не создавались, инвентаризация и baselines на
реальных данных не запускались. Документ не разрешает обучение, production writer,
production-изменения, новые зависимости, сеть, advisor, запуск живой сущности,
commit или push. Для выполнения требуется новое отдельное явное разрешение владельца.

## 1. Цель и нецели

Цель будущего наблюдения — ответить, какие фактические данные `ResponseExperience`
сохранились у одной явно выбранной жизни и достаточны ли они для постановки следующего
исследовательского вопроса. Результатом должны быть readiness-отчёт и, только при
доказуемом порядке записей, ограниченные диагностические baselines.

Инвентаризация не должна:

- обучать модель или выбирать MLP/RNN/LTC;
- открывать candidate gate или повторно использовать controlled-результат как
  доказательство качества на реальной жизни;
- создавать production writer, prospective production journal или feature flag;
- менять выбор реплики, score, память, награды, цели, ценности или конфигурацию;
- восстанавливать, «чинить» или переписывать биографию;
- запускать `DigitalBeing`, `AgentRunner`, UI, сеть или внешнюю LLM;
- переносить опыт между жизнями;
- публиковать сырые тексты, идентификаторы, пути, timestamps или sanitized-файлы.

Допустимый итог — `insufficient_data`, `temporal_order_unverified` или остановка без
чтения источника. Отсутствие пригодных данных не нужно компенсировать догадками.

## 2. Фактические источники и граница доступа

### 2.1. Текущий managed-контур

Код конфигурации на момент подготовки задаёт `CHECKPOINT_BACKEND="sqlite"`,
`MAX_CHECKPOINTS=20`, а диагностическое JSON/SQLite mirror выключено
(`config/simulation_config.py`). Для managed-жизни основной снимок сохраняется в:

```text
data/lives/<life_id>/life.sqlite3
```

Таблица `snapshots` содержит удерживаемую историю снимков, а `blobs` — их
content-addressed состояние. Запись использует WAL и транзакции
(`src/memory/checkpoint_store.py`, `src/memory/life_database.py`). Секции
`response_experience` и `social_attribution` находятся внутри Core state
(`src/core/checkpoint_serializer.py`).

Старые managed JSON могут оставаться аварийным источником:

```text
data/checkpoints/<life_id>/<life_id>_cycle_<N>.json
data/checkpoints/<life_id>/<life_id>_cycle_<N>.json.gz
```

При текущем primary SQLite они не перезаписываются. Их наличие не доказывает
полноту или непрерывность истории.

### 2.2. Legacy standalone-контур

Только если владелец отдельно выберет standalone-жизнь, допустимы:

```text
data/checkpoints/life.sqlite3
data/checkpoints/<agent_name>_cycle_<N>.json
data/checkpoints/<agent_name>_cycle_<N>.json.gz
```

Managed UUID/SQLite и standalone JSON не смешиваются в один dataset. Неоднозначность
владельца, несколько жизней с одинаковым именем или несовпадение `life_id` — stop.

### 2.3. Что исключено по умолчанию

- резервные комплекты `data/snapshots/` и другие жизни;
- `memory_traces`, `dialogue_cycles`, `episodes`, логи, экспортированные тексты и
  любые таблицы, не нужные для разрешённого среза Core checkpoint;
- внешние session-scoped ответы;
- данные установленного приложения вне разрешённого workspace-local data root;
- чтение всех файлов ради content SHA-256.

Добавление backups или второго источника требует отдельного решения: это расширяет
и приватность, и правила дедупликации. Первый прогон ограничивается одной выбранной
жизнью и её active primary + retained legacy checkpoints.

## 3. Почему штатные loaders не подходят

`SQLiteCheckpointStore.__init__()` создаёт каталог/таблицы и выполняет
`PRAGMA journal_mode=WAL`; `LifeDatabase.__init__()` дополнительно выполняет миграции
и meta-записи. Поэтому для реального источника запрещены:

- создание `SQLiteCheckpointStore(path)` или `LifeDatabase(path, life_id)`;
- `CheckpointSerializer.load("<db>#snapshot=N")`, поскольку он создаёт store;
- любой вызов `save`, `gc`, maintenance, VACUUM, backup или checkpoint recovery;
- `immutable=1` для active WAL-базы: такое чтение может игнорировать актуальный WAL.

Будущий test-only reader должен использовать собственное `mode=ro` соединение и
read-only decode без конструкторов, миграций схемы и записи. Существующий
`tools/manual/verify_stage6_checkpoint_history.py` является полезным доказательством
такого decode для проверенных backups, но его `immutable=1` протокол нельзя переносить
на active базу без выполнения условий ниже.

## 4. Протокол quiescence и согласованного чтения

### 4.1. До открытия источника

1. Владелец отдельно разрешает выполнение и явно выбирает одну жизнь/data root.
2. Живая сущность заранее останавливается штатно вне observation harness. Harness не
   запускает её и не завершает процессы самовольно.
3. Подтверждается отсутствие writers и незавершённого checkpoint. Непустой
   `life.sqlite3-wal`, активный `-shm`/journal или неизвестный writer — stop. Файлы
   не удаляются и не «чинятся» ради запуска.
4. До чтения содержимого отдельно проверяются synthetic fixtures: allowlist схемы,
   отсутствие сырых значений в output/errors, surrogate IDs, censored-логика,
   дедупликация и witness bounds. Эти fixtures создаются только в `tmp/`.
5. Для всего разрешённого data root снимается metadata-only inventory
   `(relative_path, size, mtime_ns)`. Он остаётся в памяти; наружу выходят только
   число файлов, digest и факт равенства. Пути и идентификаторы в отчёт не попадают.

### 4.2. SQLite

1. Synthetic gate выявил, что обычный `mode=ro` способен создать `-wal`/`-shm` даже
   без writer. Поэтому после подтверждённого отсутствия writers и **любых**
   WAL/SHM/journal открывается только `mode=ro&immutable=1`; сразу выполняется
   `PRAGMA query_only=ON` и задаётся конечный busy timeout. Здесь immutable безопасен
   именно потому, что актуального WAL не существует и writers исключены. При любом
   sidecar такой режим не используется: выполнение останавливается.
2. Проверяются поддержанная `user_version`, владелец снимков, `PRAGMA integrity_check`
   и структура необходимых таблиц. Ошибка выводится только как sanitized code.
3. До чтения списка снимков начинается одна deferred read transaction. Список
   `snapshots`, manifests и все выбранные blobs декодируются на одном соединении внутри
   неё. Это даёт один согласованный вид retained history.
4. Хеши blobs и структура проверяются существующей read-only логикой decode, но без
   конструктора store. После decode применяются только чистые state migrations и
   validation; агент и подсистемы не создаются.
5. Если согласованная read transaction, целостность или отсутствие writers не
   гарантированы — инвентаризация останавливается, а не переходит на частичные данные.

### 4.3. Legacy JSON

JSON/JSON.GZ читается напрямую как данные, без save/load agent, recovery, rotate или
создания приложения. Применяются чистые migration/validation. Файл, не прошедший
проверку, получает sanitized exclusion reason; содержимое ошибки не копируется.

### 4.4. После чтения

Metadata-only inventory повторяется. Любое различие `(path,size,mtime_ns)` означает
failed source-preservation gate; отчёт фиксирует только категорию изменения, без raw
path. Нельзя утверждать побайтовую неизменность: эта проверка доказывает лишь
незамеченных изменений по выбранной metadata. Content SHA-256 всех файлов не
выполняется без отдельного решения.

## 5. Privacy threat model

| Угроза | Обязательная защита |
|---|---|
| Сырой диалог раскрывает человека или личные обстоятельства | Тексты не экспортируются; используются только в памяти для length bucket и run-local repeat ID |
| UUID/response/reference IDs связывают запись с реальной жизнью | Последовательные surrogate IDs без обратного mapping |
| Путь или timestamp раскрывает профиль и расписание | Только source kind, порядковые номера и относительные циклы |
| Dynamic `plan.context` содержит выученную фразу | Только frozen enum/prefix mapping; неизвестное — `other` |
| Dynamic source/rule/borrowed context раскрывает текст | Нормализация в frozen allowlist; сырые неизвестные значения запрещены |
| Hash реализации позволяет dictionary attack или cross-run linking | Никакого hash/fingerprint; только последовательный realization surrogate внутри одного прогона |
| Ошибка SQLite/validation выводит payload или путь | Только заранее заданные error codes; `str(exc)` и traceback с данными не экспортируются |
| Маленькая категория выделяет конкретного человека/эпизод | В публичных агрегатах ячейки `n<5` подавляются как `insufficient_data` |
| Sanitized-файл всё равно позволяет персональный профiling | Только локальный ignored `tmp/`; не коммитить, не публиковать, не отправлять в сеть |
| Повторный прогон связывает биографию во времени | Surrogate IDs назначаются заново; cross-run mapping не сохраняется |

Sanitization снижает риск, но не делает копию публичной. Все sanitized-артефакты
остаются чувствительными evidence-файлами.

## 6. Sanitized-схема

### 6.1. Идентичность и происхождение

Каждая запись события может содержать только:

- `schema_version`, `record_kind="response_experience"`;
- `life_key`: `life-001`;
- `profile_key`: `profile-001`, `profile-002`, … в порядке первого безопасного
  появления;
- `response_key`: `response-000001`, … без сохранения исходного `response_id`;
- `source_kind`: `managed_sqlite`, `managed_legacy_json` или отдельно разрешённый
  standalone enum;
- `source_snapshot_ordinal`: порядок внутри источника, не SQLite ID и не путь;
- `delivery_ordinal` и `delivery_cycle_offset` относительно первой допустимой записи
  выбранной жизни;
- `episode_id="unknown"`, если подлинного episode ID в источнике нет;
- `temporal_completeness="unverified"` для retrospective checkpoints.

Исходные `(life_id, profile_id, response_id)` допускаются только в памяти для
принадлежности и дедупликации. Обратный mapping не сериализуется.

### 6.2. Признаки до исхода

Разрешены только нормализованные поля:

- frozen enums для `intention`, `context`, `source`, `expected_reaction`;
- boolean missing/unknown и наличие каждого разрешённого uncertainty;
- `input_language`, `dialogue_language`, `response_language`, language source как
  frozen enums; confidence — bounded bucket;
- `realization.kind`, `rule_id`, `act`, `fallback_policy` после allowlist mapping;
- состав component kinds и их counts;
- borrowed presence, normalized context/level/language, но не expression;
- bounded reference count и counts по frozen reference kinds;
- `provenance_verified`: `true`, `false` или `missing`;
- bounded length buckets входа и реализации;
- `realization_key`: `realization-000001`, … для одинакового текста внутри одного
  прогона; исходный текст и mapping не сохраняются.

`DialogueLearning.phrase_from_context` доказывает, что dynamic `plan.context` может
быть выученной фразой. Поэтому копирование «как есть» запрещено даже для полей,
которые выглядят категориальными. Неизвестные source/rule/borrowed values также не
выводятся дословно. Output validator должен отклонять любое поле вне схемы.

### 6.3. Исход и наблюдаемость

- `status`: `observed`, `pending`, `expired`;
- `outcome`: один из шести observed-классов либо `no_observed_reaction`, `null`;
- `outcome_cycle_offset`: всегда `null`, поскольку текущая запись его не хранит;
- `outcome_witness_lower_cycle_offset` и `outcome_witness_upper_cycle_offset`: только
  если серия снимков действительно даёт границы, иначе `null`;
- `witness_basis`: frozen enum, например `pending_then_observed`,
  `first_seen_terminal`, `latest_only`;
- `exclusion_reason`: frozen code для непригодной записи.

Если в более раннем снимке запись была `pending`, а в более позднем стала terminal,
эти снимки задают lower/upper witness interval, а не точный цикл исхода. Если запись
впервые найдена уже terminal, точное и даже нижнее событие не выдумывается. Исчезновение
записи может быть pruning, поэтому не интерпретируется как исход.

### 6.4. Явно запрещённые поля

`observed_input`, `base_text`, `realization.text`, `borrowed.expression`, произвольные
reference/response/profile/life IDs, `latest_response_id`, `imitation`, абсолютные и
относительные исходные пути, `saved_at` и другие timestamps, произвольный `metadata`,
сырые exceptions/logs, embeddings и reverse mappings не экспортируются.

## 7. Eligibility, dedup и шесть классов

В supervised readiness-count входит запись только если:

1. владелец жизни и профиля доказан;
2. зарегистрированная доставка и план проходят validation;
3. `status="observed"`, а outcome принадлежит `answer`, `follow_up`,
   `unclassified_reply`, `ordinary_reply`, `explicit_support`,
   `explicit_opposition`;
4. признаки существовали до исхода и проходят normalized whitelist;
5. исходный ключ уникален после учёта повторов одной записи в snapshots.

`pending` и `expired/no_observed_reaction` — censored, а не отрицательные метки.
Повреждённые, внешние session-scoped и неоднозначные записи получают exclusion code.
Метки не исправляются вручную и не восстанавливаются по смыслу текста.

Повтор одного `response_id` в нескольких snapshots — witnesses одной доставки, а не
новые примеры. Совпадение managed legacy и SQLite сначала проверяется по исходному
ключу и state в памяти. Конфликтующие версии не объединяются выбором «правдоподобной»:
запись исключается с `conflicting_witnesses`. Surrogate IDs не используются для
cross-source dedup после потери исходного mapping.

## 8. Окно, порядок и readiness

### 8.1. Ограничения окна

Активный экземпляр хранит до 64 записей; consolidation оставляет до 32 terminal на
профиль и сохраняет pending. SQLite/JSON history также ограничена retained snapshots.
Поэтому отчёт обязан различать:

- `registered_in_window` — наблюдаемое число в доступном окне;
- `removed_or_never_available` — `unknown`, если pruning не оставил доказательств;
- `observed`, `pending`, `expired`, `invalid`, `conflicting`;
- покрытие профилей, языков, нормализованных контекстов и классов;
- долю записей с `episode_id="unknown"`;
- долю записей с известным outcome cycle — по текущему контракту ожидается ноль, но
  это должен подтвердить фактический schema audit;
- записи с lower/upper witness bounds и основанием границ.

Ноль означает наблюденный ноль; отсутствие сведений — `unknown`. Окно нельзя называть
полной биографией.

### 8.2. Решение readiness

- `data_present`: есть валидные записи окна, но качество/порядок ещё не доказаны.
- `diagnostic_only`: порядок доставок и дедупликация доказаны, можно считать только
  ограниченные retrospective baselines; candidate gate запрещён.
- `insufficient_data`: классов/исходов/покрытия недостаточно или срезы слишком малы.
- `temporal_order_unverified`: нельзя доказать порядок/доступность исходов; baselines
  и candidate gate запрещены.
- `source_read_failed`: quiescence, integrity, privacy или preservation gate не пройден.

Retrospective checkpoints не получают строгий 60/20/20 split: исходный episode ID
отсутствует, outcome cycle не записан. Эпизоды нельзя реконструировать по соседству,
тексту, одинаковому профилю или догадке о времени. `temporal_completeness=unverified`
сам по себе запрещает вывод о превосходстве кандидата.

### 8.3. Ограниченные baselines

Только при `diagnostic_only` допускаются уже замороженные B0/B1/B2 на однозначно
упорядоченных observed-записях выбранной жизни. Разрешены описательные
retrospective/resubstitution метрики с явной пометкой `not_a_holdout_estimate`.

Запрещены random shuffle, выдуманный held-out, подбор backoff по итоговому результату,
сравнение с controlled held-out и формулировки «модель готова». Если порядок исходов
не доказан, не считаются даже diagnostic baselines. Численные candidate-пороги этой
фазой не задаются.

## 9. Формат результата

После отдельного разрешения все артефакты создаются только в новом локальном ignored
каталоге вида:

```text
tmp/response_experience_real_inventory/<run-label>/
```

Планируемые файлы:

- `sanitized-records.jsonl` — только схема раздела 6;
- `report.json` — машинные counts, readiness и witness summary;
- `report.md` — aggregate-only человекочитаемый отчёт;
- `validation.json` — sanitized checklist gates, без исходных путей и payload.

Публичный `docs/`-отчёт, если владелец позже его разрешит, содержит только агрегаты;
ячейки `n<5` заменяются на `insufficient_data`. Сами sanitized-файлы в `docs/`,
Git, issue, chat или сеть не переносятся. Нельзя печатать записи в консоль для отладки.

## 10. Stop conditions

Немедленная остановка обязательна при любом из условий:

- нет отдельного разрешения на выполнение или выбранной жизни;
- обнаружен writer, незавершённое сохранение, непустой WAL или unsafe snapshot mode;
- не гарантирована единая read transaction;
- неоднозначен владелец, неподдержанная схема или нарушена целостность;
- synthetic privacy/allowlist tests не прошли до чтения реального источника;
- output содержит поле вне whitelist, raw text/ID/path/timestamp или raw exception;
- не удаётся безопасно нормализовать dynamic категорию — она становится `other`, а
  если `other` не предусмотрен схемой, запись исключается;
- metadata источника изменилась или observation сам попытался записать в data root;
- появляется предложение создать production writer, модель, advisor или запустить
  живую сущность для «получения недостающих данных»;
- для вывода требуется выдумать episode ID, outcome cycle или отсутствующую метку.

Остановка не является поводом ослабить gate и повторить чтение другим способом.

## 11. Приёмочная матрица будущего выполнения

| ID | Проверка | Условие приёмки |
|---|---|---|
| R0-01 | Авторизация | Отдельно разрешены выполнение, одна жизнь и data root; ticket-only фаза не использовала данные |
| R0-02 | Quiescence | Writers отсутствуют; unsafe WAL/snapshot режим останавливает работу |
| R0-03 | Read-only SQLite | После отсутствия writers и всех sidecar — `mode=ro&immutable=1`, `query_only`, одна transaction; нет constructors/migrations/save/gc; immutable при WAL запрещён |
| R0-04 | Legacy safety | Прямое чтение без agent/recovery/rotation; ошибки только sanitized |
| R0-05 | Source preservation | Metadata до/после совпадает; граница доказательства сформулирована честно |
| R0-06 | Output privacy | Synthetic и post-run schema scan не находит тексты, IDs, пути, timestamps, hashes или reverse mapping |
| R0-07 | Dynamic categories | Только frozen mapping; неизвестное не просачивается дословно |
| R0-08 | Surrogates | Последовательные run-local IDs; повтор текста не раскрывает hash и не связывает прогоны |
| R0-09 | Labels | Ровно шесть observed-классов; pending/expired остаются censored |
| R0-10 | Dedup | Snapshots одной доставки не раздувают N; конфликты исключены |
| R0-11 | Temporal honesty | Нет выдуманных episode/outcome cycles; witness bounds не названы событием |
| R0-12 | Readiness | Окно не названо биографией; `unknown` не заменён нулём; малые ячейки подавлены |
| R0-13 | Baseline boundary | Только diagnostic при доказанном порядке; нет candidate gate/holdout claims |
| R0-14 | Life isolation | Одна жизнь, личные срезы разделены, cross-life перенос отсутствует |
| R0-15 | No behavior change | Нет production writer, модели, advisor, сети, agent/UI и autonomous ticks |
| R0-16 | Artifact containment | Все outputs только в ignored `tmp/`; commit/push/publication не выполнялись |

## 12. Фазы и разрешения

### R0-T — подготовка тикета, текущая фаза

Разрешены этот документ и ссылки в навигации. Не разрешены чтение содержимого реального
`data/`, создание sanitized-копий, инвентаризация, baselines, код и regression.

### R0-V — synthetic validation, отдельное будущее разрешение

Test-only reader/sanitizer и fixtures в `tmp/`; никакого чтения реальной биографии.
Если владелец разрешает R0-EXEC сразу, R0-V является обязательным первым шагом внутри
него, но не даёт права пропустить synthetic gates.

### R0-EXEC — sanitized read-only inventory, отдельное разрешение

Quiescence, metadata gate, чтение одной выбранной жизни, sanitized-артефакты и
aggregate readiness. Не включает модель, production writer, backups, вторую жизнь,
сеть, commit/push или публикацию sanitized-файлов.

### Следующий исследовательский gate

Возможен только после фактического отчёта R0. Если остаётся
`temporal_completeness=unverified`, для строгого shadow нужен отдельный тикет
prospective event-journal; текущий документ его не авторизует. Candidate/advisor
остаются за пределами даже при большом числе записей.

## 13. Проверки текущей документной фазы

Для R0-T достаточно документных whitespace/status/diff-проверок. Полный regression и
статические гейты кода не требуются, поскольку production/test-код не меняется. Их
прошлые результаты нельзя выдавать за проверку будущего reader.

Commit и push требуют отдельных явных разрешений на конкретный набор изменений.
