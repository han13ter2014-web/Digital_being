"""Read-only снимок жизни: не меняет Core и не выдумывает данные."""

from copy import deepcopy
from types import SimpleNamespace

from src.cognition.intention_history import begin_intention, finish_intention
from src.core.agent import DigitalBeing
from src.ui.life_snapshot import build_life_snapshot, recent_life_episodes


def _agent(name="Snapshot"):
    return DigitalBeing(name=name)


def test_snapshot_does_not_create_lazy_core_fields():
    agent = _agent("NoLazy")
    assert "_intention_history" not in agent.__dict__
    assert "_waiting_intentions" not in agent.__dict__
    assert "_method_preferences" not in agent.__dict__

    build_life_snapshot(agent)

    assert "_intention_history" not in agent.__dict__
    assert "_waiting_intentions" not in agent.__dict__
    assert "_method_preferences" not in agent.__dict__


def test_snapshot_does_not_mutate_agent():
    agent = _agent("Stable")
    entry = begin_intention(
        agent,
        {
            "action": "play",
            "source": "activity",
            "params": {"topic": "партия", "reason": "интерес"},
        },
    )
    keys_before = set(agent.__dict__)
    cycle_before = agent.cycle_count
    energy_before = agent.energy
    history_before = deepcopy(agent._intention_history)

    first = build_life_snapshot(agent)
    second = build_life_snapshot(agent)

    assert first == second
    assert set(agent.__dict__) == keys_before
    assert agent.cycle_count == cycle_before
    assert agent.energy == energy_before
    assert agent._intention_history == history_before
    assert first["now"]["activity"]["id"] == entry["id"]


def test_snapshot_returns_deep_copies_of_core_data():
    agent = _agent("Copies")
    entry = begin_intention(agent, {"action": "play", "params": {"topic": "игра"}})

    snapshot = build_life_snapshot(agent)
    snapshot["intentions"]["recent"][0]["status"] = "tampered"
    snapshot["now"]["activity"]["target"] = "tampered"

    assert agent._intention_history[0]["status"] == "started"
    assert agent._intention_history[0]["target"] == entry["target"]


def test_snapshot_shows_queued_effector_separately_from_succeeded():
    counts = {
        "queued": 2,
        "waiting_approval": 1,
        "succeeded": 3,
        "failed": 1,
        "rejected": 0,
    }
    agent = _agent("Effector")
    agent.delamain_effector = SimpleNamespace(
        enabled=True, status=lambda: {"counts": counts}
    )

    snapshot = build_life_snapshot(agent)

    assert snapshot["effector"]["available"] is True
    assert snapshot["effector"]["counts"]["queued"] == 2
    assert snapshot["effector"]["counts"]["succeeded"] == 3
    assert snapshot["access"]["effector"]["enabled"] is True


def test_snapshot_without_effector_is_honest_about_absence():
    agent = _agent("NoEffector")
    agent.delamain_effector = None
    snapshot = build_life_snapshot(agent)
    assert snapshot["effector"]["available"] is False
    assert snapshot["effector"]["counts"] == {}


def test_broken_subsystem_does_not_break_snapshot():
    agent = _agent("Broken")

    def explode():
        raise RuntimeError("подсистема недоступна")

    agent.motivation_system = SimpleNamespace(get_status=explode)
    snapshot = build_life_snapshot(agent)
    assert snapshot["motivation"] == {}
    assert snapshot["name"] == "Broken"


def test_waiting_intentions_are_listed_only_while_unresolved():
    agent = _agent("Waiting")
    entry = begin_intention(
        agent,
        {
            "action": "explore",
            "source": "activity",
            "params": {"topic": "память", "reason": "нет источников"},
        },
    )
    entry["evidence_goal"] = {
        "kind": "new_topic_evidence",
        "status": "pending",
        "baseline_sources": [],
        "new_sources": [],
    }
    entry["continuation_of"] = "previous"
    finish_intention(entry, outcome=None)
    from src.cognition.intention_waiting import remember_wait

    remember_wait(agent, entry)
    assert len(build_life_snapshot(agent)["intentions"]["waiting"]) == 1

    agent._waiting_intentions[next(iter(agent._waiting_intentions))]["resolution"] = {
        "kind": "forgotten",
        "reason": "источников нет",
        "cycle": agent.cycle_count,
    }
    snapshot = build_life_snapshot(agent)
    assert snapshot["intentions"]["waiting"] == []
    # Забытое не исчезает: оно уходит в отдельный список для карты.
    assert [row["id"] for row in snapshot["intentions"]["forgotten"]] == [entry["id"]]


