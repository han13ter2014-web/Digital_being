"""
Тесты Этапа 4 — экспериментальные фичи (3.2, 3.6, 3.7, 3.8).

Покрывает:
- MetricsCollector (3.6): record, get_history, snapshot, экспорт.
- I18n (3.7): перевод, fallback, интерполяция.
- WebhookManager (3.8): очередь, rate-limit, fallback.
- VoiceRouter (3.2): ConsoleVoiceEngine, capabilities.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
from unittest.mock import patch, MagicMock

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ============================================================
# 3.6 MetricsCollector
# ============================================================

class TestMetricsCollector:
    def test_record_and_get_history(self):
        from src.metrics import MetricsCollector
        mc = MetricsCollector()
        mc.record("energy", 100, cycle=1)
        mc.record("energy", 95, cycle=2)
        mc.record("energy", 90, cycle=3)
        hist = mc.get_history("energy")
        assert len(hist) == 3
        assert hist[0]["value"] == 100
        assert hist[-1]["value"] == 90
        assert hist[1]["cycle"] == 2

    def test_get_current_returns_latest(self):
        from src.metrics import MetricsCollector
        mc = MetricsCollector()
        assert mc.get_current("energy") is None
        mc.record("energy", 100)
        mc.record("energy", 90)
        assert mc.get_current("energy") == 90

    def test_get_stats(self):
        from src.metrics import MetricsCollector
        mc = MetricsCollector()
        for v in [10, 20, 30, 40, 50]:
            mc.record("x", v)
        s = mc.get_stats("x")
        assert s["count"] == 5
        assert s["min"] == 10
        assert s["max"] == 50
        assert s["avg"] == 30.0
        assert s["last"] == 50

    def test_maxlen_caps_history(self):
        from src.metrics import MetricsCollector
        mc = MetricsCollector(maxlen_per_channel=5)
        for i in range(20):
            mc.record("y", float(i))
        assert len(mc.get_history("y")) == 5
        # Первые записи должны быть отброшены, остались последние 5
        values = [e["value"] for e in mc.get_history("y")]
        assert values == [15.0, 16.0, 17.0, 18.0, 19.0]

    def test_increment_records_rate(self):
        from src.metrics import MetricsCollector
        mc = MetricsCollector()
        for _ in range(10):
            mc.increment("events")
        rate = mc.get_rate("events")
        assert rate == 10
        # Канал тоже имеет последнее значение = 1 (amount по умолчанию)
        assert mc.get_current("events") == 1.0

    def test_snapshot(self):
        from src.metrics import MetricsCollector
        mc = MetricsCollector()
        mc.record("a", 1.0)
        mc.record("b", 2.0)
        snap = mc.snapshot()
        assert "channels" in snap
        assert "a" in snap["channels"]
        assert "b" in snap["channels"]
        assert "agent_name" in snap

    def test_export_json(self, tmp_path):
        from src.metrics import MetricsCollector
        mc = MetricsCollector(persist_dir=str(tmp_path), agent_name="TestExport")
        mc.record("energy", 100)
        mc.record("energy", 90)
        path = mc.export_json()
        assert os.path.isfile(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "channels" in data
        assert "energy" in data["channels"]

    def test_list_channels(self):
        from src.metrics import MetricsCollector
        mc = MetricsCollector()
        mc.record("foo", 1)
        mc.record("bar", 2)
        names = mc.list_channels()
        assert "foo" in names
        assert "bar" in names
        # default channels тоже есть
        assert "energy" in names


# ============================================================
# 3.7 I18n
# ============================================================

class TestI18n:
    def test_default_language_loads(self):
        from src.metrics import I18n
        # Создаём с несуществующей директорией — должно работать с пустым dict
        i18n = I18n(locale_dir="/nonexistent")
        assert i18n.get_language() == "ru"

    def test_set_language_creates(self, tmp_path):
        from src.metrics import I18n
        # Создаём два языка в tmp_path
        with open(os.path.join(tmp_path, "ru.json"), "w", encoding="utf-8") as f:
            json.dump({"hello": "Привет"}, f, ensure_ascii=False)
        with open(os.path.join(tmp_path, "en.json"), "w", encoding="utf-8") as f:
            json.dump({"hello": "Hello"}, f)
        i18n = I18n(locale_dir=str(tmp_path))
        assert i18n.t("hello") == "Привет"
        assert i18n.set_language("en") is True
        assert i18n.t("hello") == "Hello"

    def test_fallback_to_default(self, tmp_path):
        from src.metrics import I18n
        with open(os.path.join(tmp_path, "ru.json"), "w", encoding="utf-8") as f:
            json.dump({"hello": "Привет", "bye": "Пока"}, f, ensure_ascii=False)
        with open(os.path.join(tmp_path, "en.json"), "w", encoding="utf-8") as f:
            json.dump({"hello": "Hi"}, f)
        i18n = I18n(locale_dir=str(tmp_path))
        i18n.set_language("en")
        # "bye" нет в en → fallback на ru
        assert i18n.t("bye") == "Пока"

    def test_interpolation(self, tmp_path):
        from src.metrics import I18n
        with open(os.path.join(tmp_path, "ru.json"), "w", encoding="utf-8") as f:
            json.dump({"greeting": "Привет, {name}!"}, f, ensure_ascii=False)
        i18n = I18n(locale_dir=str(tmp_path))
        assert i18n.t("greeting", name="Lucy") == "Привет, Lucy!"

    def test_missing_key_returns_key(self):
        from src.metrics import I18n
        i18n = I18n(locale_dir="/nonexistent")
        assert i18n.t("nonexistent_key") == "nonexistent_key"

    def test_save_translations(self, tmp_path):
        from src.metrics import I18n
        i18n = I18n(locale_dir=str(tmp_path))
        # Сначала сохраняем язык по умолчанию (ru) с тестовым ключом
        i18n.save_translations("ru", {"hello": "Привет"})
        i18n._load_language("ru")  # перечитать
        ok = i18n.save_translations("fr", {"hello": "Bonjour"})
        assert ok is True
        # В текущем языке (ru) — должно быть "Привет"
        assert i18n.t("hello") == "Привет"
        i18n.set_language("fr")
        assert i18n.t("hello") == "Bonjour"
        # Возвращаемся на ru
        i18n.set_language("ru")
        assert i18n.t("hello") == "Привет"

    def test_global_helpers(self, tmp_path):
        from src.metrics.i18n import reset_i18n, set_language, t, get_i18n
        reset_i18n()
        i = get_i18n()
        assert isinstance(i.t("missing"), str)
        # set_language на неизвестный — False
        assert set_language("xx") is False
        reset_i18n()


# ============================================================
# 3.8 Webhooks
# ============================================================

class TestWebhookManager:
    def test_empty_manager_send(self):
        from src.metrics import WebhookManager
        mgr = WebhookManager()
        # Нет ни одного webhook — send возвращает False
        assert mgr.send("hello") is False

    def test_add_remove(self):
        from src.metrics import WebhookManager, TelegramWebhook
        mgr = WebhookManager()
        w = TelegramWebhook(token="fake", chat_id="123")
        mgr.add(w)
        assert "telegram" in mgr.list_webhooks()
        assert mgr.remove("telegram") is True
        assert "telegram" not in mgr.list_webhooks()

    def test_blocking_send_calls_all_webhooks(self):
        from src.metrics import (
            WebhookManager, TelegramWebhook, DiscordWebhook,
        )
        mgr = WebhookManager()
        # Используем моки чтобы не делать реальных HTTP вызовов
        with patch.object(TelegramWebhook, "_do_send", return_value=True), \
             patch.object(DiscordWebhook, "_do_send", return_value=True):
            mgr.add(TelegramWebhook(token="t", chat_id="c"))
            mgr.add(DiscordWebhook(url="https://example.com/hook"))
            ok = mgr.send("hello", blocking=True)
            assert ok is True

    def test_rate_limit(self):
        from src.metrics import WebhookManager, TelegramWebhook
        mgr = WebhookManager(max_per_minute=2)
        with patch.object(TelegramWebhook, "_do_send", return_value=True):
            mgr.add(TelegramWebhook(token="t", chat_id="c"))
            # 2 вызова пройдут
            assert mgr.send("m1", blocking=True) is True
            assert mgr.send("m2", blocking=True) is True
            # 3-й — rate-limited
            assert mgr.send("m3", blocking=True) is False

    def test_async_queue_and_worker(self):
        from src.metrics import WebhookManager, TelegramWebhook
        mgr = WebhookManager(max_per_minute=100)
        with patch.object(TelegramWebhook, "_do_send", return_value=True):
            mgr.add(TelegramWebhook(token="t", chat_id="c"))
            mgr.start()
            try:
                # 5 асинхронных сообщений
                for i in range(5):
                    mgr.send(f"msg_{i}")
                time.sleep(0.5)  # дать worker-у обработать
                status = mgr.status()
                assert status["worker_alive"] is True
            finally:
                mgr.stop()
            status = mgr.status()
            # queue_size должно быть 0 (либо sentinel)
            assert status["queue_size"] == 0 or status["queue_size"] == 1

    def test_webhook_status(self):
        from src.metrics import TelegramWebhook
        w = TelegramWebhook(token="t", chat_id="c")
        w._sent_count = 5
        w._error_count = 1
        s = w.status()
        assert s["name"] == "telegram"
        assert s["sent_count"] == 5
        assert s["error_count"] == 1

    def test_create_default_manager_no_env(self):
        """Без env переменных — менеджер пуст."""
        # Убираем переменные на время теста
        old_token = os.environ.pop("DIGITAL_BEING_TELEGRAM_TOKEN", None)
        old_chat = os.environ.pop("DIGITAL_BEING_TELEGRAM_CHAT_ID", None)
        old_discord = os.environ.pop("DIGITAL_BEING_DISCORD_WEBHOOK_URL", None)
        try:
            from src.metrics.webhooks import create_default_manager
            mgr = create_default_manager()
            assert mgr.list_webhooks() == []
        finally:
            if old_token: os.environ["DIGITAL_BEING_TELEGRAM_TOKEN"] = old_token
            if old_chat: os.environ["DIGITAL_BEING_TELEGRAM_CHAT_ID"] = old_chat
            if old_discord: os.environ["DIGITAL_BEING_DISCORD_WEBHOOK_URL"] = old_discord


# ============================================================
# 3.2 Voice
# ============================================================

class TestVoiceRouter:
    def test_console_engine_capabilities(self):
        """ConsoleVoiceEngine имеет tts но не stt."""
        from src.metrics import ConsoleVoiceEngine
        eng = ConsoleVoiceEngine()
        assert eng.capabilities.get("tts") is True
        assert eng.capabilities.get("stt") is False
        assert eng.name == "console"
        assert eng.enabled is True

    def test_console_engine_disabled_returns_false(self):
        from src.metrics import ConsoleVoiceEngine
        eng = ConsoleVoiceEngine(enabled=False)
        # speak не должен ничего делать если disabled
        assert eng.speak("hi", blocking=True) is False

    def test_router_with_only_console(self):
        from src.metrics import VoiceRouter, ConsoleVoiceEngine
        r = VoiceRouter()
        r.add(ConsoleVoiceEngine())
        assert "console" in r.list_engines()
        # speak без TTS-движка (router пустой) → False, но тут есть console
        # Тест: роутер нашёл движок с tts
        engines_with_tts = [e for e in r._engines if e.capabilities.get("tts")]
        assert len(engines_with_tts) >= 1

    def test_router_status(self):
        from src.metrics import VoiceRouter, ConsoleVoiceEngine
        r = VoiceRouter()
        r.add(ConsoleVoiceEngine())
        s = r.status()
        assert "console" in s["available_tts"]
        assert s["available_stt"] == []  # console не умеет STT

    def test_router_speak_no_tts(self):
        """Если ни один движок не имеет TTS — speak возвращает False."""
        from src.metrics import VoiceRouter
        r = VoiceRouter()
        assert r.speak("text") is False

    def test_router_hear_no_stt(self):
        from src.metrics import VoiceRouter
        r = VoiceRouter()
        assert r.hear(timeout=0.1) is None

    def test_create_default_router_has_console(self):
        from src.metrics import create_default_router
        r = create_default_router(allow_pyttsx3=False, allow_whisper=False)
        assert "console" in r.list_engines()
        assert len(r.list_engines()) == 1

    @pytest.mark.skipif(
        os.environ.get("RUN_PYTTSX_TEST", "0") != "1",
        reason="pyttsx3 init может зависнуть на Windows. Включить: RUN_PYTTSX_TEST=1",
    )
    def test_pyttsx_engine_handles_missing_module(self):
        """PyttsxVoiceEngine без установленного pyttsx3 должен быть безопасным."""
        from src.metrics import PyttsxVoiceEngine
        eng = PyttsxVoiceEngine()
        result = eng.speak("hello", blocking=True)
        assert isinstance(result, bool)


# ============================================================
# Помощник для ручного прогона
# ============================================================

def main():
    """Ручной запуск всех тестов без pytest."""
    print("=" * 60)
    print("  🧪 ТЕСТЫ ЭТАПА 4 (экспериментальные фичи)")
    print("=" * 60)
    import inspect
    import sys as _sys

    classes = [
        TestMetricsCollector,
        TestI18n,
        TestWebhookManager,
        TestVoiceRouter,
    ]
    passed = 0
    failed = 0
    for cls in classes:
        for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
            if not name.startswith("test_"):
                continue
            print(f"\n📋 {cls.__name__}.{name}")
            instance = cls()
            try:
                # Если метод требует capsys/tmp_path — пропускаем в manual mode
                sig = inspect.signature(method)
                needs_fixtures = any(
                    p.default is inspect.Parameter.empty and
                    p.name not in ("self",)
                    for p in sig.parameters.values()
                )
                if needs_fixtures:
                    print(f"  ⏭️  пропущен (требует pytest fixtures)")
                    continue
                method(instance)
                passed += 1
                print(f"  ✅ PASS")
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