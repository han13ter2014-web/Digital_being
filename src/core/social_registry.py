"""Минимальный реестр собеседников и явное знакомство на локальном канале.

Реестр различает владельца локального канала и текущего говорящего. Он не
заменяет ``UserModel``, отношения, эпизоды или обучение: персональные снапшоты
этих данных принадлежат ``SocialAttribution``. Имя и само представление не дают
прав владельца и не считаются независимым доказательством личности.
"""

from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Optional
from uuid import UUID, uuid4

SCHEMA_VERSION = 1
MAX_PROFILES = 128
MAX_NAME_LENGTH = 40
MAX_BINDINGS = 8
PROFILE_KINDS = frozenset(
    {"local_owner", "local_person", "digital_being", "external_ai", "unknown"}
)
IDENTITY_STATUSES = frozenset({"self_declared", "observed", "verified", "unknown"})
_ACTIVE_NAMING_PHASES = frozenset({"awaiting_name", "considering", "renaming_pending"})

_NAME_TOKEN = r"[^\W\d_][\w'’-]*"
_NAME = rf"{_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,2}}"
_EXPLICIT_STRANGER_RE = re.compile(
    rf"^\s*я\s+не\s+{_NAME_TOKEN}"
    rf"(?:\s*,?\s*а\s+(?:(?:его|её|их)\s+)?"
    rf"(?:друг|подруга|знакомый|знакомая|брат|сестра)\s+"
    rf"(?P<name>{_NAME}))?\s*[.!?]*$",
    re.IGNORECASE,
)
_RELATION_RE = re.compile(
    rf"^\s*я\s+(?:друг|подруга|знакомый|знакомая|брат|сестра)\s+"
    rf"{_NAME_TOKEN}\s*[.!?]*$",
    re.IGNORECASE,
)
_NAMED_CALL_RE = re.compile(
    rf"^\s*меня\s+зовут\s+(?P<name>{_NAME})\s*[.!?]*$",
    re.IGNORECASE,
)
_DIRECT_NAME_RE = re.compile(
    rf"^\s*я\s+(?:—\s*)?(?P<name>{_NAME_TOKEN})\s*[.!?]*$",
    re.IGNORECASE,
)
# «Я рад» грамматически похоже на представление. Такие частые предикаты
# остаются обычной речью; неизвестные имена этот список не ограничивает.
_NOT_NAME_WORDS = frozenset(
    {
        "буду",
        "всё",
        "все",
        "готов",
        "готова",
        "грустен",
        "грустна",
        "друг",
        "здесь",
        "не",
        "очень",
        "подруга",
        "просто",
        "рад",
        "рада",
        "рядом",
        "сегодня",
        "сейчас",
        "счастлив",
        "счастлива",
        "тоже",
        "устал",
        "устала",
        "это",
    }
)


def _fail(path: str, message: str) -> None:
    raise ValueError(f"{path}: {message}")


