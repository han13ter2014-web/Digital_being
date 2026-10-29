"""Приёмочный сценарий v1: Core → Effector → память → UI-карта.

Сценарий полностью изолирован временной директорией: не использует сеть,
Ollama, GUI или рабочий профиль. Он проверяет не постановочную картинку,
а реальный безопасный круг уже существующих подсистем.
"""

from types import SimpleNamespace

from src.cognition.intention_history import begin_intention, finish_intention
from src.cognition.mental_models import ConceptNode
from src.core.agent import DigitalBeing
from src.core.workspace_request import creative_write_request
from src.delamain.subsystem import DelamainSubsystem
from src.ui.graph_view import build_life_graph
from src.ui.life_snapshot import build_life_snapshot


def test_full_life_cycle_from_choice_to_diary_and_graph(tmp_path):
    agent = DigitalBeing(name="AcceptanceLife")
    # Концепция нужна только для проверки честной связи «намерение → тема».
    concept = ConceptNode("память")
    concept.confidence = 0.55
    concept.experiences = [{"source": "acceptance", "evidence_kind": "observation"}]
    agent.mental_models.concepts["память"] = concept

    subsystem = DelamainSubsystem(
        agent_name=agent.name,
        workspace=tmp_path / "workspace",
        db_path=tmp_path / "delamain.sqlite3",
        enabled=True,
        approval_mode="dangerous",
        effector_enabled=True,
        core_driven=True,
        tick_interval=1,
    )
    subsystem.setup({})
    try:
        # Core действительно выбирает намерение, а не LLM и не Effector.
        intention = begin_intention(agent, {
            "action": "create_draft",
            "source": "activity",
            "params": {"topic": "память", "reason": "интерес к теме сохранился"},
        })

        # Подключаем изолированный Delamain к Core на время приёмки.
        agent.delamain = subsystem
        agent.delamain_effector = subsystem.effector
        from src.core.effector_driver import EffectorDriver
        agent.effector_driver = EffectorDriver(subsystem.effector, enabled=True)

        request = creative_write_request(
            "acceptance.txt", "Небольшая запись о памяти",
            request_id="acceptance-life-cycle",
            intention_id=intention["id"], target=intention["target"],
            core_cycle=agent.cycle_count,
        )

        queued = subsystem.effector.submit(request)
        assert queued.status.value == "queued"
        assert not queued.ok

        waiting = subsystem.effector.step(1)
        assert waiting.status.value == "waiting_approval"
        assert waiting.approval_id
        assert subsystem.effector.poll(request.request_id).status.value == "waiting_approval"

        approved = subsystem.approve(waiting.approval_id)
        assert approved["status"] == "approved"
        assert subsystem.effector.poll(request.request_id).status.value == "queued"

        # Core-owned clock advances Effector. Второго scheduler нет.
        report = agent.tick_subsystems(2)
        result_payload = report["effector"]["result"]
        assert result_payload["status"] == "succeeded"
        assert result_payload["ok"] is True
        artifact = tmp_path / "workspace" / "creative" / "acceptance.txt"
        assert artifact.read_text(encoding="utf-8") == "Небольшая запись о памяти"

        # Terminal result возвращается Core и завершает выбранное намерение.
        finish_intention(intention, outcome=SimpleNamespace(
            reason="",
            as_dict=lambda: {
                "action": "create_draft", "had_effect": True,
                "effector_request_id": request.request_id,
                "result_status": "succeeded",
            },
        ))
        assert intention["status"] == "performed"
        assert agent._last_effector_activity_result["status"] == "succeeded"
        assert agent._method_preferences["create_draft"]["effects"] == 1

        # Core сам записывает жизненный эпизод в подключённую память.
        record_id = agent._record_core_life_episode(intention)
        assert record_id is not None

        snapshot = build_life_snapshot(agent)
        assert snapshot["diary"]["episodes"]
        episode = snapshot["diary"]["episodes"][0]
        assert episode["task_id"] == intention["id"]
        assert episode["metadata"]["status"] == "performed"

        graph = build_life_graph(agent, snapshot)
        node_ids = {node["id"] for node in graph["nodes"]}
        assert f"intention:{intention['id']}" in node_ids
        assert "activity:create_draft" in node_ids
        assert "concept:память" in node_ids
        assert any(
            edge["source"] == f"intention:{intention['id']}"
            and edge["target"] == "activity:create_draft"
            and edge["kind"] == "uses"
            for edge in graph["edges"]
        )
        assert any(
            edge["source"] == f"intention:{intention['id']}"
            and edge["target"] == "concept:память"
            and edge["kind"] == "about"
            for edge in graph["edges"]
        )
    finally:
        subsystem.teardown()
