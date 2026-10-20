"""
Тесты Этапа 3.5 — PluginRegistry и Subsystem базовый класс.

Покрывает:
1. Регистрацию / дерегистрацию подсистем.
2. Tick all с приоритетами.
3. Изоляцию ошибок (одна падает — остальные работают).
4. Singleton PluginRegistry.
5. LegacySubsystemAdapter для старых подсистем.
6. attach_existing_subsystem на DigitalBeing.
7. История тиков.
8. teardown_all().
"""

import os
import sys
import io
import time

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Принудительно UTF-8 для вывода (Windows-cmd использует cp1251).
# Только reconfigure, не переустанавливаем sys.stdout/sys.stderr — это ломает
# pytest capture на Python 3.14 / pytest 8.x.
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _reset_global_registry():
    """Каждый тест начинается с чистого реестра."""
    from src.core.subsystem_base import PluginRegistry
    PluginRegistry.reset_global()
    yield
    PluginRegistry.reset_global()


# ============================================================
# 1. Базовый класс Subsystem
# ============================================================

def test_subsystem_creates_with_default_name():
    """Если name не задан — берётся из имени класса."""
    from src.core.subsystem_base import Subsystem
    class MySub(Subsystem):
        pass
    sub = MySub(agent_name="TestAgent")
    assert sub.name == "mysub"
    assert sub.agent_name == "TestAgent"
    assert sub.enabled is True
    assert sub.priority == 100


def test_subsystem_status_returns_dict():
    """status() возвращает JSON-сериализуемый dict."""
    from src.core.subsystem_base import Subsystem
    class MySub(Subsystem):
        name = "test_status"
    sub = MySub(agent_name="X")
    sub.tick(1)
    sub.tick(2)
    s = sub.status()
    assert isinstance(s, dict)
    assert s["name"] == "test_status"
    assert s["enabled"] is True
    assert s["tick_count"] == 2
    assert s["error_count"] == 0


def test_subsystem_tick_records_count():
    """tick() инкрементирует _tick_count и обновляет timestamp."""
    from src.core.subsystem_base import Subsystem
    class MySub(Subsystem):
        name = "test_tick"
    sub = MySub()
    assert sub._tick_count == 0
    sub.tick(1)
    sub.tick(2)
    assert sub._tick_count == 2
    assert sub._last_tick_ts > 0


def test_subsystem_can_be_disabled():
    """set_enabled(False) меняет флаг."""
    from src.core.subsystem_base import Subsystem
    class MySub(Subsystem):
        pass
    sub = MySub()
    assert sub.is_enabled() is True
    sub.set_enabled(False)
    assert sub.is_enabled() is False


def test_subsystem_records_error():
    """_record_error инкрементирует счётчик и записывает последнюю ошибку."""
    from src.core.subsystem_base import Subsystem
    class MySub(Subsystem):
        pass
    sub = MySub()
    try:
        raise ValueError("boom")
    except ValueError as e:
        sub._record_error(e)
    sub._record_error(RuntimeError("again"))
    assert sub._error_count == 2
    assert "RuntimeError" in sub._last_error


# ============================================================
# 2. PluginRegistry
# ============================================================

def test_registry_singleton():
    """get_global() возвращает один и тот же реестр."""
    from src.core.subsystem_base import PluginRegistry
    r1 = PluginRegistry.get_global()
    r2 = PluginRegistry.get_global()
    assert r1 is r2


def test_registry_register_and_get():
    """register() + get() возвращают подсистему."""
    from src.core.subsystem_base import Subsystem, PluginRegistry
    class Foo(Subsystem):
        name = "foo"
    reg = PluginRegistry()
    foo = Foo()
    assert reg.register(foo) is True
    assert reg.get("foo") is foo


def test_registry_register_duplicate_returns_false():
    """Повторная регистрация (без replace) возвращает False."""
    from src.core.subsystem_base import Subsystem, PluginRegistry
    class Bar(Subsystem):
        name = "bar"
    reg = PluginRegistry()
    assert reg.register(Bar()) is True
    assert reg.register(Bar()) is False
    # С replace=True — должно пройти.
    assert reg.register(Bar(), replace=True) is True


def test_registry_register_class_lazy():
    """register_class() — инстанциируется при первом get()."""
    from src.core.subsystem_base import Subsystem, PluginRegistry
    class Lazy(Subsystem):
        name = "lazy"
        def __init__(self, agent_name="unknown", **kw):
            super().__init__(agent_name=agent_name, **kw)
            self.instantiated = True
    reg = PluginRegistry()
    reg.register_class(Lazy)
    assert "lazy" not in reg._items  # ещё не инстанциирован
    inst = reg.get("lazy")
    assert inst is not None
    assert inst.instantiated is True


