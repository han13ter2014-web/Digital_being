"""
test_checkpoint_serializer.py — тесты для src.core.checkpoint_serializer.

Покрывает:
- Сериализация/десериализация в JSON.
- Поиск последнего чекпоинта.
- Прунинг при превышении лимита.
- Миграции версий (no-op, если schema_version актуален).
- ``build_state_from_agent`` / ``apply_state_to_agent`` — round-trip.
- Обработка отсутствующих/повреждённых файлов.
"""
import json
import os
import tempfile

from src.core.checkpoint_serializer import (
    DEFAULT_CHECKPOINT_DIR,
    CheckpointSerializer,
    apply_state_to_agent,
    build_state_from_agent,
)


# ============================================================
# Утилиты для fake-агента.
# Простой класс — MagicMock конфликтует с property (у DigitalBeing
# knowledge_base и energy — это property, и присваивать нельзя).
# ============================================================
# sentinel для различения «не передано» и «передано None»
_SENTINEL = object()


class FakeNamingDialogue:
    """Простая замена NamingDialogue для тестов."""
    def __init__(self, phase: str = "none", history: list | None = None):
        self.phase = phase
        self._name_history = list(history) if history else []


class FakeAgent:
    """Простой fake-агент — имитирует интерфейс DigitalBeing, нужный
    ``build_state_from_agent`` и ``apply_state_to_agent``.

    Не поднимает настоящий DigitalBeing (это ~1800 строк и десятки подсистем).
    Атрибуты — обычные Python-атрибуты (не property), чтобы тесты могли
    присваивать их напрямую.
    """

    def __init__(
        self,
        *,
        name: str = "TestAgent",
        cycle_count: int = 0,
        energy: float = 100.0,
        intelligence: int = 1,
        knowledge_base: dict | None = None,
        goals: list | None = None,
        active_goal: dict | None = _SENTINEL,
        completed_goals: int = 0,
        success_streak: int = 0,
        goal_progress: dict | None = None,
        learned_facts: set | None = None,
        known_definitions: dict | None = None,
        open_questions: list | None = None,
        naming_dialogue: FakeNamingDialogue | None = None,
    ):
        self.name = name
        self.cycle_count = cycle_count
        self.energy = energy
        self.intelligence = intelligence
        self.completed_goals = completed_goals
        self.success_streak = success_streak
        self.knowledge_base = (
            knowledge_base if knowledge_base is not None else {"python": "язык"}
        )
        self.goals = goals if goals is not None else [
            {"id": 1, "title": "Test goal", "status": "active"},
        ]
        # sentinel: различаем «не передано» (default → первая цель) и «передано None»
        self.active_goal = (
            active_goal if active_goal is not _SENTINEL else self.goals[0]
        )
        self._goal_progress = goal_progress if goal_progress is not None else {}
        self._learned_facts = learned_facts if learned_facts is not None else set()
        self._known_definitions = (
            known_definitions if known_definitions is not None else {}
        )
        self._open_questions = open_questions if open_questions is not None else []
        self.naming_dialogue = naming_dialogue or FakeNamingDialogue()


def make_fake_agent(**kwargs) -> FakeAgent:
    """Удобная фабрика (имя сохранено для читаемости тестов)."""
    return FakeAgent(**kwargs)


# ============================================================
# build_state_from_agent
# ============================================================
def test_build_state_includes_schema_version():
    """state содержит schema_version (нужно для миграций)."""
    agent = make_fake_agent()
    state = build_state_from_agent(agent)
    assert "schema_version" in state
    assert isinstance(state["schema_version"], int)


def test_build_state_includes_all_core_fields():
    """state содержит все базовые поля."""
    agent = make_fake_agent(
        name="Alpha",
        cycle_count=42,
        energy=87.5,
        intelligence=3,
        completed_goals=2,
        success_streak=5,
    )
    state = build_state_from_agent(agent)
    assert state["name"] == "Alpha"
    assert state["cycle_count"] == 42
    assert state["energy"] == 87.5
    assert state["intelligence"] == 3
    assert state["completed_goals"] == 2
    assert state["success_streak"] == 5
    assert "saved_at" in state