def test_life_episodes_are_empty_without_delamain():
    agent = _agent("NoDelamain")
    assert recent_life_episodes(agent) == []


def test_activity_catalog_matches_core_not_filesystem():
    agent = _agent("Catalog")
    snapshot = build_life_snapshot(agent)
    assert snapshot["activities"]["creative"]["count"] == 0
    assert snapshot["activities"]["creative"]["drafts"] == []
    assert snapshot["activities"]["game"] is None
    assert snapshot["diary"]["episodes"] == []


def test_diary_includes_finished_core_intention_without_delamain():
    agent = _agent("CoreDiary")
    entry = begin_intention(
        agent,
        {
            "action": "create_draft",
            "source": "activity",
            "params": {"topic": "тишина", "reason": "интерес"},
        },
    )
    finish_intention(
        entry,
        outcome=SimpleNamespace(
            reason="", as_dict=lambda: {"action": "create_draft", "had_effect": True}
        ),
    )

    diary = build_life_snapshot(agent)["diary"]["episodes"]
    assert len(diary) == 1
    assert diary[0]["task_id"] == entry["id"]
    assert diary[0]["metadata"]["source"] == "core_history"
    assert diary[0]["metadata"]["status"] == "performed"


def test_diary_snapshot_reads_episodes_without_mutating_core():
    agent = _agent("DiaryCopies")
    rows = [
        {
            "id": 1,
            "action": "play",
            "args": {"target": "партия"},
            "metadata": {"status": "performed"},
        }
    ]
    agent.delamain = SimpleNamespace(
        runtime=SimpleNamespace(
            memory=SimpleNamespace(recent_life_episodes=lambda **kwargs: rows)
        )
    )
    before = set(agent.__dict__)
    snapshot = build_life_snapshot(agent)
    snapshot["diary"]["episodes"][0]["args"]["target"] = "изменено"
    assert rows[0]["args"]["target"] == "партия"
    assert set(agent.__dict__) == before


def test_snapshot_exposes_existing_emotions_body_and_presence():
    agent = _agent("BodyAndEmotions")
    agent.emotional_state.handle_event("intention_completed", cycle=1, cause="тест")
    agent.presence = SimpleNamespace(enabled=True)

    snapshot = build_life_snapshot(agent)

    assert snapshot["emotions"] == agent.emotional_state.get_status()
    assert snapshot["body"] == agent.interoception.get_status()
    assert snapshot["access"]["presence"] == {"enabled": True, "label": "Присутствие"}
    assert snapshot["body"]["atp"] == agent.interoception.get_status()["atp"]


def test_extended_diary_uses_same_collector_without_changing_tk_window():
    from src.ui.life_snapshot import build_diary_snapshot

    agent = _agent("DiaryPages")
    rows = [
        {"id": index, "action": "play", "args": {"target": str(index)}}
        for index in range(30)
    ]
    agent.delamain = SimpleNamespace(
        runtime=SimpleNamespace(
            memory=SimpleNamespace(
                recent_life_episodes=lambda **kwargs: rows[-kwargs["limit"] :]
            )
        )
    )

    tk_snapshot = build_life_snapshot(agent)
    web_snapshot = build_diary_snapshot(agent)

    assert len(tk_snapshot["diary"]["episodes"]) == 20
    assert len(web_snapshot["episodes"]) == 30
    assert web_snapshot["episodes"][:20] == tk_snapshot["diary"]["episodes"]
    assert web_snapshot["cache_limit"] == 500


