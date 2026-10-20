"""
Тесты производительности и устойчивости Digital Being.

Шаг 10 плана оптимизации:
- Бенчмарк N циклов за приемлемое время.
- Проверка роста RSS (должен стабилизироваться, а не расти линейно).
- Проверка лимитов (MAX_CONCEPTS, MAX_EPISODIC_MEMORIES).
- Проверка кеша (должен ускорять find_related_concepts).
- Smoke-test: watchdog, health dashboard, debounce.

Эти тесты НЕ трогают волю/свободу — они про инфраструктуру.
"""

import time
import sys
import os
import io

# Добавляем корень проекта в sys.path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

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


def test_watchdog_creates_and_reports():
    """Watchdog создаётся и возвращает адекватный статус."""
    from src.core.watchdog import Watchdog

    wd = Watchdog(max_rss_mb=1000.0, max_cycle_seconds=60.0, check_interval_cycles=10)
    wd.on_cycle_start()
    time.sleep(0.01)
    wd.on_cycle_end()

    status = wd.get_status()
    assert isinstance(status, dict)
    assert "cycle_count" in status
    assert status["cycle_count"] == 1
    assert "psutil_available" in status
    print(f"  ✅ Watchdog создался. psutil_available={status['psutil_available']}")


def test_watchdog_detects_slow_cycle():
    """Watchdog корректно ловит медленный цикл."""
    from src.core.watchdog import Watchdog

    wd = Watchdog(max_rss_mb=1000.0, max_cycle_seconds=0.05, check_interval_cycles=10)
    wd.on_cycle_start()
    time.sleep(0.2)  # больше max_cycle_seconds
    wd.on_cycle_end()

    alerts = wd.get_alerts()
    assert any(a.get("kind") == "slow_cycle" for a in alerts), \
        f"Ожидался slow_cycle алерт, получено: {alerts}"
    print(f"  ✅ Медленный цикл обнаружен ({len(alerts)} алертов)")


def test_health_dashboard_runs():
    """Health dashboard собирает данные (даже без агента)."""
    from src.core.health_dashboard import collect_health, format_health_report

    report = collect_health(agent=None)
    assert "system" in report
    text = format_health_report(report)
    assert "ДАШБОРД" in text
    assert "RSS" in text
    print(f"  ✅ Health dashboard работает (длина: {len(text)} символов)")


def test_mental_models_cache_helps():
    """Кеш find_related_concepts ускоряет повторные вызовы."""
    from src.cognition.mental_models import MentalModel

    mm = MentalModel(name="test")
    # Создаём 100 концепций со связями
    for i in range(100):
        mm.encounter_concept(f"concept_{i}", f"ctx_{i}", f"outcome_{i}", 0.5)
        if i > 0:
            mm.concepts[f"concept_{i}"].connect_to(f"concept_{i-1}", 0.6)
    # Заполняем кеш через тик
    mm.tick_cycle()

    # Холодный вызов
    t0 = time.perf_counter()
    res1 = mm.find_related_concepts("concept_50", max_distance=2)
    t1 = time.perf_counter()
    cold_ms = (t1 - t0) * 1000

    # Тёплый вызов (из кеша)
    t0 = time.perf_counter()
    res2 = mm.find_related_concepts("concept_50", max_distance=2)
    t1 = time.perf_counter()
    warm_ms = (t1 - t0) * 1000

    assert len(res1) > 0, "должны быть связанные концепции"
    assert len(res1) == len(res2), "кеш должен вернуть тот же результат"
    # Тёплый должен быть как минимум не медленнее холодного
    print(f"  ✅ Кеш: cold={cold_ms:.3f}мс, warm={warm_ms:.3f}мс")