def test_build_state_active_goal_title_only():
    """active_goal сохраняется как title (строка), а не как dict."""
    agent = make_fake_agent(
        active_goal={"id": 1, "title": "Python basics", "status": "active"},
    )
    state = build_state_from_agent(agent)
    assert state["active_goal"] == "Python basics"


def test_build_state_handles_no_active_goal():
    """active_goal=None — корректно сохраняется как None."""
    agent = make_fake_agent(active_goal=None)
    state = build_state_from_agent(agent)
    assert state["active_goal"] is None


def test_build_state_naming_phase():
    """naming_dialogue_phase сохраняется."""
    nd = FakeNamingDialogue(phase="accepted", history=["Lucy", "Max"])
    agent = make_fake_agent(naming_dialogue=nd)
    state = build_state_from_agent(agent)
    assert state["naming_dialogue_phase"] == "accepted"
    assert state["naming_dialogue_history"] == ["Lucy", "Max"]


def test_build_state_open_questions_metadata():
    """Открытые вопросы сохраняются как метаданные (без explorations)."""
    agent = make_fake_agent(
        open_questions=[
            {
                "text": "что такое любовь?",
                "source": "user",
                "started_at": 5,
                "last_explored_at": 7,
                "explorations": [{"cycle": 6, "thought": "...", "strategy": "x"}],
                "max_explorations": 5,
                "hint": None,
                "answered": False,
                "answer": None,
            },
        ],
    )
    state = build_state_from_agent(agent)
    assert len(state["open_questions"]) == 1
    q = state["open_questions"][0]
    assert q["text"] == "что такое любовь?"
    assert q["explorations_count"] == 1  # посчитали
    # Полные explorations НЕ сохраняются
    assert "explorations" not in q


# ============================================================
# apply_state_to_agent
# ============================================================
def test_apply_state_restores_basic_fields():
    """apply_state корректно восстанавливает базовые поля."""
    agent = make_fake_agent()
    state = {
        "energy": 200.0,
        "cycle_count": 100,
        "intelligence": 5,
        "completed_goals": 3,
        "success_streak": 7,
        "knowledge_base": {"java": "язык"},
        "goals": [{"id": 1, "title": "X", "status": "active"}],
        "active_goal": "X",
        "_goal_progress": {},
        "_learned_facts": [],
        "_known_definitions": {},
    }
    apply_state_to_agent(agent, state)
    assert agent.energy == 200.0
    assert agent.cycle_count == 100
    assert agent.intelligence == 5
    assert agent.completed_goals == 3
    assert agent.success_streak == 7


def test_apply_state_active_goal_match():
    """active_goal восстанавливается через match по title."""
    agent = make_fake_agent(
        goals=[
            {"id": 1, "title": "Python", "status": "completed"},
            {"id": 2, "title": "Math", "status": "active"},
        ],
        active_goal={"id": 2, "title": "Math", "status": "active"},
    )
    state = {
        "active_goal": "Math",
        "goals": agent.goals,
        "knowledge_base": {},
    }
    apply_state_to_agent(agent, state)
    assert agent.active_goal["title"] == "Math"


def test_apply_state_restores_naming_dialogue():
    """Фаза и история naming-диалога восстанавливаются."""
    nd = FakeNamingDialogue(phase="none", history=[])
    agent = make_fake_agent(naming_dialogue=nd)
    state = {
        "naming_dialogue_phase": "accepted",
        "naming_dialogue_history": ["Lucy", "Max"],
    }
    apply_state_to_agent(agent, state)
    assert nd.phase == "accepted"
    assert "Lucy" in nd._name_history
    assert "Max" in nd._name_history


def test_apply_state_restores_open_questions():
    """Открытые вопросы восстанавливаются (с пустым explorations)."""
    agent = make_fake_agent()
    state = {
        "open_questions": [
            {
                "text": "что такое X?",
                "source": "user",
                "max_explorations": 5,
                "answered": False,
            },
        ],
    }
    apply_state_to_agent(agent, state)
    assert len(agent._open_questions) == 1
    assert agent._open_questions[0]["text"] == "что такое X?"
    assert agent._open_questions[0]["explorations"] == []