def test_snapshot_exposes_pending_proposal_as_deep_read_only_copy():
    agent = _agent("ProposalView")
    proposal = {
        "id": "prop_view",
        "type": "config_change",
        "title": "REST_FATIGUE_THRESHOLD: 0.6 → 0.55",
        "description": "Отдыхать чуть раньше",
        "category": "energy_efficiency",
        "attr": "REST_FATIGUE_THRESHOLD",
        "old": 0.6,
        "new": 0.55,
        "verification": {"ran": True, "passed": True},
        "code_snippet": "не показываем в карточке",
    }
    agent.architecture_proposal = SimpleNamespace(list_pending=lambda: [proposal])
    agent._safe_config_overrides = {"FORGETTING_INTERVAL": 400}
    keys_before = set(agent.__dict__)

    snapshot = build_life_snapshot(agent)

    view = snapshot["proposals"]
    assert view["pending"][0]["id"] == "prop_view"
    assert view["pending"][0]["verification"]["passed"] is True
    assert "code_snippet" not in view["pending"][0]
    assert view["effective_overrides"] == {"FORGETTING_INTERVAL": 400}
    view["pending"][0]["verification"]["passed"] = False
    view["effective_overrides"]["FORGETTING_INTERVAL"] = 1
    assert proposal["verification"]["passed"] is True
    assert agent._safe_config_overrides["FORGETTING_INTERVAL"] == 400
    assert set(agent.__dict__) == keys_before


def test_tutor_snapshot_is_safe_deep_copy_without_expected_answer():
    agent = _agent("TutorView")
    url = "https://example.test/lesson"
    request = agent.language_tutor.request_source(url, "Нужен урок", cycle=1)
    agent.web_searcher = SimpleNamespace(is_enabled=False)
    agent.language_tutor.lessons = [
        {
            "lesson_id": "lesson-safe",
            "status": "candidate",
            "exercises": [
                {
                    "exercise_id": "exercise-safe",
                    "kind": "practice",
                    "prompt": "ж?раф",
                    "expected": "жираф",
                    "status": "pending",
                }
            ],
        }
    ]
    agent.language_tutor.pending_exercise = {
        "lesson_id": "lesson-safe",
        "exercise_id": "exercise-safe",
    }
    before = deepcopy(agent.language_tutor.to_dict())

    snapshot = build_life_snapshot(agent)

    tutor = snapshot["tutor"]
    assert tutor["available"] is True
    assert tutor["web_enabled"] is False
    assert tutor["request_count"] == 1
    assert tutor["source_requests"][0]["request_id"] == request["request_id"]
    assert tutor["pending_exercise"] == {
        "prompt": "ж?раф",
        "kind": "practice",
        "lesson_id": "lesson-safe",
        "exercise_id": "exercise-safe",
    }
    assert "жираф" not in str(tutor)
    tutor["source_requests"][0]["reason"] = "изменено в UI"
    tutor["pending_exercise"]["prompt"] = "изменено в UI"
    assert agent.language_tutor.to_dict() == before


def test_missing_or_broken_tutor_does_not_break_snapshot():
    agent = _agent("NoTutor")
    agent.language_tutor = None
    assert build_life_snapshot(agent)["tutor"]["available"] is False

    def explode():
        raise RuntimeError("наставник недоступен")

    agent.language_tutor = SimpleNamespace(get_status=explode)
    snapshot = build_life_snapshot(agent)
    assert snapshot["tutor"]["available"] is True
    assert snapshot["tutor"]["approved_sources"] == []


def _external_session(agent, external_id="deepseek-web"):
    return agent.external_contacts.start_session(
        agent.social_registry,
        provider="manual",
        name="DeepSeek",
        external_id=external_id,
        topic="осторожный разговор",
        reason="проверка панели",
        cycle=agent.cycle_count,
    )


def test_external_snapshot_is_bounded_deep_copy_without_private_memory():
    agent = _agent("ExternalSnapshot")
    private_text = "Личная тайна владельца"
    agent.user_interaction.receive_user_message(private_text, cycle=1)
    started = _external_session(agent)
    session_id = started["session_id"]
    agent.external_contacts.ingest(session_id, "Привет от внешней модели", cycle=2)
    agent.external_contacts.create_draft(session_id, cycle=3)
    before = deepcopy(agent.external_contacts.to_dict())

    snapshot = build_life_snapshot(agent)
    view = snapshot["external_contacts"]
    session = view["sessions"][0]

    assert view["available"] is True
    assert view["can_manage"] is True
    assert view["pending_drafts"] == 1
    assert session["display_name"] == "DeepSeek"
    assert session["message_count"] == 2
    assert session["pending_draft"]["status"] == "draft"
    assert session["messages"][0]["claim_type"] == "external_ai_claim"
    assert private_text not in str(view)
    session["messages"][0]["text"] = "изменено в UI"
    assert agent.external_contacts.to_dict() == before


