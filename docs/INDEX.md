# Индекс документации Digital Being

Это карта документов проекта. Она отделяет **актуальные** руководства от
**исторических** отчётов, чтобы не искать нужное по всему `docs/`.

## С чего начать

| Документ | Кому | О чём |
|---|---|---|
| [README.md](../README.md) | всем | обзор, быстрый старт, текущее состояние |
| [USAGE.md](USAGE.md) | пользователю | запуск, команды, настройки, трей-режим |
| [ARCHITECTURE.md](ARCHITECTURE.md) | разработчику / агенту | устройство ядра, подсистемы, цикл жизни |
| [INTEGRATION.md](INTEGRATION.md) | разработчику / агенту | одно существо и один эффектор: контракт, бюджет действия, границы власти, дорожная карта 18–24 |
| [WILL.md](WILL.md) | пользователю / агенту | свобода воли, права, этика |
| [EVOLUTION.md](EVOLUTION.md) | разработчику / агенту | как агент может меняться |

## Текущее состояние и метрики

Контракт текущей работы после общего обзора:
[LIFE_CONTINUITY_CONTRACT.md](LIFE_CONTINUITY_CONTRACT.md) — этапы 0–1,
безопасное восстановление и ещё не закрытые границы.

| Документ | О чём |
|---|---|
| [BASELINE.md](BASELINE.md) | точка отсчёта: реальный лог, 693 362 действия, 0 целей |
| [STAGE1_REPORT.md](STAGE1_REPORT.md) | ротация логов, декомпозиция, кламп энергии, кулдаун |
| [STAGE2_REPORT.md](STAGE2_REPORT.md) | качество знаний и внешнего поиска |
| [STAGE3_REPORT.md](STAGE3_REPORT.md) | изоляция данных тестов (`DIGITAL_BEING_DATA_DIR`) |
| [STAGE4_REPORT.md](STAGE4_REPORT.md) | гигиена кода, мёртвый код, мелкие баги |
| [STAGE5_REPORT.md](STAGE5_REPORT.md) | смысл и метрики: цели, типы действий, декомпозиция |
| [STAGE6_REPORT.md](STAGE6_REPORT.md) | документация: индекс, ссылки, актуализация |
| [DELAMAIN_LOCAL.md](DELAMAIN_LOCAL.md) | локальный контур: sandbox, действия, SQLite-память, runtime, подсистема, мост, authoring, backoff, replan, контекст ошибки, bounded repair, оценка возможностей, effector-контракт, core-driven шаг и бюджет действия |
| [STAGE7_REPORT.md](STAGE7_REPORT.md) | первый замкнутый контур Delamain-local |
| [STAGE8_REPORT.md](STAGE8_REPORT.md) | интеграция Delamain-local и цикл исполняемых целей |
| [STAGE9_REPORT.md](STAGE9_REPORT.md) | навыки, повторные попытки и память-зависимый цикл |
| [STAGE10_REPORT.md](STAGE10_REPORT.md) | опциональный локальный LLM-планировщик и fallback |
| [STAGE11_REPORT.md](STAGE11_REPORT.md) | approval-политика для опасных действий и планов LLM |
| [STAGE12_REPORT.md](STAGE12_REPORT.md) | мост когнитивных целей `GoalSubsystem` и исполняемых целей Delamain |
| [STAGE13_REPORT.md](STAGE13_REPORT.md) | безопасный authoring payload: proposal, accept/reject, `/goals exec` |
| [STAGE14_REPORT.md](STAGE14_REPORT.md) | bounded backoff и перепланирование после ошибки действия |
| [STAGE15_REPORT.md](STAGE15_REPORT.md) | перепланирование с контекстом упавшего шага |
| [STAGE16_REPORT.md](STAGE16_REPORT.md) | ограниченный repair внутри одной попытки, durable repair-approval |
| [STAGE17_REPORT.md](STAGE17_REPORT.md) | детерминированная оценка возможностей: suite, метрики, CLI и ограничения |
| [STAGE18_REPORT.md](STAGE18_REPORT.md) | core-owned effector contract: идемпотентный адаптер, restart, approval и ограничения 18A |
| [STAGE18B_REPORT.md](STAGE18B_REPORT.md) | core-driven effector: один шаг за цикл ядра, пассивный tick, interval, legacy-goal isolation и ограничения 18B |
| [STAGE19_REPORT.md](STAGE19_REPORT.md) | бюджет действия: одно решение на попытку, резерв, потолок стоимости, остановка, default-off и ограничения 19 |
| [DEPTH_EXPERIMENT.md](DEPTH_EXPERIMENT.md) | проверка гипотезы глубины: 25 прогонов, коэффициент не повышен |
| [EXPERIENCE_EPISTEMICS.md](EXPERIENCE_EPISTEMICS.md) | эмоция отдельно от свидетельства, гипотезы, происхождение и сохранение опыта |
| [ACTION_EXPECTATIONS.md](ACTION_EXPECTATIONS.md) | ожидание до действия, собственное наблюдение и пересмотр представления о теле |
| [RESTART_CONTINUITY.md](RESTART_CONTINUITY.md) | обычный перезапуск сохраняет опыт и следующее ожидание; атомарный чекпоинт |
| [EMPIRICAL_CLAIMS.md](EMPIRICAL_CLAIMS.md) | отдельные утверждения об энергии и усталости: условия, независимые выводы, перезапуск |
| [EXPERIMENT_CHOICE.md](EXPERIMENT_CHOICE.md) | проверка собственного утверждения как необязательный кандидат арбитру |
| [AUTONOMOUS_LIFE_EXPERIMENT.md](AUTONOMOUS_LIFE_EXPERIMENT.md) | три естественные траектории с перезапуском; границы проверок и доминирование выхода из тупика |
| [LOOP_ESCAPE_DIAGNOSTICS.md](LOOP_ESCAPE_DIAGNOSTICS.md) | причинный журнал: повторные предложения застрявших способов и замена отдыхом |
| [METHOD_FEEDBACK.md](METHOD_FEEDBACK.md) | этап 1: бесплодный способ откладывается до арбитража, новые сведения допускают повтор |
| [SQLITE_CHECKPOINTS.md](SQLITE_CHECKPOINTS.md) | opt-in SQLite: разделяемые блоки снимков, совместимость JSON, ограничения масштаба |
| [ACCESS_AND_STORAGE_PLAN.md](ACCESS_AND_STORAGE_PLAN.md) | аудит доступов и порядок подключения собственной среды деятельности |
| [CHANGELOG.md](../CHANGELOG.md) | история изменений |

