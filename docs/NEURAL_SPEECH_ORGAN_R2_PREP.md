# Neural Speech Organ — R2-PREP

Статус: **минимальный локальный контур реализован и проверен; начата реальная
sandbox-разметка; обучение и активное подключение не выполнялись**.

Этот этап подготавливает независимую человеческую разметку для будущего R2. Он не
обучает классификатор или composer, не создаёт веса, не меняет активную речь и не
разрешает автоматический переход к R2. Живые `data/` не изменяются: окно работает
только с согласованными sandbox-копиями.

## 1. Проблема и границы

R1 зафиксировал `insufficient_data`: prospective response-journal содержит факты
доставки и наблюдаемые исходы, но не содержит human-confirmed intent labels и
human-confirmed semantic plans. Ответ сущности, её собственная оценка ответа и
автоматически предсказанный класс не могут считаться независимой разметкой.

R2-PREP вводит три intent class:

- `ASK_SELF_STATE`;
- `ASK_SELF_ACTIVITY`;
- `UNKNOWN_OR_OTHER`.

`UNKNOWN_OR_OTHER` не означает abstention. Это подтверждённый человеком класс для
входов вне двух узких self-intents. Если человек не может надёжно выбрать класс,
используется `intent_review="abstained"`, а не `UNKNOWN_OR_OTHER`.

В текущий объём входят DTO, per-life журнал, read-only projection/export, статистика
и отдельный sandbox-only UI/CLI человеческой разметки. Начат сбор реальных меток в
sandbox; обучение, active writer и интеграция с AgentRunner остаются отдельными этапами.

## 2. Целевой минимальный API

Целевой модуль: `src/core/response_annotation.py`.

```python
ANNOTATION_INTENTS = frozenset({
    "ASK_SELF_STATE",
    "ASK_SELF_ACTIVITY",
    "UNKNOWN_OR_OTHER",
})

AnnotationRevision(...)
ResponseAnnotationJournal(path, life_id)
prepare_r2_dataset(response_events, annotation_events, *, life_id)
```

`AnnotationRevision` — неизменяемое описание одной человеческой ревизии. Журнал —
append-only per-life SQLite с hash-chain. `prepare_r2_dataset` — чистая read-only
функция без записи, обучения и изменения входных событий.

Поля `AnnotationRevision`:

| Поле | Контракт |
|---|---|
| `annotation_id` | Уникальный bounded ID этой ревизии; повтор той же записи идемпотентен. |
| `life_id` | Канонический UUID жизни; обязателен и проверяется через `validate_life_id`. |
| `profile_id` | Локальный контакт, к которому относится исходная доставка. |
| `response_id`, `episode_id` | Связь с исходным эпизодом, а не с новым ответом сущности. |
| `delivery_sequence` | Sequence исходной delivery в response-journal, integer ≥ 1. |
| `source_delivery_event_hash` | SHA-256 исходной delivery; защищает от случайного или ложного join. |
| `revision` | Номер ревизии, начиная с 1. |
| `supersedes_event_hash` | `None` у revision 1; затем hash непосредственной предыдущей ревизии. |
| `annotator_id` | Ограниченный локальный псевдоним reviewer, не свободный комментарий. |
| `label_source` | Только `human_review`; model/self/automatic sources отклоняются. |
| `intent_review` | `confirmed`, `corrected` или `abstained`. |
| `intent` | Один из трёх классов; при intent abstention обязателен `None`. |
| `intent_uncertainties` | Машинные uncertainty codes; без свободного текста. |
| `plan_review` | `confirmed`, `corrected`, `abstained` или `not_applicable`. |
| `semantic_plan` | Sanitized semantic-plan label либо `None`. |
| `plan_uncertainties` | Машинные uncertainty codes плана. |
| `schema_version` | Начальная версия — 1. |

Методы DTO: `to_dict()` и `from_dict()` с проверкой unknown fields и глубоким
копированием вложенных данных.

## 3. Semantic-plan label без сырого текста

Размечается смысловая проекция `SemanticResponsePlan`, а не его текстовая реализация.
Envelope уже хранит `response_id`, `delivery_sequence` и intent, поэтому они не
дублируются внутри plan label.

