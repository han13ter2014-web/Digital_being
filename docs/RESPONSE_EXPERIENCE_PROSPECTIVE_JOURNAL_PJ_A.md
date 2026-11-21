# RE-S1-PJ-A — активация prospective journal для одной жизни

Дата подготовки: 2026-11-21.

Статус: **цикл накопления реальных событий для одной выбранной жизни штатно остановлен;
закрытие writer/WAL подтверждено**. Финальный sanitized-снимок содержит 55 delivery,
24 outcome, 29 expired и 20 `record_pruned`; integrity/hash-chain валидны,
`clean_shutdown=true`, writer lease отсутствует, WAL — 0 байт. Исходный unclean gap и два
последующих `previous_writer_degraded` сохранены как история degraded-запусков. Это не
завершённый сбор данных и не новая PJ-R: readiness остаётся `insufficient_data`.

Контракт и предыдущие границы: `RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_TICKET.md`,
`RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_PJ_I.md`.

## 1. Выбранная граница

Владелец разрешил включить журнал для одной изолированно выбранной жизни и начать сбор
будущих реальных событий. Локально выбрана текущая активная жизнь из
`data/active_profile.json`. Её исходный UUID не публикуется в этом отчёте; binding
находится только в ignored launcher.

Перед подготовкой подтверждено:

- активный указатель однозначно соответствует выбранной managed-жизни;
- существующего `response_experience_events.sqlite3` у выбранной и других жизней нет;
- процессы Python/Digital Being на момент проверки не обнаружены;
- новая жизнь, seed и восстановление другого профиля не выбирались;
- живой checkpoint, active profile и другие данные не изменялись.

## 2. Как включение ограничено одной жизнью

Создан ignored launcher:

```text
tmp/response_experience_prospective/start_pj_a_tess.ps1
```

Он:

1. сверяет UUID из `active_profile.json` с зафиксированным выбранным UUID;
2. останавливается, если активная жизнь изменилась;
3. задаёт `DIGITAL_BEING_DATA_DIR` только для своего процесса;
4. задаёт `DIGITAL_BEING_RESPONSE_JOURNAL=1` только для своего процесса;
5. запускает обычный `.venv/Scripts/python.exe main.py` без `--new`, `--seed`,
   `--no-restore` или ускоренного режима;
6. удаляет обе переменные после завершения.

Глобальные/user/machine environment variables не устанавливались. Другие жизни и обычный
запуск вне launcher не получают флаг. PowerShell syntax проверен отдельно, без запуска
`main.py` и без создания журнала.

## 3. Запуск владельца

