"""
Интеграционные тесты Digital Being (Phase 6).

Запускать через:
    pytest tests/
    или
    pytest tests/test_integration.py -v

Покрывает:
- инициализацию всех подсистем DigitalBeing
- NamingDialogue (фазы, таймаут, fallback)
- конфигурируемые правила прогресса целей
- кэширование src/* индекса
- поведение энергии (property ↔ energy_subsystem)
"""
import os
import sys
import io

import pytest

# Делаем корень проекта доступным для импортов
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Фикс кодировки для Windows-консоли
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


# =====================================================================
# 1. Инициализация подсистем
# =====================================================================
SUBSYSTEMS = [
    "goal_subsystem", "motivation", "energy_subsystem",
    "knowledge_subsystem", "reflection_pipeline", "checkpoint_subsystem",
    "long_term_memory", "soul", "decision_arbitrator", "attachment",
    "sleep_cycle", "embodiment", "mortality",
    "will_registry", "right_to_refuse", "intentional_forgetting",
    "value_evolution", "spontaneous_generator", "will_to_risk",
    "right_to_fail", "mind_dream", "architecture_proposal",
    "self_termination", "proactive_communication", "naming_dialogue",
]


def test_all_subsystems_initialized():
    """Все 24 подсистемы должны быть проинициализированы."""
    from src.core.agent import DigitalBeing
    agent = DigitalBeing("TestSubject")
    missing = [name for name in SUBSYSTEMS if not hasattr(agent, name)]
    assert not missing, f"Отсутствуют подсистемы: {missing}"


def test_energy_starts_positive():
    """Энергия должна быть положительной после инициализации."""
    from src.core.agent import DigitalBeing
    agent = DigitalBeing("TestSubject")
    assert agent.energy > 0
    assert agent.energy_subsystem.energy == agent.energy


def test_energy_property_sync():
    """self.energy и energy_subsystem.energy должны быть синхронизированы."""
    from src.core.agent import DigitalBeing
    agent = DigitalBeing("TestSubject")
    agent.energy = 42
    assert agent.energy == 42
    assert agent.energy_subsystem.energy == 42


def test_typing_imports_work():
    """Проверяем, что Optional/Dict/List импортированы (был баг)."""
    from src.core.agent import DigitalBeing
    agent = DigitalBeing("TestSubject")
    # Optional используется в type hints
    assert agent.parent_seed is None
    assert agent.parent_name is None
    assert agent.parent_dream_time is None


# =====================================================================
# 2. NamingDialogue
# =====================================================================
class _StubUserInteraction:
    """Заглушка user_interaction для теста, чтобы initiate_naming_dialogue отработал."""

    def __init__(self):
        self.sent = []

    def send_message(self, content, msg_type, tone, urgency, context, cycle):
        self.sent.append({
            "content": content, "msg_type": msg_type,
            "tone": tone, "urgency": urgency,
            "context": context, "cycle": cycle,
        })
        return f"msg_{len(self.sent)}"


def test_naming_dialogue_timeout():
    """Через NAME_TIMEOUT_CYCLES должен сработать fallback."""
    from src.core.subsystems.naming_dialogue import NamingDialogue

    stub = _StubUserInteraction()
    nd = NamingDialogue(agent_name="TestBot", user_interaction=stub)

    # До инициации — фаза NONE
    assert nd.check_timeout(0) == "ok"

    # Инициируем диалог с cycle=10 (не 0, иначе check_timeout вернёт "ok"
    # из-за защиты _initiated_at_cycle <= 0).
    nd.initiate_naming_dialogue(agent=None, cycle=10)
    assert nd.phase == NamingDialogue.PHASE_AWAITING_NAME
    assert nd._initiated_at_cycle == 10

    base = 10
    timeout = NamingDialogue.NAME_TIMEOUT_CYCLES

    # До 80% таймаута — ok
    assert nd.check_timeout(base + int(timeout * 0.5)) == "ok"
    # На 80% — warning (elapsed = 0.85 * timeout = 170, >= 160)
    assert nd.check_timeout(base + int(timeout * 0.85)) == "warning"
    # После полного таймаута — timeout
    assert nd.check_timeout(base + timeout + 1) == "timeout"

    # Обработка таймаута
    result = nd.handle_timeout(current_cycle=base + timeout + 1)
    assert result["handled"] is True
    assert nd.phase == NamingDialogue.PHASE_COMPLETED


