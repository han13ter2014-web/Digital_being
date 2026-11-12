"""Сохранность legacy JSON-памяти при ошибке записи."""

import json

from src.memory.long_term_memory import LongTermMemory


def test_legacy_save_failure_preserves_previous_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    memory = LongTermMemory("LegacyAtomic")
    memory.store("прежнее воспоминание")
    memory.save()
    previous = (tmp_path / "memory" / "LegacyAtomic_long_term.json").read_bytes()

    memory.store("новое воспоминание")

    def fail_during_dump(data, stream, **kwargs):
        stream.write('{"partial":')
        raise OSError("disk full")

    monkeypatch.setattr(json, "dump", fail_during_dump)
    memory.save()

    path = tmp_path / "memory" / "LegacyAtomic_long_term.json"
    assert path.read_bytes() == previous
    assert not (tmp_path / "memory" / "LegacyAtomic_long_term.json.tmp").exists()