def test_external_snapshot_limits_journal_and_denies_guest_management():
    agent = _agent("ExternalSnapshotLimits")
    session_id = _external_session(agent)["session_id"]
    for cycle in range(1, 8):
        agent.external_contacts.ingest(session_id, f"Реплика {cycle}", cycle=cycle)
        agent.external_contacts.create_draft(session_id, cycle=cycle)
        agent.external_contacts.reject(session_id, cycle=cycle)

    view = build_life_snapshot(agent)["external_contacts"]
    session = view["sessions"][0]
    assert session["message_count"] == 14
    assert len(session["messages"]) == view["journal_limit"] == 12
    assert session["messages"][0]["text"] == "Реплика 2"
    assert session["messages"][-1]["status"] == "rejected"

    agent.social_registry.create_local_person("Гость", cycle=8)
    guest_view = build_life_snapshot(agent)["external_contacts"]
    assert guest_view["can_manage"] is False
    assert guest_view["sessions"][0]["display_name"] == "DeepSeek"


def test_missing_external_manager_has_honest_empty_snapshot():
    agent = _agent("ExternalSnapshotMissing")
    agent.external_contacts = None

    view = build_life_snapshot(agent)["external_contacts"]

    assert view["available"] is False
    assert view["can_manage"] is False
    assert view["sessions"] == []


def test_external_snapshot_exposes_model_and_safe_automation_status():
    agent = _agent("ExternalAutomationSnapshot")
    started = agent.external_contacts.start_session(
        agent.social_registry,
        provider="rufp",
        name="RUFP",
        external_id="rufp-fixture",
        topic="проверка",
        reason="явный запуск",
        cycle=0,
        model="rufp/default",
    )
    session_id = started["session_id"]
    agent.external_contacts.record_event(session_id, "started", cycle=0)

    class Controller:
        def get_status(self):
            return {
                "state": "running",
                "in_flight": True,
                "replies_sent": 1,
                "max_replies": 3,
                "tokens_used": 25,
                "max_total_tokens": 100,
                "min_interval_sec": 2.0,
                "usage": {"total_tokens": 25},
                "tokens_estimated": False,
                "billing_receipts": [{"cost_rub": 0.01}],
                "last_error": None,
                "automatic_resume": False,
                "api_key": "must-not-leak",
                "response_text": "not part of automation DTO",
            }

    agent._external_dialogue_controllers = {session_id: Controller()}
    session = build_life_snapshot(agent)["external_contacts"]["sessions"][0]

    assert session["model"] == "rufp/default"
    assert session["automation"]["state"] == "running"
    assert session["automation"]["replies_sent"] == 1
    assert session["automation"]["automatic_resume"] is False
    assert session["control_events"] == [
        {"kind": "started", "cycle": 0, "reason": None}
    ]
    assert "must-not-leak" not in str(session)
    assert "not part of automation DTO" not in str(session)