def test_naming_dialogue_no_timeout_when_completed():
    """После завершения диалога таймаут не должен срабатывать."""
    from src.core.subsystems.naming_dialogue import NamingDialogue
    nd = NamingDialogue(agent_name="TestBot")
    nd.phase = NamingDialogue.PHASE_COMPLETED
    assert nd.check_timeout(999999) == "ok"


# =====================================================================
# 3. Конфигурируемые правила прогресса целей
# =====================================================================
def test_goal_progress_rules_present():
    """LR_CONFIG должен содержать GOAL_PROGRESS_RULES с правилами."""
    from config.simulation_config import LR_CONFIG
    assert hasattr(LR_CONFIG, "GOAL_PROGRESS_RULES")
    assert len(LR_CONFIG.GOAL_PROGRESS_RULES) >= 1

    # Проверяем, что есть правило для Python
    names = [r["name"] for r in LR_CONFIG.GOAL_PROGRESS_RULES]
    assert "python_learning" in names


def test_match_rule_to_goal():
    """Правило должно матчиться по title."""
    from src.core.agent import DigitalBeing

    rule = {
        "name": "test",
        "match_title": ["python", "питон"],
        "match_topic_keywords": ["функция", "класс"],
        "matches_needed": 3,
    }
    assert DigitalBeing._match_rule_to_goal("Выучить основы Python", rule) is True
    assert DigitalBeing._match_rule_to_goal("Изучить питон", rule) is True
    assert DigitalBeing._match_rule_to_goal("Собрать 10 фактов", rule) is False


def test_topic_matches_rule():
    """Topic должен матчиться хотя бы по одному ключевому слову."""
    from src.core.agent import DigitalBeing

    rule = {
        "match_topic_keywords": ["python", "функция", "класс"],
    }
    assert DigitalBeing._topic_matches_rule("что такое функция в python", rule) is True
    assert DigitalBeing._topic_matches_rule("что такое любовь", rule) is False
    assert DigitalBeing._topic_matches_rule("класс object", rule) is True


def test_check_goal_progress_uses_rules():
    """_check_goal_progress должен применять конфигурируемые правила."""
    from src.core.agent import DigitalBeing
    agent = DigitalBeing("TestSubject")
    # Установим активную цель «Выучить основы Python»
    for g in agent.goals:
        if "Python" in g["title"]:
            agent.active_goal = g
            break

    # Симулируем найденный ответ по теме, подходящей под правило python_learning.
    # Встреча без ответа не должна засчитываться (requires_answer=True).
    agent._check_goal_progress("что такое функция в python")
    goal_id = agent.active_goal["id"]
    assert agent._goal_progress[goal_id]["percentage"] == 0

    agent._check_goal_progress("что такое функция в python", answered=True)
    progress = agent._goal_progress[goal_id]
    assert progress["percentage"] > 0
    assert progress.get("rule_name") == "python_learning"


# =====================================================================
# 4. Кэширование src/* индекса
# =====================================================================
def test_src_file_index_cached():
    """После первого вызова _get_src_file_index кэш должен быть заполнен."""
    from src.core.agent import DigitalBeing
    # Сбрасываем кэш, чтобы тест был детерминированным
    DigitalBeing._SRC_FILE_INDEX = None

    idx1 = DigitalBeing._get_src_file_index()
    idx2 = DigitalBeing._get_src_file_index()

    # Возвращают один и тот же объект (set)
    assert idx1 is idx2
    assert len(idx1) > 0
    # Все элементы — относительные пути
    for rel_path in list(idx1)[:5]:
        assert not rel_path.startswith("src/")
        assert rel_path.endswith(".py")


