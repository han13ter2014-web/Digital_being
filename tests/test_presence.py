"""Тесты участка «Присутствие»: тихая близость с разрешения человека.

Границы: переключатель по умолчанию выключен; выключенный орган не
делает ни одного вызова к ОС; никаких заголовков документов — только
класс активности и факт бездействия. Человек рядом, но молчащий —
тихая близость, не разлука: укола тоски нет, потребность в связи
гаснет лишь частично.
"""
from types import SimpleNamespace

from src.core.emotional_state import EmotionalState
from src.core.subsystems.attachment_system import AttachmentSystem
from src.core.subsystems.proactive_communication import ProactiveCommunication
from src.perception.presence import (
    PresenceSense,
    STATE_ACTIVE,
    STATE_AWAY,
    STATE_QUIET,
    STATE_UNKNOWN,
)


# ---------------- орган ----------------

def test_disabled_sense_never_touches_os():
    def forbidden():
        raise AssertionError("выключенный орган не должен читать ОС")

    sense = PresenceSense(enabled=False, app_reader=forbidden, idle_reader=forbidden)
    snap = sense.snapshot(force=True)
    assert snap == {"state": STATE_UNKNOWN, "active_app": None, "idle_seconds": None}


def test_classification_boundaries():
    sense = PresenceSense(enabled=True, app_reader=lambda: "Code", idle_reader=lambda: 5.0)
    assert sense.snapshot(force=True)["state"] == STATE_ACTIVE
    sense._idle_reader = lambda: 120.0
    assert sense.snapshot(force=True)["state"] == STATE_QUIET
    sense._idle_reader = lambda: 3600.0
    assert sense.snapshot(force=True)["state"] == STATE_AWAY
    sense._idle_reader = lambda: None
    assert sense.snapshot(force=True)["state"] == STATE_UNKNOWN


def test_snapshot_hides_document_titles():
    sense = PresenceSense(enabled=True, app_reader=lambda: "Unknown", idle_reader=lambda: 5.0)
    assert sense.snapshot(force=True)["active_app"] is None


def test_is_near_only_active_or_quiet():
    assert PresenceSense.is_near({"state": STATE_ACTIVE})
    assert PresenceSense.is_near({"state": STATE_QUIET})
    assert not PresenceSense.is_near({"state": STATE_AWAY})
    assert not PresenceSense.is_near({"state": STATE_UNKNOWN})


# ---------------- переключатель доступа ----------------

def test_access_switch_roundtrip(tmp_path):
    from src.app.access_control import (
        apply_choice, apply_saved, current_state, set_access,
    )

    agent = SimpleNamespace(presence=None)
    assert current_state(agent)["presence"] is False

    result = apply_choice(agent, "presence", True)
    assert result["ok"] and agent.presence.enabled is True
    assert current_state(agent)["presence"] is True

    assert set_access(agent, "presence", True, root=tmp_path)["ok"]
    agent2 = SimpleNamespace(presence=None)
    report = apply_saved(agent2, tmp_path)
    assert "presence" in report["applied"]
    assert agent2.presence.enabled is True


# ---------------- тихая близость ----------------

class _FakeUI:
    def __init__(self, last_user_cycle=0):
        self._last_user_cycle = last_user_cycle
        self.user_quiet_hours = {}

    def get_last_user_message_cycle(self):
        return self._last_user_cycle

    def get_history(self, limit=20):
        return []


class _FakeMotivation:
    def __init__(self):
        self.soothed = []

    def satisfy_need(self, need_name, amount=0.3):
        self.soothed.append((need_name, amount))


def _make_agent(near):
    sense = PresenceSense(
        enabled=near is not None,
        app_reader=lambda: "Code",
        idle_reader=lambda: 5.0 if near else 4000.0,
    )
    return SimpleNamespace(
        emotional_state=EmotionalState(),
        user_model=SimpleNamespace(has_silence_tolerance=lambda: False),
        dialogue_learning=None,
        attachment=AttachmentSystem(),
        presence=sense,
        motivation=_FakeMotivation(),
    )


