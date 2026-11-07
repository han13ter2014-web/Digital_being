# Слияние К12 в main

Дата: 2026-11-07

## Хэши

- `main` до merge: `93d1f3fb5ccc372bcac09bc4e7654b8ed7a22317`
- Ветка К12: `decca230e6557792280753cbb03e5a99bc90cc4e`
- Merge-коммит: `c58e30d210126070e697676301b254457510023b`
- Способ: `git merge --no-ff kimi/k12-graph-readability`
- Конфликтов не было. Push не выполнялся. Тэсс не запускалась.

## Состав изменений main

`git diff --name-status 93d1f3f..c58e30d`:

```text
M	src/ui/web_dashboard.py
```

В main вошёл только слой представления веб-карты. Других продуктовых файлов в слиянии нет.

## Профильный гейт

Новая песочница: `merge_profile_sandbox_c58e30d`.

```text
62 passed in 10.36s
```

Журнал: `merge_profile_tests.log`.

## data/

- До merge: 98 файлов (`data_hashes_before_merge.json`).
- После merge и профильного гейта: 98 файлов (`data_hashes_after_merge.json`).
- Добавлено: 0; удалено: 0; изменено по SHA-256: 0.
- Итог сравнения: PASS (`data_merge_comparison.json`).

Прежние tracked-изменения `data/access_settings.json`, `data/active_profile.json`, `data/knowledge_base.json` сохранены в рабочем дереве и не включались в merge-коммит.