def _text(value, path: str, *, max_length: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        _fail(path, "expected a string")
    if not allow_empty and not value.strip():
        _fail(path, "expected a nonempty string")
    if len(value) > max_length:
        _fail(path, f"expected at most {max_length} characters")
    return value


def _cycle(value, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(path, "expected a nonnegative integer")
    return value


def _uuid(value, path: str) -> str:
    _text(value, path, max_length=36)
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise ValueError(f"{path}: expected a UUID") from error
    if str(parsed) != value.lower():
        _fail(path, "expected a canonical UUID")
    return str(parsed)


def _validate_binding(binding, path: str) -> None:
    if not isinstance(binding, dict):
        _fail(path, "expected a dictionary")
    _text(binding.get("channel"), f"{path}.channel", max_length=64)
    _text(
        binding.get("external_id"),
        f"{path}.external_id",
        max_length=128,
        allow_empty=True,
    )
    confidence = binding.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        _fail(f"{path}.confidence", "expected a number")
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        _fail(f"{path}.confidence", "expected a number from 0 to 1")


def _validate_lineage(lineage, path: str) -> None:
    if not isinstance(lineage, dict):
        _fail(path, "expected a dictionary or null")
    life_id = lineage.get("life_id")
    if life_id is not None:
        _uuid(life_id, f"{path}.life_id")
    _text(lineage.get("seed_id"), f"{path}.seed_id", max_length=128)
    seed_hash = lineage.get("seed_sha256")
    if (
        not isinstance(seed_hash, str)
        or re.fullmatch(r"[0-9a-f]{64}", seed_hash) is None
    ):
        _fail(f"{path}.seed_sha256", "expected a lowercase SHA-256 hex digest")
    parent_seed = lineage.get("parent_seed")
    if parent_seed is not None:
        _text(parent_seed, f"{path}.parent_seed", max_length=128)
    parent_life_id = lineage.get("parent_life_id")
    if parent_life_id is not None:
        _uuid(parent_life_id, f"{path}.parent_life_id")
    generation = lineage.get("generation")
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 0
    ):
        _fail(f"{path}.generation", "expected a nonnegative integer")
    schema_version = lineage.get("seed_schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version < 1
    ):
        _fail(f"{path}.seed_schema_version", "expected a positive integer")
    status = lineage.get("status")
    if status not in {"claimed", "observed", "verified"}:
        _fail(f"{path}.status", "unsupported lineage status")
    if status == "observed" and life_id is not None:
        _fail(f"{path}.life_id", "an unawakened observed seed cannot own a life ID")
    if status in {"claimed", "verified"} and life_id is None:
        _fail(f"{path}.life_id", "claimed and verified lineage require a life ID")


def _validate_profile(profile, path: str) -> None:
    if not isinstance(profile, dict):
        _fail(path, "expected a dictionary")
    _uuid(profile.get("profile_id"), f"{path}.profile_id")
    if profile.get("kind") not in PROFILE_KINDS:
        _fail(f"{path}.kind", "unsupported profile kind")
    _text(
        profile.get("display_name"),
        f"{path}.display_name",
        max_length=MAX_NAME_LENGTH,
        allow_empty=True,
    )
    if profile.get("identity_status") not in IDENTITY_STATUSES:
        _fail(f"{path}.identity_status", "unsupported identity status")
    introduced_by = profile.get("introduced_by")
    if introduced_by is not None:
        _uuid(introduced_by, f"{path}.introduced_by")
    created = _cycle(profile.get("created_cycle"), f"{path}.created_cycle")
    seen = _cycle(profile.get("last_seen_cycle"), f"{path}.last_seen_cycle")
    if seen < created:
        _fail(f"{path}.last_seen_cycle", "must not precede created_cycle")
    bindings = profile.get("channel_bindings")
    if not isinstance(bindings, list) or len(bindings) > MAX_BINDINGS:
        _fail(f"{path}.channel_bindings", f"expected at most {MAX_BINDINGS} bindings")
    for index, binding in enumerate(bindings):
        _validate_binding(binding, f"{path}.channel_bindings[{index}]")
    lineage = profile.get("lineage")
    if profile["kind"] == "digital_being":
        if lineage is None:
            _fail(f"{path}.lineage", "digital_being requires lineage")
        _validate_lineage(lineage, f"{path}.lineage")
    elif lineage is not None:
        _fail(f"{path}.lineage", "only digital_being profiles have lineage")


def validate_social_registry(data) -> None:
    """Проверить секцию checkpoint до любых мутаций живого агента."""
    if not isinstance(data, dict):
        _fail("social_registry", "expected a dictionary")
    if data.get("schema_version") != SCHEMA_VERSION:
        _fail("social_registry.schema_version", "unsupported schema version")
    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or not 1 <= len(profiles) <= MAX_PROFILES:
        _fail("social_registry.profiles", f"expected 1..{MAX_PROFILES} profiles")
    for key, profile in profiles.items():
        path = f"social_registry.profiles.{key}"
        _uuid(key, path)
        _validate_profile(profile, path)
        if profile["profile_id"] != key:
            _fail(f"{path}.profile_id", "must match the mapping key")
        introduced_by = profile.get("introduced_by")
        if introduced_by is not None and introduced_by not in profiles:
            _fail(f"{path}.introduced_by", "profile does not exist")
    owner_id = _uuid(data.get("owner_profile_id"), "social_registry.owner_profile_id")
    current_id = _uuid(
        data.get("current_profile_id"), "social_registry.current_profile_id"
    )
    owners = [key for key, item in profiles.items() if item["kind"] == "local_owner"]
    if len(owners) != 1 or owners[0] != owner_id:
        _fail("social_registry.owner_profile_id", "expected exactly one local owner")
    if current_id not in profiles:
        _fail("social_registry.current_profile_id", "profile does not exist")


class SocialRegistry:
    """Профили собеседников; локальный владелец существует с рождения."""

    def __init__(self) -> None:
        owner_id = str(uuid4())
        self.profiles = {owner_id: self._profile(owner_id, "local_owner")}
        self.owner_profile_id = owner_id
        self.current_profile_id = owner_id

    @staticmethod
    def _profile(
        profile_id: str,
        kind: str,
        *,
        name: str = "",
        introduced_by: Optional[str] = None,
        cycle: int = 0,
        lineage: Optional[dict] = None,
    ) -> dict:
        status = "verified" if kind == "local_owner" else "self_declared"
        if kind == "unknown":
            status = "unknown"
        elif kind == "digital_being" and lineage is not None:
            status = {
                "claimed": "self_declared",
                "observed": "observed",
                "verified": "verified",
            }[lineage["status"]]
        return {
            "profile_id": profile_id,
            "kind": kind,
            "display_name": name,
            "identity_status": status,
            "channel_bindings": [
                {"channel": "local", "external_id": "local", "confidence": 1.0}
            ],
            "introduced_by": introduced_by,
            "created_cycle": cycle,
            "last_seen_cycle": cycle,
            "lineage": deepcopy(lineage),
        }

    def current_profile(self) -> dict:
        return dict(self.profiles[self.current_profile_id])

    def get_profile(self, profile_id: str) -> Optional[dict]:
        profile = self.profiles.get(profile_id)
        return dict(profile) if profile is not None else None

    def note_contact(self, cycle: int) -> None:
        profile = self.profiles[self.current_profile_id]
        profile["last_seen_cycle"] = max(profile["last_seen_cycle"], int(cycle))

    def create_local_person(self, name: str = "", *, cycle: int = 0) -> str:
        """Создать гостя или неизвестного; права владельца не наследуются."""
        if len(self.profiles) >= MAX_PROFILES:
            raise ValueError("social registry profile limit reached")
        profile_id = str(uuid4())
        kind = "local_person" if name else "unknown"
        self.profiles[profile_id] = self._profile(
            profile_id,
            kind,
            name=name,
            introduced_by=self.owner_profile_id,
            cycle=cycle,
        )
        self.current_profile_id = profile_id
        return profile_id

    def _add_digital_being(
        self, name: str, lineage: dict, *, cycle: int, local: bool
    ) -> str:
        if len(self.profiles) >= MAX_PROFILES:
            raise ValueError("social registry profile limit reached")
        _text(name, "display_name", max_length=MAX_NAME_LENGTH, allow_empty=True)
        _validate_lineage(lineage, "lineage")
        profile_id = str(uuid4())
        profile = self._profile(
            profile_id,
            "digital_being",
            name=name,
            introduced_by=self.owner_profile_id,
            cycle=cycle,
            lineage=lineage,
        )
        if not local:
            # Внешнее заявление не доказывает принадлежность локальному каналу.
            profile["channel_bindings"] = []
        self.profiles[profile_id] = profile
        return profile_id

    def claim_digital_being(
        self,
        *,
        life_id: str,
        seed_id: str,
        seed_sha256: str,
        parent_seed: Optional[str] = None,
        parent_life_id: Optional[str] = None,
        generation: int = 0,
        seed_schema_version: int = 1,
        name: str = "",
        cycle: int = 0,
    ) -> str:
        """Записать внешнее заявление, не повышая его до наблюдения/проверки."""
        lineage = {
            "life_id": life_id,
            "seed_id": seed_id,
            "seed_sha256": seed_sha256,
            "parent_seed": parent_seed,
            "parent_life_id": parent_life_id,
            "generation": generation,
            "seed_schema_version": seed_schema_version,
            "status": "claimed",
        }
        return self._add_digital_being(name, lineage, cycle=cycle, local=False)

    def observe_local_seed(self, seed, *, cycle: int = 0) -> str:
        """Связать целостный локальный пакет с профилем, не пробуждая жизнь."""
        if not isinstance(seed, dict) or seed.get("is_complete") is not True:
            raise ValueError("local seed must be a complete inspected package")
        metadata = seed.get("metadata")
        if not isinstance(metadata, dict) or seed.get("metadata_error") is not None:
            raise ValueError("local seed metadata must be valid JSON")
        generation = metadata.get("generation", 0)
        _cycle(generation, "local seed metadata.generation")
        schema_version = metadata.get("schema_version", 1)
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version < 1
        ):
            raise ValueError("local seed metadata.schema_version must be positive")
        lineage = {
            "life_id": None,
            "seed_id": seed.get("name"),
            "seed_sha256": seed.get("seed_sha256"),
            "parent_seed": metadata.get("parent_seed"),
            "parent_life_id": metadata.get("parent_life_id"),
            "generation": generation + 1,
            "seed_schema_version": schema_version,
            "status": "observed",
        }
        _validate_lineage(lineage, "local seed lineage")
        for profile_id, profile in self.profiles.items():
            existing = profile.get("lineage")
            if (
                profile.get("kind") == "digital_being"
                and existing is not None
                and existing["status"] == "observed"
                and existing["seed_id"] == lineage["seed_id"]
                and existing["seed_sha256"] == lineage["seed_sha256"]
            ):
                return profile_id
        return self._add_digital_being(
            _clean_name(str(lineage["seed_id"])), lineage, cycle=cycle, local=True
        )

    def register_awakened_life(
        self, seed_profile_id: str, *, life_id: str, name: str = "", cycle: int = 0
    ) -> str:
        """Зарегистрировать отдельную проверенную жизнь из наблюденного семени."""
        seed_profile = self.profiles.get(seed_profile_id)
        lineage = seed_profile.get("lineage") if seed_profile is not None else None
        if (
            not isinstance(lineage, dict)
            or lineage.get("status") != "observed"
            or lineage.get("life_id") is not None
        ):
            raise ValueError("an unbound observed local seed profile is required")
        _uuid(life_id, "life_id")
        awakened = deepcopy(lineage)
        awakened.update(life_id=life_id, status="verified")
        return self._add_digital_being(name, awakened, cycle=cycle, local=True)

    def switch_to(self, profile_id: str, *, cycle: int = 0) -> None:
        if profile_id not in self.profiles:
            raise KeyError(profile_id)
        self.current_profile_id = profile_id
        self.note_contact(cycle)

    def complete_introduction(self, name: str, *, cycle: int = 0) -> None:
        """Назвать текущий безымянный профиль, не меняя владельца."""
        profile = self.profiles[self.current_profile_id]
        profile["display_name"] = name
        profile["last_seen_cycle"] = max(profile["last_seen_cycle"], int(cycle))
        if profile["kind"] == "unknown":
            profile["kind"] = "local_person"
            profile["identity_status"] = "self_declared"
            profile["introduced_by"] = self.owner_profile_id

    def get_status(self) -> dict:
        current = self.profiles[self.current_profile_id]
        return {
            "profile_count": len(self.profiles),
            "owner_profile_id": self.owner_profile_id,
            "current_profile_id": self.current_profile_id,
            "current_kind": current["kind"],
            "current_display_name": current["display_name"],
        }

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "owner_profile_id": self.owner_profile_id,
            "current_profile_id": self.current_profile_id,
            "profiles": deepcopy(self.profiles),
        }

    def load_from(self, data) -> None:
        validate_social_registry(data)
        restored = deepcopy(data)
        self.profiles = restored["profiles"]
        self.owner_profile_id = restored["owner_profile_id"]
        self.current_profile_id = restored["current_profile_id"]