def test_english_tutor_snapshot_is_safe_deep_copy_without_expected_or_excerpt():
    agent = _agent("EnglishTutorView")
    tutor = agent.english_language_tutor
    url = "https://example.test/english/regular-plural-s"
    request = tutor.request_source(url, "Check one English rule", cycle=1)
    tutor.materials = [
        {
            "url": url,
            "title": "Offline lesson",
            "language_id": "en",
            "content_hash": "a" * 64,
            "excerpt": "secret source excerpt",
            "fetched_cycle": 1,
            "status": "parsed",
            "reason": "",
        }
    ]
    tutor.rule_packs = [
        {
            "pack_id": "en-pack-safe",
            "rule_id": "en_regular_plural_s",
            "status": "candidate",
            "exercises": [
                {
                    "exercise_id": "exercise-safe",
                    "kind": "practice",
                    "prompt": "cat",
                    "expected": "cats",
                    "status": "pending",
                }
            ],
        }
    ]
    tutor.pending_exercise = {
        "pack_id": "en-pack-safe",
        "exercise_id": "exercise-safe",
    }
    agent.web_searcher = SimpleNamespace(is_enabled=False)
    before = deepcopy(tutor.to_dict())

    snapshot = build_life_snapshot(agent)["english_tutor"]

    assert snapshot["available"] is True
    assert snapshot["web_enabled"] is False
    assert snapshot["request_count"] == 1
    assert snapshot["source_requests"][0]["request_id"] == request["request_id"]
    assert snapshot["materials"] == 1
    assert snapshot["rule_packs"] == 1
    assert snapshot["pending_exercise"] == {
        "prompt": "cat",
        "kind": "practice",
        "pack_id": "en-pack-safe",
        "exercise_id": "exercise-safe",
        "rule_id": "en_regular_plural_s",
    }
    assert "cats" not in str(snapshot)
    assert "secret source excerpt" not in str(snapshot)
    snapshot["source_requests"][0]["reason"] = "изменено в UI"
    snapshot["pending_exercise"]["prompt"] = "изменено в UI"
    assert tutor.to_dict() == before


def test_missing_or_broken_english_tutor_does_not_break_snapshot():
    agent = _agent("NoEnglishTutor")
    agent.english_language_tutor = None
    assert build_life_snapshot(agent)["english_tutor"]["available"] is False

    def explode():
        raise RuntimeError("EN-наставник недоступен")

    agent.english_language_tutor = SimpleNamespace(get_status=explode)
    snapshot = build_life_snapshot(agent)["english_tutor"]
    assert snapshot["available"] is True
    assert snapshot["approved_sources"] == []
    assert snapshot["rule_packs"] == 0


def test_dialogue_snapshot_exposes_only_sanitized_language_diagnostics():
    from src.core.english_dialogue import (
        build_english_realization,
        english_response_references,
        recognize_english,
    )

    agent = _agent("DialogueDiagnostics")
    agent.cycle_count = 7
    agent.social_attribution.set_stable_dialogue_language("en")
    agent.social_attribution.resolve_language("What are you doing?")
    agent.social_attribution.set_response_language("en")
    recognition = recognize_english("What are you doing?", agent)
    realization = build_english_realization(agent, recognition)
    prepared = agent.response_experience.prepare_plan(
        agent,
        realization["text"],
        context=recognition.reply_context,
        source="test",
        user_text="What are you doing?",
        references=english_response_references(recognition),
        english_realization=realization,
    )
    agent.response_experience.register_delivery(
        "dialogue-diagnostic", prepared["plan"], agent.cycle_count
    )

    snapshot = build_life_snapshot(agent)["dialogue"]

    assert snapshot == {
        "available": True,
        "input_language": "en",
        "dialogue_language": "en",
        "response_language": "en",
        "language_source": "stable_dialogue",
        "act": "ask_about_self",
        "rule_id": "about_self",
        "fallback_policy": "none",
        "reference_count": 2,
        "references_verified": True,
        "profile_id": agent.social_registry.current_profile_id,
    }
    assert "What are you doing?" not in str(snapshot)
    assert "My name is" not in str(snapshot)


def test_dialogue_snapshot_is_honest_about_missing_or_legacy_plan():
    agent = _agent("NoDialogueDiagnostics")
    empty = build_life_snapshot(agent)["dialogue"]
    assert empty["available"] is False
    assert empty["references_verified"] is False

    agent.response_experience.responses["broken"] = {"plan": None}
    agent.response_experience.latest_response_id = "broken"
    broken = build_life_snapshot(agent)["dialogue"]
    assert broken["available"] is False

    agent = _agent("LegacyDialogueDiagnostics")
    agent.social_attribution.set_stable_dialogue_language("en")
    agent.social_attribution.resolve_language("Hello")
    prepared = agent.response_experience.prepare_plan(
        agent,
        "Legacy English plan without diagnostic metadata.",
        context="social_reply",
        source="test",
        user_text="Hello",
    )
    agent.response_experience.register_delivery(
        "legacy-dialogue", prepared["plan"], agent.cycle_count
    )
    legacy = build_life_snapshot(agent)["dialogue"]
    assert legacy["available"] is True
    assert legacy["act"] is None
    assert legacy["rule_id"] is None
    assert legacy["fallback_policy"] == "none"


