"""«Окно-1» (k16-07): окно кандидатов, фильтр валидных хендлеров, мост teaching.

Гипотезы k16-05, подтверждённые ревизией k16-09: окно [:4] даёт арбитру
имена, которые контур исполнения не ловит (legacy/helping_others);
виновник — канонизация окна, а не сироты сами по себе. Фильтр living в
motivation не изымает желание (goal_types и генерация целей untouched) —
арбитр лишь не получает пустышку.
"""
from src.core.agent import DigitalBeing
from src.core.agent_act import executable_action
from src.core.motivation.unified_motivation import ACTION_ALIASES as MOTIVATION_ALIASES


def _agent_with_drive(drive_name: str):
    agent = DigitalBeing(name=f"Window_{drive_name}")
    for need in agent.motivation_system.needs.values():
        need.current_level = need.base_level
    for drive in agent.motivation_system.drives.values():
        drive.current_level = 0
    agent.motivation_system.drives[drive_name].current_level = 0.8
    return agent


# === 1. Фильтр арбитра ===

def test_unexecutable_names_never_reach_arbitrator():
    """legacy/helping_others не проходят в кандидаты как исполняемые."""
    agent = _agent_with_drive("self_transcendence")
    candidates = agent.motivation_system.get_action_candidates({})
    offered = {c["action"] for c in candidates if c.get("drive") == "self_transcendence"}
    assert "legacy" not in offered
    assert "helping_others" not in offered


def test_executable_names_still_reach_arbitrator():
    """Валидные имена окна не потеряны фильтром."""
    agent = _agent_with_drive("self_transcendence")
    candidates = agent.motivation_system.get_action_candidates({})
    offered = {c["action"] for c in candidates if c.get("drive") == "self_transcendence"}
    assert "teaching" in offered
    assert "contribution" in offered


def test_desire_is_not_removed_from_goal_types():
    """Фильтр не изымает желание: goal_types и генерация целей живут."""
    agent = _agent_with_drive("self_transcendence")
    system = agent.motivation_system
    assert system.drives["self_transcendence"].goal_types == [
        "teaching", "contribution", "legacy", "helping_others"
    ]
    goals_hints: list[str] = []
    for _ in range(40):
        for g in system.generate_goals([], [system.drives["self_transcendence"]]):
            goals_hints.append(g["action_hint"])
    # Генерация целей читает шаблоны, не оффер-окно: contribute-цель жива.
    assert "synthesize" in goals_hints
    assert "teach_other" in goals_hints


def test_executable_action_mirrors_parser_table():
    """executable_action читает ту же таблицу, что парсер act()."""
    assert executable_action("communicate")
    assert executable_action("teaching")
    assert executable_action("social_interaction")
    assert executable_action("explore")
    assert executable_action("wait")  # честный исход, не пустышка
    assert executable_action("default")  # тоже честный тип
    assert not executable_action("legacy")
    assert not executable_action("helping_others")
    assert not executable_action("что-то неведомое")
    assert not executable_action("")
    assert not executable_action(None)


# === 2. Мост teaching ===

def test_teaching_bridge_added():
    """Фоллоу-ап k16-10: мост communicate знает имя teaching. ОЖИДАЕТ ПОДТВЕРЖДЕНИЯ РЕВИЗИИ."""
    assert "teaching" in MOTIVATION_ALIASES["communicate"]
    assert "teach_other" in MOTIVATION_ALIASES["communicate"]


# === 3. Окно канонизировано в одном месте ===

def test_window_is_single_canonical_slice():
    """У драйвов одно окно ([:4]); слот-перестановка creativity не применялась."""
    import inspect

    from src.core.motivation import unified_motivation as um

    src = inspect.getsource(um.UnifiedMotivationSystem.get_action_candidates)
    # Канонизация: единственный срез окна в цикле драйвов.
    assert src.count("action_hints[:4]") == 1
    # Оставшийся [:2] — окно НУЖД (related_actions), не драйвов: у нужды
    # curiosity 8 действий, расширение её окна захламит кандидаты.
    assert src.count("[:2]") == 1
    assert "related_actions[:2]" in src
    # creativity сохраняет порядок прямоты (первые два — прежние прямые).
    from src.core.motivation.unified_motivation import DEFAULT_DRIVES

    assert DEFAULT_DRIVES["creativity"].goal_types[:2] == ["creative_act", "play"]


def test_creativity_window_still_offers_all_organs():
    """Правка окна не сломала проводку органов k16-04."""
    agent = _agent_with_drive("creativity")
    candidates = agent.motivation_system.get_action_candidates({})
    offered = {
        agent._normalize_action(c["action"])
        for c in candidates if c.get("drive") == "creativity"
    }
    assert offered == {"play", "create_draft", "draw", "compose_music"}
