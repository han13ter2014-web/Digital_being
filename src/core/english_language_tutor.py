"""Ограниченный наставник английского языка с независимыми упражнениями.

Разрешения и материалы отделены от русского LanguageTutor. Источник остаётся
неисполняемым карантином; только строгий offline rule pack создаёт упражнения.
Ответ вычисляется из правила до сравнения с эталоном. Подтверждение относится
к одному источнику и не меняет обычный диалог, Core, память или разрешения.
"""

from __future__ import annotations

import hashlib
import math
import re
from copy import deepcopy

from src.core.language_tutor import normalize_source_url

SCHEMA_VERSION = 1
PARSER_VERSION = 1
LANGUAGE_ID = "en"
RULE_PLURAL_S = "en_regular_plural_s"
RULE_I_CAPITALIZATION = "en_pronoun_i_capitalization"
MATERIAL_STATUSES = frozenset({"quarantined", "parsed", "rejected"})
PACK_STATUSES = frozenset({"candidate", "source_verified", "needs_review"})
EXERCISE_KINDS = frozenset({"practice", "held_out"})
EXERCISE_STATUSES = frozenset({"pending", "correct", "incorrect"})
MAX_SOURCES = 20
MAX_SOURCE_REQUESTS = 8
MAX_MATERIALS = 20
MAX_RULE_PACKS = 20
MAX_EXERCISES = 12
MAX_TEXT_CHARS = 4000
MAX_TITLE_CHARS = 200
MAX_RULE_CHARS = 240
MAX_REQUEST_REASON_CHARS = 240
HELD_OUT_SUCCESSES_REQUIRED = 2

