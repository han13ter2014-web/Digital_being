"""Локализация представления: коды, неизвестные значения и настройки."""

import json

import pytest

from src.ui import i18n


@pytest.mark.parametrize(
    ("language", "expected"),
    [("ru", "Страх"), ("en", "Fear"), ("zh", "恐惧")],
)
def test_value_labels_support_all_languages(language, expected):
    assert i18n.value_label("fear", language) == expected


def test_russian_dto_label_is_reverse_mapped_without_changing_unknown_values():
    assert i18n.value_label("Страх", "en") == "Fear"
    assert i18n.field_label("Статус", "zh") == "状态"
    assert i18n.value_label("новое_значение", "en") == "новое_значение"
    assert i18n.text("Пользовательский текст", "zh") == "Пользовательский текст"


def test_language_is_normalized_and_unknown_language_falls_back_to_russian():
    assert i18n.normalize_language("zh-CN") == "zh"
    assert i18n.normalize_language("EN") == "en"
    assert i18n.normalize_language("fr") == "ru"
    assert i18n.value_label("joy", "fr") == "Радость"


def test_language_setting_round_trip_preserves_other_settings(tmp_path, monkeypatch):
    settings = tmp_path / "ui_settings.json"
    settings.write_text(
        json.dumps({"language": "ru", "window": {"width": 1200}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(i18n, "data_path", lambda name: tmp_path / name)

    i18n.save_language("zh")

    assert i18n.load_saved_language() == "zh"
    assert json.loads(settings.read_text(encoding="utf-8"))["window"] == {"width": 1200}
    assert not settings.with_suffix(".tmp").exists()


def test_corrupt_language_setting_does_not_prevent_startup(tmp_path, monkeypatch):
    (tmp_path / "ui_settings.json").write_text("не JSON", encoding="utf-8")
    monkeypatch.setattr(i18n, "data_path", lambda name: tmp_path / name)

    assert i18n.load_saved_language() == "ru"


def test_web_payload_contains_action_phrases_and_escapes_html():
    payload = json.loads(i18n.language_json())

    assert payload["actions"]["en"]["explore"] == "Exploring a topic"
    assert payload["actions"]["zh"]["play"] == "正在对弈"
    assert payload["valueCodes"]["Страх"] == "fear"
    assert "<" not in i18n.language_json()
