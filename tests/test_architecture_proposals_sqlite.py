"""Этап 5C: SQL — источник предложений архитектуры; JSON — зарегистрированный экспорт."""

from contextlib import closing
import hashlib
import json
from pathlib import Path
from uuid import uuid4


from src.core.subsystems.architecture_proposal import ArchitectureProposal
from src.core.subsystems.will_registry import WillRegistry


def _api(tmp_path, monkeypatch, life_id=None):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    if life_id is None:
        life_id = str(uuid4())
    api = ArchitectureProposal(registry=WillRegistry(agent_name="t"), life_id=life_id)
    return api, api.database, life_id


def _rows(database):
    with closing(database.connect(readonly=True)) as connection:
        return connection.execute(
            "SELECT id, status, decided_at, decision_note, payload_json "
            "FROM architecture_proposals ORDER BY created_at, id"
        ).fetchall()


def test_propose_stores_sql_row_and_registered_export(tmp_path, monkeypatch):
    api, database, life_id = _api(tmp_path, monkeypatch)

    created = api.propose(
        "config_change",
        "REST_FATIGUE_THRESHOLD",
        "Обоснование",
        code_snippet="diff",
        cycle=7,
        extra={"category": "energy_efficiency"},
    )

    assert created["created"] is True
    rows = _rows(database)
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    payload = json.loads(rows[0]["payload_json"])
    assert payload["category"] == "energy_efficiency"
    assert payload["cycle"] == 7

    export = Path(created["filepath"])
    assert export.is_file()
    assert database.life_dir.resolve() in export.resolve().parents
    assert export.read_text(encoding="utf-8").startswith("{")
    artifacts = database.list_artifacts("architecture_proposal")
    assert len(artifacts) == 1
    assert artifacts[0]["metadata"]["proposal_id"] == created["proposal_id"]
    assert artifacts[0]["sha256"] == hashlib.sha256(export.read_bytes()).hexdigest()
    assert database.verify_artifacts()["ok"] is True


def test_pending_and_decision_survive_reopen(tmp_path, monkeypatch):
    api, database, life_id = _api(tmp_path, monkeypatch)
    created = api.propose("method_add", "Заголовок", "Описание")
    proposal_id = created["proposal_id"]

    reopened = ArchitectureProposal(
        registry=WillRegistry(agent_name="t2"), life_id=life_id
    )
    pending = reopened.list_pending()
    assert [p["id"] for p in pending] == [proposal_id]
    assert reopened.latest_pending()["id"] == proposal_id

    decided = reopened.decide(proposal_id, approved=True, note="хороший lever")
    assert decided == {"decided": True, "status": "approved", "title": "Заголовок"}

    final = ArchitectureProposal(
        registry=WillRegistry(agent_name="t3"), life_id=life_id
    )
    assert final.list_pending() == []
    rows = _rows(database)
    assert rows[0]["status"] == "approved"
    assert rows[0]["decision_note"] == "хороший lever"
    assert rows[0]["decided_at"] is not None
    export = json.loads(Path(created["filepath"]).read_text(encoding="utf-8"))
    assert export["status"] == "approved"
    assert export["decision_note"] == "хороший lever"

    assert final.decide(proposal_id, approved=False) == {
        "decided": False,
        "reason": "уже решено: approved",
    }
    assert final.decide("prop_missing", approved=True) == {
        "decided": False,
        "reason": "не найдено",
    }


def test_enrich_updates_sql_and_resyncs_export(tmp_path, monkeypatch):
    api, database, _life_id = _api(tmp_path, monkeypatch)
    created = api.propose("config_change", "Т", "Д")

    enriched = api.enrich(
        created["proposal_id"],
        {"verification": {"passed": True, "cycles": 5}, "diff": "--- a\n+++ b"},
    )
    assert enriched == {
        "enriched": True,
        "proposal_id": created["proposal_id"],
    }
    row = _rows(database)[0]
    payload = json.loads(row["payload_json"])
    assert payload["verification"] == {"passed": True, "cycles": 5}
    assert payload["diff"] == "--- a\n+++ b"

    export = Path(created["filepath"])
    content = export.read_text(encoding="utf-8")
    assert '"passed": true' in content
    artifacts = database.list_artifacts("architecture_proposal")
    assert artifacts[0]["sha256"] == hashlib.sha256(export.read_bytes()).hexdigest()
    assert database.verify_artifacts()["ok"] is True

    assert api.enrich("prop_missing", {"x": 1}) == {
        "enriched": False,
        "reason": "не найдено",
    }
    assert api.enrich(created["proposal_id"], {}) == {
        "enriched": False,
        "reason": "нет данных",
    }


def test_tampered_export_does_not_become_truth(tmp_path, monkeypatch):
    api, database, life_id = _api(tmp_path, monkeypatch)
    created = api.propose("module_add", "Т", "Д")
    proposal_id = created["proposal_id"]
    export = Path(created["filepath"])

    forged = json.loads(export.read_text(encoding="utf-8"))
    forged["status"] = "approved"
    export.write_text(json.dumps(forged), encoding="utf-8")

    assert [p["id"] for p in api.list_pending()] == [proposal_id]

    decided = api.decide(proposal_id, approved=False, note="нет")
    assert decided["status"] == "rejected"
    restored = json.loads(export.read_text(encoding="utf-8"))
    assert restored["status"] == "rejected"
    artifacts = database.list_artifacts("architecture_proposal")
    assert artifacts[0]["sha256"] == hashlib.sha256(export.read_bytes()).hexdigest()
    assert database.verify_artifacts()["ok"] is True