def test_round_trip_build_apply():
    """build → apply возвращает эквивалентное состояние."""
    original = make_fake_agent(
        name="Alpha",
        cycle_count=42,
        energy=87.5,
        intelligence=3,
        knowledge_base={"python": "язык программирования"},
        open_questions=[
            {
                "text": "что такое X?",
                "source": "user",
                "started_at": 0,
                "last_explored_at": 0,
                "explorations": [],
                "max_explorations": 5,
                "hint": None,
                "answered": False,
                "answer": None,
            },
        ],
    )
    state = build_state_from_agent(original)
    restored = make_fake_agent(
        knowledge_base={},  # другой, чтобы проверить update
        open_questions=[],
    )
    apply_state_to_agent(restored, state)
    assert restored.cycle_count == 42
    assert restored.energy == 87.5
    assert restored.intelligence == 3
    assert "python" in restored.knowledge_base
    assert len(restored._open_questions) == 1


# ============================================================
# CheckpointSerializer.save/load
# ============================================================
def test_save_creates_file():
    """save() создаёт файл."""
    with tempfile.TemporaryDirectory() as tmp:
        ser = CheckpointSerializer(checkpoint_dir=tmp, max_checkpoints=20)
        state = {"name": "Test", "cycle_count": 1, "energy": 100}
        path = ser.save(state, "Test", 1)
        assert os.path.exists(path)
        assert path.endswith("Test_cycle_1.json")