def test_invalidate_src_file_index():
    """_invalidate_src_file_index сбрасывает кэш."""
    from src.core.agent import DigitalBeing
    DigitalBeing._get_src_file_index()  # наполнить кэш
    assert DigitalBeing._SRC_FILE_INDEX is not None

    DigitalBeing._invalidate_src_file_index()
    assert DigitalBeing._SRC_FILE_INDEX is None


# =====================================================================
# 5. Симуляция цикла: perceive → think → act → evolve
# =====================================================================
def test_basic_cycle():
    """Базовый цикл жизни агента не должен падать."""
    from src.core.agent import DigitalBeing
    agent = DigitalBeing("TestSubject")

    stimulus = "вопрос: что такое тест"
    perceived = agent.perceive(stimulus)
    assert perceived == stimulus

    thought = agent.think(perceived)
    assert thought  # непустая строка

    action = agent.act(thought)
    assert "Ответ" in action or action

    agent.evolve()
    # После evolve цикл может слегка увеличить intelligence
    assert agent.cycle_count >= 0


def test_is_alive_initially():
    """Свежесозданный агент должен быть жив."""
    from src.core.agent import DigitalBeing
    agent = DigitalBeing("TestSubject")
    assert agent.is_alive() is True


# =====================================================================
# 6. NamingDialogue через agent (tick_communication)
# =====================================================================
def test_tick_communication_naming_timeout():
    """tick_communication должен реагировать на таймаут NamingDialogue."""
    from src.core.agent import DigitalBeing
    from src.core.subsystems.naming_dialogue import NamingDialogue

    agent = DigitalBeing("TestSubject")
    # Имитируем что диалог идёт уже давно — ставим фазу и время старта
    # отличным от 0, иначе защита _initiated_at_cycle <= 0 сработает.
    agent.naming_dialogue.phase = NamingDialogue.PHASE_AWAITING_NAME
    agent.naming_dialogue._initiated_at_cycle = 1

    # cycle должен быть больше _initiated_at_cycle + NAME_TIMEOUT_CYCLES
    timeout_cycles = 1 + NamingDialogue.NAME_TIMEOUT_CYCLES + 5
    result = agent.tick_communication(cycle_count=timeout_cycles)

    assert result.get("naming_timeout") is not None, (
        f"Ожидался naming_timeout, got: {result}"
    )
    assert result["naming_timeout"]["handled"] is True


# =====================================================================
# 7. NamingDialogue автоматический старт при первом запуске
# =====================================================================
def test_naming_dialogue_initiated_in_main_flow():
    """При первом запуске агент должен сам начать диалог об имени.

    Это регрессионный тест на баг: пользователь запускал main.py / main_tray.py,
    агент молчал и не здоровался. Ожидается, что agent.start_naming_dialogue()
    переводит NamingDialogue в PHASE_AWAITING_NAME и публикует сообщение naming.
    """
    from src.core.agent import DigitalBeing
    from src.core.subsystems.naming_dialogue import NamingDialogue

    agent = DigitalBeing("TestSubject")
    # === Предусловие: диалог ещё не начинался (PHASE_NONE) ===
    # Пересоздаём dialogue на свежую, чтобы не зависеть от порядка тестов.
    agent.naming_dialogue = NamingDialogue(
        agent_name="TestSubject",
        user_interaction=agent.user_interaction,
    )
    assert agent.naming_dialogue.phase == NamingDialogue.PHASE_NONE

    # === Действие: имитируем вызов main.py / main_tray.py ===
    result = agent.start_naming_dialogue(cycle=0)

    # === Пост-условия ===
    assert result.get("status") == "initiated", f"Ожидался initiated, got: {result}"
    assert agent.naming_dialogue.phase == NamingDialogue.PHASE_AWAITING_NAME
    # Должно быть опубликовано хотя бы одно сообщение типа "naming"
    pending = agent.user_interaction.get_pending_messages(
        include_acknowledged=False
    )
    naming_msgs = [m for m in pending if m.get("msg_type") == "naming"]
    assert len(naming_msgs) >= 1, (
        f"Должно быть хотя бы одно naming-сообщение, got: {pending}"
    )


