"""Палитра и формы узлов — единый источник для окна и карты."""

from src.ui import theme


def test_known_node_kinds_have_color_and_shape():
    for kind in ("concept", "intention", "value", "activity", "topic", "forgotten"):
        assert theme.node_color(kind).startswith("#")
        assert theme.node_shape(kind) != "outline" or kind == "forgotten"


def test_unknown_node_kind_is_quiet_not_invented():
    assert theme.node_color("мнимая-сущность") == theme.GREY
    assert theme.node_shape("мнимая-сущность") == "outline"


def test_font_families_are_named():
    assert theme.font_family()
    assert theme.mono_family()


def test_spacing_scale_is_ordered():
    values = [theme.SPACING[key] for key in ("xs", "sm", "md", "lg")]
    assert values == sorted(values)