Разрешённые поля plan label:

```json
{
  "schema_version": 1,
  "language": "ru",
  "activity": {
    "status": "current",
    "kind": "draw",
    "started_cycle": 12
  },
  "last_completed_action": {
    "kind": "compose_music",
    "cycle": 9
  },
  "energy": 0.7,
  "allowed_claims": ["activity.current:draw", "activity.completed:compose_music"]
}
```

Для `activity.status="none"` действие не содержит `kind` и `started_cycle`. Вложенные
поля и `allowed_claims` валидируются по тем же смысловым правилам, что
`SemanticResponsePlan`.

В annotation journal **не принимаются**:

- `baseline_text`, входной текст, текст ответа и их hashes/fingerprints;
- `activity.target`, `activity.work_id`, `last_completed_action.target`;
- evidence/reference IDs внутри label;
- свободные reviewer comments и rationale;
- outcome или реакция пользователя как источник semantic label.

`allowed_claims` может содержать machine claim `activity.target`: это признак наличия
цели, не её содержимое. Исходная delivery связывается только через технические ID и
`source_delivery_event_hash` envelope.

Для `ASK_SELF_STATE` и `ASK_SELF_ACTIVITY` требуется plan review. Для
`UNKNOWN_OR_OTHER` и intent abstention используется `plan_review="not_applicable"` и
`semantic_plan=None`.

## 4. Подтверждение, исправление и неопределённость

`confirmed` означает, что человек подтвердил предложенные intent/plan. `corrected`
означает, что человек записал исправленные значения. Обе формы требуют
`label_source="human_review"`; automatic self-labeling API отсутствует.

Метка считается resolved для соответствующего вида обучения только если:

1. review status — `confirmed` или `corrected`;
2. значение присутствует и валидно;
3. соответствующий uncertainty tuple пуст.

Начальный uncertainty vocabulary:

- `input_meaning`;
- `source_provenance`;
- `state_facts`;
- `activity_facts`;
- `plan_facts`.

`abstained` требует отсутствия значения и хотя бы одного uncertainty code.
Подтверждённая/исправленная метка с uncertainty сохраняется для диагностики, но не
входит в resolved labels и не повышает training readiness.

Неопределённость не превращается в четвёртый intent class и не заполняется по
предсказанию модели.

## 5. Append-only corrections

`ResponseAnnotationJournal.record(revision)` добавляет событие `annotation` со своим
монотонным `event_sequence`. Старые события не обновляются и не удаляются. SQLite
triggers запрещают UPDATE/DELETE, hash-chain и head проверяются при reopen.

Правила ревизий:

1. revision 1 не имеет `supersedes_event_hash`;
2. revision N > 1 ссылается на event hash текущей ревизии N−1 того же response/profile;
3. пропуск номера, ссылка на чужую ревизию, другой response или другую жизнь
   отклоняются;
4. повтор того же `annotation_id` с идентичным содержимым возвращает существующее
   событие; конфликт содержимого отклоняется;
5. `events()` возвращает всю историю, `labels(annotation_before_sequence=None)` —
   последнюю доступную ревизию каждого response на указанный cutoff;
6. чтение возвращает копии и не позволяет мутировать журнал.

Ошибки записи не вызывают ответ, действие, обучение или изменение жизненного цикла.
В R2-PREP журнал открывается только явно по sandbox path; глобальный opener и
AgentRunner integration не добавляются.

## 6. Временной split и provenance

`prepare_r2_dataset(response_events, annotation_events, *, life_id)` использует
существующий `response_shadow_inventory.temporal_split`: целые episode IDs делятся по
первой delivery 60/20/20 без shuffle. Разметка самостоятельно не выбирает split и не
перемешивает эпизоды.

Join разрешён только при совпадении:

- `life_id`, `profile_id`, `response_id`, `episode_id`;
- `delivery_sequence`;
- `source_delivery_event_hash` с hash исходной delivery.

Orphan, cross-life, duplicate/conflicting source и hash mismatch не становятся
обучающими примерами и отражаются в `provenance_gaps`.

