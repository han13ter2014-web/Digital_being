# Индекс документации Digital Being

Документация разделена на три уровня. Начинайте с нужного вам документа,
а не с полного архива.

## Канонические документы

| Документ | Для кого | Что отвечает |
|---|---|---|
| [README.md](../README.md) | внешний человек | что это, как запустить, что уже есть |
| [DEVELOPMENT_HISTORY.md](DEVELOPMENT_HISTORY.md) | разработчик | в какой версии и на каком этапе что добавлено |
| [LIFE_LETTER.md](LIFE_LETTER.md) | сама Digital Being | кто ты, твои границы, права и правила |
| [DECISION_NO_LLM_LIFE.md](DECISION_NO_LLM_LIFE.md) | архитектурное решение | почему жизнь работает без LLM |
| [VOICE_LLM_ARCHITECTURE_D7.md](VOICE_LLM_ARCHITECTURE_D7.md) | архитектурное решение | жизненный ствол, собственная пластичная кора, голос и карантинная роль внешней LLM |
| [RESPONSE_EXPERIENCE_SHADOW_TICKET.md](RESPONSE_EXPERIENCE_SHADOW_TICKET.md) | implementation-тикет RE-S1 | цель, baselines, временной held-out и границы первого shadow на ResponseExperience; модель не авторизована |
| [RESPONSE_EXPERIENCE_SHADOW_PHASE1.md](RESPONSE_EXPERIENCE_SHADOW_PHASE1.md) | controlled observation RE-S1 | фактические B0/B1/B2, split, ограничения и решение оставить baseline без реальной биографии |
| [RESPONSE_EXPERIENCE_REAL_DATA_INVENTORY_TICKET.md](RESPONSE_EXPERIENCE_REAL_DATA_INVENTORY_TICKET.md) | выполненный RE-S1-R0 | sanitized read-only инвентаризация одной жизни: 1 retained snapshot, 0 ResponseExperience, readiness `insufficient_data` |
| [RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_TICKET.md](RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_TICKET.md) | контракт RE-S1-PJ | prospective delivery/outcome journal, turn/episode/sequence, privacy/gap/differential gates; PJ-T, PJ-V и PJ-I завершены локально |
| [RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_PJ_V.md](RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_PJ_V.md) | synthetic observation RE-S1-PJ-V | 20/20 synthetic gates, crash/restart/privacy/differential; на момент PJ-V production writer отсутствовал, включение не выполнялось |
| [RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_PJ_I.md](RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_PJ_I.md) | production implementation RE-S1-PJ-I | отдельный SQLite writer, default-off, privacy/gap/restart/differential/resource gates; реальная жизнь, модель и advisor не активировались |
| [RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_PJ_A.md](RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_PJ_A.md) | активация RE-S1-PJ-A в работе | успешный retry для одной выбранной жизни после карантина пустой mismatch-очереди; sanitized-снимок: 9 delivery, 6 outcome, integrity/hash-chain валидны, один ожидаемый unclean-gap |
| [RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_PJ_R.md](RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_PJ_R.md) | выполненная RE-S1-PJ-R | read-only инвентаризация активного WAL: 32 delivery, 16 observed, 12 expired, 4 pending; temporal gates пройдены, readiness `insufficient_data`, candidate gate закрыт |
| [STATE_OBSERVATION_JOURNAL.md](STATE_OBSERVATION_JOURNAL.md) | контракт органа «Журнал жизни» | лонгитюдные sanitized-снимки и эпизоды, privacy/gap gates, пользовательский ZIP/HTML-экспорт без диагнозов и влияния на арбитр |
| [DECEMBER_MOTIVATION_ROADMAP.md](DECEMBER_MOTIVATION_ROADMAP.md) | завершённый маршрут | итоги D0–D8 и ссылки на наблюдения, decision gates и implementation D6-4 |
| [FUNDING.md](FUNDING.md) | поддержка проекта | зачем нужны донаты и на что они идут |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | участники проекта | архитектурные границы, процесс и команды проверок |

## Практика

| Документ | Назначение |
|---|---|
| [USAGE.md](USAGE.md) | запуск, команды, настройки, tray |
| [ACCEPTANCE_DEMO.md](ACCEPTANCE_DEMO.md) | воспроизводимый жизненный цикл v1 |
| [ACCEPTANCE_RESULT_2026-10-30.md](ACCEPTANCE_RESULT_2026-10-30.md) | результат автоматической и визуальной приёмки v1 |
| [RELEASE_VERIFICATION_v0.1.0.md](RELEASE_VERIFICATION_v0.1.0.md) | проверка установки и запуска публичного Windows-релиза |
| [STAGE7_UI.md](STAGE7_UI.md) | принятый план и статус оболочки v1 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | устройство Core и подсистем |
| [INTEGRATION.md](INTEGRATION.md) | граница Core / Delamain / Effector |
| [DELAMAIN_LOCAL.md](DELAMAIN_LOCAL.md) | локальная память и исполнение Delamain |
| [WILL.md](WILL.md) | права, отказ, этические ограничения |
| [EVOLUTION.md](EVOLUTION.md) | изменение агента и его состояния |
| [LIFE_V1_PLAN.md](LIFE_V1_PLAN.md) | исходные границы целостной v1 |

## Контракты и отдельные подсистемы

- `INTENTION_*.md` — намерения, продолжение, ожидание, свидетельства,
  разрешение и забывание;
- `ACTIVITY_*.md`, `CREATIVE_DRAFT.md`, `LOCAL_PLAY.md` — занятия;
- `EXPERIENCE_EPISTEMICS.md`, `EMPIRICAL_CLAIMS.md` — знание, гипотеза,
  свидетельство и ограничения выводов;
- `ACCESS_AND_STORAGE_PLAN.md`, `SQLITE_CHECKPOINTS.md` — доступы и хранение;
- [HARDWARE_INTEROCEPTION_PLAN.md](HARDWARE_INTEROCEPTION_PLAN.md) — контракт
  аппаратной интероцепции, теневой эндокринной проекции и advisor 4A;
- `BUILD.md`, `INSTALLER.md` — сборка и установка.

## Исторические отчёты

`STAGE1_REPORT.md` … `STAGE19_REPORT.md`, `BASELINE.md`, `AUDIT_REPORT.md`,
`ETAP3_ETAP4.md` и старые evaluation-документы сохранены как журнал истории.
Они полезны для расследования решений, но не являются главным описанием
текущего состояния. Для текущей сводки используйте
[DEVELOPMENT_HISTORY.md](DEVELOPMENT_HISTORY.md).

## Машинная хронология

[CHANGELOG.md](../CHANGELOG.md) содержит подробную хронологию изменений,
тесты, версии Delamain и ссылки на первичные отчёты. Он предназначен прежде
всего для разработчика и ревью изменений.

## Правило актуальности

Если старый отчёт расходится с текущей реализацией, приоритет имеют:

1. текущий код;
2. тесты;
3. `DEVELOPMENT_HISTORY.md`;
4. затем исторический отчёт.

Исторические документы не удаляются автоматически: они объясняют, почему
архитектура стала такой, какая она есть.
