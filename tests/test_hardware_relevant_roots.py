"""12A: только владельческий инвентарь relevant roots, без выборки дисков."""

from copy import deepcopy

import pytest

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.hardware_relevant_roots import RelevantRootRegistry


def test_default_registry_has_only_data_and_does_not_create_directories(tmp_path):
    data_root = tmp_path / "private" / "data"

    registry = RelevantRootRegistry(data_root=data_root)

    assert registry.root_ids == ("data",)
    assert registry.path_for("data") == str(data_root.absolute())
    assert not data_root.exists()
    status = registry.status()
    assert status["mode"] == "owner_allowlist"
    assert status["root_count"] == 1
    assert status["roots"][0]["root_id"] == "data"
    assert status["roots"][0]["origin"] == "existing_data"
    assert "checkpoints" in status["roots"][0]["write_scopes"]
    assert "creative_artifacts" in status["roots"][0]["write_scopes"]
    assert str(tmp_path) not in str(status)


def test_owner_ids_are_stable_across_order_and_status_is_sanitized(tmp_path):
    archive = tmp_path / "private archive"
    drafts = tmp_path / "private drafts"
    first = RelevantRootRegistry(
        {"archive": archive, "drafts": drafts}, data_root=tmp_path / "data"
    )
    second = RelevantRootRegistry(
        {"drafts": drafts, "archive": archive}, data_root=tmp_path / "data"
    )

    assert first.status() == second.status()
    assert first.root_ids == ("data", "archive", "drafts")
    assert first.path_for("archive") == second.path_for("archive")
    assert str(archive) not in str(first.status())
    assert str(drafts) not in repr(first.status())
    assert all(
        row["write_scopes"] == []
        for row in first.status()["roots"]
        if row["origin"] == "owner_allowlist"
    )

    status = first.status()
    status["roots"][0]["write_scopes"].append("tampered")
    status["roots"].append({"root_id": "tampered"})
    assert first.status()["root_count"] == 3
    assert "tampered" not in str(first.status())


def test_removed_and_unknown_roots_have_no_substitute(tmp_path):
    data_root = tmp_path / "data"
    archive = tmp_path / "archive"
    registry = RelevantRootRegistry({"archive": archive}, data_root=data_root)
    assert registry.path_for("archive") == str(archive.absolute())

    removed = RelevantRootRegistry(data_root=data_root)

    assert removed.path_for("archive") is None
    assert removed.path_for("unknown") is None
    assert removed.root_ids == ("data",)
    assert removed.path_for("data") == str(data_root.absolute())


@pytest.mark.parametrize(
    "allowlist",
    [
        ["not", "a", "mapping"],
        {"": "somewhere"},
        {"Bad ID": "somewhere"},
        {"data": "override"},
        {"archive": ""},
        {"archive": None},
        {"archive": "bad\x00path"},
    ],
)
def test_invalid_allowlist_is_rejected_without_path_disclosure(allowlist, tmp_path):
    with pytest.raises(ValueError) as captured:
        RelevantRootRegistry(allowlist, data_root=tmp_path / "data")

    assert str(tmp_path) not in str(captured.value)


def test_duplicate_and_nested_roots_are_rejected(tmp_path):
    data_root = tmp_path / "data"
    for allowlist in (
        {"archive": data_root},
        {"archive": data_root / "nested"},
        {"first": tmp_path / "same", "second": tmp_path / "same"},
        {"first": tmp_path / "parent", "second": tmp_path / "parent" / "child"},
    ):
        with pytest.raises(ValueError):
            RelevantRootRegistry(allowlist, data_root=data_root)


def test_allowlist_is_bounded(tmp_path):
    allowlist = {f"root_{index}": tmp_path / f"root_{index}" for index in range(8)}

    with pytest.raises(ValueError, match="at most 8"):
        RelevantRootRegistry(allowlist, data_root=tmp_path / "data")


def test_restart_uses_current_owner_allowlist_without_checkpoint_migration(
    monkeypatch, tmp_path
):
    source = DigitalBeing(name="RelevantRootsSource")
    initial = build_state_from_agent(source)
    assert source.hardware_interoception.relevant_roots.root_ids == ("data",)
    assert "relevant_roots" not in source.hardware_interoception.to_checkpoint()

    archive = tmp_path / "private archive"
    monkeypatch.setattr(
        "config.simulation_config.SIM_CONFIG.HARDWARE_RELEVANT_ROOTS",
        {"archive": str(archive)},
    )
    restored = DigitalBeing(name="RelevantRootsRestored")
    apply_state_to_agent(restored, deepcopy(initial))

    assert restored.hardware_interoception.relevant_roots.path_for("archive") == str(
        archive.absolute()
    )
    assert "relevant_roots" not in restored.hardware_interoception.to_checkpoint()
    assert str(archive) not in str(
        restored.hardware_interoception.relevant_roots.status()
    )

    monkeypatch.setattr(
        "config.simulation_config.SIM_CONFIG.HARDWARE_RELEVANT_ROOTS", {}
    )
    removed = DigitalBeing(name="RelevantRootsRemoved")
    apply_state_to_agent(removed, deepcopy(initial))
    assert removed.hardware_interoception.relevant_roots.path_for("archive") is None
    assert removed.hardware_interoception.relevant_roots.root_ids == ("data",)