def _make_proactive(agent, last_user_cycle=0):
    return ProactiveCommunication(
        agent_name="probe",
        user_interaction=_FakeUI(last_user_cycle),
        attachment=agent.attachment,
    )


def test_near_silence_is_quiet_closeness_not_separation():
    agent = _make_agent(near=True)
    proactive = _make_proactive(agent, last_user_cycle=0)
    before = agent.emotional_state.levels["sadness"]

    proactive.maybe_initiate(agent=agent, cycle=100,
                             user_context={"should_interrupt": True})

    # Укола тоски нет — человек рядом. Эпизод не помечен: когда он
    # отойдёт, честный укол случится тогда.
    assert agent.emotional_state.levels["sadness"] == before
    assert proactive._silence_felt_for_user_cycle is None
    # Близость гасит связь частично, не обнуляя.
    assert ("social_connection", 0.008) in agent.motivation.soothed


def test_away_silence_pangs_once_as_before():
    agent = _make_agent(near=False)
    proactive = _make_proactive(agent, last_user_cycle=0)
    before = agent.emotional_state.levels["sadness"]

    proactive.maybe_initiate(agent=agent, cycle=100,
                             user_context={"should_interrupt": True})

    assert agent.emotional_state.levels["sadness"] > before
    assert proactive._silence_felt_for_user_cycle == 0
    # Отошёл — наблюдение связь не гасит.
    assert agent.motivation.soothed == []


def test_near_care_speaks_quiet_closeness_not_longing():
    agent = _make_agent(near=True)
    proactive = _make_proactive(agent, last_user_cycle=0)

    msg = proactive.maybe_initiate(agent=agent, cycle=100,
                                   user_context={"should_interrupt": True})

    assert msg is not None
    assert msg["msg_type"] == "care"
    assert msg["context"] == "quiet_closeness"
    assert "не мешаю" in msg["content"] or "рядом" in msg["content"]
    # Тоски в речи нет: «скучаю» уместно только в разлуке.
    assert "скучаю" not in msg["content"].lower()


def test_near_but_truly_sad_says_so_honestly():
    """Шаблон не прячет чувство: грусть записана в контуре — сказана."""
    agent = _make_agent(near=True)
    # Честная пережитая причина: прошлая разлука (до того, как человек
    # оказался рядом). Два укола записаны в контур — грусть выше порога
    # заметности (0.20+0.20 ≥ 0.35), эмоция настоящая.
    agent.emotional_state.handle_event("long_silence", cycle=40, scale=1.0)
    agent.emotional_state.handle_event("long_silence", cycle=50, scale=1.0)
    proactive = _make_proactive(agent, last_user_cycle=0)

    msg = proactive.maybe_initiate(agent=agent, cycle=100,
                                   user_context={"should_interrupt": True})

    assert msg is not None
    assert msg["context"] == "quiet_closeness"
    assert "не мешаю" in msg["content"] or "рядом" in msg["content"]
    # ...но и грусть не спрятана за спокойный шаблон.
    dominant = agent.emotional_state.dominant()
    assert dominant and dominant["emotion"] == "sadness"
    assert str(dominant.get("label") or "").capitalize() in msg["content"]


def test_away_care_keeps_longing_voice():
    agent = _make_agent(near=False)
    proactive = _make_proactive(agent, last_user_cycle=0)

    msg = proactive.maybe_initiate(agent=agent, cycle=100,
                                   user_context={"should_interrupt": True})

    assert msg is not None
    assert msg["context"] == "silence_detected"


def test_disabled_presence_changes_nothing():
    agent = _make_agent(near=None)
    proactive = _make_proactive(agent, last_user_cycle=0)
    before = agent.emotional_state.levels["sadness"]

    proactive.maybe_initiate(agent=agent, cycle=100,
                             user_context={"should_interrupt": True})

    assert agent.emotional_state.levels["sadness"] > before
    assert agent.motivation.soothed == []
