# RE-S1-PJ — Prospective event-journal доставок и исходов

Дата подготовки: 2026-11-21.

Орган: **Собственная пластичная кора** по `body_plan.md`. Связанные контракты:
`RESPONSE_EXPERIENCE_SHADOW_TICKET.md` и
`RESPONSE_EXPERIENCE_REAL_DATA_INVENTORY_TICKET.md`.

Статус: **PJ-T, synthetic PJ-V и production PJ-I завершены локально; PJ-A успешно
повторно запущена владельцем после карантина пустого mismatch-файла и накапливает
реальные события для одной выбранной жизни; PJ-R выполнена на одном согласованном
снимке активного WAL**. Отчёты —
`RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_PJ_V.md` (20/20 synthetic gates),
`RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_PJ_I.md` (production writer, isolated
regressions и ресурсы), `RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_PJ_A.md` (диагностика
первой попытки и успешный retry) и `RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_PJ_R.md`
(32 delivery, 16 observed, 12 expired, 4 pending; integrity/hash-chain и temporal gates
пройдены, readiness `insufficient_data`, candidate gate закрыт). PJ-V выявил import-time
перекрытие pytest-песочницы существующим controlled observation; в test-only границах
исправление заменено на `setdefault()` и закреплено regression-тестом. PJ-I получила
отдельное разрешение только на writer, feature flag и проверки и сама активацию не
разрешала. Разрешение PJ-A ограничено одним процессом выбранной жизни и запуском
владельцем. Оно не разрешает другие жизни, искусственные диалоги, изменение
checkpoint-схемы, общее per-life исправление очереди, обучение, advisor, сеть, новые
зависимости, commit или push.

Фактическое основание: controlled prospective журнал сначала был проверен только на
синтетике (`RESPONSE_EXPERIENCE_SHADOW_PHASE1.md`). Sanitized read-only R0 активной
жизни нашёл один retained SQLite snapshot и **ноль записей `ResponseExperience`**:
observed/pending/expired отсутствовали. Это окно не равно полной биографии. После
отдельного включения PJ-A и последующей PJ-R подтверждены 32 реальные delivery и 16
observed outcomes, но представлены только 2 класса из 6, есть малые срезы и исходный
unclean-gap. Baselines не выполнялись, readiness остаётся `insufficient_data`.

## 1. Задача

Будущий журнал должен в момент реального жизненного цикла сохранять:

1. фактическую доставку локальной реплики и её pre-outcome признаки;
2. последующий фактический исход той же доставки;
3. истечение ожидания без реакции;
4. достаточные `episode_id`, delivery/outcome cycles и монотонный event sequence,
   чтобы не реконструировать временной split задним числом;
5. признаки непрерывности журнала, restart, pruning и возможных пропусков.

Журнал нужен только для последующего изолированного анализа. Он не предсказывает
исход, не обучает модель и не влияет на жизнь. Даже полный журнал не разрешает
shadow-кандидата без отдельного inventory и decision gate.

## 2. Неприкосновенные границы

- Жизненный цикл, смертность, восстановление и отсутствие автономного rollback не
  меняются.
- Выбор стратегии, Composer, текст, score, арбитр, награды, цели, ценности, память,
  сон и исполнение не меняются.
- Внешняя LLM не создаёт события, признаки, метки или эпизоды.
- Внешние session-scoped ответы не попадают в локальный журнал.
- `DialogueStrategyMemory` остаётся отдельным контуром и не подменяет исходы.
- Отключённый, недоступный или повреждённый журнал не мешает доставке, памяти, сну и
  жизненному циклу.
- Ни одна ошибка journaling не вызывает повторную доставку реплики: повтор создал бы
  новое поведение и новый фактический опыт.
- Журнал не становится скрытым production writer внутри текущего R0 или controlled
  harness. Для него требуются отдельные фазы и разрешения раздела 13.

## 3. Источник событий: только фактические переходы

### 3.1. Доставка

Событие допустимо только на существующем локальном пути после получения непустого
`message_id` и успешного `register_delivery()` в `AgentRunner._reply_to_user()`.
Мысль, отказ доставки, ошибка валидации, session-scoped внешний ответ и повторный
`response_id` события не создают.

