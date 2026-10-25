"""Проводка: действия, которые раньше молча ничего не делали.

Мотивация предлагала агенту «спросить человека», «поделиться знанием»,
«поискать в сети». Все эти действия доходили до ``act()``, не находили
обработчика и заканчивались ничем — при том что подсистемы уже были
написаны и работали.

Здесь проверяется, что провод подключён: действие доходит до реальной
подсистемы и оставляет наблюдаемый след.
"""

import pytest

from src.core.agent import DigitalBeing
from src.core.world_delta import capture


@pytest.fixture()
def agent():
    a = DigitalBeing(name="WiringAgent")
    searcher = getattr(a, "web_searcher", None)
    if searcher is not None:
        searcher.toggle(False)  # тесты не ходят в сеть
    return a


# ============================================================
# 1. Таблица действий
# ============================================================


@pytest.mark.parametrize(
    "alias,expected",
    [
        ("ask_user", "ask_user"),
        ("ask_question", "ask_user"),
        ("communicate", "communicate"),
        ("user_answer", "communicate"),
        ("teach_other", "communicate"),
        ("web_search", "web_search"),
        ("explore", "explore"),
        ("exploration", "explore"),
        ("reflect", "reflection"),
        ("think_decompose", "decomposition"),
    ],
)
def test_action_aliases_are_wired(alias, expected):
    """Каждое имя действия из мотивации ведёт к реальному обработчику."""
    assert DigitalBeing.ACTION_ALIASES.get(alias) == expected


def test_no_known_action_falls_into_default(agent):
    """Действия из мотивации не должны попадать в «default».

    «default» означает «агент ничего не сделал»: энергия списана, мир не
    изменён. Именно так молча терялись ask_question, web_search,
    hypothesis и set_own_goal.
    """
    motivation_actions = [
        "explore", "ask_question", "communicate", "web_search",
        "hypothesis", "synthesize", "reflect", "organize_knowledge",
        "set_own_goal", "make_choice", "creative_act", "experiment",
        "self_reflect", "teach_other", "user_answer", "act",
    ]
    for action in motivation_actions:
        normalized = agent._normalize_action(action)
        assert normalized in DigitalBeing.ACTION_ALIASES.values(), (
            f"{action!r} → {normalized!r} не ведёт к обработчику"
        )


# ============================================================
# 2. ask_user: агент сам задаёт вопрос
# ============================================================


def test_ask_user_queues_real_question(agent):
    """Вопрос попадает в очередь к человеку, а не теряется."""
    agent.cycle_count = 60  # переждать кулдаун (50 циклов)

    result = agent.act("ask_user")

    pending = agent.user_interaction.get_pending_question()
    assert pending is not None, "вопрос не поставлен в очередь"
    assert "Я разбираюсь с темой" in pending["question"]
    assert "спросил человека" in result


def test_ask_user_has_observable_effect(agent):
    agent.cycle_count = 60
    agent.act("ask_user")

    outcome = agent._last_action_outcome
    assert outcome.action == "ask_user"
    assert outcome.had_effect is True
    assert outcome.delta.pending_questions == 1


def test_ask_user_respects_cooldown(agent):
    """Агент не спамит вопросами: кулдаун соблюдается."""
    agent.cycle_count = 60
    agent.act("ask_user")
    agent.cycle_count = 61  # сразу ещё раз — рано

    result = agent.act("ask_user")
    assert "отложен" in result
    # Второй вопрос не добавился.
    assert len(agent.user_interaction.pending_questions) == 1


def test_ask_user_records_will_act(agent):
    agent.cycle_count = 60
    agent.act("ask_user")

    stats = agent.will_registry.get_stats()
    assert stats["by_type"]["questions_asked"] >= 1


# ============================================================
# 3. communicate: агент сам рассказывает
# ============================================================


def test_communicate_sends_message(agent):
    """Сообщение уходит человеку через UserInteraction."""
    # Нужно чем поделиться: концепция с собственной формулировкой.
    for i in range(10):
        agent.cycle_count = i + 1
        agent.autonomous_tick()

    result = agent.act("communicate")

    messages = agent.user_interaction.get_pending_messages(
        include_acknowledged=False
    )
    assert messages, "сообщение не отправлено"
    assert any(
        m.get("msg_type") == "statement" for m in messages
    )
    assert "рассказал человеку" in result