def test_rebind_switches_to_authoritative_database(tmp_path, monkeypatch):
    api, _database, life_a = _api(tmp_path, monkeypatch)
    created = api.propose("behavior_change", "Т", "Д")

    life_b = str(uuid4())
    api.rebind(life_b)
    assert api.database.life_id == life_b
    assert api.list_pending() == []

    again = ArchitectureProposal(registry=WillRegistry(agent_name="x"), life_id=life_a)
    assert [p["id"] for p in again.list_pending()] == [created["proposal_id"]]


def test_import_legacy_registers_without_deleting_originals(tmp_path, monkeypatch):
    api, database, _life_id = _api(tmp_path, monkeypatch)
    legacy_dir = tmp_path / "architecture_proposals"
    legacy_dir.mkdir()
    pending = {
        "id": "prop_20261101_000000_1",
        "type": "config_change",
        "title": "Старое",
        "description": "Описание",
        "code_snippet": "",
        "status": "pending",
        "created_at": "2026-11-01T00:00:00",
        "cycle": 3,
    }
    decided = {
        "id": "prop_20261102_000000_2",
        "type": "method_add",
        "title": "Решённое",
        "description": "",
        "code_snippet": "",
        "status": "rejected",
        "created_at": "2026-11-02T00:00:00",
        "cycle": 4,
    }
    (legacy_dir / "prop_20261101_000000_1.json").write_text(
        json.dumps(pending, ensure_ascii=False), encoding="utf-8"
    )
    (legacy_dir / "prop_20261102_000000_2.json").write_text(
        json.dumps(decided, ensure_ascii=False), encoding="utf-8"
    )
    (legacy_dir / "not_a_proposal.json").write_text("[]", encoding="utf-8")
    before = {
        path.name: path.read_bytes() for path in sorted(legacy_dir.glob("*.json"))
    }

    report = api.import_legacy()

    assert report["imported"] == 2
    assert len(report["errors"]) == 1
    rows = _rows(database)
    assert [row["status"] for row in rows] == ["pending", "rejected"]
    registered = database.list_artifacts("architecture_proposal")
    assert len(registered) == 2
    assert all(item["metadata"]["source"] == "legacy_import" for item in registered)
    for name, content in before.items():
        assert (legacy_dir / name).read_bytes() == content

    again = api.import_legacy()
    assert again["imported"] == 0 and again["skipped"] == 2
    assert len(_rows(database)) == 2


def test_standalone_file_mode_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    api = ArchitectureProposal(registry=WillRegistry(agent_name="s"))

    created = api.propose("config_change", "Т", "Д", code_snippet="diff")
    assert created["created"] is True
    legacy_file = tmp_path / "architecture_proposals" / f"{created['proposal_id']}.json"
    assert legacy_file.is_file()
    assert not (tmp_path / "lives").exists()

    assert [p["id"] for p in api.list_pending()] == [created["proposal_id"]]
    enriched = api.enrich(created["proposal_id"], {"verification": {"passed": False}})
    assert enriched["enriched"] is True
    on_disk = json.loads(legacy_file.read_text(encoding="utf-8"))
    assert on_disk["verification"] == {"passed": False}

    decided = api.decide(created["proposal_id"], approved=True)
    assert decided["decided"] is True
    on_disk = json.loads(legacy_file.read_text(encoding="utf-8"))
    assert on_disk["status"] == "approved"
    assert api.list_pending() == []

    report = api.import_legacy()
    assert report["errors"] == ["режим без UUID жизни управляется файлами"]


def test_standalone_same_second_proposals_do_not_overwrite_decision(
    tmp_path, monkeypatch
):
    """Одна секунда и цикл не должны превращать два предложения в одно."""
    from datetime import datetime as RealDateTime

    class SameSecond(RealDateTime):
        @classmethod
        def now(cls, tz=None):
            return RealDateTime(2026, 11, 12, 12, 0, 0, tzinfo=tz)

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "src.core.subsystems.architecture_proposal.datetime", SameSecond
    )
    api = ArchitectureProposal(registry=WillRegistry(agent_name="s"))

    first = api.propose("config_change", "Первое", "Первое описание", cycle=7)
    assert api.decide(first["proposal_id"], approved=True)["decided"] is True
    first_path = Path(first["filepath"])

    second = api.propose("method_add", "Второе", "Второе описание", cycle=7)

    assert second["created"] is True
    assert second["proposal_id"] != first["proposal_id"]
    first_saved = json.loads(first_path.read_text(encoding="utf-8"))
    assert first_saved["title"] == "Первое"
    assert first_saved["status"] == "approved"
    second_saved = json.loads(Path(second["filepath"]).read_text(encoding="utf-8"))
    assert second_saved["title"] == "Второе"
    assert second_saved["status"] == "pending"


def test_managed_agent_creation_binds_sql_backend(tmp_path, monkeypatch):
    from src.core.agent import DigitalBeing

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing(name="ManagedProposals", profile_managed=True)
    api = agent.architecture_proposal
    assert api.database is not None
    assert api.database.life_id == agent.life_id
    created = api.propose("method_add", "Т", "Д")
    assert created["created"] is True
    assert [p["id"] for p in api.list_pending()] == [created["proposal_id"]]
    assert agent.life_guard.database is not api.database