Нельзя считать сам вызов `ResponseExperience.register_delivery()` универсальным
доказательством доставки: test/session callers существуют. Источник события должен
быть привязан именно к подтверждённому локальному AgentRunner-пути.

### 3.2. Обычная реплика и явный отзыв

Outcome создаётся только из фактического перехода `pending → observed` в существующих
`observe_reply()` или `observe_feedback()`:

- `answer`;
- `follow_up`;
- `unclassified_reply`;
- `ordinary_reply`;
- `explicit_support`;
- `explicit_opposition`.

Обычная реплика не интерпретируется как поддержка. Явный отзыв оценивает конкретный
показанный ответ, а не истинность. Поздний отзыв после terminal-статуса нового события
не создаёт.

### 3.3. Истечение и pruning

`pending → expired/no_observed_reaction` записывается как censored-переход, а не
отрицательный класс. Для `expire()` используются фактические изменения записей, а не
один агрегированный счётчик без identity.

Consolidation/pruning фиксируется отдельным событием `record_pruned` с ссылкой на
исходную доставку. Удаление из оперативного окна не удаляет событие журнала и не
становится outcome. Если прошлая доставка отсутствует в журнале, это обозначается
`origin_unavailable`, а не выдуманная история.

## 4. Единицы идентичности: life, profile, turn, episode, response

### 4.1. Обязательные ключи

- `life_id` — существующий UUID текущей жизни; новые жизни не наследуют журнал.
- `profile_id` — существующий личный контур доставленной реплики.
- `response_id` — существующий уникальный ключ доставки.
- `turn_id` — монотонный ID принятого локального пользовательского входа.
- `episode_id` — ID диалогового эпизода, к которому относится исходная доставка.
- `event_sequence` — монотонный последовательный номер события внутри жизни.

Никакой из ключей не создаётся задним числом по тексту или соседству записей.

### 4.2. Turn

Новый `turn_id` назначается, когда AgentRunner принимает следующий локальный вход
пользователя к обработке. Автономный tick не создаёт пользовательский turn. Один turn
может закрыть ожидание предыдущей доставки и позже породить новую доставку.

### 4.3. Episode

Для первого журнального контракта эпизод — **цепочка одной локальной доставки и всех
событий её ожидания/исхода**. `episode_id` назначается при фактической доставке и
остаётся неизменным для outcome, expiry и pruning этой доставки.

Outcome событие содержит одновременно:

- `episode_id` исходной доставки;
- `observation_turn_id` входа, на котором реакция наблюдена, либо `null` для expiry в
  автономном цикле.

Так split целых эпизодов не разрывает delivery и outcome. При этом эпизод не
выдаётся за полный человеческий разговор или смысловую сессию: это узкая техническая
единица оценки. Если будущий анализ потребует более крупных разговорных эпизодов,
нужна новая версия контракта и более консервативный split, а не переименование текущего
ID.

Повторная доставка получает новый response/episode ID. Повторное наблюдение того же
terminal-исхода не создаёт второй outcome.

## 5. Схема событий

### 5.1. Общий конверт

Каждое событие содержит:

- `journal_schema_version` и `feature_contract_version`;
- `event_kind`: `delivery`, `outcome`, `expired`, `record_pruned`, `journal_started`,
  `journal_stopped`, `journal_gap`;
- `event_sequence`, предыдущий integrity hash и hash текущего canonical event;
- `life_id`, `profile_id` там, где применимо;
- `cycle` фактического события;
- `turn_id`, `episode_id`, `response_id` или их явные `null` для lifecycle-событий;
- `emission_status`: `committed`;
- служебный `writer_contract_version`.

Wall-clock timestamp может храниться локально для диагностики, но не участвует в
временном split и не экспортируется. Порядок определяется только `event_sequence` и
циклами.

### 5.2. Delivery

Дополнительно:

- `delivery_cycle` и `turn_id`;
- whitelist pre-outcome признаков раздела 6;
- `expected_reaction` и наличие uncertainties;
- `repeat_in_retained_window`;
- `realization_origin_response_id` либо `null`;
- `repeat_evidence_scope`: `retained_window`, `unknown_after_pruning`;
- `outcome` отсутствует как поле, а не получает предварительную метку.

Изменение будущего исхода при неизменном плане не должно менять delivery event.

### 5.3. Outcome / expired

Дополнительно:

- исходные `response_id` и `episode_id`;
- `delivery_sequence` — ссылка на событие доставки;
- `outcome_cycle`;
- `observation_turn_id` или `null`;
- `observed_outcome` из шести классов либо `no_observed_reaction`;
- `observation_kind`: `ordinary_reply`, `explicit_feedback`, `ttl_expired`.

Outcome без существующего delivery в том же журнале записывается только как
`journal_gap/orphan_outcome`, не получает выдуманную delivery и не входит в supervised
dataset.

### 5.4. Lifecycle и gaps

`journal_started` фиксирует последнюю проверенную sequence/hash и режим чистого
старта. `journal_stopped` фиксирует штатное завершение. После restart отсутствие
`journal_stopped` обозначает `previous_shutdown_unclean`, но не доказывает потерю
событий.

`journal_gap` обязателен при обнаруженном orphan, sequence mismatch, повреждении,
превышении budget или невозможности записать событие. Сам gap должен быть виден после
restart даже если исходная ошибка не смогла быть записана в момент сбоя.

Exactly-once между внешней доставкой и локальным SQLite не заявляется. Crash между
фактической доставкой и записью может потерять событие. Такой интервал получает
`completeness=unverified` и исключается из строгого gate, если потерю нельзя исключить.

## 6. Pre-outcome whitelist и приватность

### 6.1. Разрешённые признаки

На delivery сохраняются только:

- frozen enums для intention/context/source/expected_reaction;
- boolean indicators uncertainties и missing language context;
- разрешённые языковые enums и bounded confidence bucket;
- normalized realization kind/rule/act/fallback;
- component kinds, borrowed presence/context/level/language после нормализации;
- bounded reference counts по frozen kinds;
- provenance boolean/missing;
- bounded input/realization length buckets;
- repeat flags и origin link из раздела 6.2.

Dynamic `plan.context`, source, rule ID и borrowed context проходят тот же frozen
mapping, что в R0. Неизвестное становится `other`; сырое значение не пишется. Смена
mapping требует новой `feature_contract_version` и не переписывает старые события.

### 6.2. Повторы без хранения текста или hash

До добавления новой записи writer сравнивает текущую реализацию с уже доступными
raw-реализациями в существующем `ResponseExperience` только в памяти:

- если точный текст найден, сохраняется `repeat_in_retained_window=true` и
  `realization_origin_response_id` самой ранней доступной совпадающей записи;
- если не найден, сохраняется `false` с `repeat_evidence_scope=retained_window`;
- если прошлое уже недоступно из-за pruning/restart-ограничений, область вывода
  остаётся ограниченной окном и не превращается в «впервые в жизни».

В production journal не сохраняются raw text, SHA-256/fingerprint текста или reverse
mapping. Origin link позволяет строить repeat graph внутри журнала. После pruning
отсутствующий origin обозначается `origin_unavailable`.

### 6.3. Запрещённое содержимое

`observed_input`, `base_text`, `realization.text`, `borrowed.expression`, произвольные
reference IDs, `latest_response_id`, `imitation`, сырые dynamic категории, внешние
тексты и LLM-разметка не записываются. Журнал остаётся чувствительным даже без текстов:
он содержит настоящие life/profile/response IDs и личную хронологию.

Sanitized export выполняется только по отдельному R0-протоколу с surrogate IDs,
относительными циклами, малой ячейкой `n<5` и локальным ignored `tmp/`.

## 7. Хранилище и атомарность

Предлагаемый отдельный per-life файл:

```text
data/lives/<life_id>/response_experience_events.sqlite3
```

Он не заменяет Core checkpoint и не добавляет в него новую секцию. Требования:

1. SQLite WAL, `synchronous=FULL`, одна транзакция на событие и обновление journal head.
2. Append-only events; UPDATE/DELETE событий запрещены контрактом.
3. `event_sequence` и head обновляются атомарно; повторный event ID не создаёт дубль.
4. Canonical payload и цепочка integrity hashes позволяют обнаружить повреждение.
5. Проверка integrity/hash chain выполняется до append после restart.
6. Повреждённый журнал переводится в quarantine/status без исправления истории и без
   блокировки жизни. Новый файл поверх старого не создаётся незаметно.
7. Никакого автоматического pruning событий. Retention требует отдельного решения.
8. Soft/hard storage budgets замеряются и замораживаются до включения. При hard budget
   writer прекращает append, создаёт видимый gap/status и не блокирует жизнь.
