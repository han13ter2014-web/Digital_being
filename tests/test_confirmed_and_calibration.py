"""«Подтверждение-1» и «Калибровка-1» (k16-14).

Слепое пятно k16-12 (вариант C): флаг confirmed_result ставили только
deep_rest и play — rest, let_go, create_draft, set_own_goal, repair,
checkpoint_now давали успех без флага, и фон качнулся в sadness-за-успех.
Флаг живёт в ветке обработчика, где знание семантики и место; условие —
проверяемый факт свершившегося результата, не факт вызова.

Калибровка: intention_completed/failed получают кулдаун 300 (механизм
COOLED_EVENTS) — иначе при частых семьях joy насыщается до хронической
единицы (расчёт: L_eq = I/период/0.002 >= 1.0 при периоде < 200).
"""
from src.core.agent import DigitalBeing
from src.core.emotional_state import EmotionalState

# === 1. Флаги confirmed_result ===

def test_rest_recovery_confirms():
    agent = DigitalBeing(name="ConfirmRest")
    closer = agent.loop_closer
    before_energy = float(agent.energy)
    agent.act("rest")
    outcome = closer.last_outcome
    assert outcome.confirmed_result
    assert "восстановлена" in outcome.result_description
    assert float(agent.energy) > before_energy


def test_let_go_forgotten_confirms_but_not_found_does_not():
    from src.cognition.intention_history import begin_intention
    from src.cognition.intention_waiting import remember_wait

    agent = DigitalBeing(name="ConfirmLetGo")
    closer = agent.loop_closer

    # not_found: нечего отпускать — честный промах, флага нет.
    agent.act("let_go", intention={"params": {
        "action": "explore", "topic": "несуществующая тема",
        "reason": "проверка промаха",
    }})
    assert not closer.last_outcome.confirmed_result

    # forgotten: намерение существовало и реально помечено — флаг есть.
    entry = begin_intention(agent, {"action": "explore", "source": "new_interest",
                                    "params": {"topic": "реальная тема", "reason": "интерес"}})
    entry["continuation_of"] = "x"
    entry["status"] = "unobserved"
    remember_wait(agent, entry)
    agent.act("let_go", intention={"params": {
        "action": "explore", "topic": "реальная тема",
        "reason": "остыла",
    }})
    assert closer.last_outcome.confirmed_result
    assert "помечено forgotten" in closer.last_outcome.result_description


def test_create_draft_confirms_written_revision():
    agent = DigitalBeing(name="ConfirmDraft")
    closer = agent.loop_closer
    agent.act("create_draft")
    outcome = closer.last_outcome
    assert outcome.confirmed_result
    assert "редакция" in outcome.result_description


def test_leaving_draft_is_not_effectual_success():
    """mode='leave' — сознательное оставление работы: не достижение.

    Флага confirmed_result нет (k16-02: валентность для leave — ноль),
    в описании результата нет «редакции» — описание результата
    зарезервировано за подтверждённым фактом записанной ревизии.
    """
    agent = DigitalBeing(name="ConfirmDraftLeave")
    closer = agent.loop_closer

    # Контраст: само создание черновика флаг получает.
    agent.act("create_draft")
    assert closer.last_outcome.confirmed_result

    agent.act("create_draft", intention={"params": {
        "draft_mode": "leave", "reason": "остыла",
    }})
    outcome = closer.last_outcome
    assert not outcome.confirmed_result
    assert "редакция" not in outcome.result_description


def test_set_own_goal_confirms_created_id():
    agent = DigitalBeing(name="ConfirmGoal")
    closer = agent.loop_closer
    # set_own_goal создаёт дело из нажатой play-нужды или цель «Понять: X».
    for need in agent.motivation_system.needs.values():
        need.current_level = need.base_level
    agent.motivation_system.needs["play"].current_level = 0.0
    agent._pick_exploration_target = lambda: "энтелехия"
    agent.act("set_own_goal")
    outcome = closer.last_outcome
    assert outcome.confirmed_result
    assert "цель #" in outcome.result_description


