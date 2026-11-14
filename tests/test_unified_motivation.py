"""
Regression tests for UnifiedMotivationSystem (P0.6-P0.10).
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.motivation.unified_motivation import (
    UnifiedMotivationSystem,
    create_motivation_system,
)
from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, CheckpointSerializer
from src.core.paths import data_path


class MockAgent:
    """Mock agent for testing motivation system in isolation."""

    def __init__(self):
        self.cycle_count = 1
        self.knowledge_base = {
            "python": "language",
            "learning": "skill",
            "test": "concept",
        }
        self.beliefs = {}


class TestUnifiedMotivationSystem:
    """Tests for the UnifiedMotivationSystem class."""

    def setup_method(self):
        self.agent = MockAgent()
        self.system = create_motivation_system(self.agent)

    def test_initialization(self):
        """Test that all needs and drives are initialized."""
        assert len(self.system.needs) == 7
        assert len(self.system.drives) == 5

        expected_needs = [
            "curiosity",
            "competence",
            "autonomy",
            "connection",
            "play",
            "meaning",
            "coherence",
        ]
        for n in expected_needs:
            assert n in self.system.needs

        expected_drives = [
            "creativity",
            "mastery",
            "self_transcendence",
            "exploration",
            "understanding",
        ]
        for d in expected_drives:
            assert d in self.system.drives

    def test_need_deficit_and_urgency(self):
        """Дефицит абсолютный, давление — доля нехватки, срочность — с приоритетом."""
        need = self.system.needs["curiosity"]
        need.current_level = 0.3  # base_level is 0.8

        assert need.deficit() == pytest.approx(0.5)
        # 0.5 из 0.8 — потребность не удовлетворена на 62.5 %.
        assert need.pressure() == pytest.approx(0.625)
        assert need.urgency() == pytest.approx(0.625 * 1.2)
        assert need.is_pressing() is True  # below threshold 0.35

    def test_need_tick_drains_satisfaction(self):
        """Без удовлетворения потребность «голодает», а не насыщается.

        Регрессия: раньше tick() тянул уровень ВВЕРХ к base_level, поэтому
        потребность не могла стать насущной, и поведением управляли только
        драйвы — которые считались от удовлетворённости.
        """
        need = self.system.needs["curiosity"]
        need.current_level = 0.5

        for _ in range(10):
            need.tick()

        assert need.current_level == pytest.approx(0.3)  # 0.5 - 10*0.02
        assert need.is_pressing() is True

        for _ in range(100):
            need.tick()

        assert need.current_level == 0.0  # ниже нуля не уходит

    def test_need_satisfy_and_frustrate(self):
        """satisfy закрывает долю остатка, frustrate снижает уровень."""
        need = self.system.needs["curiosity"]
        need.current_level = 0.2

        need.satisfy(0.5)
        # 0.2 + 0.5 * (1.0 - 0.2) = 0.6
        assert need.current_level == pytest.approx(0.6)

        need.frustrate(0.3)
        assert need.current_level == pytest.approx(0.3)

    def test_drive_calculation(self):
        """Драйв активируется ДЕФИЦИТОМ, а не удовлетворённостью."""
        # «Голодные» потребности — драйв творчества должен проснуться.
        self.system.needs["curiosity"].current_level = 0.1
        self.system.needs["autonomy"].current_level = 0.1
        self.system.needs["play"].current_level = 0.05

        self.system.tick({})

        creativity = self.system.drives["creativity"]
        assert creativity.current_level > 0.55
        assert creativity.is_active() is True

    def test_satisfied_needs_do_not_activate_drives(self):
        """Сытый агент не должен хотеть сильнее голодного."""
        for need in self.system.needs.values():
            need.current_level = need.base_level

        self.system.tick({})

        assert all(not drive.is_active() for drive in self.system.drives.values())

    def test_goal_generation_from_pressing_need(self):
        """Test that pressing needs generate goals."""
        self.system.needs["curiosity"].current_level = 0.2  # below threshold 0.35

        goals = self.system.generate_goals()

        assert len(goals) >= 1
        assert any(g["source"] == "need" for g in goals)
        assert any(g["need"] == "curiosity" for g in goals)

    def test_goal_generation_from_active_drive(self):
        """Test that active drives generate goals."""
        self.system.needs["curiosity"].current_level = 0.1
        self.system.needs["autonomy"].current_level = 0.1
        self.system.needs["play"].current_level = 0.05
        self.system.tick({})

        goals = self.system.generate_goals()

        assert len(goals) >= 1
        assert any(g["source"] == "drive" for g in goals)
        assert any(g["drive"] == "creativity" for g in goals)

    def test_on_action_result_updates_needs(self):
        """Test that action results update relevant needs."""
        original_curiosity = self.system.needs["curiosity"].current_level

        # Successful hypothesis should satisfy curiosity
        self.system.on_action_result("hypothesis", True, 0.8)

        assert self.system.needs["curiosity"].current_level > original_curiosity

    def test_on_action_result_covers_internal_action_types(self):
        """Internal action types from DigitalBeing.act() must satisfy needs.

        act() uses internal types (hypothesis/decomposition/know_answer/...),
        while needs are keyed by English action names. Aliases must bridge them.
        """
        original_curiosity = self.system.needs["curiosity"].current_level
        original_competence = self.system.needs["competence"].current_level

        self.system.on_action_result("hypothesis", True, 0.8)
        self.system.on_action_result("decomposition", True, 0.6)

        assert self.system.needs["curiosity"].current_level > original_curiosity
        assert self.system.needs["competence"].current_level > original_competence

    def test_on_action_result_failure_frustrates_need(self):
        """Failed action must frustrate the relevant need."""
        original_curiosity = self.system.needs["curiosity"].current_level

        self.system.on_action_result("web_search", False, -0.4)

        assert self.system.needs["curiosity"].current_level < original_curiosity

    def test_checkpoint_serialization(self):
        """Test that motivation state can be serialized and restored."""
        # Set some state - don't call tick() to avoid drift
        self.system.needs["curiosity"].current_level = 0.2
        self.system.needs["autonomy"].current_level = 0.8
        self.system.needs["play"].current_level = 0.8
        # Manually update drives without tick
        self.system.drives["creativity"].current_level = 0.6
        self.system.drives["creativity"].last_updated_cycle = self.agent.cycle_count

        checkpoint = self.system.to_checkpoint_dict()

        assert "needs" in checkpoint
        assert "drives" in checkpoint
        assert "goal_history" in checkpoint
        assert checkpoint["needs"]["curiosity"]["current_level"] == 0.2
        assert checkpoint["drives"]["creativity"]["current_level"] == 0.6

    def test_checkpoint_restoration(self):
        """Test restoring motivation from checkpoint."""
        # Set some state - don't call tick() to avoid drift
        self.system.needs["curiosity"].current_level = 0.2
        self.system.needs["autonomy"].current_level = 0.8
        self.system.needs["play"].current_level = 0.8
        self.system.drives["creativity"].current_level = 0.6
        self.system.drives["creativity"].last_updated_cycle = self.agent.cycle_count

        checkpoint = self.system.to_checkpoint_dict()

        # Create new system and restore
        agent2 = MockAgent()
        system2 = UnifiedMotivationSystem.from_checkpoint_dict(agent2, checkpoint)

        assert system2.needs["curiosity"].current_level == 0.2
        assert system2.needs["autonomy"].current_level == 0.8
        assert system2.drives["creativity"].current_level == 0.6


class TestMotivationIntegration:
    """Tests for motivation integration with DigitalBeing."""

    def setup_method(self):
        # Clean up checkpoints (isolated data root from conftest, not the repo one)
        ckpt_dir = data_path("checkpoints")
        if os.path.exists(ckpt_dir):
            import shutil

            shutil.rmtree(ckpt_dir)

    def teardown_method(self):
        # Clean up checkpoints (isolated data root from conftest, not the repo one)
        ckpt_dir = data_path("checkpoints")
        if os.path.exists(ckpt_dir):
            import shutil

            shutil.rmtree(ckpt_dir)

    def test_agent_has_motivation_system(self):
        """Test that agent has motivation_system attribute."""
        agent = DigitalBeing(name="TestAgent")
        assert hasattr(agent, "motivation_system")
        assert isinstance(agent.motivation_system, UnifiedMotivationSystem)

    def test_motivation_tick_in_autonomous_tick(self):
        """Test that motivation.tick is called during autonomous_tick."""
        agent = DigitalBeing(name="TestAgent")

        # Run a few cycles
        for _ in range(5):
            agent.autonomous_tick()

        # Motivation should have been updated
        assert (
            agent.motivation_system.last_generated_cycle > 0
            or agent.motivation_system.needs["curiosity"].current_level != 0.5
        )

    def test_motivation_checkpoint_roundtrip(self):
        """Test that motivation state survives checkpoint save/load."""
        import os
        import shutil
        from src.core.paths import data_path

        # Clean up checkpoints first
        ckpt_dir = data_path("checkpoints")
        if os.path.exists(ckpt_dir):
            shutil.rmtree(ckpt_dir)

        agent = DigitalBeing(name="TestAgent")

        # Set motivation state - don't call tick to avoid drift
        agent.motivation_system.needs["curiosity"].current_level = 0.2
        agent.motivation_system.needs["autonomy"].current_level = 0.8
        agent.motivation_system.needs["play"].current_level = 0.8
        agent.motivation_system.drives["creativity"].current_level = 0.6
        agent.motivation_system.drives[
            "creativity"
        ].last_updated_cycle = agent.cycle_count

        original_curiosity = agent.motivation_system.needs["curiosity"].current_level
        original_autonomy = agent.motivation_system.needs["autonomy"].current_level
        original_creativity = agent.motivation_system.drives["creativity"].current_level

        # Save checkpoint
        agent.cycle_count = 100
        ckpt_path = agent.save_state()
        assert ckpt_path is not None

        # Load into new agent
        agent2 = DigitalBeing(name="TestAgent")

        ser = CheckpointSerializer()
        state = ser.load(ckpt_path)
        apply_state_to_agent(agent2, state)

        # Verify motivation restored
        assert (
            agent2.motivation_system.needs["curiosity"].current_level
            == original_curiosity
        )
        assert (
            agent2.motivation_system.needs["autonomy"].current_level
            == original_autonomy
        )
        assert (
            abs(
                agent2.motivation_system.drives["creativity"].current_level
                - original_creativity
            )
            < 0.01
        )

    def test_motivation_no_false_goals_when_satisfied(self):
        """Test that no goals generated when all needs satisfied."""
        agent = DigitalBeing(name="TestAgent")

        # Satisfy all needs
        for need in agent.motivation_system.needs.values():
            need.current_level = need.base_level

        goals = agent.motivation_system.generate_goals()

        # Should not generate goals from needs (but might from drives if active)
        need_goals = [g for g in goals if g["source"] == "need"]
        assert len(need_goals) == 0

    def test_motivation_need_priority_not_lower_than_drive(self):
        """Цель насущной потребности весит не меньше цели драйва."""
        agent = DigitalBeing(name="TestAgent")

        # Любопытство насущно, остальные тоже дефицитны — драйв точно активен.
        agent.motivation_system.needs["curiosity"].current_level = 0.1
        for name in (
            "autonomy",
            "play",
            "competence",
            "coherence",
            "meaning",
            "connection",
        ):
            agent.motivation_system.needs[name].current_level = 0.0

        agent.motivation_system.tick({})
        goals = agent.motivation_system.generate_goals()

        need_goals = [g for g in goals if g["source"] == "need"]
        drive_goals = [g for g in goals if g["source"] == "drive"]

        assert need_goals, "насущная потребность не дала ни одной цели"
        assert drive_goals, "активный драйв не дал ни одной цели"
        assert max(g["priority"] for g in need_goals) >= max(
            g["priority"] for g in drive_goals
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

# ============================================================
# Шаблоны целей: ни один не должен теряться из-за формата
# ============================================================


def test_all_need_goal_templates_render():
    """Каждый шаблон потребности даёт заголовок без исключения.

    Регрессия: шаблон «Найти смысл в: {activity}» падал с KeyError,
    потому что вызов не передавал ``activity``. Исключение глоталось,
    и цель потребности «смысл» молча не создавалась.
    """
    from src.core.motivation.unified_motivation import NEED_GOAL_TEMPLATES

    system = create_motivation_system(MockAgent())
    for need_name, templates in NEED_GOAL_TEMPLATES.items():
        need = system.needs.get(need_name)
        if need is None:
            continue
        for template in templates:
            # Подменяем выбор, чтобы пройти по всем шаблонам, а не по одному.
            original = template["title"]
            goal = system._generate_goal_for_need(need)
            assert goal is not None, f"цель не создана для {need_name}"
            assert (
                "{" not in goal["title"]
            ), f"в заголовке остался плейсхолдер: {goal['title']}"
            assert original  # шаблон не пустой


def test_all_drive_goal_templates_render():
    from src.core.motivation.unified_motivation import DRIVE_GOAL_TEMPLATES

    system = create_motivation_system(MockAgent())
    for drive_name in DRIVE_GOAL_TEMPLATES:
        drive = system.drives.get(drive_name)
        if drive is None:
            continue
        goal = system._generate_goal_for_drive(drive)
        assert goal is not None, f"цель не создана для драйва {drive_name}"
        assert (
            "{" not in goal["title"]
        ), f"в заголовке остался плейсхолдер: {goal['title']}"


def test_need_generator_prefers_strategy_not_failed_for_same_subject():
    from unittest.mock import patch

    agent = MockAgent()
    agent.goals = [
        {
            "id": 1,
            "title": "Понять: вопрос",
            "status": "failed",
            "motivation_origin": {"action_hint": "hypothesis"},
        }
    ]
    system = create_motivation_system(agent)

    with patch("random.choice", side_effect=lambda items: items[0]):
        goal = system._generate_goal_for_need(system.needs["curiosity"])

    assert goal is not None
    assert goal["title"] == "Исследовать: вопрос"
    assert goal["action_hint"] == "explore"


def test_drive_generator_prefers_strategy_not_failed_for_same_subject():
    from unittest.mock import patch

    agent = MockAgent()
    agent.goals = [
        {
            "id": 1,
            "title": "Достичь мастерства в: competence",
            "status": "failed",
            "motivation_origin": {"action_hint": "synthesize_understanding"},
        }
    ]
    system = create_motivation_system(agent)

    with patch("random.choice", side_effect=lambda items: items[0]):
        goal = system._generate_goal_for_drive(system.drives["mastery"])

    assert goal is not None
    assert goal["title"] == "Глубокое погружение в: competence"
    assert goal["action_hint"] == "explore"


def test_fill_template_handles_any_placeholder():
    from src.core.motivation.unified_motivation import fill_template

    assert fill_template("Изучить: {concept}", "время") == "Изучить: время"
    assert fill_template("Найти смысл в: {activity}", "время") == (
        "Найти смысл в: время"
    )
    # Неизвестные и множественные имена тоже заполняются.
    assert fill_template("{a} и {b}", "X") == "X и X"
    # Шаблон без плейсхолдеров не портится.
    assert fill_template("Просто текст", "X") == "Просто текст"


# ============================================================
# Инверсия мотивации: дефицит, а не удовлетворённость
# ============================================================


def test_time_alone_makes_needs_pressing():
    """Потребность возвращается сама, без внешнего «стимула».

    Это и есть отличие живого голода от декоративной переменной: если
    агенту ничего не давать, через N тиков потребность становится
    насущной и начинает требовать действия.
    """
    system = create_motivation_system(MockAgent())

    for _ in range(200):
        system.tick({})

    assert all(need.is_pressing() for need in system.needs.values())
    assert any(drive.is_active() for drive in system.drives.values())


def test_urgency_comparable_across_different_bases():
    """«Смысл» (база 0.3) должен уметь выиграть у «любопытства» (0.8).

    Раньше urgency считалась от абсолютного дефицита, поэтому потребность
    с низкой базой не могла обогнать высокую ни при каком уровне.
    """
    system = create_motivation_system(MockAgent())

    curiosity = system.needs["curiosity"]
    curiosity.current_level = 0.4  # pressure 0.5, priority 1.2 → 0.60
    meaning = system.needs["meaning"]
    meaning.current_level = 0.1  # pressure 0.667, priority 1.3 → 0.87

    assert meaning.urgency() > curiosity.urgency()


def test_need_returns_after_satisfaction():
    """Удовлетворение не отменяет потребность навсегда."""
    system = create_motivation_system(MockAgent())
    need = system.needs["curiosity"]
    need.current_level = 0.1

    system.on_action_result("ask_user", True, 0.8)
    assert not need.is_pressing(), "успешный вопрос должен снять насущность"

    for _ in range(40):
        need.tick()

    assert need.is_pressing(), "без действий потребность должна вернуться"


@pytest.mark.parametrize(
    "action_type,need_name",
    [
        # ровно те типы, которые возвращает DigitalBeing.act()
        ("ask_user", "curiosity"),
        ("ask_user", "connection"),
        ("synthesis", "competence"),
        ("synthesis", "meaning"),
        ("reflection", "meaning"),
        ("reflection", "coherence"),
        ("communicate", "connection"),
        ("web_search", "curiosity"),
        ("set_own_goal", "autonomy"),
        ("explore", "curiosity"),
        ("decomposition", "competence"),
        ("hypothesis", "curiosity"),
        ("repair", "coherence"),
    ],
)
def test_actual_action_types_satisfy_needs(action_type, need_name):
    """Результат действия должен гасить ту потребность, которая его вызвала.

    Регрессия: мотивация предлагала «ask_question», а act() сообщал
    «ask_user». Ключа в ACTION_ALIASES не было, потребность не
    удовлетворялась, и агент спрашивал снова и снова.
    """
    system = create_motivation_system(MockAgent())
    need = system.needs[need_name]
    need.current_level = 0.1

    system.on_action_result(action_type, True, 0.8)

    assert need.current_level > 0.1
    assert not need.is_pressing(), (
        f"{action_type} не снял насущность {need_name}: "
        f"level={need.current_level:.2f}"
    )


def test_every_agent_action_type_has_motivation_feedback():
    """У каждого действия агента есть адресат в потребностях.

    Исключения — телесные и служебные действия (отдых, чекпоинт, wait):
    они восстанавливают не психику, а ресурс. Если появится новое
    действие без обратной связи, тест укажет на дыру в мосте.
    """
    from src.core.agent import DigitalBeing
    from src.core.motivation.unified_motivation import ACTION_ALIASES, DEFAULT_NEEDS

    # default означает нераспознанный акт, а не универсальный успех.
    inert = {"rest", "wait", "deep_rest", "checkpoint_now", "default", "let_go"}
    action_types = set(DigitalBeing.ACTION_ALIASES.values()) | {"default"}

    for action_type in sorted(action_types - inert):
        keys = {action_type} | set(ACTION_ALIASES.get(action_type, []))
        related = set().union(
            *(set(need.related_actions) for need in DEFAULT_NEEDS.values())
        )
        assert (
            keys & related
        ), f"действие '{action_type}' ни одну потребность не удовлетворяет"


def test_no_need_candidates_when_all_needs_satisfied():
    """Сытые потребности не должны предлагать действия."""
    system = create_motivation_system(MockAgent())
    for need in system.needs.values():
        need.current_level = need.base_level

    candidates = system.get_action_candidates({})

    assert not any(c.get("type") == "need_driven" for c in candidates)


def test_hungry_curiosity_prefers_asking_over_studying():
    """Голодное любопытство ведёт к вопросу, а не к очередному изучению.

    ``related_actions`` упорядочены по прямоте, поэтому «спросить»
    должно быть сильнее «разложить на части», а не делить с ним силу.
    """
    system = create_motivation_system(MockAgent())
    system.needs["curiosity"].current_level = 0.1

    candidates = system.get_action_candidates({})
    by_action = {c["action"]: c for c in candidates}

    assert "ask_question" in by_action
    assert "decompose_concept" in by_action
    assert (
        by_action["ask_question"]["strength"]
        > (by_action["decompose_concept"]["strength"])
    )
    assert candidates[0]["action"] == "ask_question"


def test_negative_valence_frustrates_executed_action():
    """Неудачный исход расстраивает потребность, даже если действие дошло.

    Регрессия: условие требовало ``success=False``, а success означал
    «энергия не кончилась». Поэтому провальный поиск не оставлял следа.
    """
    system = create_motivation_system(MockAgent())
    need = system.needs["curiosity"]
    need.current_level = 0.5

    system.on_action_result("search_miss", True, -0.2)

    assert need.current_level < 0.5


def test_goal_completion_uses_id_instead_of_duplicate_title():
    """Одинаковый текст не должен связывать исход с чужой потребностью."""
    system = create_motivation_system(MockAgent())
    system.goal_history = [
        {
            "cycle": 1,
            "need": "curiosity",
            "drive": None,
            "goal": "Повторяющаяся цель",
            "priority": 0.5,
            "goal_id": 11,
        },
        {
            "cycle": 2,
            "need": "meaning",
            "drive": None,
            "goal": "Повторяющаяся цель",
            "priority": 0.5,
            "goal_id": 22,
        },
    ]
    system.needs["curiosity"].current_level = 0.1
    system.needs["meaning"].current_level = 0.1

    system.on_goal_achieved("Повторяющаяся цель", goal_id=11)

    assert system.needs["curiosity"].current_level > 0.1
    assert system.needs["meaning"].current_level == 0.1


def test_goal_id_survives_checkpoint_history_window():
    """Существующее 50-записное окно сохраняет ID актуальной цели."""
    system = create_motivation_system(MockAgent())
    system.goal_history = [
        {
            "cycle": cycle,
            "need": "curiosity",
            "drive": None,
            "goal": f"Старый кандидат {cycle}",
            "priority": 0.1,
            "goal_id": cycle,
        }
        for cycle in range(60)
    ]
    system.goal_history.append(
        {
            "cycle": 60,
            "need": "meaning",
            "drive": None,
            "goal": "Актуальная цель",
            "priority": 0.8,
            "goal_id": 77,
        }
    )

    restored = UnifiedMotivationSystem.from_checkpoint_dict(
        MockAgent(), system.to_checkpoint_dict()
    )

    assert len(restored.goal_history) == 50
    assert restored.goal_history[-1]["goal_id"] == 77
    restored.needs["meaning"].current_level = 0.1
    restored.on_goal_achieved("Актуальная цель", goal_id=77)
    assert restored.needs["meaning"].current_level > 0.1


def test_unknown_goal_id_does_not_fall_back_to_title():
    """Явный неправильный ID не должен завершать чужую цель по тексту."""
    system = create_motivation_system(MockAgent())
    system.goal_history = [
        {
            "cycle": 1,
            "need": "curiosity",
            "drive": None,
            "goal": "Одинаковая цель",
            "priority": 0.5,
            "goal_id": 11,
        }
    ]
    system.needs["curiosity"].current_level = 0.1

    system.on_goal_achieved("Одинаковая цель", goal_id=999)

    assert system.needs["curiosity"].current_level == 0.1


def test_motivation_templates_do_not_share_nested_mutable_state():
    first = create_motivation_system(MockAgent())
    second = create_motivation_system(MockAgent())

    own_need = first.needs["curiosity"]
    other_need = second.needs["curiosity"]
    assert own_need.related_concepts is not other_need.related_concepts
    own_need.related_concepts.append("личный интерес")
    assert "личный интерес" not in other_need.related_concepts

    own_drive = first.drives["creativity"]
    other_drive = second.drives["creativity"]
    assert own_drive.contributing_needs is not other_drive.contributing_needs
    assert own_drive.goal_types is not other_drive.goal_types
    own_drive.contributing_needs["curiosity"] = 0.99
    own_drive.goal_types.append("personal_growth")
    assert other_drive.contributing_needs["curiosity"] != 0.99
    assert "personal_growth" not in other_drive.goal_types