9. Никаких сетевых вызовов, внешних очередей и фоновых writers после shutdown.

Предложенный путь и схема не создаются текущим тикетом. Окончательная реализация
должна сначала пройти synthetic crash/restart/differential gates.

## 8. Отказоустойчивость и честная полнота

### 8.1. Ошибка writer

Writer работает fail-open относительно жизни: ошибка журнала не меняет ответ и не
останавливает сущность. Однако нельзя после ошибки продолжать называть журнал полным.
Статус становится `degraded`, ближайший restart создаёт gap marker, а candidate gate
для затронутого интервала закрыт.

### 8.2. Restart

- Та же жизнь продолжает последнюю проверенную sequence, не начиная с нуля.
- Новая жизнь начинает с пустого журнала и новой цепочки.
- Восстановление Core checkpoint не откатывает журнал автоматически и не переписывает
  исходы. Расхождение checkpoint/journal получает `completeness=unverified`.
- Наследование журнала через seed запрещено.

### 8.3. Доступность исходов

Исход становится доступным для обучения/оценки только начиная с его
`outcome_sequence`. Для примера в train требуется
`outcome_sequence < validation_first_delivery_sequence`. Поздний исход ранней доставки
не протекает в прошлое.

Pending и censored не получают искусственные метки. Pruning ограничивает repeat/window
evidence, но не стирает уже записанный фактический исход.

## 9. Изоляция поведения

До включения в живой жизни differential на одинаковых controlled сценариях должен
доказать тождественность с writer disabled/enabled:

- выбранных стратегий, действий, арбитра и score;
- планов, реализаций, текста и фактических доставок;
- наблюдаемых исходов, expiry и consolidation;
- целей, наград, памяти, self-model, ценностей и конфигурации;
- restore/expire/consolidate и внешних session-scoped ответов;
- autonomous ticks, shutdown и всех внешних эффектов, кроме разрешённого журнала и его
  sanitized status.

Единственное допустимое различие — отдельный journal artifact и явный диагностический
status. Изменение tick latency измеряется отдельно и не скрывается под функциональным
равенством.

## 10. Временной split и будущие baselines

После отдельного inventory:

1. Единица split — целый `episode_id`, включая delivery/outcome/expiry/pruning.
2. Разбиение выполняется внутри одной жизни; профили не смешиваются скрыто.
3. Эпизоды упорядочиваются по `delivery_sequence`, без shuffle.
4. Каркас 60/20/20 применяется только при достаточном объёме и доказанной полноте.
5. B0/B1/B2 используют frozen правила controlled фазы, но не её искусственные метрики.
6. Любые исторические признаки вычисляются только из доступного прошлого.
7. Gap/orphan/unclean interval не маскируется; затронутые сегменты исключаются по
   заранее заданному правилу, а не по улучшению метрики.
8. Недостаток классов или срезов даёт `insufficient_data`.
9. Held-out просматривается один раз после замораживания кандидатских порогов.
10. Новый кандидат после held-out требует нового более позднего held-out.

Нулевой R0 не переносится в prospective журнал как события. Журнал начинается только
с будущих фактических доставок после отдельного включения.

## 11. Приёмочная матрица