def test_registry_has_method():
    """has() проверяет наличие по имени (в items и classes)."""
    from src.core.subsystem_base import Subsystem, PluginRegistry
    class A(Subsystem):
        name = "a"
    class B(Subsystem):
        name = "b"
    reg = PluginRegistry()
    reg.register(A())
    reg.register_class(B)
    assert reg.has("a") is True
    assert reg.has("b") is True
    assert reg.has("c") is False


def test_registry_unregister_calls_teardown():
    """unregister() вызывает teardown()."""
    from src.core.subsystem_base import Subsystem, PluginRegistry
    torn_down = {"called": False}
    class T(Subsystem):
        name = "t"
        def teardown(self):
            super().teardown()
            torn_down["called"] = True
    reg = PluginRegistry()
    reg.register(T())
    assert reg.unregister("t") is True
    assert torn_down["called"] is True
    assert reg.has("t") is False


# ============================================================
# 3. Tick по приоритетам и изоляция ошибок
# ============================================================

def test_tick_all_runs_in_priority_order():
    """tick_all() вызывает подсистемы по priority (меньше = раньше)."""
    from src.core.subsystem_base import Subsystem, PluginRegistry
    order = []

    class P1(Subsystem):
        name = "p1"; priority = 50
        def tick(self, cycle, context=None):
            order.append("p1")
    class P2(Subsystem):
        name = "p2"; priority = 10
        def tick(self, cycle, context=None):
            order.append("p2")
    class P3(Subsystem):
        name = "p3"; priority = 30
        def tick(self, cycle, context=None):
            order.append("p3")

    reg = PluginRegistry()
    reg.register(P1())
    reg.register(P2())
    reg.register(P3())
    report = reg.tick_all(1, {})
    assert order == ["p2", "p3", "p1"]
    assert len(report["ok"]) == 3
    assert report["failed"] == []


def test_tick_all_isolates_errors():
    """Ошибка одной подсистемы не валит остальные."""
    from src.core.subsystem_base import Subsystem, PluginRegistry
    class Good(Subsystem):
        name = "good"
        def tick(self, cycle, context=None):
            return {"events": [{"name": "x", "data": 1}]}
    class Bad(Subsystem):
        name = "bad"
        def tick(self, cycle, context=None):
            raise RuntimeError("intended")
    reg = PluginRegistry()
    reg.register(Good())
    reg.register(Bad())
    report = reg.tick_all(1, {})
    assert "good" in report["ok"]
    assert any(f["name"] == "bad" for f in report["failed"])
    assert report["results"]["good"] is not None
    assert report["results"]["bad"] is None


def test_tick_all_skips_disabled():
    """set_enabled(False) — подсистема пропускается."""
    from src.core.subsystem_base import Subsystem, PluginRegistry
    ran = []
    class S(Subsystem):
        name = "s"
        def tick(self, cycle, context=None):
            ran.append(cycle)
    reg = PluginRegistry()
    inst = S()
    inst.set_enabled(False)
    reg.register(inst)
    report = reg.tick_all(5, {})
    assert ran == []
    assert "s" not in report["ok"]


def test_setup_all_calls_setup():
    """setup_all() вызывает setup для всех."""
    from src.core.subsystem_base import Subsystem, PluginRegistry
    setups = []
    class S(Subsystem):
        name = "s"
        def setup(self, context):
            super().setup(context)
            setups.append(context.get("agent_name"))
    reg = PluginRegistry()
    reg.register(S())
    count = reg.setup_all({"agent_name": "Ctx"})
    assert count == 1
    assert setups == ["Ctx"]


def test_teardown_all_calls_teardown():
    """teardown_all() вызывает teardown для всех."""
    from src.core.subsystem_base import Subsystem, PluginRegistry
    torn = []
    class S1(Subsystem):
        name = "teardown_s1"
        def teardown(self):
            super().teardown()
            torn.append(self.name)
    class S2(Subsystem):
        name = "teardown_s2"
        def teardown(self):
            super().teardown()
            torn.append(self.name)
    reg = PluginRegistry()
    reg.register(S1())
    reg.register(S2())
    count = reg.teardown_all()
    assert count == 2
    assert sorted(torn) == ["teardown_s1", "teardown_s2"]


# ============================================================
# 4. status_all и история
# ============================================================

def test_status_all_summary():
    """status_all() возвращает сводный снимок."""
    from src.core.subsystem_base import Subsystem, PluginRegistry
    class A(Subsystem):
        name = "a"
    class B(Subsystem):
        name = "b"; priority = 50
    reg = PluginRegistry()
    reg.register(A())
    reg.register(B())
    reg.tick_all(1, {})
    s = reg.status_all()
    assert s["subsystem_count"] == 2
    assert s["enabled_count"] == 2
    assert s["total_ticks"] == 2