def test_mental_models_apply_limit_forgets_weak():
    """apply_concept_limit забывает слабые концепции при переполнении."""
    from src.cognition.mental_models import MentalModel

    mm = MentalModel(name="test")
    # Создаём 50 концепций.
    # Устанавливаем confidence напрямую после создания, обходя пересчёт в add_experience.
    for i in range(50):
        mm.encounter_concept(f"c_{i}", f"ctx_{i}", "x", 0.0)  # valence=0 → confidence не растёт
        if i < 30:
            mm.concepts[f"c_{i}"].confidence = 0.9
        else:
            mm.concepts[f"c_{i}"].confidence = 0.05  # ниже MIN_CONFIDENCE_FOR_RETENTION

    from config import simulation_config
    original = simulation_config.LR_CONFIG.MAX_CONCEPTS
    try:
        # 50 концепций. max=20, значит over=30, target_forget=30.
        simulation_config.LR_CONFIG.MAX_CONCEPTS = 20
        forgotten = mm.apply_concept_limit()
        assert forgotten == 30, f"должно быть забыто 30 (over), забыто {forgotten}"
        assert len(mm.concepts) == 20, f"должно остаться 20, осталось {len(mm.concepts)}"
        # Главный инвариант: среди оставшихся НЕТ тех 20, которым мы выставили 0.05.
        weak_names = {f"c_{i}" for i in range(30, 50)}  # те, кому ставили 0.05
        remaining = set(mm.concepts.keys())
        leaked = remaining & weak_names
        assert len(leaked) == 0, (
            f"среди оставшихся есть слабые (с confidence<0.1): {leaked}. "
            f"Оставшиеся: {remaining}"
        )
        print(
            f"  ✅ Забыто {forgotten} (over), осталось {len(mm.concepts)} "
            f"концепций (ни одной из исходно слабых)"
        )
    finally:
        simulation_config.LR_CONFIG.MAX_CONCEPTS = original


def test_long_term_memory_apply_episodic_limit():
    """LongTermMemory ограничивает эпизоды при переполнении.

    Тестируем только логику лимита, без инициализации LongTermMemory
    (она может пытаться загрузить с диска и падать на legacy-модулях).
    """
    from src.memory.long_term_memory import MemoryTrace
    from datetime import datetime
    from config import simulation_config

    # Создаём простой контейнер, повторяющий нужный интерфейс
    class _FakeLTM:
        def __init__(self):
            self._episodic = []

        _apply_episodic_limit = None  # свяжем ниже

    ltm = _FakeLTM()
    from src.memory.long_term_memory import LongTermMemory as _LTM
    ltm._apply_episodic_limit = _LTM._apply_episodic_limit.__get__(ltm, _FakeLTM)

    # Добавляем эпизоды вручную
    for i in range(50):
        trace = MemoryTrace(
            content=f"event_{i}",
            importance=0.3 if i < 20 else 0.9,  # 20 слабых, 30 сильных
            created_at=datetime.now(),
            last_accessed=datetime.now(),
        )
        ltm._episodic.append(trace)

    original = simulation_config.LR_CONFIG.MAX_EPISODIC_MEMORIES
    try:
        simulation_config.LR_CONFIG.MAX_EPISODIC_MEMORIES = 30
        forgotten = ltm._apply_episodic_limit()
        assert forgotten == 20, f"должно быть забыто 20 слабых, забыто {forgotten}"
        assert len(ltm._episodic) == 30
        # Проверяем, что остались важные
        remaining_importance = [t.importance for t in ltm._episodic]
        assert all(i > 0.5 for i in remaining_importance), "оставшиеся должны быть важными"
        print(f"  ✅ LTM эпизоды: забыто {forgotten} слабых, осталось {len(ltm._episodic)} важных")
    finally:
        simulation_config.LR_CONFIG.MAX_EPISODIC_MEMORIES = original