| ID | Проверка | Условие приёмки |
|---|---|---|
| PJ-01 | Фактическая доставка | Нет delivery без подтверждённого локального `message_id` и `response_id` |
| PJ-02 | Истинные исходы | Только реальные observe/expire transitions; шесть классов и censored разделены |
| PJ-03 | Внешние сессии | Session-scoped ответы и внешняя LLM не создают локальных событий |
| PJ-04 | Episode/turn | Delivery/outcome связаны исходным episode; observation turn не подменяет его |
| PJ-05 | Sequence | Монотонная per-life sequence, атомарный head, нет дублей после retry |
| PJ-06 | Outcome availability | Поздний исход недоступен в прошлом; late-outcome regression пройден |
| PJ-07 | Leakage | Изменение будущего исхода не меняет delivery event |
| PJ-08 | Dynamic privacy | Сырые тексты, dynamic категории, IDs references и fingerprints отсутствуют |
| PJ-09 | Repeat graph | Origin link точен в retained окне; pruning не назван «первым в жизни» |
| PJ-10 | Pruning | Удаление окна не удаляет/не меняет outcome и оставляет origin evidence ограниченным |
| PJ-11 | Crash honesty | Нет exactly-once claims; crash/gap/orphan получают unverified/degraded |
| PJ-12 | Fail-open | Writer failure не меняет доставку и жизнь, но обязательно портит completeness status |
| PJ-13 | Restart | Проверенная sequence/hash продолжается; unclean shutdown виден |
| PJ-14 | Corruption | Повреждение обнаружено до append; история не исправляется, жизнь продолжается |
| PJ-15 | Вторая жизнь | Журнал, sequence, origin links и статистики первой жизни отсутствуют |
| PJ-16 | Restore | Core restore не откатывает журнал и не переписывает исходы |
| PJ-17 | Differential | Disabled/enabled жизненные поведения тождественны; различён только journal/status |
| PJ-18 | Ресурсы | Artifact/RAM/write latency/tick impact замерены и укладываются в frozen budget |
| PJ-19 | Shutdown | Нет фонового writer после stop; WAL закрыт штатно; integrity подтверждена |
| PJ-20 | Граница результата | Журнал не включает модель, advisor, речь или candidate gate автоматически |

## 12. Критерии остановки

Реализация или включение останавливается, если:

- writer способен изменить доставку, score, память или выбор;
- событие можно создать без фактической доставки/исхода;
- для split приходится выдумывать episode/outcome sequence;
- журнал хранит сырые тексты или dynamic значения ради удобства;
- crash/ошибка скрывается без gap/unverified;
- corruption перезаписывается новым пустым журналом;
- вторая жизнь наследует историю;
- differential, restart, shutdown или resource gates не пройдены;
- включение предлагается без отдельного разрешения владельца;
- по результату inventory снова недостаточно данных — тогда остаёмся без модели.

## 13. Фазы и независимые разрешения

### PJ-T — текущий тикет

Только этот документ и навигационные ссылки. Никакого writer, production/test-кода,
записи в живой `data/` или regression.

### PJ-V — test-only prospective adapter

Отдельное разрешение. Расширение controlled harness на turn/episode/gap/repeat/prune,
crash/restart/corruption/second-life и differential. Только synthetic events и
`DIGITAL_BEING_DATA_DIR` в `tmp/`; живой writer не создаётся.

### PJ-I — production implementation, выключено по умолчанию

Новое отдельное разрешение. Минимальный production writer, schema/integrity/status,
узкие regression-тесты, полный regression и статические гейты. По умолчанию writer
выключен; активация и запись в живой `data/` этой фазой запрещены.

### PJ-A — отдельная активация для одной жизни

Только после отчёта PJ-I и явного разрешения владельца: включение для одной выбранной
жизни, запуск принадлежит владельцу/обычному контуру, наблюдаются исключительно будущие
естественные события. Никаких искусственных диалогов ради раздувания dataset, модели
или advisor.

### PJ-R — выполненная read-only inventory

Выполнена по отдельному разрешению на активном WAL через одну read transaction:
sequence 63, 32 доставки = 16 observed + 12 expired + 4 pending; 28/28 terminal имеют
известный outcome cycle, 32/32 — episode identity. Integrity, temporal и privacy gates
пройдены; readiness — `insufficient_data`. Baselines не входили в разрешение и не
выполнялись; candidate gate остаётся закрыт. Фактический отчёт —
`RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_PJ_R.md`.

### Shadow candidate

Только новый тикет после достаточного PJ-R. Даже успешный journal не выбирает
архитектуру и не разрешает влияние на жизнь.

## 14. Обязательные будущие проверки

Для PJ-T полный regression не требуется: код и тесты не меняются.

PJ-V/PJ-I обязаны включать профильные тесты и полный regression по `AGENTS.md`, Ruff,
format, mypy, Bandit и compileall. Отдельно фиксируются crash/restart/corruption,
вторая жизнь, differential, concurrent writer, shutdown/WAL, storage/latency budget и
metadata/content integrity живого `data/` в разрешённых границах.

Каждый отчёт содержит фактические команды, passed/skipped, commit, версии контрактов,
seed, ресурсы и невыполненные проверки. Прошлый controlled regression не является
проверкой prospective writer. Commit/push — только по отдельным разрешениям.
