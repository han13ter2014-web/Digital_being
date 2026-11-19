"""Преобразование снимка жизни в строки для карточек окна.

Чистая логика без Tk: сюда приходит словарь из ``build_life_snapshot``,
отсюда выходят готовые строки. Так карточки можно тестировать без экрана.

Главное правило — не выдумывать. Карточка показывает только то, что реально
лежит в снимке:

* «Почему выбрано» строится из причины намерения, состояния тела и прошлого
  исхода. Если ядро не сохранило проигравшие варианты, карточка их не
  рисует — лучше пусто, чем выдуманное «рассматривал X, Y, Z»;
* Effector показывает ``queued`` и ``waiting_approval`` отдельно от
  ``succeeded``: ожидание не выдаётся за выполненную работу.
"""

from __future__ import annotations

import math
from functools import partial
from typing import Any, Dict, List, Optional, Tuple

from src.ui import i18n

Row = Tuple[str, str]

# Действие → человеческая фраза для заголовка «Сейчас».
_ACTION_PHRASES = {
    "play": "Играю партию",
    "create_draft": "Продолжаю творческий черновик",
    "write_creative_draft": "Пишу творческий черновик",
    "explore": "Исследую тему",
    "communicate": "Общаюсь",
    "rest": "Отдыхаю",
    "deep_rest": "Глубоко отдыхаю",
    "reflect": "Размышляю",
    "self_reflect": "Размышляю о себе",
    "wait": "Жду",
    "ask_user": "Спрашиваю пользователя",
    "ask_question": "Задаю вопрос",
    "user_answer": "Отвечаю пользователю",
    "send_message": "Отправляю сообщение",
    "web_search": "Ищу в интернете",
    "process_stimulus": "Обрабатываю впечатление",
    "let_go": "Отпускаю намерение",
    "hypothesis": "Строю предположение",
    "synthesize_understanding": "Собираю понимание",
    "synthesize": "Соединяю знания",
    "act": "Действую",
    "set_own_goal": "Выбираю собственную цель",
    "make_choice": "Делаю выбор",
    "propose_alternative": "Предлагаю альтернативу",
    "teach_other": "Делюсь знанием",
    "creative_act": "Создаю",
    "draw": "Рисую",
    "compose_music": "Сочиняю музыку",
    "repair": "Исправляю",
    "organize_knowledge": "Упорядочиваю знания",
}

_SOURCE_LABELS = {
    "active_inference": "активный выбор",
    "legacy_active_inference": "прежний механизм выбора",
    "external_attention": "внешнее внимание",
    "embodiment": "состояние тела",
    "self_fading": "затухание намерения",
    "deliberate_pause": "осознанная пауза",
    "fallback_first_candidate": "первый доступный вариант",
    "social": "общение",
    "motivation": "мотивация",
    "intrinsic": "внутренняя мотивация",
    "need": "потребность",
    "drive": "влечение",
    "own_activity": "собственное занятие",
    "active_goal": "активная цель",
    "intention_continuation": "продолжение намерения",
    "new_interest": "новый интерес",
    "core_history": "история ядра",
}

_MOTIVATION_LABELS = {
    "curiosity": "любопытство",
    "competence": "мастерство",
    "autonomy": "автономия",
    "connection": "связь",
    "play": "игра",
    "rest": "отдых",
    "meaning": "смысл",
    "coherence": "внутренняя согласованность",
    "creativity": "творчество",
    "mastery": "совершенствование",
    "self_transcendence": "саморазвитие",
    "exploration": "исследование",
    "understanding": "понимание",
}

# Темы, к которым осмысленно добавлять название в кавычках.
_ACTION_WITH_TOPIC = {"create_draft", "explore"}

_FATIGUE_LABELS = {
    "fresh": "свежая",
    "normal": "обычная",
    "tired": "усталость",
    "exhausted": "истощение",
    "critical": "критическая",
}

_STATE_LABELS = {
    "alive": "жив",
    "dormant": "спит",
    "terminated": "ушёл",
    "unknown": "неизвестно",
}

# Статусы Effector в человекочитаемом виде. Порядок важен: активные сверху.
_EFFECTOR_LABELS = (
    ("queued", "в очереди"),
    ("waiting_approval", "ждёт подтверждения"),
    ("succeeded", "выполнено"),
    ("failed", "ошибка"),
    ("rejected", "отклонено"),
)

