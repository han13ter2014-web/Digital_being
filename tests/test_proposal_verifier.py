"""Тесты «Эволюция-1»: проба — изолированная проверка предложения.

Верификатор поднимает отдельный процесс Python с временной папкой
данных: рабочая data/ и живой стенд не затрагиваются. Вердикт честный:
«пройдена» только при чистом завершении рабочего процесса.
"""

from src.evolution.proposal_verifier import verify_config_change


def test_verify_benign_config_change_passes():
    """Безобидный рычаг: проба собирается и проживает такт эволюции."""
    result = verify_config_change("FORGETTING_INTERVAL", 400, cycles=1)
    assert result["ran"] is True
    assert result["passed"] is True, result["log_tail"]


def test_verify_unknown_attr_fails_honestly():
    """Неизвестный рычаг: проба не пройдена, а не «сошлось»."""
    result = verify_config_change("NO_SUCH_TUNABLE", 1, cycles=1)
    assert result["ran"] is True
    assert result["passed"] is False
    assert "неизвестный рычаг" in result["log_tail"]