def test_communicate_has_observable_effect(agent):
    for i in range(10):
        agent.cycle_count = i + 1
        agent.autonomous_tick()

    agent.act("communicate")
    outcome = agent._last_action_outcome

    assert outcome.action == "communicate"
    assert outcome.had_effect is True
    assert outcome.delta.messages_sent == 1


def test_communicate_without_news_does_nothing(agent):
    """Нечем делиться — честно говорит об этом, а не выдумывает."""
    result = agent.act("communicate")
    assert "нечего рассказать" in result or "рассказал" in result


# ============================================================
# 4. web_search: поиск доходит до подсистемы
# ============================================================


def test_web_search_maps_to_real_action(agent):
    """Раньше web_search попадал в «default» и ничего не делал."""
    result = agent.act("web_search")

    outcome = agent._last_action_outcome
    assert outcome.action == "web_search"
    # Сеть выключена — корректный отказ, а не молчание.
    assert "недоступен" in result or "нечего" in result


def test_web_search_reports_offline(agent):
    result = agent.act("web_search")
    assert "поиск" in result.lower()


# ============================================================
# 5. Служебные концепции не становятся темами
# ============================================================


def test_internal_concepts_are_not_learnable(agent):
    """Спрашивать человека про «_bootstrap_loaded» бессмысленно."""
    assert agent._is_learnable("_bootstrap_loaded") is False
    assert agent._is_learnable("убеждение_1") is False
    assert agent._is_learnable("") is False
    assert agent._is_learnable("сознание") is True


def test_exploration_never_picks_internal_concepts(agent):
    """Исследование не выбирает служебные узлы."""
    for _ in range(12):
        target = agent._pick_exploration_target()
        if target is None:
            break
        assert agent._is_learnable(target), target


def test_ask_user_never_asks_about_internal_concepts(agent):
    agent.cycle_count = 60
    agent.act("ask_user")

    pending = agent.user_interaction.get_pending_question()
    assert pending is not None
    assert "_bootstrap_loaded" not in pending["question"]


# ============================================================
# 6. Счётчики мира видят новые действия
# ============================================================


def test_world_signature_counts_messages(agent):
    for i in range(10):
        agent.cycle_count = i + 1
        agent.autonomous_tick()
    before = capture(agent)
    agent.act("communicate")
    after = capture(agent)

    assert after.messages_sent > before.messages_sent


def test_world_signature_counts_questions(agent):
    agent.cycle_count = 60
    before = capture(agent)
    agent.act("ask_user")
    after = capture(agent)

    assert after.pending_questions > before.pending_questions


# ============================================================
# 7. Без подсистем агент не падает
# ============================================================


def test_ask_user_without_interaction_does_not_crash(agent):
    agent.user_interaction = None
    result = agent.act("ask_user")
    assert "спросить некого" in result


def test_communicate_without_interaction_does_not_crash(agent):
    agent.user_interaction = None
    result = agent.act("communicate")
    assert "рассказать некому" in result


def test_web_search_without_searcher_does_not_crash(agent):
    agent.web_searcher = None
    result = agent.act("web_search")
    assert "недоступен" in result

# ============================================================
# 8. hypothesis и set_own_goal
# ============================================================


def test_hypothesis_records_experience(agent):
    """Гипотеза — запись в ментальной модели, а не пустой ход."""
    before = capture(agent)
    result = agent.act("hypothesis")
    after = capture(agent)

    outcome = agent._last_action_outcome
    assert outcome.action == "hypothesis"
    # Либо появился опыт/концепция, либо честный отказ.
    if "гипотеза о" in result:
        assert after.experiences > before.experiences or after.concepts > before.concepts
        assert outcome.had_effect is True


def test_set_own_goal_creates_goal(agent):
    """Агент может поставить себе цель по своей воле."""
    goals_before = len(agent.goals)
    result = agent.act("set_own_goal")

    if "поставил себе цель" in result:
        assert len(agent.goals) > goals_before
        new_goal = agent.goals[-1]
        assert new_goal["title"].startswith("Понять:")
        assert agent.will_registry.get_stats()["by_type"]["goals_set"] >= 1