def test_naming_dialogue_phase_persisted_in_checkpoint():
    """Фаза диалога должна сохраняться в чекпоинт, чтобы не повторять приветствие.

    Регрессионный тест: после рестарта агент должен помнить, что NamingDialogue
    уже завершён (или в фазе AWAITING_NAME), а не начинать заново.
    """
    import json
    import os
    import tempfile

    from src.core.agent import DigitalBeing
    from src.core.subsystems.naming_dialogue import NamingDialogue

    with tempfile.TemporaryDirectory() as tmpdir:
        ckpt_dir = os.path.join(tmpdir, "checkpoints")
        os.makedirs(ckpt_dir, exist_ok=True)

        # 1. Создаём агента и завершаем NamingDialogue
        agent = DigitalBeing("TestSubject")
        agent.naming_dialogue.phase = NamingDialogue.PHASE_COMPLETED
        agent.naming_dialogue._name_history.append({
            "old_name": "TestSubject",
            "new_name": "Luna",
            "reason": "user_proposed",
        })

        # 2. Сохраняем state вручную с нашим путём
        from src.core.checkpoint_migrations import SCHEMA_VERSION
        state = {
            "schema_version": SCHEMA_VERSION,
            "name": agent.name,
            "energy": agent.energy,
            "cycle_count": agent.cycle_count,
            "knowledge_base": dict(agent.knowledge_base),
            "intelligence": agent.intelligence,
            "completed_goals": agent.completed_goals,
            "goals": list(agent.goals),
            "active_goal": (
                agent.active_goal["title"] if agent.active_goal else None
            ),
            "success_streak": agent.success_streak,
            "saved_at": "now",
            "_goal_progress": {
                k: list(v.get("matched_concepts", []))
                for k, v in agent._goal_progress.items()
            },
            "_learned_facts": list(agent._learned_facts),
            "_known_definitions": dict(agent._known_definitions),
            "naming_dialogue_phase": agent.naming_dialogue.phase,
            "naming_dialogue_history": list(agent.naming_dialogue._name_history),
        }
        ckpt_path = os.path.join(ckpt_dir, "test_ckpt.json")
        with open(ckpt_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)

        # 3. Создаём нового агента и загружаем checkpoint
        new_agent = DigitalBeing("TestSubject")
        # Сбросим naming_dialogue, чтобы убедиться, что load_state восстанавливает
        new_agent.naming_dialogue.phase = NamingDialogue.PHASE_NONE
        new_agent.naming_dialogue._name_history = []
        new_agent.load_state(ckpt_path)

        # 4. Проверяем, что фаза восстановлена
        assert new_agent.naming_dialogue.phase == NamingDialogue.PHASE_COMPLETED, (
            f"Phase не восстановлен: {new_agent.naming_dialogue.phase}"
        )
        # История имён должна содержать Luna
        names = [h.get("new_name") for h in new_agent.naming_dialogue._name_history]
        assert "Luna" in names, f"История имён не восстановлена: {names}"