def test_hardware_snapshot_is_compact_deep_copy_without_os_sampling(monkeypatch):
    agent = _agent("HardwareSnapshot")
    status = {
        "mode": "shadow",
        "observation": {"channels": {"host_cpu": {"value": 95.0}}},
        "latest_experience": {"own_load": {"risk": 0.95, "experienced": 0.85}},
        "personal_profile": {"baseline": {"own_load": {"sample_count": 50}}},
        "current_episode": {"start_cycle": 1},
        "episodes": [{"start_cycle": 1}, {"start_cycle": 20}],
        "recent_events": [{"cycle": cycle} for cycle in range(12)],
    }
    agent.hardware_interoception = SimpleNamespace(status=lambda: status)
    keys_before = set(agent.__dict__)

    def unexpected_sampling(*args, **kwargs):
        raise AssertionError("snapshot must not sample the OS")

    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage", unexpected_sampling
    )
    monkeypatch.setattr(
        "src.core.watchdog.Watchdog.get_resource_status", unexpected_sampling
    )

    first = build_life_snapshot(agent)
    second = build_life_snapshot(agent)

    assert first == second
    assert first["hardware"]["initialized"] is True
    assert first["hardware"]["episode_count"] == 2
    assert "episodes" not in first["hardware"]
    assert len(first["hardware"]["recent_events"]) == 10
    assert first["hardware"]["recent_events"][0]["cycle"] == 2
    assert set(agent.__dict__) == keys_before

    first["hardware"]["personal_profile"]["baseline"]["own_load"]["sample_count"] = 0
    first["hardware"]["recent_events"][0]["cycle"] = -1
    assert status["personal_profile"]["baseline"]["own_load"]["sample_count"] == 50
    assert status["recent_events"][2]["cycle"] == 2


def test_hardware_snapshot_is_explicit_when_observer_is_absent_or_broken():
    agent = _agent("NoHardware")
    agent.hardware_interoception = None
    assert build_life_snapshot(agent)["hardware"] == {
        "mode": "shadow",
        "initialized": False,
        "reason": "not_initialized",
    }

    def explode():
        raise RuntimeError("C:/private/sensor failure")

    agent.hardware_interoception = SimpleNamespace(status=explode)
    snapshot = build_life_snapshot(agent)
    assert snapshot["hardware"]["initialized"] is False
    assert "C:/private" not in str(snapshot)


def test_hardware_rows_distinguish_unavailable_stale_and_unknown():
    from src.ui.life_view import hardware_rows

    base = {
        "initialized": True,
        "observation": {
            "channels": {
                "host_cpu": {"status": "unavailable", "value": None},
                "process_cpu": {"status": "stale", "value": 50.0},
            }
        },
        "latest_experience": {"own_load": {"risk": None, "experienced": None}},
        "personal_profile": {"baseline": {}},
        "shadow_strain": None,
        "shadow_recovery": None,
    }
    snapshot = {"hardware": base}
    russian = "\n".join(f"{key}: {value}" for key, value in hardware_rows(snapshot))
    assert "CPU среды: недоступно" in russian
    assert "CPU процесса: устарело" in russian
    assert "риск Нет данных" in russian
    assert "0.0%" not in russian

    english = "\n".join(
        f"{key}: {value}" for key, value in hardware_rows(snapshot, "en")
    )
    assert "Host CPU: unavailable" in english
    assert "Process CPU: stale" in english
    assert "insufficient experience" in english