def _clean_name(value: str) -> str:
    return " ".join(value.split())[:MAX_NAME_LENGTH]


def _new_introduction(registry: SocialRegistry, name: str, cycle: int) -> dict:
    try:
        registry.create_local_person(name, cycle=cycle)
    except ValueError:
        return {"reply": "Пока не могу сохранить ещё один профиль собеседника."}
    if name:
        reply = (
            f"Приятно познакомиться, {name}. "
            "Буду помнить этот разговор как общение с тобой."
        )
    else:
        reply = "С кем я сейчас разговариваю? Можешь представиться?"
    return {"reply": reply}


def process_introduction(
    registry: SocialRegistry,
    text: str,
    *,
    cycle: int = 0,
    pending_question=None,
    naming_phase: str = "none",
) -> Optional[dict]:
    """Обработать только явное представление; обычную речь вернуть как None."""
    explicit = _EXPLICIT_STRANGER_RE.match(text) or _RELATION_RE.match(text)
    if explicit is not None:
        name = ""
        if explicit.re is _EXPLICIT_STRANGER_RE:
            name = _clean_name(explicit.groupdict().get("name") or "")
        return _new_introduction(registry, name, cycle)
    if pending_question is not None or naming_phase in _ACTIVE_NAMING_PHASES:
        return None
    named = _NAMED_CALL_RE.match(text)
    if named is None:
        named = _DIRECT_NAME_RE.match(text)
        if (
            named is None
            or _clean_name(named.group("name")).casefold() in _NOT_NAME_WORDS
        ):
            return None
    name = _clean_name(named.group("name"))
    current = registry.current_profile()
    if not current["display_name"]:
        registry.complete_introduction(name, cycle=cycle)
    elif current["display_name"].casefold() != name.casefold():
        return _new_introduction(registry, name, cycle)
    return {"reply": f"Приятно познакомиться, {name}."}
