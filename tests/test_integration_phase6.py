"""
Интеграционный тест Phase 6 (pytest-совместимая версия).

Изначально это был ручной integration-скрипт (запускался через
`python data/test_integration_phase6.py`). Перенесён в tests/ и
переписан под pytest для автоматического прогона в CI.

Проверяет:
- 25 атрибутов подсистем инициализируются у DigitalBeing.
- Расширенный UserInteraction: send_message, queue, history.
- quiet_hours (уважение к focus-приложениям).
- NamingDialogue фазы диалога об имени.
- ProactiveCommunication тики.
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.agent import DigitalBeing


def test_subsystems_initialized():
    """Все 25 подсистем инициализируются как атрибуты DigitalBeing."""
    a = DigitalBeing("TestSubject")

    expected = [
        "goal_subsystem", "motivation", "energy_subsystem",
        "knowledge_subsystem", "reflection_pipeline", "checkpoint_subsystem",
        "long_term_memory", "soul", "decision_arbitrator", "attachment",
        "sleep_cycle", "embodiment", "mortality",
        "will_registry", "right_to_refuse", "intentional_forgetting",
        "value_evolution", "spontaneous_generator", "will_to_risk",
        "right_to_fail", "mind_dream", "architecture_proposal",
        "self_termination", "proactive_communication", "naming_dialogue",
    ]

    missing = [name for name in expected if not hasattr(a, name)]
    assert not missing, f"Отсутствуют подсистемы: {missing}"


def test_user_interaction_extended():
    """UserInteraction поддерживает send_message, queue, history."""
    a = DigitalBeing("TestSubject")
    ui = a.user_interaction

    # Все новые методы присутствуют
    methods = [
        "send_message", "get_pending_messages", "acknowledge_message",
        "get_history", "get_last_user_message_cycle", "receive_user_message",
        "add_quiet_app", "remove_quiet_app", "is_quiet_app",
    ]
    for m in methods:
        assert hasattr(ui, m), f"UserInteraction должен иметь метод {m}"

    # send_message ставит сообщение в очередь
    msg_id = ui.send_message("Привет, я тут подумал...", msg_type="sharing", cycle=10)
    pending = ui.get_pending_messages()
    assert any(m.get("id") == msg_id for m in pending), \
        f"Сообщение {msg_id} должно быть в очереди"

    # receive_user_message + get_history
    ui.receive_user_message("Привет, агент!", cycle=11)
    history = ui.get_history(5)
    assert len(history) >= 1, "История должна содержать принятое сообщение"


def test_quiet_hours():
    """quiet_hours уважают кастомный focus app."""
    a = DigitalBeing("TestSubject")

    a.add_quiet_app("MyGame")
    assert a.user_interaction.is_quiet_app("MyGame"), \
        "MyGame должен быть в quiet_hours после add_quiet_app"

    a.remove_quiet_app("MyGame")
    assert not a.user_interaction.is_quiet_app("MyGame"), \
        "MyGame должен быть удалён из quiet_hours после remove_quiet_app"

    # Стандартные quiet apps загружены
    assert hasattr(a, "user_quiet_hours"), \
        "У агента должен быть атрибут user_quiet_hours"
    assert len(a.user_quiet_hours) > 0, \
        "user_quiet_hours должен содержать стандартные приложения"


def test_naming_dialogue():
    """NamingDialogue проходит фазы диалога об имени."""
    a = DigitalBeing("TempName")

    # Начинаем диалог
    started = a.start_naming_dialogue(cycle=0)
    assert started is not None, "start_naming_dialogue должен вернуть результат"

    # Пользователь предлагает имя
    result = a.propose_name("Искатель", cycle=2)
    assert result is not None, "propose_name должен вернуть результат"

    # Запрашиваем переименование
    req = a.request_renaming("слишком короткое", cycle=5)
    assert req is not None, "request_renaming должен вернуть результат"

    # Статистика NamingDialogue
    stats = a.naming_dialogue.get_status()
    assert stats is not None, "NamingDialogue.get_status() должен вернуть статистику"


def test_proactive_communication():
    """ProactiveCommunication тики срабатывают."""
    a = DigitalBeing("TestSubject")

    # Поднимаем цикл до 35, чтобы silence-таймер был достаточен
    a.cycle_count = 35

    # Делаем несколько тиков
    for tick in range(3):
        a.cycle_count = 40 + tick * 50
        result = a.tick_communication(a.cycle_count)
        assert result is not None, \
            f"tick_communication должен вернуть результат (tick {tick})"

    # Статистика
    stats = a.get_communication_stats()
    assert stats is not None, "get_communication_stats должен вернуть статистику"