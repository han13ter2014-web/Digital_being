# Ручные проверки

Скрипты в этой папке **не запускаются pytest** — у них нет утверждений
(`assert`) и они печатают результат в консоль. Это инструменты для
ручной проверки поведения, когда нужно посмотреть на живой вывод.

Запуск (из корня проекта):

```bash
python tools/manual/synthesis_manual.py
python tools/manual/new_systems_manual.py
python tools/manual/checkpoint_restore_manual.py
python tools/manual/death_risk_driven_manual.py
```

Автоматические тесты живут в `tests/` и запускаются так:

```bash
python -m pytest -q
```

## Почему они здесь

Раньше эти файлы лежали в корне проекта с именами `test_*.py`, хотя
тестами в понимании pytest не были. Pytest их не собирал
(`testpaths = ["tests"]`), но они создавали впечатление, что тестов
больше, чем есть. Имена изменены на `*_manual.py`, чтобы это было
очевидно.

Если какой-то из сценариев нужен в CI — его следует переписать с
`assert` и положить в `tests/`.