## Эксплуатация и сборка

| Документ | О чём |
|---|---|
| [BUILD.md](BUILD.md) | сборка `DigitalBeing.exe` через PyInstaller |
| [INSTALLER.md](INSTALLER.md) | Windows-установщик, обновление, типичные проблемы |

## Философия проекта

| Документ | О чём |
|---|---|
| [README_DIGITAL_LIFE.md](README_DIGITAL_LIFE.md) | цифровая жизнь, анатомия, три периода эволюции |
| [digital_life_anatomy.md](digital_life_anatomy.md) | описание «анатомии» агента |
| [anatomy_evaluation.md](anatomy_evaluation.md) | краткая оценка анатомической модели |

## Исторические материалы

Эти документы полезны как контекст, но **не описывают текущее состояние**.
Их цифры (число тестов, файлов, строк) относятся к датам внутри файлов.

| Документ | Дата | Почему исторический |
|---|---|---|
| [AUDIT_REPORT.md](AUDIT_REPORT.md) | 24.06.2026 | аудит до ревизии этапов 0–6 |
| [ETAP3_ETAP4.md](ETAP3_ETAP4.md) | июнь 2026 | ранняя нумерация этапов разработки |
| [evaluation_self_developing_life_report.md](evaluation_self_developing_life_report.md) | 22.06.2026 | исследовательская оценка |
| [final_evaluation_partnership_report.md](final_evaluation_partnership_report.md) | 23.06.2026 | исследовательская оценка |
| [test_fic/](test_fic/) | июнь 2026 | архив консольных выводов и старых прогонов |

## Про нумерацию этапов

В проекте встречаются две разные нумерации:

* **Ревизия 2026-10** — отчёты `STAGE1`–`STAGE19` (безопасность и утечка,
  данные и поиск, изоляция тестов, гигиена, смысл/метрики, документация,
  первый контур действия/памяти Delamain-local, интеграция этого контура
  с агентом, переиспользование навыков и повторы, опциональный локальный
  LLM-планировщик, approval для опасных действий, мост когнитивных и
  исполняемых целей, безопасный authoring executable-payload, bounded
  backoff и перепланирование после ошибки, replan с контекстом упавшего
  шага, bounded repair внутри одной попытки, детерминированная оценка
  возможностей и CLI для неё, core-owned effector contract, core-driven
  шаг эффектора для перехода от двух контуров к одному существу и единое
  бюджетное решение поверх существующей энергии).
  Это текущая линия работ. Этап 0 был подготовительным (инициализация git,
  бэкап `data/`, удаление исходного лога) и отдельного отчёта не имеет —
  его результат зафиксирован в [BASELINE.md](BASELINE.md).
* **Ранняя разработка (июнь 2026)** — внутренние «Этап 3.5», «Этап 4.5»,
  «Этап 5», «Этап 6» в [ARCHITECTURE.md](ARCHITECTURE.md) и
  [ETAP3_ETAP4.md](ETAP3_ETAP4.md). Это про PluginRegistry, evolve-pipeline
  и метрики, а не про текущую ревизию.

При ссылке на «этап» уточняйте, какая нумерация имеется в виду.

## Проверка ссылок

Все относительные ссылки на `.md` в `README.md`, `CHANGELOG.md` и
`docs/*.md` проверены скриптом: битых путей нет. Якоря (`#...`) не
проверяются автоматически — при переименовании заголовков их нужно
обновлять вручную.