def test_hardware_rows_show_physical_values_without_hiding_missing_channels():
    from src.ui.life_view import hardware_rows

    snapshot = {
        "hardware": {
            "initialized": True,
            "observation": {
                "channels": {
                    "gpu_utilization": {
                        "status": "available",
                        "value": 80.0,
                        "unit": "percent",
                    },
                    "gpu_memory": {
                        "status": "available",
                        "value": 0.75,
                        "unit": "ratio",
                    },
                    "gpu_temperature": {
                        "status": "available",
                        "value": 70.0,
                        "unit": "celsius",
                    },
                    "gpu_power": {
                        "status": "available",
                        "value": 0.9,
                        "unit": "ratio",
                    },
                    "cpu_temperature": {"status": "unavailable", "value": None},
                    "external_power": {
                        "status": "available",
                        "value": 1.0,
                        "unit": "ratio",
                    },
                    "battery_charge": {"status": "unavailable", "value": None},
                }
            },
            "states": {"physical_strain": {"value": 0.8}},
            "latest_experience": {},
            "personal_profile": {"baseline": {}},
        }
    }

    russian = "\n".join(f"{key}: {value}" for key, value in hardware_rows(snapshot))
    assert "Загрузка GPU: 80.0%" in russian
    assert "Память GPU: 75.0%" in russian
    assert "Температура GPU: 70.0 °C" in russian
    assert "Мощность GPU: 90.0%" in russian
    assert "Температура CPU: недоступно" in russian
    assert "Внешнее питание: да" in russian
    assert "Заряд батареи: недоступно" in russian
    assert "Физическое напряжение: 80.0%" in russian

    english = "\n".join(
        f"{key}: {value}" for key, value in hardware_rows(snapshot, "en")
    )
    assert "GPU utilization: 80.0%" in english
    assert "CPU temperature: unavailable" in english
    assert "External power: yes" in english

    chinese = "\n".join(
        f"{key}: {value}" for key, value in hardware_rows(snapshot, "zh")
    )
    assert "GPU 温度: 70.0 °C" in chinese
    assert "CPU 温度: 不可用" in chinese


def _hormonal_checkpoint():
    names = ("dopamine", "serotonin", "oxytocin", "cortisol", "prolactin")
    levels = {
        "dopamine": 0.55,
        "serotonin": 0.52,
        "oxytocin": 0.3,
        "cortisol": 0.15,
        "prolactin": 0.2,
    }
    profile = {
        name: {
            "baseline": levels[name],
            "sensitivity": 1.0,
            "half_life_scale": 1.0,
            "confidence": 0.0,
            "sample_count": 0,
            "source_sample_counts": {},
        }
        for name in names
    }
    profile["dopamine"].update(
        {
            "baseline": 0.43,
            "sensitivity": 0.98,
            "half_life_scale": 1.02,
            "confidence": 0.125,
            "sample_count": 25,
            "source_sample_counts": {"action_outcome": 25},
        }
    )
    return {
        "schema_version": 2,
        "time_model": "tick_only",
        "legacy_mixed_time": False,
        "hormones": levels,
        "profile": profile,
        "episodes": [
            {
                "time": float(cycle),
                "event": "success",
                "source": "action_outcome",
                "cycle": cycle,
                "reason": "knowledge_changed",
                "action": "explore",
                "origin": "own",
                "intensity": 1.0,
                "changes": {"dopamine": 0.15},
                "private": "C:/private/message",
            }
            for cycle in range(5)
        ],
        "history": [{"event": "success", "message": "C:/private/history"}],
        "cycle_time": 300.0,
    }


def test_hormonal_snapshot_is_compact_deep_copy_with_bounded_reasons():
    agent = _agent("HormonalSnapshot")
    checkpoint = _hormonal_checkpoint()
    agent.hormonal_system = SimpleNamespace(to_checkpoint=lambda: checkpoint)
    keys_before = set(agent.__dict__)

    first = build_life_snapshot(agent)
    second = build_life_snapshot(agent)

    assert first == second
    assert set(agent.__dict__) == keys_before
    projection = first["hormonal_projection"]
    assert projection["initialized"] is True
    assert projection["mode"] == "shadow_interoception"
    assert projection["time_model"] == "tick_only"
    assert projection["legacy_mixed_time"] is False
    assert projection["levels"] == checkpoint["hormones"]
    assert projection["profile"] == checkpoint["profile"]
    assert "history" not in projection
    assert "episodes" not in projection
    assert "cycle_time" not in projection
    assert len(projection["recent_reasons"]) == 3
    assert [item["cycle"] for item in projection["recent_reasons"]] == [2, 3, 4]
    assert all(
        set(item) == {"event", "source", "cycle", "reason", "action", "origin"}
        for item in projection["recent_reasons"]
    )
    assert "C:/private" not in str(projection)

    projection["levels"]["dopamine"] = 0.0
    projection["profile"]["dopamine"]["baseline"] = 0.0
    projection["recent_reasons"][0]["action"] = "tampered"
    assert checkpoint["hormones"]["dopamine"] == 0.55
    assert checkpoint["profile"]["dopamine"]["baseline"] == 0.43
    assert checkpoint["episodes"][2]["action"] == "explore"


