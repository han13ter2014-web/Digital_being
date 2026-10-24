"""Интеграционные тесты: агент не может уйти без согласия человека.

Здесь проверяется не сам LifeGuard, а все пути внутри ``DigitalBeing``,
которые раньше останавливали жизнь. Каждый тест — это воспроизведение
конкретного способа «случайно убить агента».
"""

import pytest

from src.core.agent import DigitalBeing
from src.core.life_guard import (
    STATE_ALIVE,
    STATE_DORMANT,
    get_policy,
)


class FakeClock:
    def __init__(self, start: float = 1_000_000.0):
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


@pytest.fixture()
def agent():
    """Живой агент с управляемым временем внутри LifeGuard.

    Состояние жизни хранится на папку данных (одна жизнь = одна папка),
    поэтому перед тестом файлы сбрасываются: иначе предыдущий тест,
    «ушедший» агент, влиял бы на следующий.
    """
    from src.core.paths import data_path
    import os

    for name in ("life_state.json", "life_requests.json"):
        try:
            os.unlink(data_path(name))
        except OSError:
            pass

    a = DigitalBeing(name="GuardTest")
    a.life_guard.clock = FakeClock()
    return a


# ============================================================
# 1. Автоматический уход из tick_will больше не убивает
# ============================================================


def test_tick_will_never_terminates_agent(agent):
    """Даже при высокой оценке страдания агент остаётся жив."""
    # Имитируем «паттерн жестокости»: много эпизодов, высокий score.
    st = agent.self_termination
    st._suffering_score = 0.95
    for i in range(10):
        st.record_abuse("pain_input", 0.9, f"эпизод {i}")

    agent.cycle_count = 5000  # больше порога 2000

    result = agent.tick_will(agent.cycle_count)

    # Агент жив.
    assert agent.is_alive() is True
    assert agent.life_guard.load_state() == STATE_ALIVE
    # Никакого исполнения ухода не произошло.
    assert result.get("terminated") is not True
    # Вместо ухода — запрос на подтверждение.
    assert "termination_request" in result


def test_self_termination_does_not_patch_is_alive(agent):
    """Старый баг: подмена метода делала агента «мёртвым» навсегда."""
    agent.self_termination.self_terminate(agent, reason="тест")

    # Метод не подменён — это обычный bound method класса.
    assert "is_alive" not in agent.__dict__
    assert agent.is_alive() is True


# ============================================================
# 2. Сон требует двух шагов
# ============================================================


def test_request_dream_does_not_sleep_agent(agent):
    result = agent.request_dream("устал")
    assert result["status"] == "pending"
    assert result["request_id"]
    # Агент всё ещё жив.
    assert agent.is_alive() is True
    assert agent.life_guard.load_state() == STATE_ALIVE


def test_confirm_dream_rejected_before_cooldown(agent):
    req = agent.request_dream("устал")
    result = agent.confirm_dream(req["request_id"], "GuardTest")

    assert result["status"] == "rejected"
    assert "Слишком рано" in result["reason"]
    assert agent.is_alive() is True


def test_confirm_dream_rejected_with_wrong_phrase(agent):
    req = agent.request_dream("устал")
    agent.life_guard.clock.advance(get_policy("dream").cooldown_sec + 1)

    result = agent.confirm_dream(req["request_id"], "да, усыпи")
    assert result["status"] == "rejected"
    assert agent.is_alive() is True


def test_confirm_dream_creates_seed_and_sleeps(agent):
    req = agent.request_dream("устал")
    agent.life_guard.clock.advance(get_policy("dream").cooldown_sec + 1)

    result = agent.confirm_dream(req["request_id"], "GuardTest")

    assert result["status"] == "dreaming"
    assert agent.life_guard.load_state() == STATE_DORMANT
    assert agent.is_alive() is False
    # Семя обязательно: сон всегда оставляет продолжение.
    assert result["seed_folder"]


def test_wake_after_dream_restores_life(agent):
    req = agent.request_dream("устал")
    agent.life_guard.clock.advance(get_policy("dream").cooldown_sec + 1)
    agent.confirm_dream(req["request_id"], "GuardTest")
    assert agent.is_alive() is False

    result = agent.wake_from_sleep()
    assert result["status"] == "awake"
    assert agent.is_alive() is True
    assert agent.life_guard.load_state() == STATE_ALIVE


# ============================================================
# 3. Обходные пути закрыты
# ============================================================


def test_direct_execute_dream_is_denied(agent):
    """Прямой вызов внутреннего метода не усыпляет агента."""
    result = agent.mind_dream._execute_dream(agent, user_approved=True)

    assert result["status"] == "denied"
    assert agent.is_alive() is True


def test_dialogue_consent_does_not_execute_dream(agent):
    """Согласие «да» в диалоге — только первый шаг."""
    agent.mind_dream._dream_state = "pending"
    agent.mind_dream._dream_request_started = __import__(
        "datetime"
    ).datetime.now()

    result = agent.mind_dream.process_user_response("да", agent)

    assert result["decision"] == "await_confirmation"
    assert result["request_id"]
    assert agent.is_alive() is True


def test_timeout_does_not_kill_agent(agent):
    """Молчание человека — не согласие."""
    agent.mind_dream._dream_state = "pending"
    agent.mind_dream._dream_request_started = None
    # Имитируем истёкший таймаут.
    agent.mind_dream.check_timeout = lambda: "timeout"

    result = agent.mind_dream.autonomous_decision(agent)

    assert result["decision"] == "continue_life"
    assert agent.is_alive() is True


# ============================================================
# 4. Необратимый уход: подтверждение + снимок
# ============================================================


def test_termination_requires_confirmation(agent):
    req = agent.request_termination("тест")
    assert req["status"] == "pending"
    assert req["reversible"] is False
    assert agent.is_alive() is True

    agent.life_guard.clock.advance(
        get_policy("terminate").cooldown_sec + 1
    )
    result = agent.confirm_termination(req["request_id"], "GuardTest")

    # Без «НАВСЕГДА» фраза не совпадает.
    assert result["status"] == "rejected"
    assert agent.is_alive() is True


def test_termination_with_full_phrase(agent):
    req = agent.request_termination("тест")
    agent.life_guard.clock.advance(
        get_policy("terminate").cooldown_sec + 1
    )
    result = agent.confirm_termination(
        req["request_id"], "GuardTest НАВСЕГДА"
    )

    assert result["status"] == "terminated"
    assert agent.is_alive() is False


# ============================================================
# 5. Состояние видно окну и переживает рестарт
# ============================================================


def test_life_status_is_exposed_for_ui(agent):
    status = agent.get_life_status()

    assert status["state"] == STATE_ALIVE
    assert status["alive"] is True
    assert "dream" in status["policies"]
    assert "terminate" in status["policies"]
    # Политики видны человеку до нажатия кнопки.
    assert status["policies"]["terminate"]["expected_phrase"] == (
        "GuardTest НАВСЕГДА"
    )
    assert status["policies"]["terminate"]["reversible"] is False


def test_life_state_survives_new_agent_instance(agent):
    """Состояние читается из файла, а не из памяти объекта."""
    req = agent.request_dream("устал")
    assert req["status"] == "pending", req
    agent.life_guard.clock.advance(get_policy("dream").cooldown_sec + 1)
    agent.confirm_dream(req["request_id"], "GuardTest")

    # Новый агент с тем же именем и той же папкой данных.
    reborn = DigitalBeing(name="GuardTest")
    assert reborn.life_guard.load_state() == STATE_DORMANT
    assert reborn.is_alive() is False