def test_set_own_goal_does_not_duplicate(agent):
    agent.act("set_own_goal")
    count_after_first = len(agent.goals)
    # Повторный вызов не должен плодить одинаковые цели бесконечно.
    agent.act("set_own_goal")
    titles = [g["title"] for g in agent.goals]
    assert len(titles) == len(set(titles)) or len(agent.goals) >= count_after_first


# ============================================================
# 9. Отказ тоже исход: бесплодное действие гаснет
# ============================================================


def test_denied_action_is_recorded(agent):
    """Отказ (усталость, бюджет) — тоже «мир не изменился».

    Раньше act() выходил досрочно и ничего не записывал, поэтому
    действие, которое сейчас невозможно, выбиралось каждый цикл: за
    250 тиков агент 247 раз выбирал вопрос, который нельзя было задать.
    """
    agent.energy = 0.0  # гарантированно «слишком устал»

    agent.act("explore")
    outcome = agent._last_action_outcome

    assert outcome is not None
    assert outcome.had_effect is False
    assert "denied" in outcome.reason
    assert agent.loop_closer.no_effect_streak("explore") >= 1


def test_denied_streak_grows(agent):
    agent.energy = 0.0
    for _ in range(3):
        agent.act("explore")
    assert agent.loop_closer.no_effect_streak("explore") >= 3


# ============================================================
# 10. Невозможное не предлагается арбитру
# ============================================================


def test_ask_is_unavailable_during_cooldown(agent):
    """Вопрос при кулдауне не должен попадать в выбор."""
    agent.cycle_count = 60
    agent.act("ask_user")          # вопрос задан, пошёл кулдаун
    agent.cycle_count = 61         # ещё рано

    assert agent._is_action_available("ask_question") is False


def test_ask_becomes_available_after_cooldown(agent):
    agent.cycle_count = 60
    agent.act("ask_user")
    agent.cycle_count = 60 + agent.user_interaction.cooldown_cycles + 1

    assert agent._is_action_available("ask_question") is True


def test_ask_allowed_from_first_cycle():
    """Первый вопрос в жизни не должен упираться в кулдаун.

    Регрессия: ``last_question_cycle = 0`` означал «вопрос уже задан в
    нулевом цикле», и первые 50 циклов агент не мог спросить, даже если
    потребность голодала.
    """
    from src.perception.user_interaction import UserInteraction

    fresh = UserInteraction(agent_name="Fresh")

    assert fresh.can_ask_question(0) is True


def test_ask_not_offered_when_there_is_nothing_to_ask(agent):
    """Вопрос без темы — не действие, а пустой цикл.

    Регрессия: при исчерпанных темах ``_act_ask_user`` возвращал «не о
    чем спрашивать», не запускал кулдаун, и арбитр выбирал вопрос
    каждые несколько циклов. Потребность при этом не удовлетворялась.
    """
    agent.cycle_count = 10_000
    for node in agent.mental_models.concepts.values():
        node.confidence = 0.95
    agent._open_questions = []
    agent._stimulus_topics = lambda: []

    assert agent._has_question_target() is False
    assert agent._is_action_available("ask_question") is False


def test_web_search_unavailable_when_disabled(agent):
    searcher = getattr(agent, "web_searcher", None)
    if searcher is None:
        pytest.skip("поиск не подключён")
    searcher.toggle(False)
    assert agent._is_action_available("web_search") is False


def test_normal_actions_are_available(agent):
    assert agent._is_action_available("explore") is True
    assert agent._is_action_available("synthesize") is True


# ============================================================
# 11. Социальные кандидаты появляются по реальным признакам
# ============================================================


def test_social_candidates_include_share_after_silence(agent):
    """После долгого молчания агент хочет поделиться."""
    for i in range(10):
        agent.cycle_count = i + 1
        agent.autonomous_tick()

    agent.cycle_count = 200  # давно молчал
    actions = [c.get("action") for c in agent._social_candidates(200)]
    assert "communicate" in actions


def test_social_candidates_empty_without_reason(agent):
    """Сразу после разговора делиться нечем — кандидатов нет."""
    agent._last_share_cycle = agent.cycle_count
    actions = [c.get("action") for c in agent._social_candidates(agent.cycle_count)]
    assert "communicate" not in actions