_RULES = {
    RULE_PLURAL_S: {
        "lesson": "lesson: en regular plural s",
        "rule": "for the supported regular nouns in this lesson, form the plural by adding -s",
    },
    RULE_I_CAPITALIZATION: {
        "lesson": "lesson: en pronoun i",
        "rule": "capitalize the standalone first-person pronoun i",
    },
}
_EXERCISE_RE = re.compile(
    r"^([A-Za-z]+(?: [A-Za-z]+){0,7})\s*->\s*" r"([A-Za-z]+(?: [A-Za-z]+){0,7})$"
)
_PLURAL_WORD_RE = re.compile(r"^[a-z]+$")
_I_PROMPT_RE = re.compile(r"^i(?: [a-z]+){1,7}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _fail(path, message):
    raise ValueError(f"{path}: {message}")


def _cycle(value, path="cycle"):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(path, "expected a nonnegative integer")


def _text(value, path, limit, *, nonempty=True):
    if (
        not isinstance(value, str)
        or len(value) > limit
        or nonempty
        and not value.strip()
    ):
        _fail(path, "expected a bounded string")


def _normalized_rule(text) -> str:
    return " ".join(str(text or "").lower().strip(" .!…").split())


def _source_request_id(url: str) -> str:
    digest = hashlib.sha256(f"en\n{url}".encode("utf-8")).hexdigest()
    return f"en-request-{digest[:16]}"


def _content_hash(url, text) -> str:
    return hashlib.sha256(f"en\n{url}\n{text}".encode("utf-8")).hexdigest()


def _rule_pack_id(content_hash: str) -> str:
    return f"en-pack-{content_hash[:16]}"


def _validate_prompt(rule_id, prompt, expected, path) -> None:
    match = _EXERCISE_RE.fullmatch(f"{prompt} -> {expected}")
    if match is None:
        _fail(path, "invalid English exercise format")
    if rule_id == RULE_PLURAL_S:
        if (
            _PLURAL_WORD_RE.fullmatch(prompt) is None
            or _PLURAL_WORD_RE.fullmatch(expected) is None
        ):
            _fail(path, "plural exercise expects lowercase single nouns")
    elif rule_id == RULE_I_CAPITALIZATION:
        if _I_PROMPT_RE.fullmatch(prompt) is None:
            _fail(path, "capitalization exercise expects a standalone initial i")
    else:
        _fail(path, "unsupported rule")


def _solve_rule(rule_id, prompt) -> str:
    """Получить ответ только из правила и prompt, не из source expected."""
    if rule_id == RULE_PLURAL_S:
        if _PLURAL_WORD_RE.fullmatch(prompt) is None:
            raise ValueError("unsupported plural prompt")
        return f"{prompt}s"
    if rule_id == RULE_I_CAPITALIZATION:
        if _I_PROMPT_RE.fullmatch(prompt) is None:
            raise ValueError("unsupported capitalization prompt")
        return f"I{prompt[1:]}"
    raise ValueError("unsupported rule")


def _validate_exercise(exercise, path, *, rule_id, pack_id):
    if not isinstance(exercise, dict):
        _fail(path, "expected a dictionary")
    _text(exercise.get("exercise_id"), f"{path}.exercise_id", 160)
    if exercise.get("kind") not in EXERCISE_KINDS:
        _fail(f"{path}.kind", "unknown exercise kind")
    prompt = exercise.get("prompt")
    expected = exercise.get("expected")
    _text(prompt, f"{path}.prompt", 160)
    _text(expected, f"{path}.expected", 160)
    _validate_prompt(rule_id, prompt, expected, path)
    status = exercise.get("status")
    if status not in EXERCISE_STATUSES:
        _fail(f"{path}.status", "unknown exercise status")
    attempts = exercise.get("attempts")
    if isinstance(attempts, bool) or not isinstance(attempts, int):
        _fail(f"{path}.attempts", "expected an integer")
    submitted = exercise.get("submitted")
    solved_cycle = exercise.get("solved_cycle")
    if status == "pending":
        if attempts != 0 or submitted is not None or solved_cycle is not None:
            _fail(path, "pending exercise cannot have an attempt")
        return
    if attempts != 1:
        _fail(path, "completed exercise allows one attempt")
    _text(submitted, f"{path}.submitted", 160)
    _cycle(solved_cycle, f"{path}.solved_cycle")
    answer = _solve_rule(rule_id, prompt)
    if submitted != answer:
        _fail(f"{path}.submitted", "answer was not computed by the rule")
    if (status == "correct") != (submitted == expected):
        _fail(f"{path}.status", "result does not match the hidden source answer")


def validate_english_language_tutor(data) -> None:
    """Проверить весь EN snapshot до изменения живого состояния."""
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        _fail("english_language_tutor", "unsupported snapshot")
    if data.get("language_id") != LANGUAGE_ID:
        _fail("english_language_tutor.language_id", "expected en")

    sources = data.get("approved_sources")
    if not isinstance(sources, list) or len(sources) > MAX_SOURCES:
        _fail("english_language_tutor.approved_sources", "expected a bounded list")
    normalized_sources = []
    for index, url in enumerate(sources):
        try:
            normalized = normalize_source_url(url)
        except ValueError as exc:
            _fail(f"english_language_tutor.approved_sources[{index}]", str(exc))
        if normalized != url:
            _fail(
                f"english_language_tutor.approved_sources[{index}]",
                "expected normalized URL",
            )
        normalized_sources.append(normalized)
    if len(set(normalized_sources)) != len(normalized_sources):
        _fail("english_language_tutor.approved_sources", "duplicate source")

    requests = data.get("source_requests", [])
    if not isinstance(requests, list) or len(requests) > MAX_SOURCE_REQUESTS:
        _fail("english_language_tutor.source_requests", "expected a bounded list")
    request_ids = set()
    request_urls = set()
    for index, request in enumerate(requests):
        path = f"english_language_tutor.source_requests[{index}]"
        if not isinstance(request, dict):
            _fail(path, "expected a dictionary")
        try:
            url = normalize_source_url(request.get("url"))
        except ValueError as exc:
            _fail(f"{path}.url", str(exc))
        if url != request["url"]:
            _fail(f"{path}.url", "expected normalized URL")
        request_id = request.get("request_id")
        _text(request_id, f"{path}.request_id", 48)
        if request_id != _source_request_id(url):
            _fail(f"{path}.request_id", "request ID does not match URL")
        if request_id in request_ids or url in request_urls:
            _fail(path, "duplicate source request")
        request_ids.add(request_id)
        request_urls.add(url)
        _text(request.get("reason"), f"{path}.reason", MAX_REQUEST_REASON_CHARS)
        _cycle(request.get("cycle"), f"{path}.cycle")

    materials = data.get("materials")
    if not isinstance(materials, list) or len(materials) > MAX_MATERIALS:
        _fail("english_language_tutor.materials", "expected a bounded list")
    material_by_key = {}
    for index, material in enumerate(materials):
        path = f"english_language_tutor.materials[{index}]"
        if not isinstance(material, dict):
            _fail(path, "expected a dictionary")
        if material.get("language_id") != LANGUAGE_ID:
            _fail(f"{path}.language_id", "expected en")
        try:
            url = normalize_source_url(material.get("url"))
        except ValueError as exc:
            _fail(f"{path}.url", str(exc))
        if url != material["url"]:
            _fail(f"{path}.url", "expected normalized URL")
        _text(material.get("title"), f"{path}.title", MAX_TITLE_CHARS)
        _text(material.get("excerpt"), f"{path}.excerpt", MAX_TEXT_CHARS)
        content_hash = material.get("content_hash")
        if (
            not isinstance(content_hash, str)
            or _HASH_RE.fullmatch(content_hash) is None
        ):
            _fail(f"{path}.content_hash", "expected SHA-256")
        if content_hash != _content_hash(url, material["excerpt"]):
            _fail(f"{path}.content_hash", "content hash does not match excerpt")
        _cycle(material.get("fetched_cycle"), f"{path}.fetched_cycle")
        if material.get("status") not in MATERIAL_STATUSES:
            _fail(f"{path}.status", "unknown material status")
        _text(material.get("reason"), f"{path}.reason", 160, nonempty=False)
        key = (url, content_hash)
        if key in material_by_key:
            _fail(path, "duplicate material")
        material_by_key[key] = material

    packs = data.get("rule_packs")
    if not isinstance(packs, list) or len(packs) > MAX_RULE_PACKS:
        _fail("english_language_tutor.rule_packs", "expected a bounded list")
    pack_ids = set()
    exercise_by_id = {}
    for index, pack in enumerate(packs):
        path = f"english_language_tutor.rule_packs[{index}]"
        if not isinstance(pack, dict):
            _fail(path, "expected a dictionary")
        pack_id = pack.get("pack_id")
        _text(pack_id, f"{path}.pack_id", 160)
        if pack_id in pack_ids:
            _fail(path, "duplicate rule pack")
        pack_ids.add(pack_id)
        if pack.get("language_id") != LANGUAGE_ID:
            _fail(f"{path}.language_id", "expected en")
        rule_id = pack.get("rule_id")
        if rule_id not in _RULES:
            _fail(f"{path}.rule_id", "unsupported rule")
        if pack.get("rule_version") != 1:
            _fail(f"{path}.rule_version", "unsupported rule version")
        if pack.get("parser_version") != 1:
            _fail(f"{path}.parser_version", "unsupported parser version")
        if _normalized_rule(pack.get("rule_text")) != _RULES[rule_id]["rule"]:
            _fail(f"{path}.rule_text", "unsupported rule text")
        _text(pack.get("rule_text"), f"{path}.rule_text", MAX_RULE_CHARS)
        try:
            url = normalize_source_url(pack.get("source_url"))
        except ValueError as exc:
            _fail(f"{path}.source_url", str(exc))
        source_hash = pack.get("source_hash")
        if not isinstance(source_hash, str) or _HASH_RE.fullmatch(source_hash) is None:
            _fail(f"{path}.source_hash", "expected SHA-256")
        material = material_by_key.get((url, source_hash))
        if material is None:
            _fail(f"{path}.source_hash", "pack requires real quarantined material")
        if pack_id != _rule_pack_id(source_hash):
            _fail(f"{path}.pack_id", "pack ID does not match source hash")
        if material["status"] != "parsed":
            _fail(f"{path}.source_hash", "pack requires parsed material")
        status = pack.get("status")
        if status not in PACK_STATUSES:
            _fail(f"{path}.status", "unknown pack status")
        confidence = pack.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            _fail(f"{path}.confidence", "expected a finite number")
        if not math.isfinite(float(confidence)) or not 0.0 <= confidence <= 1.0:
            _fail(f"{path}.confidence", "expected a number in [0, 1]")
        expected_confidence = 0.6 if status == "source_verified" else 0.3
        if confidence != expected_confidence:
            _fail(f"{path}.confidence", "confidence does not match pack status")
        _cycle(pack.get("created_cycle"), f"{path}.created_cycle")
        exercises = pack.get("exercises")
        if not isinstance(exercises, list) or not 3 <= len(exercises) <= MAX_EXERCISES:
            _fail(f"{path}.exercises", "expected a bounded exercise list")
        kinds = []
        prompts = set()
        for exercise_index, exercise in enumerate(exercises):
            exercise_path = f"{path}.exercises[{exercise_index}]"
            _validate_exercise(
                exercise, exercise_path, rule_id=rule_id, pack_id=pack_id
            )
            exercise_id = exercise["exercise_id"]
            if (pack_id, exercise_id) in exercise_by_id:
                _fail(exercise_path, "duplicate exercise")
            exercise_by_id[(pack_id, exercise_id)] = exercise
            if exercise["prompt"] in prompts:
                _fail(exercise_path, "duplicate exercise prompt")
            prompts.add(exercise["prompt"])
            kinds.append(exercise["kind"])
        if kinds.count("practice") < 1 or kinds.count("held_out") < 2:
            _fail(f"{path}.exercises", "practice and two held-out exercises required")
        practice_ok = any(
            item["kind"] == "practice" and item["status"] == "correct"
            for item in exercises
        )
        held_out_ok = sum(
            item["kind"] == "held_out" and item["status"] == "correct"
            for item in exercises
        )
        has_error = any(item["status"] == "incorrect" for item in exercises)
        verified = (
            practice_ok and held_out_ok >= HELD_OUT_SUCCESSES_REQUIRED and not has_error
        )
        if (status == "source_verified") != verified:
            _fail(f"{path}.status", "pack status does not match exercise evidence")
        if status == "needs_review" and not has_error:
            _fail(f"{path}.status", "needs_review requires an incorrect exercise")

    pending = data.get("pending_exercise")
    if pending is not None:
        if not isinstance(pending, dict):
            _fail("english_language_tutor.pending_exercise", "expected a dictionary")
        key = (pending.get("pack_id"), pending.get("exercise_id"))
        exercise = exercise_by_id.get(key)
        if exercise is None or exercise["status"] != "pending":
            _fail(
                "english_language_tutor.pending_exercise",
                "unknown or completed exercise",
            )


class EnglishLanguageTutor:
    """Отдельные EN-разрешения, карантин и проверяемые учебные попытки."""

    def __init__(self) -> None:
        self.approved_sources = []
        self.source_requests = []
        self.materials = []
        self.rule_packs = []
        self.pending_exercise = None

    def approve_source(self, url) -> dict:
        url = normalize_source_url(url)
        if url in self.approved_sources:
            self._remove_source_request(url)
            return {"status": "already_approved", "url": url}
        if len(self.approved_sources) >= MAX_SOURCES:
            return {"status": "limit_reached", "url": url}
        self.approved_sources.append(url)
        self._remove_source_request(url)
        return {"status": "approved", "url": url}

    def _remove_source_request(self, url: str) -> None:
        self.source_requests = [
            request for request in self.source_requests if request["url"] != url
        ]

    def request_source(self, url, reason, *, cycle) -> dict:
        """Создать EN-карточку намерения без разрешения и загрузки."""
        url = normalize_source_url(url)
        _text(reason, "reason", MAX_REQUEST_REASON_CHARS)
        _cycle(cycle)
        if url in self.approved_sources:
            return {"status": "already_approved", "url": url}
        request_id = _source_request_id(url)
        for request in self.source_requests:
            if request["request_id"] == request_id:
                return {"status": "already_requested", **deepcopy(request)}
        if len(self.source_requests) >= MAX_SOURCE_REQUESTS:
            return {"status": "limit_reached", "url": url}
        request = {
            "request_id": request_id,
            "url": url,
            "reason": str(reason).strip(),
            "cycle": cycle,
            "language_id": LANGUAGE_ID,
        }
        self.source_requests.append(request)
        return {"status": "requested", **deepcopy(request)}

    def resolve_source_request(self, request_id, *, approved: bool) -> dict:
        _text(request_id, "request_id", 48)
        request = next(
            (item for item in self.source_requests if item["request_id"] == request_id),
            None,
        )
        if request is None:
            return {"status": "not_found", "request_id": request_id}
        if not approved:
            self.source_requests.remove(request)
            return {"status": "rejected", **deepcopy(request)}
        result = self.approve_source(request["url"])
        return {**deepcopy(request), **result}

    def revoke_source(self, url) -> dict:
        url = normalize_source_url(url)
        if url not in self.approved_sources:
            return {"status": "not_approved", "url": url}
        self.approved_sources.remove(url)
        return {"status": "revoked", "url": url}

    def ingest(self, url, *, cycle, fetcher) -> dict:
        """Получить только предварительно разрешённый EN-источник."""
        url = normalize_source_url(url)
        _cycle(cycle)
        if url not in self.approved_sources:
            return {"status": "permission_denied", "url": url}
        if not callable(fetcher):
            return {"status": "fetcher_unavailable", "url": url}
        try:
            page = fetcher(url)
        except Exception as exc:
            return {"status": "fetch_error", "url": url, "error": type(exc).__name__}
        if not isinstance(page, dict) or page.get("found") is not True:
            error = (
                str(page.get("error") or "not_found") if isinstance(page, dict) else ""
            )
            return {"status": "fetch_failed", "url": url, "error": error[:80]}
        title = page.get("title")
        text = page.get("extract")
        try:
            _text(title, "title", MAX_TITLE_CHARS)
            _text(text, "extract", MAX_TEXT_CHARS)
        except ValueError:
            return {"status": "invalid_material", "url": url}
        return self._store_material(url, title, text, cycle)

    def _store_material(self, url, title, text, cycle) -> dict:
        content_hash = _content_hash(url, text)
        for material in self.materials:
            if material["content_hash"] == content_hash and material["url"] == url:
                return {"status": "duplicate", "url": url, "content_hash": content_hash}
        if len(self.materials) >= MAX_MATERIALS:
            return {"status": "limit_reached", "url": url}
        material = {
            "url": url,
            "title": str(title),
            "language_id": LANGUAGE_ID,
            "content_hash": content_hash,
            "excerpt": str(text),
            "fetched_cycle": cycle,
            "status": "quarantined",
            "reason": "",
        }
        self.materials.append(material)
        try:
            pack = self._parse_rule_pack(url, content_hash, text, cycle)
        except ValueError as exc:
            material["status"] = "rejected"
            material["reason"] = str(exc)[:160]
            return {"status": "rejected", "url": url, "error": material["reason"]}
        if len(self.rule_packs) >= MAX_RULE_PACKS:
            material["status"] = "rejected"
            material["reason"] = "rule pack limit reached"
            return {"status": "limit_reached", "url": url}
        self.rule_packs.append(pack)
        material["status"] = "parsed"
        return {
            "status": "quarantined_rule_pack",
            "url": url,
            "pack_id": pack["pack_id"],
            "rule_id": pack["rule_id"],
            "exercises": len(pack["exercises"]),
        }

    @staticmethod
    def _parse_rule_pack(url, content_hash, text, cycle) -> dict:
        lines = [" ".join(line.strip().split()) for line in str(text).splitlines()]
        normalized = [line.lower() for line in lines]
        rule_id = next(
            (
                candidate
                for candidate, definition in _RULES.items()
                if definition["lesson"] in normalized
            ),
            None,
        )
        if rule_id is None:
            raise ValueError("unsupported English lesson")
        if normalized.count(_RULES[rule_id]["lesson"]) != 1:
            raise ValueError("one explicit English lesson is required")

        def one_value(prefix):
            matches = [line for line in normalized if line.startswith(prefix)]
            if len(matches) != 1:
                raise ValueError(f"one {prefix.strip()} field is required")
            return matches[0].split(":", 1)[1].strip()

        if one_value("language:") != LANGUAGE_ID:
            raise ValueError("English lesson requires language en")
        if one_value("rule_id:") != rule_id:
            raise ValueError("rule ID does not match lesson")
        if one_value("rule_version:") != "1":
            raise ValueError("unsupported rule version")
        rule_text = one_value("rule:")
        if _normalized_rule(rule_text) != _RULES[rule_id]["rule"]:
            raise ValueError("unsupported rule text")

        pack_id = _rule_pack_id(content_hash)
        exercises = []
        prompts = set()
        for line in lines:
            lowered = line.lower()
            kind = None
            payload = ""
            if lowered.startswith("practice:"):
                kind = "practice"
                payload = line.split(":", 1)[1].strip()
            elif lowered.startswith("held_out:"):
                kind = "held_out"
                payload = line.split(":", 1)[1].strip()
            if kind is None:
                continue
            match = _EXERCISE_RE.fullmatch(payload)
            if match is None:
                raise ValueError("invalid English exercise format")
            prompt, expected = match.groups()
            _validate_prompt(rule_id, prompt, expected, "exercise")
            if prompt in prompts:
                raise ValueError("duplicate exercise")
            prompts.add(prompt)
            exercises.append(
                {
                    "exercise_id": f"{pack_id}:ex:{len(exercises)}",
                    "kind": kind,
                    "prompt": prompt,
                    "expected": expected,
                    "status": "pending",
                    "attempts": 0,
                    "submitted": None,
                    "solved_cycle": None,
                }
            )
            if len(exercises) > MAX_EXERCISES:
                raise ValueError("too many exercises")
        kinds = [exercise["kind"] for exercise in exercises]
        if kinds.count("practice") < 1 or kinds.count("held_out") < 2:
            raise ValueError("practice and two held-out exercises required")
        return {
            "pack_id": pack_id,
            "language_id": LANGUAGE_ID,
            "rule_id": rule_id,
            "rule_version": 1,
            "parser_version": PARSER_VERSION,
            "rule_text": rule_text,
            "source_url": url,
            "source_hash": content_hash,
            "status": "candidate",
            "confidence": 0.3,
            "created_cycle": cycle,
            "exercises": exercises,
        }

    def begin_exercise(self) -> dict:
        """Показать задание без эталона; повтор сохраняет текущее задание."""
        if self.pending_exercise is not None:
            pack_id = self.pending_exercise["pack_id"]
            exercise_id = self.pending_exercise["exercise_id"]
            for pack in self.rule_packs:
                if pack["pack_id"] != pack_id:
                    continue
                for exercise in pack["exercises"]:
                    if exercise["exercise_id"] == exercise_id:
                        return {
                            "status": "exercise",
                            "pack_id": pack_id,
                            "exercise_id": exercise_id,
                            "rule_id": pack["rule_id"],
                            "kind": exercise["kind"],
                            "prompt": exercise["prompt"],
                        }
        for pack in self.rule_packs:
            if pack["status"] == "needs_review":
                continue
            for exercise in pack["exercises"]:
                if exercise["status"] != "pending":
                    continue
                self.pending_exercise = {
                    "pack_id": pack["pack_id"],
                    "exercise_id": exercise["exercise_id"],
                }
                return {
                    "status": "exercise",
                    "pack_id": pack["pack_id"],
                    "exercise_id": exercise["exercise_id"],
                    "rule_id": pack["rule_id"],
                    "kind": exercise["kind"],
                    "prompt": exercise["prompt"],
                }
        return {"status": "no_exercise"}

    def solve_pending(self, *, cycle) -> dict:
        """Выполнить одну попытку; эталон становится виден только после неё."""
        _cycle(cycle)
        if self.pending_exercise is None:
            return {"status": "no_pending"}
        pack_id = self.pending_exercise["pack_id"]
        exercise_id = self.pending_exercise["exercise_id"]
        pack = next(item for item in self.rule_packs if item["pack_id"] == pack_id)
        exercise = next(
            item for item in pack["exercises"] if item["exercise_id"] == exercise_id
        )
        answer = _solve_rule(pack["rule_id"], exercise["prompt"])
        correct = answer == exercise["expected"]
        exercise["attempts"] = 1
        exercise["status"] = "correct" if correct else "incorrect"
        exercise["submitted"] = answer
        exercise["solved_cycle"] = cycle
        self.pending_exercise = None
        if not correct:
            pack["status"] = "needs_review"
        elif exercise["kind"] == "held_out":
            self._refresh_pack_status(pack)
        return {
            "status": "correct" if correct else "incorrect",
            "pack_id": pack_id,
            "exercise_id": exercise_id,
            "answer": answer,
            "expected": exercise["expected"],
            "kind": exercise["kind"],
            "pack_status": pack["status"],
        }

    @staticmethod
    def _refresh_pack_status(pack) -> None:
        exercises = pack["exercises"]
        practice_ok = any(
            item["kind"] == "practice" and item["status"] == "correct"
            for item in exercises
        )
        held_out_ok = sum(
            item["kind"] == "held_out" and item["status"] == "correct"
            for item in exercises
        )
        has_error = any(item["status"] == "incorrect" for item in exercises)
        if practice_ok and held_out_ok >= HELD_OUT_SUCCESSES_REQUIRED and not has_error:
            pack["status"] = "source_verified"
            pack["confidence"] = 0.6

    def get_status(self) -> dict:
        current = None
        if self.pending_exercise is not None:
            for pack in self.rule_packs:
                if pack["pack_id"] != self.pending_exercise["pack_id"]:
                    continue
                for exercise in pack["exercises"]:
                    if exercise["exercise_id"] == self.pending_exercise["exercise_id"]:
                        current = {
                            "pack_id": pack["pack_id"],
                            "rule_id": pack["rule_id"],
                            **{
                                key: exercise[key]
                                for key in ("exercise_id", "kind", "prompt")
                            },
                        }
        return {
            "language_id": LANGUAGE_ID,
            "approved_sources": len(self.approved_sources),
            "source_requests": len(self.source_requests),
            "materials": len(self.materials),
            "rule_packs": len(self.rule_packs),
            "source_verified": sum(
                pack["status"] == "source_verified" for pack in self.rule_packs
            ),
            "pending": self.pending_exercise is not None,
            "pending_exercise": current,
        }

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "language_id": LANGUAGE_ID,
            "approved_sources": list(self.approved_sources),
            "source_requests": deepcopy(self.source_requests),
            "materials": deepcopy(self.materials),
            "rule_packs": deepcopy(self.rule_packs),
            "pending_exercise": deepcopy(self.pending_exercise),
        }

    def load_from(self, data) -> None:
        validate_english_language_tutor(data)
        self.approved_sources = list(data["approved_sources"])
        self.source_requests = deepcopy(data.get("source_requests", []))
        self.materials = deepcopy(data["materials"])
        self.rule_packs = deepcopy(data["rule_packs"])
        self.pending_exercise = deepcopy(data["pending_exercise"])
