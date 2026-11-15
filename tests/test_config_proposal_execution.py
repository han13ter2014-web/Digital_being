"""Т6: ограниченное исполнение одобренных безопасных config_change."""

import hashlib
import json
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from config.simulation_config import LR_CONFIG
from src.core.paths import project_root
from src.core.subsystems.architecture_proposal import ArchitectureProposal
from src.core.subsystems.will_registry import WillRegistry
from src.evolution.self_coding import draft_config_change


def _api(tmp_path, monkeypatch, life_id=None, standalone=False):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    managed_id = None if standalone else (life_id or str(uuid4()))
    api = ArchitectureProposal(
        registry=WillRegistry(agent_name="executor-test"), life_id=managed_id
    )
    return api


def _approved(api, category="energy_efficiency", *, passed=True, proposal_type=None):
    draft = draft_config_change(category)
    created = api.propose(
        proposal_type or "config_change",
        draft["title"],
        "Проверка исполнителя",
        code_snippet=draft["diff"],
        cycle=9,
        extra={
            **draft,
            "verification": {"ran": True, "passed": passed, "cycles": 5},
        },
    )
    proposal_id = created["proposal_id"]
    assert api.decide(proposal_id, approved=True)["decided"] is True
    return proposal_id, draft


def _status(api, proposal_id):
    return api._get(proposal_id)["status"]


