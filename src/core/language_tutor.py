"""Ограниченный интернет-наставник русского языка.

Источник разрешается отдельно от общего web-поиска. Страница сохраняется как
неисполняемый карантинный текст; только строгий формат урока «жи/ши» создаёт
упражнения. Ответ вычисляется из правила до сравнения с эталоном. Успех
подтверждает соответствие одному источнику, а не универсальную истину и не
изменяет Core, общий лексикон, цели, память эпизодов или разрешения.
"""

from __future__ import annotations

import hashlib
import math
import re
import urllib.parse
from copy import deepcopy

SCHEMA_VERSION = 1
RULE_ZHI_SHI = "zhi_shi"
CANONICAL_RULE = "после ж и ш пиши и"
MATERIAL_STATUSES = frozenset({"quarantined", "parsed", "rejected"})
LESSON_STATUSES = frozenset({"candidate", "source_verified", "needs_review"})
EXERCISE_KINDS = frozenset({"practice", "held_out"})
EXERCISE_STATUSES = frozenset({"pending", "correct", "incorrect"})
MAX_SOURCES = 20
MAX_SOURCE_REQUESTS = 8
MAX_MATERIALS = 20
MAX_LESSONS = 20
MAX_EXERCISES = 12
MAX_TEXT_CHARS = 4000
MAX_TITLE_CHARS = 200
MAX_URL_CHARS = 600
MAX_RULE_CHARS = 240
MAX_REQUEST_REASON_CHARS = 240
HELD_OUT_SUCCESSES_REQUIRED = 2