def test_history_records_tick_reports():
    """get_history() возвращает последние отчёты tick_all()."""
    from src.core.subsystem_base import Subsystem, PluginRegistry
    class S(Subsystem):
        name = "s"
    reg = PluginRegistry()
    reg.register(S())
    for i in range(5):
        reg.tick_all(i, {})
    hist = reg.get_history(last_n=10)
    assert len(hist) == 5
    assert hist[-1]["cycle"] == 4


# ============================================================
# 5. LegacySubsystemAdapter
# ============================================================

def test_legacy_adapter_wraps_existing_subsystem():
    """Адаптер корректно оборачивает подсистему без Subsystem-родителя."""
    from src.core.subsystem_base import LegacySubsystemAdapter, PluginRegistry

    class _OldStyle:
        def __init__(self):
            self.calls = 0
        def get_status(self):
            return {"old": True}
        def state(self):
            return "running"

    wrapped = _OldStyle()
    adapter = LegacySubsystemAdapter(
        name="legacy_test",
        wrapped=wrapped,
        agent=None,
        priority=99,
    )
    s = adapter.status()
    assert s["wrapped_status"] == {"old": True}
    assert s["state"] == "running"
    assert s["priority"] == 99


def test_attach_existing_subsystem_registers():
    """attach_existing_subsystem() находит атрибут и регистрирует."""
    from src.core.subsystem_base import attach_existing_subsystem, PluginRegistry

    class _FakeAgent:
        name = "TestAgent"
        my_subsystem = type("S", (), {"get_status": lambda self: {"x": 1}})()

    agent = _FakeAgent()
    reg = PluginRegistry()
    adapter = attach_existing_subsystem(agent, "my_subsystem", registry=reg)
    assert adapter is not None
    assert reg.has("my_subsystem") is True
    assert adapter.status()["wrapped_status"] == {"x": 1}


def test_attach_existing_subsystem_returns_none_for_missing():
    """Если атрибута нет — возвращает None, не падает."""
    from src.core.subsystem_base import attach_existing_subsystem, PluginRegistry

    class _FakeAgent:
        name = "TestAgent"

    agent = _FakeAgent()
    reg = PluginRegistry()
    adapter = attach_existing_subsystem(agent, "nonexistent", registry=reg)
    assert adapter is None
    assert reg.list_names() == []


# ============================================================
# 6. Интеграция с DigitalBeing
# ============================================================

def test_digital_being_has_plugin_registry():
    """DigitalBeing имеет plugin_registry и get_subsystems_status."""
    from src.core.agent import DigitalBeing
    from src.core.subsystem_base import PluginRegistry

    agent = DigitalBeing("TestSubject")
    assert hasattr(agent, "plugin_registry")
    assert isinstance(agent.plugin_registry, PluginRegistry)
    # В реестре должно быть как минимум несколько подсистем
    names = agent.plugin_registry.list_names()
    assert len(names) >= 5
    # Обязательные подсистемы
    for must in ("goal_subsystem", "energy_subsystem", "knowledge_subsystem",
                  "soul", "embodiment"):
        assert must in names, f"Подсистема {must} не зарегистрирована"


def test_digital_being_subsystems_status():
    """get_subsystems_status() возвращает JSON-снимок всех подсистем."""
    from src.core.agent import DigitalBeing

    agent = DigitalBeing("TestSubject")
    status = agent.get_subsystems_status()
    assert "subsystem_count" in status
    assert "subsystems" in status
    assert status["subsystem_count"] >= 5
    for sub in status["subsystems"]:
        assert "name" in sub
        assert "enabled" in sub


def test_digital_being_tick_subsystems():
    """tick_subsystems() вызывает tick() через PluginRegistry."""
    from src.core.agent import DigitalBeing

    agent = DigitalBeing("TestSubject")
    report = agent.tick_subsystems(cycle=1)
    assert "ok" in report
    assert "failed" in report
    assert "results" in report
    assert "elapsed_ms" in report
    # Не должно быть ошибок у стандартных подсистем
    assert report["failed"] == [], f"Неожиданные ошибки: {report['failed']}"


def test_digital_being_does_not_break_with_registry_disabled():
    """Если подсистему выключить — tick() пропускает её."""
    from src.core.agent import DigitalBeing

    agent = DigitalBeing("TestSubject")
    sub = agent.plugin_registry.get("soul")
    if sub is not None:
        sub.set_enabled(False)
        report = agent.tick_subsystems(cycle=1)
        assert "soul" not in report["ok"]
        # Включаем обратно для других тестов.
        sub.set_enabled(True)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])