def test_managed_success_persists_without_mutating_global_config(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    proposal_id, draft = _approved(api)
    overrides = {}
    source = Path(project_root()) / "config" / "simulation_config.py"
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    result = api.apply_approved(proposal_id, overrides)

    assert result["applied"] is True
    assert result["status"] == "implemented"
    assert overrides[draft["attr"]] == draft["new"]
    assert getattr(LR_CONFIG, draft["attr"]) == draft["old"]
    assert _status(api, proposal_id) == "implemented"
    assert api.load_config_overrides() == {draft["attr"]: draft["new"]}
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before

    reopened = _api(tmp_path, monkeypatch, life_id=api.life_id)
    assert reopened.load_config_overrides() == {draft["attr"]: draft["new"]}
    export = json.loads(
        Path(created_path(api, proposal_id)).read_text(encoding="utf-8")
    )
    assert export["status"] == "implemented"
    assert export["execution"]["ok"] is True


def created_path(api, proposal_id):
    return api.database.life_dir / api.EXPORT_DIR / f"{proposal_id}.json"


def test_standalone_success_survives_reopen(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch, standalone=True)
    proposal_id, draft = _approved(api, category="memory_management")
    overrides = {}

    result = api.apply_approved(proposal_id, overrides)

    assert result["applied"] is True
    assert overrides == {draft["attr"]: draft["new"]}
    reopened = _api(tmp_path, monkeypatch, standalone=True)
    assert reopened.load_config_overrides() == {draft["attr"]: draft["new"]}


def test_rebind_restores_only_selected_life(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    life_a = api.life_id
    proposal_id, draft = _approved(api)
    overrides = {}
    assert api.apply_approved(proposal_id, overrides)["applied"] is True

    api.rebind(str(uuid4()))
    assert api.load_config_overrides() == {}
    api.rebind(life_a)
    assert api.load_config_overrides() == {draft["attr"]: draft["new"]}


def test_stale_proposal_is_rejected_without_runtime_change(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    proposal_id, draft = _approved(api)
    overrides = {draft["attr"]: 0.77}

    result = api.apply_approved(proposal_id, overrides)

    assert result["applied"] is False
    assert "не совпадает" in result["reason"]
    assert overrides == {draft["attr"]: 0.77}
    assert _status(api, proposal_id) == "approved"
    assert api._get(proposal_id)["execution"]["ok"] is False
    assert api.load_config_overrides() == {}


def test_tampered_candidate_is_rejected(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    draft = draft_config_change("energy_efficiency")
    created = api.propose(
        "config_change",
        draft["title"],
        "Подмена",
        extra={
            **draft,
            "new": 0.51,
            "verification": {"ran": True, "passed": True},
        },
    )
    proposal_id = created["proposal_id"]
    api.decide(proposal_id, approved=True)
    overrides = {}

    result = api.apply_approved(proposal_id, overrides)

    assert result["applied"] is False
    assert "кандидатом" in result["reason"]
    assert overrides == {}
    assert _status(api, proposal_id) == "approved"


def test_failed_verification_is_not_executable(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    proposal_id, _draft = _approved(api, passed=False)

    result = api.apply_approved(proposal_id, {})

    assert result["applied"] is False
    assert "проба" in result["reason"]
    assert _status(api, proposal_id) == "approved"


def test_non_config_proposal_is_only_approved_not_implemented(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    created = api.propose("method_add", "Новый метод", "Не рычаг")
    proposal_id = created["proposal_id"]
    api.decide(proposal_id, approved=True)

    result = api.apply_approved(proposal_id, {})

    assert result == {
        "applied": False,
        "supported": False,
        "reason": "этот тип предложения не исполняется автоматически",
        "title": "Новый метод",
    }
    assert _status(api, proposal_id) == "approved"


def test_storage_failure_rolls_back_runtime_and_success_status(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    proposal_id, draft = _approved(api)
    overrides = {}
    original = api._store_execution

    def fail_implemented(proposal, expected_status):
        if proposal["status"] == "implemented":
            raise OSError("диск недоступен")
        return original(proposal, expected_status)

    monkeypatch.setattr(api, "_store_execution", fail_implemented)

    result = api.apply_approved(proposal_id, overrides)

    assert result["applied"] is False
    assert "диск недоступен" in result["reason"]
    assert overrides == {}
    proposal = api._get(proposal_id)
    assert proposal["status"] == "approved"
    assert proposal["execution"]["ok"] is False
    assert api.load_config_overrides() == {}


def test_unapproved_proposal_cannot_execute(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    draft = draft_config_change("energy_efficiency")
    created = api.propose(
        "config_change",
        draft["title"],
        "Ещё ждёт",
        extra={**draft, "verification": {"ran": True, "passed": True}},
    )

    result = api.apply_approved(created["proposal_id"], {})

    assert result["applied"] is False
    assert "не одобрено" in result["reason"]
    assert _status(api, created["proposal_id"]) == "pending"


def test_sql_export_remains_consistent_after_execution(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    proposal_id, _draft = _approved(api)

    assert api.apply_approved(proposal_id, {})["applied"] is True

    export = created_path(api, proposal_id)
    with closing(api.database.connect(readonly=True)) as connection:
        row = connection.execute(
            "SELECT status FROM architecture_proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
    assert row["status"] == "implemented"
    artifacts = api.database.list_artifacts("architecture_proposal")
    assert artifacts[0]["sha256"] == hashlib.sha256(export.read_bytes()).hexdigest()
    assert api.database.verify_artifacts()["ok"] is True


def test_real_standalone_agent_restores_override_and_body_uses_it(
    tmp_path, monkeypatch
):
    from src.core.agent import DigitalBeing

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    first = DigitalBeing(name="ConfigRestart")
    draft = draft_config_change("energy_efficiency", first)
    created = first.architecture_proposal.propose(
        "config_change",
        draft["title"],
        "Восстановление после повторного открытия",
        extra={**draft, "verification": {"ran": True, "passed": True}},
    )
    proposal_id = created["proposal_id"]
    assert first.architecture_proposal.decide(proposal_id, approved=True)["decided"]
    assert first.architecture_proposal.apply_approved(
        proposal_id, first._safe_config_overrides
    )["applied"]

    second = DigitalBeing(name="ConfigRestart")

    assert second._safe_config_overrides == {draft["attr"]: draft["new"]}
    second.energy = float(LR_CONFIG.ENERGY_MAX)
    second.interoception.state.fatigue = 0.57
    assert float(LR_CONFIG.REST_FATIGUE_THRESHOLD) > 0.57
    assert second._body_needs_rest() is True


def test_tampered_implemented_value_is_not_restored(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch, standalone=True)
    proposal_id, _draft = _approved(api)
    assert api.apply_approved(proposal_id, {})["applied"] is True
    path = Path(api.proposals_dir) / f"{proposal_id}.json"
    proposal = json.loads(path.read_text(encoding="utf-8"))
    proposal["new"] = 0.01
    path.write_text(json.dumps(proposal), encoding="utf-8")

    reopened = _api(tmp_path, monkeypatch, standalone=True)

    assert reopened.load_config_overrides() == {}