_GAME_RESULTS = {
    "X": "победа",
    "O": "поражение",
    "draw": "ничья",
    None: "идёт",
}


def life_state_label(state: Any, language: str = "ru") -> str:
    """Локализованное состояние; неизвестное значение отдаём как есть."""
    if i18n.normalize_language(language) == "ru":
        return _STATE_LABELS.get(str(state), str(state))
    return i18n.value_label(state, language)


def action_phrase(
    action: str, target: Optional[str] = None, language: str = "ru"
) -> str:
    phrase = i18n.action_phrase(action, language)
    if target and action in _ACTION_WITH_TOPIC:
        return f"{phrase} «{target}»"
    return phrase


def now_headline(snapshot: Dict[str, Any], language: str = "ru") -> str:
    """Одна живая фраза о том, что происходит прямо сейчас."""
    T = partial(i18n.text, language=language)
    life = snapshot.get("life") or {}
    state = str(life.get("state", "unknown"))
    if state == "dormant":
        return T("Сплю в Яслях")
    if state == "terminated":
        return T("Жизнь завершена")
    if state not in {"alive", "unknown"}:
        return f"{T('Состояние')}: {i18n.value_label(state, language)}"

    activity = (snapshot.get("now") or {}).get("activity")
    if activity:
        return action_phrase(
            str(activity.get("action") or ""), activity.get("target"), language
        )

    waiting = (snapshot.get("intentions") or {}).get("waiting") or []
    if waiting:
        target = waiting[0].get("target")
        if target:
            return f"{T('Жду новых сведений по теме')} «{target}»"
        return T("Жду новых условий")

    if life.get("needs_rest"):
        return T("Отдыхаю после напряжённой работы")
    return T("Выбираю, чем заняться")


def emotion_rows(
    snapshot: Dict[str, Any], language: str = "ru"
) -> List[Tuple[str, str, float]]:
    """Полная палитра из снимка: стабильный код, подпись и уровень 0…1."""
    emotions = snapshot.get("emotions") or {}
    levels = emotions.get("levels")
    if not isinstance(levels, dict):
        return []
    rows: List[Tuple[str, str, float]] = []
    for raw_name, raw_level in levels.items():
        try:
            level = float(raw_level)
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(level):
            continue
        name = str(raw_name)
        rows.append((name, i18n.value_label(name, language), max(0.0, min(1.0, level))))
    return rows


def dominant_emotion(snapshot: Dict[str, Any], language: str = "ru") -> str:
    """Доминирующий компонент только если ядро действительно его записало."""
    dominant = (snapshot.get("emotions") or {}).get("dominant") or {}
    name = dominant.get("emotion") if isinstance(dominant, dict) else None
    if name:
        return i18n.value_label(name, language)
    return i18n.text("Нет данных", language)


def body_rows(snapshot: Dict[str, Any], language: str = "ru") -> List[Row]:
    """Строки карточки тела: цифры, которые действительно есть."""
    T = partial(i18n.text, language=language)
    life = snapshot.get("life") or {}
    body = snapshot.get("body") or {}
    rows: List[Row] = [(T("Цикл"), str(life.get("cycle", 0)))]
    energy = life.get("energy")
    if energy is not None:
        rows.append((T("Энергия"), f"{float(energy):.0f}"))
    fatigue = life.get("fatigue")
    if fatigue is None:
        fatigue = body.get("fatigue")
    if fatigue is not None:
        level = life.get("fatigue_level") or body.get("fatigue_level")
        suffix = f" ({i18n.value_label(level, language)})" if level else ""
        rows.append((T("Усталость"), f"{float(fatigue):.2f}{suffix}"))
    for key, label in (
        ("atp", "АТФ"),
        ("atp_ratio", "АТФ, доля"),
        ("glucose", "Глюкоза"),
        ("mitochondrial_health", "Митохондрии"),
    ):
        value = body.get(key)
        if value is not None:
            rows.append((T(label), f"{float(value):.2f}"))
    needs_rest = life.get("needs_rest")
    if needs_rest is None:
        needs_rest = body.get("needs_rest")
    if needs_rest is True:
        rows.append((T("Нужен отдых"), T("да")))
    return rows