_EXERCISE_RE = re.compile(r"^([а-яё]*[жш]\?[а-яё]+)\s*=\s*([а-яё]+)$")
_ANSWER_RE = re.compile(r"^[а-яё]+$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _source_request_id(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return f"request-{digest[:16]}"


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


def normalize_source_url(url) -> str:
    """Каноническая HTTPS-ссылка без fragment и учётных данных."""
    _text(url, "url", MAX_URL_CHARS)
    try:
        parts = urllib.parse.urlsplit(str(url).strip())
        if (
            parts.scheme.lower() != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
        ):
            raise ValueError("url: expected public HTTPS source")
        host = parts.hostname.lower()
        port = parts.port
    except ValueError as exc:
        raise ValueError("url: invalid HTTPS source") from exc
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc += f":{port}"
    return urllib.parse.urlunsplit(
        ("https", netloc, parts.path or "/", parts.query, "")
    )


def _normalized_rule(text) -> str:
    return " ".join(str(text or "").lower().strip(" .!…").split())


def _content_hash(url, text) -> str:
    return hashlib.sha256(f"{url}\n{text}".encode("utf-8")).hexdigest()


def _validate_exercise(exercise, path):
    if not isinstance(exercise, dict):
        _fail(path, "expected a dictionary")
    _text(exercise.get("exercise_id"), f"{path}.exercise_id", 160)
    if exercise.get("kind") not in EXERCISE_KINDS:
        _fail(f"{path}.kind", "unknown exercise kind")
    prompt = exercise.get("prompt")
    expected = exercise.get("expected")
    if (
        not isinstance(prompt, str)
        or _EXERCISE_RE.fullmatch(f"{prompt} = {expected}") is None
    ):
        _fail(path, "invalid жи/ши exercise")
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
    else:
        if attempts != 1:
            _fail(f"{path}.attempts", "completed exercise allows one attempt")
        _text(submitted, f"{path}.submitted", 80)
        if _ANSWER_RE.fullmatch(submitted) is None:
            _fail(f"{path}.submitted", "expected a Russian word")
        _cycle(solved_cycle, f"{path}.solved_cycle")


def validate_language_tutor(data) -> None:
    """Проверить весь снапшот до восстановления живого контура."""
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        _fail("language_tutor", "unsupported snapshot")
    sources = data.get("approved_sources")
    if not isinstance(sources, list) or len(sources) > MAX_SOURCES:
        _fail("language_tutor.approved_sources", "expected a bounded list")
    normalized_sources = []
    for index, url in enumerate(sources):
        try:
            normalized = normalize_source_url(url)
        except ValueError as exc:
            _fail(f"language_tutor.approved_sources[{index}]", str(exc))
        if normalized != url:
            _fail(
                f"language_tutor.approved_sources[{index}]", "expected normalized URL"
            )
        normalized_sources.append(normalized)
    if len(set(normalized_sources)) != len(normalized_sources):
        _fail("language_tutor.approved_sources", "duplicate source")

    requests = data.get("source_requests", [])
    if not isinstance(requests, list) or len(requests) > MAX_SOURCE_REQUESTS:
        _fail("language_tutor.source_requests", "expected a bounded list")
    request_ids = set()
    request_urls = set()
    for index, request in enumerate(requests):
        path = f"language_tutor.source_requests[{index}]"
        if not isinstance(request, dict):
            _fail(path, "expected a dictionary")
        try:
            url = normalize_source_url(request.get("url"))
        except ValueError as exc:
            _fail(f"{path}.url", str(exc))
        if url != request["url"]:
            _fail(f"{path}.url", "expected normalized URL")
        request_id = request.get("request_id")
        _text(request_id, f"{path}.request_id", 40)
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
        _fail("language_tutor.materials", "expected a bounded list")
    material_keys = set()
    for index, material in enumerate(materials):
        path = f"language_tutor.materials[{index}]"
        if not isinstance(material, dict):
            _fail(path, "expected a dictionary")
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
        if key in material_keys:
            _fail(path, "duplicate material")
        material_keys.add(key)

    lessons = data.get("lessons")
    if not isinstance(lessons, list) or len(lessons) > MAX_LESSONS:
        _fail("language_tutor.lessons", "expected a bounded list")
    lesson_ids = set()
    exercise_by_id = {}
    for index, lesson in enumerate(lessons):
        path = f"language_tutor.lessons[{index}]"
        if not isinstance(lesson, dict):
            _fail(path, "expected a dictionary")
        lesson_id = lesson.get("lesson_id")
        _text(lesson_id, f"{path}.lesson_id", 160)
        if lesson_id in lesson_ids:
            _fail(path, "duplicate lesson")
        lesson_ids.add(lesson_id)
        if lesson.get("rule_id") != RULE_ZHI_SHI:
            _fail(f"{path}.rule_id", "unsupported rule")
        if _normalized_rule(lesson.get("rule_text")) != CANONICAL_RULE:
            _fail(f"{path}.rule_text", "unsupported rule text")
        _text(lesson.get("rule_text"), f"{path}.rule_text", MAX_RULE_CHARS)
        try:
            url = normalize_source_url(lesson.get("source_url"))
        except ValueError as exc:
            _fail(f"{path}.source_url", str(exc))
        source_hash = lesson.get("source_hash")
        if not isinstance(source_hash, str) or _HASH_RE.fullmatch(source_hash) is None:
            _fail(f"{path}.source_hash", "expected SHA-256")
        if (url, source_hash) not in material_keys:
            _fail(f"{path}.source_hash", "lesson requires real quarantined material")
        status = lesson.get("status")
        if status not in LESSON_STATUSES:
            _fail(f"{path}.status", "unknown lesson status")
        confidence = lesson.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            _fail(f"{path}.confidence", "expected a finite number")
        if not math.isfinite(float(confidence)) or not 0.0 <= confidence <= 1.0:
            _fail(f"{path}.confidence", "expected a number in [0, 1]")
        _cycle(lesson.get("created_cycle"), f"{path}.created_cycle")
        exercises = lesson.get("exercises")
        if not isinstance(exercises, list) or not 3 <= len(exercises) <= MAX_EXERCISES:
            _fail(f"{path}.exercises", "expected a bounded exercise list")
        kinds = []
        for exercise_index, exercise in enumerate(exercises):
            exercise_path = f"{path}.exercises[{exercise_index}]"
            _validate_exercise(exercise, exercise_path)
            exercise_id = exercise["exercise_id"]
            if (lesson_id, exercise_id) in exercise_by_id:
                _fail(exercise_path, "duplicate exercise")
            exercise_by_id[(lesson_id, exercise_id)] = exercise
            kinds.append(exercise["kind"])
        if kinds.count("practice") < 1 or kinds.count("held_out") < 2:
            _fail(f"{path}.exercises", "practice and two held-out exercises required")

    pending = data.get("pending_exercise")
    if pending is not None:
        if not isinstance(pending, dict):
            _fail("language_tutor.pending_exercise", "expected a dictionary")
        key = (pending.get("lesson_id"), pending.get("exercise_id"))
        exercise = exercise_by_id.get(key)
        if exercise is None or exercise["status"] != "pending":
            _fail("language_tutor.pending_exercise", "unknown or completed exercise")


class LanguageTutor:
    """Явные разрешения, карантин и проверяемые учебные попытки."""

    def __init__(self) -> None:
        self.approved_sources = []
        self.source_requests = []
        self.materials = []
        self.lessons = []
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
        """Создать карточку намерения; разрешения и загрузки здесь нет."""
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
        }
        self.source_requests.append(request)
        return {"status": "requested", **deepcopy(request)}

    def resolve_source_request(self, request_id, *, approved: bool) -> dict:
        """Применить решение человека к одной ожидающей карточке."""
        _text(request_id, "request_id", 40)
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
        # При переполнении списка карточка остаётся: разрешение не было выдано.
        return {**deepcopy(request), **result}

    def revoke_source(self, url) -> dict:
        url = normalize_source_url(url)
        if url not in self.approved_sources:
            return {"status": "not_approved", "url": url}
        self.approved_sources.remove(url)
        # Уже полученные уроки остаются доступны офлайн как прошлый опыт.
        return {"status": "revoked", "url": url}

    def ingest(self, url, *, cycle, fetcher) -> dict:
        """Получить только предварительно разрешённый источник."""
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
            "content_hash": content_hash,
            "excerpt": str(text),
            "fetched_cycle": cycle,
            "status": "quarantined",
            "reason": "",
        }
        self.materials.append(material)
        try:
            lesson = self._parse_lesson(url, content_hash, text, cycle)
        except ValueError as exc:
            material["status"] = "rejected"
            material["reason"] = str(exc)[:160]
            return {"status": "rejected", "url": url, "error": material["reason"]}
        if len(self.lessons) >= MAX_LESSONS:
            material["status"] = "rejected"
            material["reason"] = "lesson limit reached"
            return {"status": "limit_reached", "url": url}
        self.lessons.append(lesson)
        material["status"] = "parsed"
        return {
            "status": "quarantined_lesson",
            "url": url,
            "lesson_id": lesson["lesson_id"],
            "exercises": len(lesson["exercises"]),
        }

    @staticmethod
    def _parse_lesson(url, content_hash, text, cycle) -> dict:
        lines = [" ".join(line.strip().split()) for line in str(text).splitlines()]
        normalized = [line.lower() for line in lines]
        if "урок: жи/ши" not in normalized:
            raise ValueError("unsupported lesson")
        rule_lines = [line for line in lines if line.lower().startswith("правило:")]
        if len(rule_lines) != 1:
            raise ValueError("one explicit rule is required")
        rule_text = rule_lines[0].split(":", 1)[1].strip()
        if _normalized_rule(rule_text) != CANONICAL_RULE:
            raise ValueError("unsupported rule text")

        lesson_id = f"lesson-{content_hash[:16]}"
        exercises = []
        prompts = set()
        for line in lines:
            lowered = line.lower()
            kind = None
            payload = ""
            if lowered.startswith("тренировка:"):
                kind = "practice"
                payload = line.split(":", 1)[1].strip().lower()
            elif lowered.startswith("проверка:"):
                kind = "held_out"
                payload = line.split(":", 1)[1].strip().lower()
            if kind is None:
                continue
            match = _EXERCISE_RE.fullmatch(payload)
            if match is None:
                raise ValueError("invalid exercise format")
            prompt, expected = match.groups()
            if prompt in prompts:
                raise ValueError("duplicate exercise")
            prompts.add(prompt)
            exercises.append(
                {
                    "exercise_id": f"{lesson_id}:ex:{len(exercises)}",
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
            "lesson_id": lesson_id,
            "rule_id": RULE_ZHI_SHI,
            "rule_text": rule_text,
            "source_url": url,
            "source_hash": content_hash,
            "status": "candidate",
            "confidence": 0.3,
            "created_cycle": cycle,
            "exercises": exercises,
        }

    @staticmethod
    def _solve_rule(rule_id, prompt) -> str:
        if rule_id != RULE_ZHI_SHI:
            raise ValueError("unsupported rule")
        # Эталон здесь не читается: ответ получен только из правила и prompt.
        return str(prompt).replace("?", "и")

    def begin_exercise(self) -> dict:
        """Показать задание без эталона; повтор сохраняет текущее задание."""
        if self.pending_exercise is not None:
            lesson_id = self.pending_exercise["lesson_id"]
            exercise_id = self.pending_exercise["exercise_id"]
            for lesson in self.lessons:
                if lesson["lesson_id"] != lesson_id:
                    continue
                for exercise in lesson["exercises"]:
                    if exercise["exercise_id"] == exercise_id:
                        return {
                            "status": "exercise",
                            "lesson_id": lesson_id,
                            "exercise_id": exercise_id,
                            "kind": exercise["kind"],
                            "prompt": exercise["prompt"],
                        }
        for lesson in self.lessons:
            if lesson["status"] == "needs_review":
                continue
            for exercise in lesson["exercises"]:
                if exercise["status"] != "pending":
                    continue
                self.pending_exercise = {
                    "lesson_id": lesson["lesson_id"],
                    "exercise_id": exercise["exercise_id"],
                }
                return {
                    "status": "exercise",
                    "lesson_id": lesson["lesson_id"],
                    "exercise_id": exercise["exercise_id"],
                    "kind": exercise["kind"],
                    "prompt": exercise["prompt"],
                }
        return {"status": "no_exercise"}

    def solve_pending(self, *, cycle) -> dict:
        """Выполнить одну попытку; эталон становится виден только после неё."""
        _cycle(cycle)
        if self.pending_exercise is None:
            return {"status": "no_pending"}
        lesson_id = self.pending_exercise["lesson_id"]
        exercise_id = self.pending_exercise["exercise_id"]
        lesson = next(item for item in self.lessons if item["lesson_id"] == lesson_id)
        exercise = next(
            item for item in lesson["exercises"] if item["exercise_id"] == exercise_id
        )
        answer = self._solve_rule(lesson["rule_id"], exercise["prompt"])
        correct = answer == exercise["expected"]
        exercise["attempts"] = 1
        exercise["status"] = "correct" if correct else "incorrect"
        exercise["submitted"] = answer
        exercise["solved_cycle"] = cycle
        self.pending_exercise = None
        if not correct:
            lesson["status"] = "needs_review"
        elif exercise["kind"] == "held_out":
            self._refresh_lesson_status(lesson)
        return {
            "status": "correct" if correct else "incorrect",
            "lesson_id": lesson_id,
            "exercise_id": exercise_id,
            "answer": answer,
            "expected": exercise["expected"],
            "kind": exercise["kind"],
            "lesson_status": lesson["status"],
        }

    @staticmethod
    def _refresh_lesson_status(lesson) -> None:
        exercises = lesson["exercises"]
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
            lesson["status"] = "source_verified"
            lesson["confidence"] = 0.6

    def get_status(self) -> dict:
        current = None
        if self.pending_exercise is not None:
            for lesson in self.lessons:
                if lesson["lesson_id"] != self.pending_exercise["lesson_id"]:
                    continue
                for exercise in lesson["exercises"]:
                    if exercise["exercise_id"] == self.pending_exercise["exercise_id"]:
                        current = {
                            "lesson_id": lesson["lesson_id"],
                            **{
                                key: exercise[key]
                                for key in ("exercise_id", "kind", "prompt")
                            },
                        }
        return {
            "approved_sources": len(self.approved_sources),
            "source_requests": len(self.source_requests),
            "materials": len(self.materials),
            "lessons": len(self.lessons),
            "source_verified": sum(
                lesson["status"] == "source_verified" for lesson in self.lessons
            ),
            "pending": self.pending_exercise is not None,
            "pending_exercise": current,
        }

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "approved_sources": list(self.approved_sources),
            "source_requests": deepcopy(self.source_requests),
            "materials": deepcopy(self.materials),
            "lessons": deepcopy(self.lessons),
            "pending_exercise": deepcopy(self.pending_exercise),
        }

    def load_from(self, data) -> None:
        validate_language_tutor(data)
        self.approved_sources = list(data["approved_sources"])
        self.source_requests = deepcopy(data.get("source_requests", []))
        self.materials = deepcopy(data["materials"])
        self.lessons = deepcopy(data["lessons"])
        self.pending_exercise = deepcopy(data["pending_exercise"])