Команда из корня проекта:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "tmp\response_experience_prospective\start_pj_a_tess.ps1"
```

Запуск принадлежит владельцу и использует обычный UI/темп проекта. Агент жизнь не
запускал и не должен создавать искусственные диалоги ради dataset.

Writer создаёт `journal_started`. Далее журналируются только будущие фактические
локальные доставки и их реальные transitions. Мысли, внешние session-scoped ответы и
доставки без `message_id` не становятся опытом.

Первая попытка остановилась до диалога. После разрешённого карантина пустого
mismatch-файла владелец повторил запуск и подтвердил «Работает». При повторном открытии
writer, как и требовал контракт, создал `journal_gap` с `previous_shutdown_unclean` и
degraded status. Это честная отметка первого аварийного завершения, а не новый дефект и
не доказательство потери событий.

## 4. Первая попытка запуска: FAILED, затем разрешённый карантин

Владелец выполнил первый запуск через launcher. Жизнь остановилась до обычного диалога:

```text
ValueError: журнал сообщений принадлежит другой жизни
ValueError: Не удалось восстановить журнал принятых сообщений; данные сохранены
```

Источник — защита `PersistentMessageQueue._read_journal()` в
`src/core/agent_runner.py`. Последующая ошибка `'NoneType' object has no attribute
'mainloop'` относится к закрытию UI после основной остановки. Это не падение prospective
writer.

Sanitized-проверка глобального `data/checkpoints/pending_messages.json` показала:
`schema_version=1`, `life_matches_active=false`, `pending_count=0`,
`deferred_present=false`. Непрочитанных и отложенных сообщений в mismatch-файле не было.
Общее per-life исправление production-очереди не выполнялось: оно требует отдельного
решения владельца.

Prospective writer успел создать per-life SQLite и записать ровно один `journal_started`
с `event_sequence=1`. Проверка дала `integrity_check=ok`, валидную hash-chain,
`allocated_turns=0`, ноль delivery/outcome. Чистого shutdown нет; lease и WAL/SHM
сохранились после аварийного закрытия. Это не corruption и не доказательство потери
событий: реальных доставок ещё не было.

Владелец отдельно выбрал карантин mismatch-файла. Одноразовый fail-closed скрипт:

- сначала сохранил backup
  `tmp/response_experience_prospective/pj_a_diagnostics/pending_messages.before-quarantine.json`;
- затем переместил исходник в
  `data/checkpoints/quarantine/pending_messages.empty-mismatch.20261121T200558233018.json`;
- подтвердил побайтовое совпадение источника, backup и карантина;
- не изменял prospective journal.

Размер сохранённого файла — 105 байт, SHA-256:

```text
363085ca6ec43073b4bf488727ee28a20f7092609341a7938e36e99dec9130e2
```

Исходный mismatch-файл после операции отсутствовал. Это не удаление истории: он полностью
сохранён в двух местах. Повторно запускать quarantine-скрипт нельзя — он намеренно
остановится на отсутствующем источнике или существующем backup. Повторный запуск жизни
выполнен только обычным launcher выше.

## 5. Sanitized-снимок успешного повторного запуска

После подтверждения владельца «Работает» выполнен read-only скрипт
`tmp/response_experience_prospective/pj_a_diagnostics/read_sanitized_status.py`.
Он не экспортирует тексты, response/profile IDs или исходный life UUID. Перед повторным
использованием в него добавлена обработка отсутствующего queue-файла; production-код не
изменялся.

Фактический результат снимка:

| Показатель | Значение |
|---|---|
| Активный профиль соответствует launcher | `true` |
| Новая queue schema / соответствие жизни | `1` / `true` |
| Queue pending / deferred | `0` / `false` |
| SQLite integrity | `ok` |
| Hash-chain и head | валидны |
| Writer status / причина | `degraded` / `previous_shutdown_unclean` |
| Event sequence / allocated turns | `18` / `9` |
| `journal_started` | `2` |
| `journal_gap` | `1`, только `previous_shutdown_unclean` |
| Delivery | `9` |
| Outcome | `6`: `ordinary_reply=3`, `unclassified_reply=3` |
| Доставки без terminal-исхода в снимке | `3` |
| Expiry / pruning | `0` / `0` |
| Main DB / WAL | `4096` / `527392` байта |
| Lease / SHM / clean shutdown | `1` / присутствует / `false` |

Один lease, SHM и отсутствие clean shutdown ожидаемы во время работающего процесса. Три
доставки без terminal-исхода остаются pending и не получают искусственных меток. Статус
`degraded` относится к зафиксированному первому аварийному завершению; новых gap,
corruption или sequence/hash mismatch в снимке нет. Штатное закрытие writer/WAL этим
наблюдением ещё не проверено.

### 5.1. Финальный снимок после штатной остановки

После последующего естественного диалога владелец сохранил и штатно остановил жизнь.
Процесс завершился с кодом 0. Тот же read-only скрипт затем подтвердил:

| Показатель | Значение |
|---|---|
| Активный профиль соответствует launcher | `true` |
| SQLite integrity / hash-chain | `ok` / валидна |
| Event sequence / allocated turns | `138` / `45` |
| Delivery / outcome / expired | `55` / `24` / `29` |
| Доставки без terminal-исхода | `2` |
| Outcome classes | `ordinary_reply=9`, `unclassified_reply=15` |
| `record_pruned` | `20` |
| `journal_started` / `journal_stopped` / `journal_gap` | `4` / `3` / `3` |
| Gap reasons | `previous_shutdown_unclean=1`, `previous_writer_degraded=2` |
| Main DB / WAL | `241664` / `0` байт |
| Writer lease / clean shutdown | `0` / `true` |

Счёт сходится: **55 delivery = 24 outcome + 29 expired + 2 pending**. Pending и expired
не получили искусственных отрицательных меток. Штатное закрытие writer и WAL теперь
подтверждено; исторические gap и статус `degraded` не скрываются и не делают журнал
полным. Представлены по-прежнему только 2 из 6 observed-классов, поэтому это новое
sanitized-состояние PJ-A, а не повторная PJ-R, baseline или candidate gate.

## 6. Что наблюдать дальше

При последующих разрешённых sanitized наблюдениях фиксируются:

- writer `active/degraded/quarantine`, sequence, gaps и dropped events;
- delivery/outcome/expiry/pruning без экспорта сырых текстов;
- исходный `previous_shutdown_unclean` отдельно от любых новых gaps;
- unclean restart, corruption и Core restore divergence;
- storage, write latency и фактический tick impact;
- штатное закрытие writer/WAL после обычного завершения жизни.

Нельзя считать журнал полным при degraded/gap. Exactly-once между внешней доставкой и
SQLite не заявляется. Естественные события не подменяются synthetic-кейсами.

Если следующий запуск остановится, нельзя вслепую повторять запуск или перемещать другие
файлы: сначала разбирается новая ошибка.

## 7. Неразрешённые действия

PJ-A не разрешает модель, обучение, advisor, candidate gate, изменение поведения,
глобальное включение для других жизней, искусственные диалоги, сеть, новые зависимости,
общее per-life исправление очереди, commit или push. PJ-R и любые baselines требуют
отдельного разрешения после накопления достаточного реального окна.

Повторный запуск работает, реальные события накапливаются, но текущего небольшого снимка
с исходным gap недостаточно для модели или candidate gate. Readiness остаётся
`insufficient_data`. Последующая отдельно разрешённая read-only инвентаризация более
позднего окна зафиксирована в `RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_PJ_R.md`.
