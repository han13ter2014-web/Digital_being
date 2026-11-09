"""«Сироты-1» (k16-10): маппинги, коллизия парсера, наблюдаемость памяти.

Три дыры из ревизии k16-09: (1) имена действий мотивации
(social_interaction, teaching, contribution) не ловились парсером и
ACTION_ALIASES — исполнение вхолостую; (2) «не нашёл ответ» матчился
подстрокой «нашёл» как know_answer — промах классифицировался как
успех; (3) потеря эпизода при memory is None была невидима, а мостовой
тест с Mock-памятью маскировал путь записи.
"""
from types import SimpleNamespace

from src.core.agent import DigitalBeing
from src.core.agent_act import classify_decision
from src.core.agent_effector import _record_core_life_episode_impl
from src.delamain.memory import MemoryStore

# === 1. Маппинги сирот ===

def test_orphan_action_names_normalize():
    agent = DigitalBeing(name="OrphanRoutes")
    assert agent._normalize_action("social_interaction") == "communicate"
    assert agent._normalize_action("teaching") == "communicate"
    assert agent._normalize_action("contribution") == "synthesis"


def test_orphan_mappings_have_no_collisions():
    """Новые ключи не затирали существующие маппинги."""
    aliases = DigitalBeing.ACTION_ALIASES
    assert aliases["communicate"] == "communicate"
    assert aliases["teach_other"] == "communicate"
    assert aliases["synthesize"] == "synthesis"
    assert aliases["philosophy"] == "synthesis"


def test_orphan_satisfaction_bridge_matches():
    """Исполнение по новым маппингам гасит соответствующие потребности."""
    agent = DigitalBeing(name="OrphanSatisfaction")
    system = agent.motivation_system
    for need in system.needs.values():
        need.current_level = need.base_level
    system.needs["connection"].current_level = 0.0

    # social_interaction → communicate → need connection.
    before = system.needs["connection"].current_level
    agent.act("social_interaction")
    assert system.needs["connection"].current_level > before


def test_legacy_and_helping_others_stay_honest_default():
    """Неотмапленные сироты дают честный default: исполнено впустую → sadness."""
    agent = DigitalBeing(name="LegacyHonest")
    for need in agent.motivation_system.needs.values():
        need.current_level = need.base_level
    assert agent._normalize_action("legacy") == "legacy"
    assert agent._normalize_action("helping_others") == "helping_others"

    sadness_before = agent.emotional_state.levels["sadness"]
    agent.act("legacy")
    # default ничего не делает в мире: k16-03 красит это как промах.
    assert agent.emotional_state.levels["sadness"] > sadness_before


# === 2. Коллизия парсера ===
# «Единство-1» (k16-14): зеркала больше нет — тест импортирует тот же
# classify_decision, которым пользуется парсер act() и фильтр кандидатов
# (импорт — в шапке файла).


def test_negative_found_is_miss_not_know_answer():
    assert classify_decision("Ответ: не нашёл ответ про 'энтелехия'") == "search_miss"
    assert classify_decision("не нашел ничего") == "search_miss"
    assert classify_decision("в сети ничего не найдено") == "search_miss"


def test_positive_found_is_know_answer():
    assert classify_decision("нашёл ответ в своих записях") == "know_answer"
    assert classify_decision("знаю ответ заранее") == "know_answer"


# === 3. Наблюдаемость и запись эпизодов ===

def test_life_episode_written_with_real_memory(tmp_path):
    """Мост с живым MemoryStore пишет эпизод — Mock больше не единственное покрытие."""
    store = MemoryStore(tmp_path / "memory.db")
    agent = SimpleNamespace(
        delamain=SimpleNamespace(
            runtime=SimpleNamespace(memory=store),
        ),
        life_id="life-k16-10",
    )
    entry = {
        "id": "intention-42",
        "action": "web_search",
        "target": "энтелехия",
        "status": "performed",
        "outcome": {"action": "web_search", "had_effect": True},
    }
    result = _record_core_life_episode_impl(agent, entry)
    assert result is not None

    episodes = store.recent_life_episodes(life_id="life-k16-10", limit=10)
    assert len(episodes) == 1
    assert episodes[0]["task_id"] == "intention-42"
    assert episodes[0]["action"] == "web_search"
    assert episodes[0]["metadata"]["status"] == "performed"
    store.close()


def _read_log(tmp_path) -> str:
    """Буферизированный логгер пишет в файл: перехват через caplog не виден."""
    from src.core.buffered_logger import get_logger

    get_logger().flush()
    return (tmp_path / "logs" / "agent_log.txt").read_text(encoding="utf-8")


def test_missing_memory_is_logged_not_silent(tmp_path, monkeypatch):
    """memory is None: одна строка лога, исключение не пробрасывается."""
    from src.core import buffered_logger as bl
    from src.core.buffered_logger import BufferedLogger

    logger = BufferedLogger(
        log_file=str(tmp_path / "logs" / "agent_log.txt"), buffer_size=1
    )
    monkeypatch.setattr(bl, "_logger", logger)

    agent = SimpleNamespace(delamain=None, life_id="life-x")
    entry = {"id": "i-1", "action": "explore", "target": "т", "status": "performed"}

    result = _record_core_life_episode_impl(agent, entry)

    assert result is None  # живой цикл не роняется
    assert "не записан" in _read_log(tmp_path)


def test_broken_memory_is_logged_not_silent(tmp_path, monkeypatch):
    """Падение записи тоже видно в логе (прежняя ветка, теперь проверена)."""
    from src.core import buffered_logger as bl
    from src.core.buffered_logger import BufferedLogger

    logger = BufferedLogger(
        log_file=str(tmp_path / "logs" / "agent_log.txt"), buffer_size=1
    )
    monkeypatch.setattr(bl, "_logger", logger)

    class _Boom:
        def record_life_episode(self, **kwargs):
            raise RuntimeError("sqlite locked")

    agent = SimpleNamespace(
        delamain=SimpleNamespace(runtime=SimpleNamespace(memory=_Boom())),
        life_id="life-y",
    )
    result = _record_core_life_episode_impl(
        agent, {"id": "i-2", "action": "rest", "target": "", "status": "performed"}
    )
    assert result is None
    assert "не записан" in _read_log(tmp_path)