def _hardware_percent(value: Any, language: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return i18n.text("Нет данных", language)
    if not math.isfinite(float(value)):
        return i18n.text("Нет данных", language)
    return f"{float(value) * 100.0:.1f}%"


def _hardware_channel_text(
    channel: Dict[str, Any], language: str, key: str = ""
) -> str:
    status = channel.get("status")
    if status in {"unavailable", "stale"}:
        return i18n.text(
            "недоступно" if status == "unavailable" else "устарело", language
        )
    value = channel.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return i18n.text("Нет данных", language)
    if not math.isfinite(float(value)):
        return i18n.text("Нет данных", language)
    if key == "external_power" and float(value) in {0.0, 1.0}:
        return i18n.text("да" if float(value) == 1.0 else "нет", language)
    unit = channel.get("unit")
    if unit == "percent":
        return f"{float(value):.1f}%"
    if unit == "mb":
        return f"{float(value):.1f} {i18n.text('МБ', language)}"
    if unit == "celsius":
        return f"{float(value):.1f} °C"
    if unit in {"free_ratio", "ratio"}:
        return _hardware_percent(value, language)
    return f"{float(value):.2f}"


def hardware_rows(snapshot: Dict[str, Any], language: str = "ru") -> List[Row]:
    """Отдельная read-only диагностика, не смешанная с ресурсами тела."""
    T = partial(i18n.text, language=language)
    hardware = snapshot.get("hardware") or {}
    if hardware.get("initialized") is not True:
        return [(T("Аппаратное состояние"), T("Нет данных"))]

    rows: List[Row] = [(T("Режим"), T("только наблюдение"))]
    channels = (hardware.get("observation") or {}).get("channels") or {}
    for key, label in (
        ("host_cpu", "CPU среды"),
        ("process_cpu", "CPU процесса"),
        ("host_memory", "Память среды"),
        ("process_rss", "RSS процесса"),
        ("data_storage", "Свободное место data"),
        ("gpu_utilization", "Загрузка GPU"),
        ("gpu_memory", "Память GPU"),
        ("gpu_temperature", "Температура GPU"),
        ("gpu_power", "Мощность GPU"),
        ("cpu_temperature", "Температура CPU"),
        ("external_power", "Внешнее питание"),
        ("battery_charge", "Заряд батареи"),
    ):
        rows.append(
            (
                T(label),
                _hardware_channel_text(channels.get(key) or {}, language, key),
            )
        )

    experience = hardware.get("latest_experience") or {}
    for key, label in (
        ("own_load", "Собственная нагрузка"),
        ("environmental_pressure", "Давление среды"),
        ("memory_pressure", "Давление памяти"),
        ("storage_risk", "Риск хранилища"),
    ):
        item = experience.get(key) or {}
        risk = item.get("risk")
        text = f"{T('риск')} {_hardware_percent(risk, language)}"
        if risk is not None:
            text += f" · {T('переживается')} {_hardware_percent(item.get('experienced'), language)}"
        if (
            item.get("expectedness") == "familiar"
            and isinstance(risk, (int, float))
            and risk >= 0.85
        ):
            text += f" · {T('привычно, но риск сохраняется')}"
        rows.append((T(label), text))

    domains = hardware.get("domain_experience") or {}
    freshness_labels = {
        "fresh": "свежие данные",
        "stale": "устаревшие данные",
        "unavailable": "недоступно",
        "no_observation": "нет наблюдения",
    }
    reason_labels = {
        "observed_physical_channels": "наблюдаемые физические каналы",
        "observed_data_storage": "наблюдаемое хранилище data",
        "channel_unavailable": "канал недоступен",
        "waiting_for_fresh_observation_after_restart": (
            "ожидание свежего наблюдения после перезапуска"
        ),
        "no_observation": "нет наблюдения",
    }
    for key, label in (("physical", "Физический опыт"), ("storage", "Опыт хранилища")):
        domain = domains.get(key) or {}
        latest = domain.get("latest") or {}
        risk = latest.get("risk")
        text = f"{T('риск')} {_hardware_percent(risk, language)}"
        if risk is not None:
            text += f" · {T('переживается')} {_hardware_percent(latest.get('experienced'), language)}"
        if (
            latest.get("expectedness") == "familiar"
            and isinstance(risk, (int, float))
            and risk >= 0.85
        ):
            text += f" · {T('привычно, но риск сохраняется')}"
        rows.append((T(label), text))

        freshness = freshness_labels.get(latest.get("freshness"), "Нет данных")
        reason = latest.get("reason")
        reason_label = reason_labels.get(reason, reason)
        reason_text = (
            T(reason_label)
            if isinstance(reason_label, str) and reason_label
            else T("Нет данных")
        )
        rows.append(
            (
                f"{T('Свежесть')} · {T(label)}",
                f"{T(freshness)} · {reason_text}",
            )
        )

        episode = domain.get("current_episode")
        if isinstance(episode, dict):
            episode_text = (
                f"{T('с цикла')} {episode.get('start_cycle', '—')} · "
                f"{T('свежих циклов')} {episode.get('fresh_observations', 0)} · "
                f"{T('подтверждён')} "
                f"{T('да' if episode.get('strain_cycle') is not None else 'нет')}"
            )
        else:
            episode_text = T("Нет данных")
        rows.append((f"{T('Текущий эпизод')} · {T(label)}", episode_text))

        baseline = domain.get("baseline") or {}
        baseline_value = baseline.get("baseline")
        baseline_text = (
            _hardware_percent(baseline_value, language)
            if baseline.get("sample_count", 0) >= 50
            else T("недостаточно опыта")
        )
        rows.append(
            (
                f"{T('Привыкание')} · {T(label)}",
                f"{float(domain.get('adaptation', 0.0)):.2f} · "
                f"{T('уверенность')} {float(domain.get('confidence', 0.0)):.2f} · "
                f"{T('Личная норма')} {baseline_text}",
            )
        )

    profile = hardware.get("personal_profile") or {}
    baselines = profile.get("baseline") or {}
    has_baseline = any(
        isinstance(item, dict) and item.get("sample_count", 0) >= 50
        for item in baselines.values()
    )
    if not has_baseline:
        rows.append((T("Личная норма"), T("недостаточно опыта")))
    rows.extend(
        [
            (
                T("Привыкание"),
                f"{float(profile.get('adaptation', 0.0)):.2f} · "
                f"{T('уверенность')} {float(profile.get('confidence', 0.0)):.2f}",
            ),
            (
                T("Теневое напряжение"),
                _hardware_percent(hardware.get("shadow_strain"), language),
            ),
            (
                T("Теневое восстановление"),
                _hardware_percent(hardware.get("shadow_recovery"), language),
            ),
            (T("Завершённые эпизоды"), str(profile.get("completed_episode_count", 0))),
            (
                T("Физическое напряжение"),
                _hardware_percent(
                    ((hardware.get("states") or {}).get("physical_strain") or {}).get(
                        "value"
                    ),
                    language,
                ),
            ),
        ]
    )
    recovery = hardware.get("recovery_behavior")
    if "recovery_behavior" not in hardware:
        recovery_mode = T("Shadow · без влияния на выбор")
    elif not isinstance(recovery, dict):
        recovery_mode = T("Нет данных")
    elif recovery.get("mode") == "advisor":
        recovery_mode = T("Advisor · ограниченное влияние на выбор")
    else:
        recovery_mode = T("Shadow · без влияния на выбор")
    rows.append((f"{T('Восстановление')} · {T('Режим')}", recovery_mode))
    if isinstance(recovery, dict):
        rows.extend(
            [
                (
                    f"{T('Восстановление')} · {T('Активность')}",
                    T("да" if recovery.get("active") is True else "нет"),
                ),
                (
                    f"{T('Восстановление')} · {T('Причина')}",
                    str(recovery.get("reason") or T("Нет данных")),
                ),
                (
                    f"{T('Восстановление')} · {T('Серия')}",
                    f"{recovery.get('strain_cycles', 0)} + "
                    f"{recovery.get('recovery_cycles', 0)}",
                ),
            ]
        )
        for entry in (recovery.get("adjustments") or [])[-3:]:
            if not isinstance(entry, dict):
                continue
            rows.append(
                (
                    f"{T('Поправка')} · {entry.get('action') or 'unknown'}",
                    f"{_hormonal_number(entry.get('before_strength'), language)}"
                    f" → {_hormonal_number(entry.get('after_strength'), language)}"
                    f" · ×{_hormonal_number(entry.get('factor'), language)}"
                    f" · {entry.get('source') or 'unknown'}",
                )
            )
    return rows


def _hormonal_number(value: Any, language: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return i18n.text("Нет данных", language)
    if not math.isfinite(float(value)):
        return i18n.text("Нет данных", language)
    return f"{float(value):.2f}"


def hormonal_rows(snapshot: Dict[str, Any], language: str = "ru") -> List[Row]:
    """Уровни, личный профиль и ограниченная runtime-диагностика advisor."""
    T = partial(i18n.text, language=language)
    projection = snapshot.get("hormonal_projection") or {}
    if projection.get("initialized") is not True:
        return [(T("Гормональная проекция"), T("Нет данных"))]

    time_model = projection.get("time_model")
    time_text = (
        T("только тик")
        if time_model == "tick_only"
        else str(time_model)
        if time_model
        else T("Нет данных")
    )
    legacy = projection.get("legacy_mixed_time")
    legacy_text = (
        T("да" if legacy else "нет") if isinstance(legacy, bool) else T("Нет данных")
    )
    # Старые снимки без ключа описывали только shadow-наблюдение. Новый None
    # означает restart до первого тика и не должен выдумывать режим или нули.
    behavior = projection.get("behavior")
    if "behavior" not in projection:
        mode_text = T("Shadow · без влияния на выбор")
    elif not isinstance(behavior, dict):
        mode_text = T("Нет данных")
    elif behavior.get("mode") == "advisor":
        mode_text = T("Advisor · ограниченное влияние на выбор")
    else:
        mode_text = T("Shadow · без влияния на выбор")
    rows: List[Row] = [
        (T("Режим"), mode_text),
        (T("Модель времени"), time_text),
        (T("Прежнее смешанное время"), legacy_text),
    ]
    if isinstance(behavior, dict):
        rows.extend(
            [
                (T("Активность"), T("да" if behavior.get("active") is True else "нет")),
                (T("Причина"), str(behavior.get("reason") or T("Нет данных"))),
            ]
        )
        signals = behavior.get("signals") or {}
        evidence = behavior.get("evidence") or {}
        for name, label in (
            ("dopamine", "Дофамин"),
            ("oxytocin", "Окситоцин"),
            ("cortisol", "Кортизол"),
        ):
            rows.append(
                (
                    f"{T('Сигнал')} · {T(label)}",
                    f"{_hormonal_number(signals.get(name), language)}"
                    f" · {T('Доказательства')} "
                    f"{_hormonal_number(evidence.get(name), language)}",
                )
            )
        for entry in (behavior.get("adjustments") or [])[-3:]:
            if not isinstance(entry, dict):
                continue
            contribution = entry.get("contribution")
            contribution_text = (
                f"{float(contribution) * 100.0:+.1f}%"
                if not isinstance(contribution, bool)
                and isinstance(contribution, (int, float))
                and math.isfinite(float(contribution))
                else T("Нет данных")
            )
            rows.append(
                (
                    f"{T('Поправка')} · {entry.get('action') or 'unknown'}",
                    f"{_hormonal_number(entry.get('before_strength'), language)}"
                    f" → {_hormonal_number(entry.get('after_strength'), language)}"
                    f" · {contribution_text} · {entry.get('source') or 'unknown'}",
                )
            )

    levels = projection.get("levels") or {}
    profile = projection.get("profile") or {}
    has_personal_profile = False
    for name, label in (
        ("dopamine", "Дофамин"),
        ("serotonin", "Серотонин"),
        ("oxytocin", "Окситоцин"),
        ("cortisol", "Кортизол"),
        ("prolactin", "Пролактин"),
    ):
        text = _hormonal_number(levels.get(name), language)
        values = profile.get(name) or {}
        sample_count = values.get("sample_count")
        if (
            not isinstance(sample_count, bool)
            and isinstance(sample_count, int)
            and sample_count > 0
        ):
            has_personal_profile = True
            text += (
                f" · {T('Базовый уровень')} "
                f"{_hormonal_number(values.get('baseline'), language)}"
                f" · {T('Чувствительность')} "
                f"{_hormonal_number(values.get('sensitivity'), language)}"
                f" · {T('Масштаб half-life')} "
                f"{_hormonal_number(values.get('half_life_scale'), language)}"
                f" · {T('уверенность')} "
                f"{_hormonal_number(values.get('confidence'), language)}"
                f" · {T('Подтверждённые эпизоды')} {sample_count}"
            )
        rows.append((T(label), text))
    if not has_personal_profile:
        rows.append((T("Личный профиль"), T("Нет данных")))

    for entry in (projection.get("recent_reasons") or [])[-3:]:
        if not isinstance(entry, dict):
            continue
        reason = " · ".join(
            str(entry[field])
            for field in ("event", "source", "action", "reason", "origin")
            if entry.get(field) is not None
        )
        cycle = entry.get("cycle")
        label = T("Последние причины")
        if cycle is not None:
            label += f" · {T('цикл')} {cycle}"
        rows.append((label, reason or T("Нет данных")))
    return rows


def body_summary(snapshot: Dict[str, Any], language: str = "ru") -> str:
    """Одна строка о теле для подзаголовка: цикл · энергия · усталость."""
    T = partial(i18n.text, language=language)
    life = snapshot.get("life") or {}
    parts: List[str] = []
    if life.get("cycle") is not None:
        parts.append(f"{T('цикл')} {life.get('cycle')}")
    energy = life.get("energy")
    if energy is not None:
        parts.append(f"{T('энергия')} {float(energy):.0f}")
    fatigue = life.get("fatigue")
    if fatigue is not None:
        level = life.get("fatigue_level")
        suffix = f" ({i18n.value_label(level, language)})" if level else ""
        parts.append(f"{T('усталость')} {float(fatigue):.2f}{suffix}")
    if life.get("needs_rest") is True:
        parts.append(T("нужен отдых"))
    return " · ".join(parts) if parts else T("нет данных о теле")


def activity_rows(snapshot: Dict[str, Any], language: str = "ru") -> List[Row]:
    """Строки текущего занятия с реальными деталями игры или черновика."""
    T = partial(i18n.text, language=language)
    activity = (snapshot.get("now") or {}).get("activity")
    if not activity:
        return [(T("Занятие"), T("начатого дела пока нет"))]

    action = str(activity.get("action") or "")
    rows: List[Row] = [
        (T("Действие"), action_phrase(action, activity.get("target"), language))
    ]
    # Для черновика тему покажет сама карточка работы: не дублируем.
    if activity.get("target") and action != "create_draft":
        rows.append((T("Тема"), str(activity["target"])))

    if action == "play":
        game = (snapshot.get("activities") or {}).get("game")
        if isinstance(game, dict):
            rows.append((T("Ходов"), str(game.get("turns", 0))))
            rows.append((T("Партия"), str(game.get("round", 1))))
            result = _GAME_RESULTS.get(game.get("result"), "идёт")
            rows.append((T("Результат"), T(result)))
    elif action == "create_draft":
        drafts = ((snapshot.get("activities") or {}).get("creative") or {}).get(
            "drafts"
        ) or []
        active = [
            d
            for d in drafts
            if isinstance(d, dict) and d.get("status", "active") == "active"
        ]
        if active:
            draft = active[-1]
            rows.append((T("Черновик"), str(draft.get("theme") or "—")))
            rows.append((T("Редакция"), str(draft.get("revision", 1))))

    if activity.get("cycle") is not None:
        rows.append((T("Начато"), f"{T('цикл')} {activity['cycle']}"))
    return rows


def choice_rows(snapshot: Dict[str, Any], language: str = "ru") -> List[Row]:
    """Почему выбрано именно это — из реальных полей, без вымысла."""
    T = partial(i18n.text, language=language)
    activity = (snapshot.get("now") or {}).get("activity")
    if not activity:
        return []

    action = str(activity.get("action") or "")
    rows: List[Row] = [
        (T("Выбрано"), action_phrase(action, activity.get("target"), language)),
        (
            T("Источник"),
            i18n.value_label(activity.get("source") or "—", language),
        ),
    ]
    reason = str(activity.get("reason") or "").strip()
    rows.append((T("Причина"), reason or T("не записана")))

    life = snapshot.get("life") or {}
    energy = life.get("energy")
    fatigue = life.get("fatigue")
    if energy is not None or fatigue is not None:
        parts = []
        if energy is not None:
            parts.append(f"{T('энергия')} {float(energy):.0f}")
        if fatigue is not None:
            parts.append(f"{T('усталость')} {float(fatigue):.2f}")
        rows.append((T("Состояние тела"), ", ".join(parts)))

    pref = (snapshot.get("preferences") or {}).get(action)
    if isinstance(pref, dict):
        rows.append(
            (
                T("Опыт способа"),
                f"{T('попыток')} {pref.get('attempts', 0)}, "
                f"{T('с эффектом')} {pref.get('effects', 0)}, "
                f"{T('сбоев')} {pref.get('failures', 0)}",
            )
        )

    loop = (snapshot.get("now") or {}).get("loop") or {}
    last_action = loop.get("last_action")
    if last_action:
        effect = T("был эффект" if loop.get("last_effect") else "без эффекта")
        rows.append(
            (
                T("Прошлый исход"),
                f"{action_phrase(str(last_action), language=language)}: {effect}",
            )
        )

    return rows


def influence_rows(snapshot: Dict[str, Any], language: str = "ru") -> List[Row]:
    """Что влияет на выбор: потребности, влечения и ожидающие дела."""
    T = partial(i18n.text, language=language)

    def L(value: Any) -> str:
        if i18n.normalize_language(language) == "ru":
            return _MOTIVATION_LABELS.get(str(value), str(value))
        return i18n.value_label(value, language)

    motivation = snapshot.get("motivation") or {}
    rows: List[Row] = []

    most = motivation.get("most_pressing_need")
    if most:
        rows.append((T("Сильнее всего"), L(most)))
    pressing = motivation.get("pressing_needs") or []
    if pressing:
        rows.append(
            (T("Настойчивые потребности"), ", ".join(L(item) for item in pressing))
        )
    drives = motivation.get("active_drives") or []
    if drives:
        rows.append((T("Активные влечения"), ", ".join(L(item) for item in drives)))

    waiting = (snapshot.get("intentions") or {}).get("waiting") or []
    if waiting:
        targets = [str(item.get("target") or "—") for item in waiting[:3]]
        rows.append((T("Ждут условий"), ", ".join(targets)))

    if not rows:
        rows.append((T("Сейчас"), T("ничего заметно не давит")))
    return rows


_ACCESS_LABELS = {
    "network": "Интернет-поиск",
    "delamain": "Планирование задач",
    "effector": "Выполнение действий",
    "presence": "Присутствие",
}


def access_rows(snapshot: Dict[str, Any], language: str = "ru") -> List[Row]:
    """Что реально разрешено. Только существующие переключатели."""
    T = partial(i18n.text, language=language)
    access = snapshot.get("access") or {}
    rows: List[Row] = []
    for key in ("network", "delamain", "effector", "presence"):
        item = access.get(key)
        if isinstance(item, dict):
            label = item.get("label") or _ACCESS_LABELS[key]
            rows.append(
                (T(label), T("включено" if item.get("enabled") else "выключено"))
            )
    workspace = access.get("workspace")
    if isinstance(workspace, dict):
        rows.append(
            (
                T(workspace.get("label") or "Рабочая область"),
                str(workspace.get("path") or "—"),
            )
        )
    return rows


def effector_rows(snapshot: Dict[str, Any], language: str = "ru") -> List[Row]:
    """Счётчики действий. Ожидание и выполнение — разные строки."""
    T = partial(i18n.text, language=language)
    effector = snapshot.get("effector") or {}
    if not effector.get("available"):
        return [(T("Состояние"), T("Исполнитель команд не подключён"))]
    counts = effector.get("counts") or {}
    return [
        (T(label), str(int(counts.get(key, 0) or 0))) for key, label in _EFFECTOR_LABELS
    ]


def pending_effector_note(
    snapshot: Dict[str, Any], language: str = "ru"
) -> Optional[str]:
    """Честная пометка, если есть незавершённые действия."""
    counts = (snapshot.get("effector") or {}).get("counts") or {}
    pending = int(counts.get("queued", 0) or 0) + int(
        counts.get("waiting_approval", 0) or 0
    )
    if pending <= 0:
        return None
    return i18n.text(
        "Не завершено: {count} (в очереди или ждёт подтверждения)", language
    ).format(count=pending)