Sequence response-journal и annotation-journal — разные шкалы и никогда не сравниваются
напрямую. Для annotation revisions применяются отдельные cutoffs:

- `train_annotation_before_sequence` — первая аннотация validation/held-out episode;
- `validation_annotation_before_sequence` — первая аннотация held-out episode;
- `held_out_annotation_before_sequence` — следующий sequence после последней аннотации;
- отсутствующий cutoff заменяется следующим sequence после последней аннотации.

Для каждого split выбирается последняя ревизия **строго до** его annotation cutoff.
Поздняя correction не переписывает прошлый train snapshot: при повторном export с более
ранним cutoff видна прежняя ревизия, а если ранней ревизии не было, пример отсутствует.
Это предотвращает утечку поздних меток и reviewer knowledge в train.

Результат projection:

```text
{
  life_id,
  split: {
    train, validation, held_out,
    train_annotation_before_sequence,
    validation_annotation_before_sequence,
    held_out_annotation_before_sequence,
    ...
  },
  samples: {train, validation, held_out},
  coverage: {total, train, validation, held_out},
  readiness
}
```

Sample содержит технический provenance, resolved/uncertain/abstained status и флаги
`eligible_intent` / `eligible_semantic_plan`. Он не содержит сырых текстов и не вызывает
обучение. Входные events не мутируются; повторный export детерминирован.

## 7. Покрытие, readiness и вторая жизнь

Coverage отдельно показывает:

- deliveries, annotated и unannotated deliveries;
- resolved intent labels и resolved semantic-plan labels;
- uncertain labels и abstentions по каждому виду;
- intent class counts для всех трёх классов;
- provenance gaps и исключённые cutoff ревизии.

Стартовые пороги R1 сохраняются без переосмысления: не менее 50 подтверждённых intent
labels и не менее 50 semantic-plan labels **всего**, а не по 50 на класс. Temporal и
class coverage измеряются отдельно. Отсутствие любого intent class в train делает данные
непригодными для R2 review; конкретный минимум на класс не выдумывается в R2-PREP и
должен быть зафиксирован до обучения.

`prepare_r2_dataset` переиспользует `assess_readiness`, добавляет annotation coverage и
не может вернуть `training_allowed=True` при недостатке меток, provenance gaps,
неполном temporal/class coverage или unresolved-only данных. Даже
`ready_for_r2_review` означает только право рассмотреть следующий gate, а не запуск
обучения.

Каждая жизнь имеет отдельный SQLite и отдельный export. Вторая жизнь начинает с пустой
разметки, пустых samples и `training_allowed=False`; общие счётчики, defaults и weights
из первой жизни не наследуются.

## 8. Privacy и sandbox

- Все тесты используют `tmp_path` и `DIGITAL_BEING_DATA_DIR`, указывающий в sandbox.
- Живые `data/` не читаются и не изменяются; реальная Тэсс не запускается.
- Импорт модуля не создаёт файлы и не подключается к активной речи.
- Экспорт по умолчанию содержит только whitelisted sanitized fields.
- Отдельный raw-text export в R2-PREP не проектируется и не разрешается.
- Сеть, внешняя LLM, model self-review и автоматические псевдометки не используются.

## 9. Отдельное окно ручной разметки

`src/core/response_annotation_review.py` соединяет экспортированный snapshot и
read-only response-journal в примеры для человека. `src/ui/annotation_review_window.py`
показывает их в отдельном Tk-окне; `tools/manual/review_response_annotations.py` —
единственная точка запуска. Импорт этих модулей не создаёт файлы и не открывает окно.

Все четыре пути обязательны. Snapshot, исходный response-journal и annotation-journal
должны находиться внутри явно указанного `--sandbox-root`; default-путей к живым
`data/` нет. Сначала нужно остановить сущность и подготовить согласованные копии
snapshot и response-journal в отдельной песочнице. Окно само не копирует живую базу.

Пример PowerShell:

```powershell
.venv/Scripts/python.exe tools/manual/review_response_annotations.py `
  --sandbox-root "C:\review-sandbox" `
  --snapshot "C:\review-sandbox\snapshot.json" `
  --response-journal "C:\review-sandbox\response_experience_events.sqlite3" `
  --annotation-journal "C:\review-sandbox\response_annotations.sqlite3" `
  --life-id "UUID-ЖИЗНИ"
```

В окне доступны:

- read-only сообщение человека и baseline-текст ответа;
- классы «Вопрос о состоянии», «Вопрос о занятии», «Другое» и «Не уверен»;
- подтверждение исходного варианта, исправление и отдельное «Факты неясны»;
- обычные поля энергии, текущего и завершённого занятия вместо редактирования JSON;
- навигация, счётчики размеченных и resolved меток.

Raw texts существуют только в памяти окна для показа. Annotation SQLite получает
очищенные labels без текстов, их hashes, target/work_id и evidence IDs. Повторное
исправление добавляет revision и `supersedes_event_hash`; история не переписывается.
Несопоставленные snapshot/delivery записи не превращаются в метки, а возвращаются в
счётчиках пропусков загрузчика.

## 10. Acceptance tests

`tests/test_neural_speech_r2_prep.py` фиксирует:

1. три intent class и human-only provenance;
2. запрет self-labeling и подмены abstention классом `UNKNOWN_OR_OTHER`;
3. связь response/plan/delivery hash и строгий sanitized plan schema;
4. append-only corrections, idempotency и reopen integrity;
5. uncertainty/abstention и отдельную статистику покрытия;
6. детерминированный temporal split и исключение поздних revisions;
7. cross-life, orphan и conflicting provenance rejection;
8. пустую вторую жизнь и отсутствие training permission при недостатке данных;
9. отсутствие raw-text полей и runtime side effects.

`tests/test_response_annotation_review.py` дополнительно фиксирует:

1. read-only загрузку и проверку hash-chain исходного response-journal;
2. видимые пропуски orphan/unmatched записей вместо ложных меток;
3. подтверждение, исправление, uncertainty, abstention и reopen через session;
4. независимость второй жизни и отклонение всех путей вне sandbox;
5. отсутствие текстов, их hashes и приватных target/reference IDs в SQLite меток;
6. построение Tk-окна, видимость действий и рабочие кнопки исправления/abstention;
7. использование выбранного self-intent при «Факты неясны» и блокировку кнопки для
   `UNKNOWN_OR_OTHER`/`ABSTAIN`;
8. явный пропуск `missing_input` для записей без человеческого входа.

Фактические проверки реализации:

- контрактные тесты R2-PREP: **29 passed**;
- тесты sandbox UI/session: **13 passed**;
- профильный regression диалога и разметки: **305 passed**;
- полный regression: **4279 passed, 2 skipped за 550,31 с**;
- Ruff check и форматирование 601 файла: passed;
- compileall: passed;
- mypy: no issues в стандартной проверке 2 entry points и отдельной проверке 3 модулей разметки;
- Bandit: passed; только существующие informational `nosec` warnings.

UI/CLI разметки реализован и проверен на синтетических sandbox-данных и на согласованной
sandbox-копии реальных ответов. Пользователь подтвердил, что после исправления «Факты
неясны» сохраняет выбранный self-intent без ошибочного окна. Первая разметка сохранила
30 человеческих меток без provenance gaps: 20 resolved intent labels и 8 resolved semantic
plans. Все 10 записей с пустым `observed_input` получили abstention и не стали resolved
метками; исправленный загрузчик исключает их из окна как `missing_input`, оставляя 20
пригодных примера. Append-only журнал при этом не перезаписывается.

Для новых пользовательских ответов Runner передаёт исходный `user_text` во все ветки
`_reply_to_user`; без человеческого входа остаётся только служебное приветствие
`chat_opened`. Обучение и подключение к активной речи не выполнялись: набор остаётся
`insufficient_data`, `training_allowed=False`. Живые `data/` не изменялись, а работающая
сущность к разметке не подключалась. Commit и push не выполнялись. Следующий отдельный
gate — сбор дополнительных человеческих меток и оценка готовности набора, а не
автоматический запуск R2.