def test_repair_confirms_only_real_changes():
    agent = DigitalBeing(name="ConfirmRepair")
    closer = agent.loop_closer
    integrity = agent.death_risk.integrity
    # Уже целостная структура: только коррупция-аккумулятор даёт пустой
    # вклад (0.0) — чинить нечего, флага нет.
    integrity.manual_repair(intensity=0.0)
    # Фактически прогоняем act() с «чистым» состоянием: все компоненты по 1.0.
    integrity.cognitive_coherence = 1.0
    integrity.memory_consistency = 1.0
    integrity.value_stability = 1.0
    integrity.metabolic_viability = 1.0
    integrity.social_coherence = 1.0
    integrity.corruption_accumulator = 0.0
    agent.act("repair")
    assert not closer.last_outcome.confirmed_result

    # Повреждение есть: ремонт поднимает — флаг есть.
    integrity.cognitive_coherence = 0.5
    agent.act("repair")
    assert closer.last_outcome.confirmed_result
    assert "целостность восстановлена" in closer.last_outcome.result_description
    # И описание несёт положительную дельту, а не ноль.
    assert "+0." in closer.last_outcome.result_description


def test_checkpoint_confirms_created_checkpoint():
    agent = DigitalBeing(name="ConfirmCheckpoint")
    closer = agent.loop_closer
    before = len(agent.death_risk.integrity.checkpoints)
    agent.act("checkpoint_now")
    outcome = closer.last_outcome
    assert outcome.confirmed_result
    assert "чекпоинт создан" in outcome.result_description
    assert len(agent.death_risk.integrity.checkpoints) > before


# === 2. Калибровка: кулдаун на частые события ===

def test_intention_completed_does_not_accumulate_into_chronic_joy():
    """События каждые 2 цикла: радость не накапливается выше одного пика."""
    state = EmotionalState()
    for cycle in range(1, 1201):
        state.tick(cycle)
        state.handle_event("intention_completed", cycle=cycle, cause="rest")
    # Один пик 0.40, между всплесками — полное затухание. Хронического
    # накопления нет: уровень никогда не поднимается выше одной интенсивности.
    assert state.levels["joy"] <= 0.40


def test_intention_failed_does_not_accumulate_into_chronic_sadness():
    state = EmotionalState()
    for cycle in range(1, 1201):
        state.tick(cycle)
        state.handle_event("intention_failed", cycle=cycle, cause="search_miss")
    assert state.levels["sadness"] <= 0.25


def test_cooldown_allows_new_peak_after_fade():
    """Кулдаун — не вечная глухота: новый пик после затухания переживается."""
    state = EmotionalState()
    state.handle_event("intention_completed", cycle=10)
    assert state.levels["joy"] == 0.40
    # В окне кулдауна — тишина.
    assert state.handle_event("intention_completed", cycle=100) is None
    # Между пиками — жизнь идёт: радость затухает полностью
    # (0.40 / 0.002 = 200 циклов, здесь тиков больше).
    for cycle in range(11, 400):
        state.tick(cycle)
    assert state.levels["joy"] == 0.0
    # После кулдауна — новый честный всплеск на одну интенсивность,
    # а не накопление поверх незатухшего остатка (k16-29).
    episode = state.handle_event("intention_completed", cycle=400)
    assert episode is not None
    assert state.levels["joy"] == 0.40


def test_rare_events_still_fire_every_time():
    """Кулдаун не глушит редкие события: каждый контакт с человеком виден."""
    state = EmotionalState()
    first = state.handle_event("user_contact", cycle=10)
    second = state.handle_event("user_contact", cycle=20)
    assert first is not None and second is not None
    assert state.levels["joy"] == 0.50


# === 3. Классификатор: слышимая поломка регистрации ===

def test_unregistered_table_is_loud_not_silent(tmp_path, monkeypatch):
    from src.core import buffered_logger as bl
    from src.core.agent_act import classify_decision
    from src.core.buffered_logger import BufferedLogger

    logger = BufferedLogger(
        log_file=str(tmp_path / "logs" / "agent_log.txt"), buffer_size=1
    )
    monkeypatch.setattr(bl, "_logger", logger)
    monkeypatch.setattr("src.core.agent_act.ACTION_ALIASES_TABLE", None)
    monkeypatch.setattr("src.core.agent_act._TABLE_WARNED", False)

    # Подстрочные правила работают и без таблицы, и поломка слышна в логе
    # (одно предупреждение на период отсутствия таблицы — не спам).
    assert classify_decision("не нашел ничего") == "search_miss"
    assert classify_decision("не нашла") == "default"  # подстроки не знает
    log_text = (tmp_path / "logs" / "agent_log.txt").read_text(encoding="utf-8")
    assert "не зарегистрирована" in log_text
    assert log_text.count("не зарегистрирована") == 1