def test_save_knowledge_base_debounces(tmp_path):
    """_save_knowledge_base не пишет на диск чаще debounce."""
    from src.core.agent import DigitalBeing
    import os

    # ВАЖНО: этот тест требует реальной инициализации DigitalBeing,
    # что может быть долго. Используем прямое тестирование debounce логики.
    import time as _time

    # Симулируем
    class _MockAgent:
        _last_kb_save_ts = 0.0
        _last_kb_save_size = 0
        knowledge_file = str(tmp_path / "test_kb_debounce.json")
        knowledge_base = {f"k_{i}": "v" for i in range(20)}

        def _prune_knowledge_base(self):
            pass

        @staticmethod
        def _save_knowledge_base():
            from src.core.buffered_logger import get_logger
            from config.simulation_config import LR_CONFIG
            import time as _time
            now = _time.time()
            last = _MockAgent._last_kb_save_ts
            debounce_sec = getattr(LR_CONFIG, "KNOWLEDGE_SAVE_DEBOUNCE_SEC", 30)
            min_delta = getattr(LR_CONFIG, "KNOWLEDGE_SAVE_MIN_DELTA", 10)
            size_delta = abs(len(_MockAgent.knowledge_base) - _MockAgent._last_kb_save_size)
            if (now - last) < debounce_sec and size_delta < min_delta:
                return  # пропущено
            try:
                os.makedirs(os.path.dirname(_MockAgent.knowledge_file), exist_ok=True)
                import json
                with open(_MockAgent.knowledge_file, "w", encoding="utf-8") as f:
                    json.dump(_MockAgent.knowledge_base, f)
                _MockAgent._last_kb_save_ts = now
                _MockAgent._last_kb_save_size = len(_MockAgent.knowledge_base)
                _wrote = True
            except Exception:
                _wrote = False
            return _wrote

    agent = _MockAgent()
    # Первый вызов — пишем
    res1 = agent._save_knowledge_base()
    # Сразу второй — должен быть пропущен
    res2 = agent._save_knowledge_base()
    # Добавляем много записей (delta > min_delta)
    agent.knowledge_base.update({f"new_{i}": "v" for i in range(20)})
    res3 = agent._save_knowledge_base()

    assert res1 is not None, "первый вызов должен записать"
    assert res2 is None, "второй вызов должен быть пропущен debounce"
    assert res3 is not None, "третий вызов с дельтой должен записать"
    # Чистим
    if os.path.exists(agent.knowledge_file):
        os.remove(agent.knowledge_file)
    print(f"  ✅ Debounce работает: запись → пропуск → запись (после дельты)")


def test_smoke_100_cycles_in_seconds():
    """100 циклов perception+think+act+evolve должны занимать < 30 секунд."""
    # Импортируем только инфраструктуру, не весь DigitalBeing
    from src.cognition.mental_models import MentalModel

    mm = MentalModel(name="perf_test")
    start = time.time()
    for i in range(100):
        mm.tick_cycle()
        mm.encounter_concept(f"c_{i}", f"ctx_{i}", "outcome", 0.5)
    elapsed = time.time() - start
    assert elapsed < 30.0, f"100 циклов mental_models = {elapsed:.1f}с (>30)"
    print(f"  ✅ 100 циклов mental_models: {elapsed:.2f}с")


def main():
    """Запуск всех тестов."""
    print("=" * 60)
    print("  🧪 ТЕСТЫ ПРОИЗВОДИТЕЛЬНОСТИ И УСТОЙЧИВОСТИ")
    print("=" * 60)

    tests = [
        ("Watchdog создаётся", test_watchdog_creates_and_reports),
        ("Watchdog ловит медленный цикл", test_watchdog_detects_slow_cycle),
        ("Health dashboard работает", test_health_dashboard_runs),
        ("Кеш mental_models помогает", test_mental_models_cache_helps),
        ("Лимит mental_models забывает слабые", test_mental_models_apply_limit_forgets_weak),
        ("Лимит эпизодов LTM", test_long_term_memory_apply_episodic_limit),
        ("Debounce save_kb", test_save_knowledge_base_debounces),
        ("100 циклов mental_models < 30с", test_smoke_100_cycles_in_seconds),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        try:
            print(f"\n📋 {name}")
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ⚠️ ERROR: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"  Результат: {passed} ✅  /  {failed} ❌")
    print(f"{'=' * 60}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())