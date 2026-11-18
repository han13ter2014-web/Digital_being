"""Явно подтверждённые связи языковых форм с существующими понятиями.

Совпадение предполагаемых переводов связь не создаёт. Запись появляется только
через внутренний ``confirm_link`` с provenance и ограниченной уверенностью.
"""

from __future__ import annotations

import math
from copy import deepcopy

SCHEMA_VERSION = 1
MAX_LINKS = 128
MAX_CONCEPT_ID = 160
MAX_SURFACE_FORM = 80
MAX_PROVENANCE = 160
LANGUAGES = frozenset({"en", "zh"})


def _fail(path, message):
    raise ValueError(f"{path}: {message}")


def _text(value, path, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        _fail(path, "expected a bounded nonempty string")
    return " ".join(value.split())


def _confidence(value, path):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0.0 <= value <= 1.0
    ):
        _fail(path, "expected a number from 0 to 1")
    return float(value)


def _validate_link(link, path):
    if not isinstance(link, dict) or set(link) != {
        "concept_id",
        "surface_form",
        "language_id",
        "provenance",
        "confidence",
    }:
        _fail(path, "expected exactly the versioned link fields")
    concept_id = _text(link.get("concept_id"), f"{path}.concept_id", MAX_CONCEPT_ID)
    surface = _text(link.get("surface_form"), f"{path}.surface_form", MAX_SURFACE_FORM)
    if link.get("language_id") not in LANGUAGES:
        _fail(f"{path}.language_id", "unsupported link language")
    provenance = _text(link.get("provenance"), f"{path}.provenance", MAX_PROVENANCE)
    confidence = _confidence(link.get("confidence"), f"{path}.confidence")
    return {
        "concept_id": concept_id,
        "surface_form": surface,
        "language_id": link["language_id"],
        "provenance": provenance,
        "confidence": confidence,
    }


def validate_language_concept_links(data) -> None:
    if not isinstance(data, dict) or set(data) != {"schema_version", "links"}:
        _fail("language_concept_links", "expected exactly schema_version and links")
    if data.get("schema_version") != SCHEMA_VERSION:
        _fail("language_concept_links.schema_version", "unsupported schema version")
    links = data.get("links")
    if not isinstance(links, list) or len(links) > MAX_LINKS:
        _fail("language_concept_links.links", "expected a bounded list")
    keys = set()
    for index, raw in enumerate(links):
        link = _validate_link(raw, f"language_concept_links.links[{index}]")
        key = (link["language_id"], link["surface_form"].casefold())
        if key in keys:
            _fail("language_concept_links.links", "duplicate surface form")
        keys.add(key)


class LanguageConceptLinks:
    """Небольшой versioned реестр подтверждённых поверхностных форм."""

    def __init__(self):
        self._links = []

    def confirm_link(
        self, concept_id, surface_form, *, language_id="en", provenance, confidence=1.0
    ) -> dict:
        link = _validate_link(
            {
                "concept_id": concept_id,
                "surface_form": surface_form,
                "language_id": language_id,
                "provenance": provenance,
                "confidence": confidence,
            },
            "language_concept_link",
        )
        key = (language_id, link["surface_form"].casefold())
        existing = next(
            (
                item
                for item in self._links
                if (item["language_id"], item["surface_form"].casefold()) == key
            ),
            None,
        )
        if existing is not None:
            if existing != link:
                raise ValueError("language_concept_link: conflicting confirmed link")
            return deepcopy(existing)
        if len(self._links) >= MAX_LINKS:
            raise ValueError("language_concept_link: link limit reached")
        self._links.append(link)
        return deepcopy(link)

    def resolve(self, surface_form, *, language_id="en") -> dict | None:
        normalized = " ".join(str(surface_form or "").split()).casefold()
        if not normalized:
            return None
        link = next(
            (
                item
                for item in self._links
                if item["language_id"] == language_id
                and item["surface_form"].casefold() == normalized
            ),
            None,
        )
        return deepcopy(link) if link is not None else None

    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "links": deepcopy(self._links)}

    def load_from(self, data) -> None:
        validate_language_concept_links(data)
        staged = [
            _validate_link(item, f"language_concept_links.links[{index}]")
            for index, item in enumerate(data["links"])
        ]
        self._links = staged
