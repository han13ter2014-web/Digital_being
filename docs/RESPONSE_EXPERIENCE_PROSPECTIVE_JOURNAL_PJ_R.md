# RE-S1-PJ-R — sanitized read-only инвентаризация prospective journal

Дата: 2026-11-21.

Статус: **один согласованный снимок активного журнала инвентаризирован; readiness —
`insufficient_data`, candidate gate закрыт**. Модель, обучение, baselines, split,
advisor и влияние на жизнь не выполнялись. Commit/push/publication не выполнялись.

Контракты: `RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_TICKET.md`,
`RESPONSE_EXPERIENCE_REAL_DATA_INVENTORY_TICKET.md`. Предыдущая активация:
`RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_PJ_A.md`.

## 1. Разрешённая граница и источник

Владелец отдельно разрешил PJ-R для одной уже выбранной жизни и оставил её работать в
фоне. Обработан только prospective SQLite journal, без чтения текстов диалога, других
жизней, backups, memory traces, логов или внешних session-scoped ответов.

Активный WAL прочитан через `mode=ro`, `query_only` и одну deferred read transaction.
`immutable=1` не использовался. Constructors, миграции, save/gc/recovery, agent/UI,
сеть и внешняя LLM не вызывались. Writer не останавливался и естественные события могли
продолжить журнал после снимка.

Это адаптация R0-протокола к активному prospective WAL: согласованность обеспечивается
одной read transaction, а не quiescence всей жизни. Побайтовая неизменность data root не
заявляется. Размеры live-файлов измерены после снимка и не являются transactional
metadata.

## 2. Проверки до и после чтения

До обращения к реальному источнику synthetic-гейты прошли **11/11**:

- события, статусы и шесть observed-классов сверены;
- pending/expired остаются censored;
- порядок outcome после delivery проверен;
- surrogate repeat origin не раскрывает исходный ID;
- ячейки `n<5` подавляются в aggregate-only отчёте;
- подмена hash и дополнительное raw-поле отклоняются;
- conservative readiness и privacy scan пройдены.

На реальном снимке SQLite integrity — `ok`, sequence/hash-chain/head валидны, SQL counts
совпали с decoded events. Feature whitelist, surrogate IDs, отсутствие reverse mapping,
post-run privacy scan и повторное чтение артефактов пройдены. Независимый пересчёт
sanitized-артефактов подтвердил записи, классы, срезы, temporal links и ресурсный бюджет.

## 3. Фактическое окно

| Показатель | Значение |
|---|---:|
| Event sequence | 63 |
| Allocated turns | 31 |
| Зарегистрировано доставок | 32 |
| Observed / supervised eligible | 16 / 16 |
| Expired (censored) | 12 |
| Pending | 4 |
| Invalid / conflicting witnesses / temporal violations | 0 / 0 / 0 |
| Профили | 1 |
| Terminal с известным outcome cycle | 28 / 28 |
| Доставки с известной episode identity | 32 / 32 |
| Pruned | 0 |

События: `delivery=32`, `outcome=16`, `expired=12`, `journal_started=2`,
`journal_gap=1`. Счёт сходится: **63 события**, **32 доставки = 16 observed + 12 expired
+ 4 pending**.

Окно относится к одной жизни и не является полной биографией.
`removed_or_never_available=unknown`. Pending и expired не получают отрицательных меток.
Порядок delivery/outcome и доступность late outcomes подтверждены в наблюдаемом
event-stream; исходный unclean interval сохраняет `completeness=unverified`.

## 4. Исходы и покрытие

| Observed outcome | Число |
|---|---:|
| `answer` | 0 |
| `follow_up` | 0 |
| `unclassified_reply` | 11 |
| `ordinary_reply` | 5 |
| `explicit_support` | 0 |
| `explicit_opposition` | 0 |

Представлены только 2 из 6 observed-классов. `no_observed_reaction` относится к 12
expired и не смешивается с observed-классами.

Aggregate-only покрытие observed-записей; ячейки `n<5` обозначены `insufficient_data`:

| Срез | Распределение |
|---|---|
| Context | `other=8`, `unknown_reply=5`; `dialogue_learning` и `social_reply` — `insufficient_data` |
| Expected reaction | `continuation_or_support=5`, `explicit_feedback_or_relevant_reply=10`; `answer_or_feedback` — `insufficient_data` |
| Response language | `ru=16` |
| Source после frozen normalization | `other=16` |
| Realization kind | `fixed_template=16` |
| Borrowed present | `false=16` |
| Repeat in retained window | `false=12`, `true` — `insufficient_data` |

Все source значения попали в frozen `other`: это ограничение текущего нормализованного
признака, а не доказательство одинакового происхождения реплик. Один профиль и один язык
также не дают доказанного покрытия других личных и языковых контуров.

## 5. Gap и ресурсы

Единственный gap — ожидаемый `previous_shutdown_unclean` после первой неудачной попытки
запуска. Новых gap reasons, corruption, orphan/conflicting outcomes и temporal violations
в снимке нет. Writer остаётся `degraded` по исходной причине; это не скрывается.

| Ресурс | Наблюдено |
|---|---:|
| Main DB | 4 096 байт |
| WAL после снимка | 1 680 992 байта |
| Frozen main + WAL budget | 64 MiB |
| Бюджет | не превышен |

SHM присутствует, clean shutdown — `false`: жизнь продолжала работать. Штатное закрытие
writer/WAL этой фазой не проверялось. Write latency и фактический tick impact живого
процесса отдельно не измерялись.

## 6. Readiness и решение

Итог — **`insufficient_data`** по фактическим причинам:

1. представлены только 2 из 6 observed-классов;
2. личный, контекстный и ожидательный срезы малы или имеют подавленные ячейки;
3. исходный unclean-gap остаётся частью журнала;
4. снимок взят из активного незакрытого writer;
5. одна жизнь, один профиль и `ru` не доказывают покрытие остальных режимов.

B0/B1/B2 и 60/20/20 не запускались: владельцем была разрешена инвентаризация и оценка
readiness, а не baselines. Даже доказанный event-order не открывает candidate gate и не
выбирает MLP/RNN/LTC. Следующий шаг — естественное накопление более широкого реального
окна и новая отдельная оценка, а не обучение на текущих 16 observed-примерах.

## 7. Артефакты и воспроизводимость

Чувствительные sanitized-артефакты находятся только в ignored
`tmp/response_experience_prospective/pj_r/r01/`:

- `sanitized-records.jsonl` — 32 записи с run-local surrogate IDs, относительными
  циклами/event offsets и whitelist features;
- `report.json`, `report.md`, `validation.json`, `self-test.json`;
- `pj_r_inventory.py`, `verify_pj_r.py`.

Выполнены:

```powershell
.venv/Scripts/python.exe tmp/response_experience_prospective/pj_r/r01/pj_r_inventory.py --self-test
.venv/Scripts/python.exe tmp/response_experience_prospective/pj_r/r01/pj_r_inventory.py --run
.venv/Scripts/python.exe tmp/response_experience_prospective/pj_r/r01/verify_pj_r.py
```

Все три проверки завершились `status=passed`. Sanitized-записи в docs, Git, issue, chat
или сеть не переносились. В этом документе присутствуют только агрегаты; raw text,
исходные IDs/paths/timestamps, integrity hashes, reverse mapping и raw exceptions
отсутствуют. Production-код и тесты проекта не изменялись, поэтому полный regression этой
документно-диагностической фазой не запускался.