def test_save_writes_valid_json():
    """save() пишет валидный JSON, который можно прочитать."""
    with tempfile.TemporaryDirectory() as tmp:
        ser = CheckpointSerializer(checkpoint_dir=tmp, max_checkpoints=20)
        state = {
            "name": "Test",
            "cycle_count": 1,
            "energy": 100,
            "schema_version": 1,
        }
        ser.save(state, "Test", 1)
        with open(os.path.join(tmp, "Test_cycle_1.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["name"] == "Test"
        assert data["cycle_count"] == 1


def test_load_returns_state():
    """load() читает state и применяет миграции."""
    with tempfile.TemporaryDirectory() as tmp:
        ser = CheckpointSerializer(checkpoint_dir=tmp, max_checkpoints=20)
        path = os.path.join(tmp, "Test_cycle_5.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "schema_version": 1,
                "name": "Test",
                "cycle_count": 5,
                "energy": 50,
            }, f)
        state = ser.load(path)
        assert state is not None
        assert state["name"] == "Test"
        assert state["cycle_count"] == 5


def test_load_nonexistent_returns_none():
    """load() на несуществующем файле → None."""
    with tempfile.TemporaryDirectory() as tmp:
        ser = CheckpointSerializer(checkpoint_dir=tmp, max_checkpoints=20)
        assert ser.load(os.path.join(tmp, "nope.json")) is None


def test_load_corrupted_returns_none():
    """load() на битом JSON → None (не падает)."""
    with tempfile.TemporaryDirectory() as tmp:
        ser = CheckpointSerializer(checkpoint_dir=tmp, max_checkpoints=20)
        path = os.path.join(tmp, "Test_cycle_1.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("not a json {{{")
        assert ser.load(path) is None


# ============================================================
# Поиск чекпоинтов
# ============================================================
def test_get_latest_path_returns_newest():
    """get_latest_path() возвращает чекпоинт с макс. cycle."""
    with tempfile.TemporaryDirectory() as tmp:
        ser = CheckpointSerializer(checkpoint_dir=tmp, max_checkpoints=20)
        ser.save({"x": 1}, "Test", 1)
        ser.save({"x": 2}, "Test", 2)
        ser.save({"x": 5}, "Test", 5)
        path = ser.get_latest_path("Test")
        assert path is not None
        assert path.endswith("Test_cycle_5.json")


def test_get_latest_path_no_checkpoints():
    """get_latest_path() без чекпоинтов → None."""
    with tempfile.TemporaryDirectory() as tmp:
        ser = CheckpointSerializer(checkpoint_dir=tmp, max_checkpoints=20)
        assert ser.get_latest_path("Nobody") is None


def test_list_checkpoints_sorted():
    """list_checkpoints() возвращает отсортированный список."""
    with tempfile.TemporaryDirectory() as tmp:
        ser = CheckpointSerializer(checkpoint_dir=tmp, max_checkpoints=20)
        ser.save({}, "Test", 3)
        ser.save({}, "Test", 1)
        ser.save({}, "Test", 2)
        paths = ser.list_checkpoints("Test")
        cycles = [int(p.split("_")[-1].split(".")[0]) for p in paths]
        assert cycles == [1, 2, 3]


def test_only_target_agent_checkpoints():
    """list_checkpoints() фильтрует по имени агента."""
    with tempfile.TemporaryDirectory() as tmp:
        ser = CheckpointSerializer(checkpoint_dir=tmp, max_checkpoints=20)
        ser.save({}, "Alice", 1)
        ser.save({}, "Bob", 1)
        alice_paths = ser.list_checkpoints("Alice")
        bob_paths = ser.list_checkpoints("Bob")
        assert len(alice_paths) == 1
        assert len(bob_paths) == 1
        assert "Alice" in alice_paths[0]
        assert "Bob" in bob_paths[0]


# ============================================================
# Прунинг
# ============================================================
def test_prune_when_above_limit():
    """При превышении лимита старые удаляются."""
    with tempfile.TemporaryDirectory() as tmp:
        ser = CheckpointSerializer(checkpoint_dir=tmp, max_checkpoints=3)
        # Создаём 5 чекпоинтов
        for i in range(1, 6):
            ser.save({"x": i}, "Test", i)
        # Должно остаться только 3 последних (3, 4, 5)
        paths = ser.list_checkpoints("Test")
        assert len(paths) == 3
        cycles = [int(p.split("_")[-1].split(".")[0]) for p in paths]
        assert cycles == [3, 4, 5]


def test_no_prune_below_limit():
    """При <= лимита ничего не удаляется."""
    with tempfile.TemporaryDirectory() as tmp:
        ser = CheckpointSerializer(checkpoint_dir=tmp, max_checkpoints=10)
        for i in range(1, 4):
            ser.save({"x": i}, "Test", i)
        paths = ser.list_checkpoints("Test")
        assert len(paths) == 3


# ============================================================
# Default dir
# ============================================================
def test_default_checkpoint_dir():
    """DEFAULT_CHECKPOINT_DIR == 'data/checkpoints' (для обратной совместимости)."""
    assert DEFAULT_CHECKPOINT_DIR == "data/checkpoints"


# ============================================================
# Gzip-сжатие (Этап 5: оптимизация)
# ============================================================


def test_gzip_save_load_roundtrip():
    """С gzip=True: save → load возвращает идентичный state."""
    with tempfile.TemporaryDirectory() as tmp:
        ser = CheckpointSerializer(checkpoint_dir=tmp, compress=True)
        agent = FakeAgent()
        state = build_state_from_agent(agent)
        path = ser.save(state, "Test", 1)
        # Файл имеет расширение .json.gz
        assert path.endswith(".json.gz")
        # Содержимое — gzip (магические байты \\x1f\\x8b)
        with open(path, "rb") as f:
            magic = f.read(2)
        assert magic == b"\x1f\x8b", f"Ожидался gzip magic, получено {magic!r}"
        # Load работает и возвращает идентичный state
        loaded = ser.load(path)
        assert loaded is not None
        assert loaded["name"] == state["name"]
        assert loaded["cycle_count"] == state["cycle_count"]


def test_gzip_reduces_size_on_repetitive_data():
    """gzip должен значительно сжимать повторяющиеся данные (knowledge_base)."""
    with tempfile.TemporaryDirectory() as tmp:
        # Сериализатор без сжатия
        ser_plain = CheckpointSerializer(checkpoint_dir=tmp + "/plain", compress=False)
        # Сериализатор с gzip
        ser_gzip = CheckpointSerializer(checkpoint_dir=tmp + "/gz", compress=True)

        # Создаём state с большим повторяющимся контентом (как knowledge_base)
        state = {
            "schema_version": 1,
            "name": "Big",
            "knowledge_base": {f"topic_{i}": "x" * 100 for i in range(500)},
            "cycle_count": 42,
        }
        path_plain = ser_plain.save(state, "Big", 42)
        path_gzip = ser_gzip.save(state, "Big", 42)

        size_plain = os.path.getsize(path_plain)
        size_gzip = os.path.getsize(path_gzip)
        # Ожидаем минимум 5x сжатие (типично 60-80% экономии)
        assert size_gzip < size_plain / 5, (
            f"gzip должен сжимать минимум в 5 раз, но {size_plain} -> {size_gzip} "
            f"(сжатие: {size_plain / max(size_gzip, 1):.1f}x)"
        )


def test_gzip_and_plain_files_coexist():
    """Старые .json и новые .json.gz файлы могут сосуществовать и читаются."""
    with tempfile.TemporaryDirectory() as tmp:
        ser_plain = CheckpointSerializer(checkpoint_dir=tmp, compress=False)
        ser_gzip = CheckpointSerializer(checkpoint_dir=tmp, compress=True)

        state1 = {"x": 1, "name": "Plain"}
        state2 = {"x": 2, "name": "Gzip"}

        path_plain = ser_plain.save(state1, "Agent", 10)
        path_gzip = ser_gzip.save(state2, "Agent", 20)

        assert path_plain.endswith(".json")
        assert path_gzip.endswith(".json.gz")

        # list_checkpoints должен видеть оба файла (по расширениям).
        paths = ser_gzip.list_checkpoints("Agent")
        assert len(paths) == 2
        # Сортировка по номеру цикла.
        cycles = [int(os.path.basename(p).split("_")[-1].split(".")[0]) for p in paths]
        assert cycles == [10, 20]

        # get_latest_path возвращает gzip (он новее).
        latest = ser_gzip.get_latest_path("Agent")
        assert latest is not None
        assert latest.endswith(".json.gz")

        # load работает для обоих.
        loaded_plain = ser_gzip.load(path_plain)
        loaded_gzip = ser_gzip.load(path_gzip)
        assert loaded_plain["x"] == 1
        assert loaded_gzip["x"] == 2


def test_gzip_load_corrupted_returns_none():
    """Повреждённый gzip-файл load() возвращает None, не падает."""
    with tempfile.TemporaryDirectory() as tmp:
        ser = CheckpointSerializer(checkpoint_dir=tmp, compress=True)
        # Создаём битый gzip-файл
        path = os.path.join(tmp, "Test_cycle_1.json.gz")
        with open(path, "wb") as f:
            f.write(b"\x1f\x8b not really gzip data")  # магические байты есть, но дальше мусор
        # load не должен бросать исключение
        result = ser.load(path)
        assert result is None


def test_gzip_compress_level_clamped():
    """compress_level ограничивается в диапазоне 1-9."""
    with tempfile.TemporaryDirectory() as tmp:
        ser_low = CheckpointSerializer(checkpoint_dir=tmp, compress=True, compress_level=0)
        ser_high = CheckpointSerializer(checkpoint_dir=tmp, compress=True, compress_level=99)
        assert ser_low.compress_level == 1
        assert ser_high.compress_level == 9


def test_extract_cycle_number_supports_gz():
    """_extract_cycle_number корректно работает с .json.gz."""
    from src.core.checkpoint_serializer import _extract_cycle_number
    assert _extract_cycle_number("Alpha_cycle_42.json", "Alpha_cycle_") == "42"
    assert _extract_cycle_number("Alpha_cycle_42.json.gz", "Alpha_cycle_") == "42"
    assert _extract_cycle_number("Beta_cycle_100.json.gz", "Beta_cycle_") == "100"