def test_hormonal_snapshot_is_explicit_when_system_is_absent_or_broken():
    agent = _agent("NoHormones")
    agent.hormonal_system = None
    assert build_life_snapshot(agent)["hormonal_projection"] == {
        "initialized": False,
        "mode": "shadow_interoception",
        "reason": "not_initialized",
    }

    def explode():
        raise RuntimeError("C:/private/endocrine failure")

    agent.hormonal_system = SimpleNamespace(to_checkpoint=explode)
    snapshot = build_life_snapshot(agent)
    assert snapshot["hormonal_projection"]["initialized"] is False
    assert "C:/private" not in str(snapshot)


def test_hormonal_rows_keep_no_evidence_distinct_from_personal_profile():
    from src.ui.life_view import hormonal_rows

    checkpoint = _hormonal_checkpoint()
    for profile in checkpoint["profile"].values():
        profile.update(
            {
                "confidence": 0.0,
                "sample_count": 0,
                "source_sample_counts": {},
            }
        )
    snapshot = {
        "hormonal_projection": {
            "initialized": True,
            "time_model": "tick_only",
            "legacy_mixed_time": False,
            "levels": checkpoint["hormones"],
            "profile": checkpoint["profile"],
            "recent_reasons": [],
        }
    }

    russian = "\n".join(f"{key}: {value}" for key, value in hormonal_rows(snapshot))
    assert "Дофамин: 0.55" in russian
    assert "Личный профиль: Нет данных" in russian
    assert "Модель времени: только тик" in russian
    assert "Прежнее смешанное время: нет" in russian
    assert "уверенность 0.00" not in russian

    english = "\n".join(
        f"{key}: {value}" for key, value in hormonal_rows(snapshot, "en")
    )
    assert "Dopamine: 0.55" in english
    assert "Personal profile: No data" in english
    assert "Time model: tick only" in english

    chinese = "\n".join(
        f"{key}: {value}" for key, value in hormonal_rows(snapshot, "zh")
    )
    assert "多巴胺: 0.55" in chinese
    assert "个人档案: 暂无数据" in chinese
    assert "时间模型: 仅按周期" in chinese


def test_hormonal_rows_show_real_profile_and_reason_codes_in_three_languages():
    from src.ui.life_view import hormonal_rows

    checkpoint = _hormonal_checkpoint()
    snapshot = {
        "hormonal_projection": {
            "initialized": True,
            "time_model": "tick_only",
            "legacy_mixed_time": False,
            "levels": checkpoint["hormones"],
            "profile": checkpoint["profile"],
            "recent_reasons": [checkpoint["episodes"][-1]],
        }
    }

    russian = "\n".join(f"{key}: {value}" for key, value in hormonal_rows(snapshot))
    assert (
        "Дофамин: 0.55 · Базовый уровень 0.43 · Чувствительность 0.98 · "
        "Масштаб half-life 1.02 · уверенность 0.12 · Подтверждённые эпизоды 25"
    ) in russian
    assert "Последние причины · цикл 4: success · action_outcome" in russian
    assert "explore · knowledge_changed" in russian
    assert "C:/private" not in russian

    english = "\n".join(
        f"{key}: {value}" for key, value in hormonal_rows(snapshot, "en")
    )
    assert (
        "Dopamine: 0.55 · Baseline 0.43 · Sensitivity 0.98 · "
        "Half-life scale 1.02 · confidence 0.12 · Confirmed episodes 25"
    ) in english
    assert "Recent reasons · cycle 4" in english

    chinese = "\n".join(
        f"{key}: {value}" for key, value in hormonal_rows(snapshot, "zh")
    )
    assert (
        "多巴胺: 0.55 · 基础水平 0.43 · 敏感性 0.98 · "
        "半衰期缩放 1.02 · 置信度 0.12 · 已确认事件 25"
    ) in chinese
    assert "最近原因 · 周期 4" in chinese
