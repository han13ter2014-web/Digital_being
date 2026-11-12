"""Цели без мусора, дела — не только отдых.

В наблюдениях 2026-11-05 среди живых целей всплыли
«Понять: 🙂🙂🙂», «Понять: ты», «Понять: теминг тест» — шум диалога
старых сессий осел в концепциях и выбирался целями исследования.
Теперь выбор цели требует осмысленной темы (≥2 букв, не одни
местоимения), а дедупликация целей идёт по нормализованному тексту.

За 7115 циклов music_works=0, web_browses=0 — гипотеза
наблюдателей: циклы съедал вечный отдых. После фикса
отдыха проверяем симуляцией 200 циклов тишины на живом
``autonomous_tick``: хотя бы одно не-игровое дело (музыка, веб,
синтез, исследование) должно быть выбрано и исполнено.
"""

import random

import pytest

from src.core.agent import DigitalBeing


# ============================================================
# Фильтр осмысленности темы
# ============================================================


@pytest.mark.parametrize(
    "topic,expected",
    [
        # шум наблюдателей
        ("🙂🙂🙂", False),
        ("!!!", False),
        ("ты", False),
        ("я", False),
        ("а", False),
        ("", False),
        ("   ", False),
        (None, False),
        # одни местоимения — не тема
        ("я ты мы", False),
        ("это", False),
        # содержание мира — тема
        ("истина", True),
        ("время", True),
        ("обучение", True),
        ("квантовая запутанность", True),
        # местоимение рядом с содержанием не мешает
        ("моя песня", True),
    ],
)
def test_meaningful_topic_table(topic, expected):
    agent = DigitalBeing(name="NoiseFilterTable")
    assert agent._is_meaningful_topic(topic) is expected


def _fill_concepts(agent, names, *, clear=False):
    # clear=True: свежее существо рождается с врождёнными концепциями
    # («понимать» и др.) — для чистой посылки «в памяти только шум»
    # их убираем.
    if clear:
        agent.mental_models.concepts.clear()
    for name in names:
        agent.mental_models.encounter_concept(name, "контекст", "исход", source="test")


def _empty_pool(monkeypatch):
    """Пустой пул стимулов и без углубления: выбор только из концепций."""
    from config.simulation_config import LR_CONFIG

    monkeypatch.setattr(LR_CONFIG, "STIMULI_POOL", [])
    monkeypatch.setattr(LR_CONFIG, "EXPLORATION_DEPTH_RATIO", 0.0)


def test_picker_never_returns_noise_concepts(monkeypatch):
    """Мусор в концепциях не становится целью исследования."""
    _empty_pool(monkeypatch)
    agent = DigitalBeing(name="NoisePicker")
    _fill_concepts(agent, ["🙂🙂🙂", "ты", "это", "истина"], clear=True)

    for _ in range(20):
        target = agent._pick_exploration_target()
        assert target not in {"🙂🙂🙂", "ты", "это"}
        if target is None:
            break
        assert target == "истина"


def test_picker_with_only_noise_returns_none(monkeypatch):
    _empty_pool(monkeypatch)
    agent = DigitalBeing(name="NoiseOnly")
    _fill_concepts(agent, ["🙂🙂🙂", "ты"], clear=True)

    assert agent._pick_exploration_target() is None


def test_own_goal_refuses_noise_target(monkeypatch):
    """Цель «Понять: 🙂🙂🙂» не создаётся, даже если в памяти только шум."""
    _empty_pool(monkeypatch)
    agent = DigitalBeing(name="NoiseGoal")
    _fill_concepts(agent, ["🙂🙂🙂", "ты"], clear=True)

    result = agent._act_set_own_goal()

    assert "не из чего" in result["text"]
    titles = [str(g.get("title", "")) for g in agent.goals]
    assert not any("🙂" in t for t in titles)


def test_own_goal_dedup_normalizes_whitespace():
    """«Понять:  истина» и «Понять: истина» — одна цель после нормализации."""
    agent = DigitalBeing(name="DedupGoal")
    agent.set_goal("Понять:  истина", difficulty=1)

    agent._pick_exploration_target = lambda: "истина"
    result = agent._act_set_own_goal()

    assert "уже есть" in result["text"]
    titles = [str(g.get("title", "")) for g in agent.goals]
    assert len([t for t in titles if "истина" in t]) == 1


# ============================================================
# Работа после отдыха и чистота целей: 200 циклов тишины на живом цикле
# ============================================================

# Не-игровые дела из критерия приёмки: музыка, веб, синтез — плюс
# исследовательская работа (explore/synthesis/hypothesis/decomposition).
_NON_GAME_ACTIONS = {
    "compose_music",
    "browse_web",
    "web_search",
    "read_news",
    "synthesis",
    "hypothesis",
    "explore",
    "decomposition",
}


def test_silence_200_cycles_work_happens_and_goals_stay_clean():
    """После фикса отдыха циклы не съедаются сном целиком —
    за 200 циклов тишины хотя бы одно не-игровое дело исполнено.
    Проверка фильтра: ни одной цели с эмодзи/одиночными символами."""
    random.seed(20261105)
    agent = DigitalBeing(name="SilenceSim")
    # Материал для любопытства: немного неуверенных тем, включая мусор
    # из старых сессий — он не должен всплыть целями.
    _fill_concepts(agent, ["истина", "время", "музыка", "🙂🙂🙂", "ты"])

    performed = []
    original_act = agent.act

    def recording_act(decision, *, intention=None):
        performed.append(agent._normalize_action(decision))
        return original_act(decision, intention=intention)

    agent.act = recording_act

    for _ in range(200):
        agent.cycle_count += 1
        agent.autonomous_tick()

    # Хотя бы одно не-игровое дело за 200 циклов тишины.
    non_game = [a for a in performed if a in _NON_GAME_ACTIONS]
    assert non_game, (
        "за 200 циклов тишины ни одного не-игрового дела — "
        "гипотеза «циклы съедает отдых» не подтвердилась, "
        "нужно смотреть механику выбора"
    )

    # Ноль целей с эмодзи/одиночными символами.
    titles = [str(g.get("title", "")) for g in agent.goals]
    for title in titles:
        assert "🙂" not in title
        assert "Понять: ты" not in title