def test_naming_dialogue_not_reinitiated_after_checkpoint():
    """После восстановления из чекпоинта приветствие НЕ должно повторяться.

    Воспроизводит реальный сценарий из main_tray.py:
    1. Создать агента, инициировать naming, сохранить.
    2. Восстановить — повторный start_naming_dialogue должен вернуть
       status='no_op' (или просто оставить фазу COMPLETED), а не "initiated".

    Защита от повторного вызова реализована в NamingDialogue.initiate_naming_dialogue():
    если phase != NONE — возвращается {"status": "no_op", ...} и сообщение
    НЕ публикуется.
    """
    from src.core.agent import DigitalBeing
    from src.core.subsystems.naming_dialogue import NamingDialogue

    agent = DigitalBeing("TestSubject")
    # 1. Инициируем диалог в первый раз
    init_result = agent.start_naming_dialogue(cycle=0)
    assert init_result.get("status") == "initiated"
    assert agent.naming_dialogue.phase == NamingDialogue.PHASE_AWAITING_NAME

    # 2. Принудительно завершаем диалог (минуем случайность propose_name,
    #    который в 30% предлагает альтернативу и фаза остаётся CONSIDERING).
    agent.naming_dialogue.phase = NamingDialogue.PHASE_COMPLETED
    agent.naming_dialogue._name_history.append({
        "old_name": "TestSubject",
        "new_name": "Luna",
        "cycle": 0,
        "source": "test",
    })

    # 3. Считаем сообщения ДО повторного вызова
    initial_msgs = agent.user_interaction.get_pending_messages(include_acknowledged=True)
    initial_naming_msgs = [m for m in initial_msgs if m.get("msg_type") == "naming"]

    # 4. Повторный вызов — должен вернуть no_op и НЕ создавать новое сообщение
    repeat_result = agent.start_naming_dialogue(cycle=1)
    assert repeat_result.get("status") == "no_op", (
        f"Ожидался no_op, got: {repeat_result}"
    )
    assert repeat_result.get("phase") == NamingDialogue.PHASE_COMPLETED

    # 5. Количество naming-сообщений НЕ должно измениться
    after_msgs = agent.user_interaction.get_pending_messages(include_acknowledged=True)
    after_naming_msgs = [m for m in after_msgs if m.get("msg_type") == "naming"]
    assert len(after_naming_msgs) == len(initial_naming_msgs), (
        f"После повторного вызова не должно быть новых naming-сообщений. "
        f"before={len(initial_naming_msgs)}, after={len(after_naming_msgs)}"
    )


# =====================================================================
# 8. СВОБОДА ВОЛИ: открытые вопросы (vs «туннельный» режим стимулов)
# =====================================================================
def test_open_questions_basic_queue():
    """agent.ask_user() должен добавлять вопрос в очередь."""
    from src.core.agent import DigitalBeing
    agent = DigitalBeing("TestSubject")
    assert agent.has_open_questions() is False

    result = agent.ask_user("что такое любовь?")
    assert result["status"] == "queued"
    assert agent.has_open_questions() is True

    queue = agent.get_open_questions()
    assert len(queue) == 1
    assert queue[0]["text"] == "что такое любовь?"
    assert queue[0]["answered"] is False


def test_open_question_takes_priority_over_stimuli():
    """_consume_open_question должен возвращать стимул-исследование для открытого вопроса.

    Регрессионный тест на философский баг: пользователь спрашивает "что такое
    любовь?", но агент гонит его через рандомные стимулы про Python/import/def,
    потому что у него активна цель "Выучить основы Python". Теперь агент САМ
    решает думать над открытым вопросом.
    """
    from src.core.agent import DigitalBeing
    agent = DigitalBeing("TestSubject")
    # Активная цель по умолчанию — "Выучить основы Python".
    # Пользователь задаёт открытый вопрос НЕ про Python.
    agent.ask_user("что такое любовь?")

    # В течение следующих 5 циклов агент должен думать о любви,
    # а не о Python.
    explored_stimuli = []
    for _ in range(5):
        stimulus = agent._consume_open_question()
        if stimulus:
            explored_stimuli.append(stimulus)

    # Хотя бы один стимул должен содержать слово "люб"
    assert any("люб" in s.lower() for s in explored_stimuli), (
        f"Открытый вопрос не использовался как приоритет. "
        f"Полученные стимулы: {explored_stimuli}"
    )
    # Не должно быть стимулов "import" / "def" / "object" — это Python-темы
    assert not any(
        "import" in s.lower() or " def " in s.lower() or "object" in s.lower()
        for s in explored_stimuli
    ), (
        f"Агент продолжил туннель Python. Стимулы: {explored_stimuli}"
    )


def test_open_question_duplicate_not_added():
    """Дубликат открытого вопроса НЕ должен добавляться дважды."""
    from src.core.agent import DigitalBeing
    agent = DigitalBeing("TestSubject")
    r1 = agent.ask_user("что такое любовь?")
    r2 = agent.ask_user("Что такое любовь?")  # разный регистр
    r3 = agent.ask_user("  что такое любовь?  ")  # пробелы

    assert r1["status"] == "queued"
    assert r2["status"] == "duplicate"
    assert r3["status"] == "duplicate"
    assert len(agent._open_questions) == 1


def test_open_question_hint_and_drop():
    """hint_to_open_question и drop_open_question работают."""
    from src.core.agent import DigitalBeing
    agent = DigitalBeing("TestSubject")
    agent.ask_user("что такое сознание?")

    # Добавить подсказку
    r = agent.hint_to_open_question("что такое сознание?", "это связано с нейронами")
    assert r["status"] == "hint_added"
    assert any(
        q.get("hint") == "это связано с нейронами"
        for q in agent._open_questions
    )

    # Удалить вопрос
    r = agent.drop_open_question("что такое сознание?")
    assert r["status"] == "dropped"
    assert agent.has_open_questions() is False


def test_open_questions_persisted_in_checkpoint():
    """Открытые вопросы должны сохраняться и восстанавливаться через чекпоинт."""
    import json
    import os
    import tempfile

    from src.core.agent import DigitalBeing
    from src.core.checkpoint_migrations import SCHEMA_VERSION

    with tempfile.TemporaryDirectory() as tmpdir:
        ckpt_dir = os.path.join(tmpdir, "checkpoints")
        os.makedirs(ckpt_dir, exist_ok=True)

        # 1. Создаём агента с открытым вопросом
        agent = DigitalBeing("TestSubject")
        agent.ask_user("что такое время?")
        assert agent.has_open_questions() is True

        # 2. Сохраняем state вручную
        state = {
            "schema_version": SCHEMA_VERSION,
            "name": agent.name,
            "energy": agent.energy,
            "cycle_count": agent.cycle_count,
            "knowledge_base": dict(agent.knowledge_base),
            "intelligence": agent.intelligence,
            "completed_goals": agent.completed_goals,
            "goals": list(agent.goals),
            "active_goal": (
                agent.active_goal["title"] if agent.active_goal else None
            ),
            "success_streak": agent.success_streak,
            "saved_at": "now",
            "_goal_progress": {},
            "_learned_facts": list(agent._learned_facts),
            "_known_definitions": dict(agent._known_definitions),
            "naming_dialogue_phase": "completed",
            "naming_dialogue_history": [],
            "open_questions": [
                {
                    "text": q["text"],
                    "source": q["source"],
                    "started_at": q["started_at"],
                    "last_explored_at": q["last_explored_at"],
                    "explorations_count": len(q["explorations"]),
                    "max_explorations": q["max_explorations"],
                    "hint": q.get("hint"),
                    "answered": q["answered"],
                    "answer": q["answer"],
                }
                for q in agent._open_questions
            ],
        }
        ckpt_path = os.path.join(ckpt_dir, "openq_ckpt.json")
        with open(ckpt_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)

        # 3. Загружаем в нового агента
        new_agent = DigitalBeing("TestSubject")
        new_agent.load_state(ckpt_path)

        # 4. Проверяем, что открытый вопрос восстановлен
        assert new_agent.has_open_questions() is True
        queue = new_agent.get_open_questions()
        assert any(q["text"] == "что такое время?" for q in queue)


if __name__ == "__main__":
    # Можно запустить напрямую: python tests/test_integration.py
    pytest.main([__file__, "-v"])
