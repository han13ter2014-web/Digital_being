"""Персональные диалоговые состояния, связанные с ``SocialRegistry``.

Активные объекты агента остаются прежними для существующих подсистем. При смене
собеседника их содержимое сохраняется в снапшот прежнего профиля, затем заменяется
снапшотом нового. Отношения и SocialCell уже используют отдельные ключи и не
дублируются здесь. Старый checkpoint без этой секции принадлежит только владельцу.
"""

from __future__ import annotations

from copy import deepcopy

from src.core.associative_lexicon import (
    AssociativeLexicon,
    validate_associative_lexicon,
)
from src.core.dialogue_learning import DialogueLearning
from src.core.language_context import (
    LanguageContext,
    default_language_state,
    legacy_language_context,
    resolve_language_context,
    validate_language_state,
)
from src.core.response_experience import (
    ResponseExperience,
    validate_response_experience,
)
from src.core.user_model import UserModel
from src.perception.user_interaction import UserInteraction

SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2})
_STATE_FIELDS = (
    "user_model",
    "dialogue_learning",
    "associative_lexicon",
    "response_experience",
    "user_interaction",
)


def _fail(path: str, message: str) -> None:
    raise ValueError(f"{path}: {message}")


def _validate_messages(messages, path: str, profile_id: str) -> None:
    if (
        not isinstance(messages, list)
        or len(messages) > UserInteraction.MESSAGE_HISTORY_MAX
    ):
        _fail(path, "expected a bounded list of messages")
    for index, entry in enumerate(messages):
        entry_path = f"{path}[{index}]"
        if not isinstance(entry, dict):
            _fail(entry_path, "expected a dictionary")
        if entry.get("sender") not in {"user", "agent"}:
            _fail(f"{entry_path}.sender", "expected user or agent")
        for field in ("id", "content"):
            if not isinstance(entry.get(field), str) or not entry[field]:
                _fail(f"{entry_path}.{field}", "expected a nonempty string")
        cycle = entry.get("cycle")
        if isinstance(cycle, bool) or not isinstance(cycle, int) or cycle < 0:
            _fail(f"{entry_path}.cycle", "expected a nonnegative integer")
        language_context = entry.get("language_context")
        if language_context is not None:
            context = LanguageContext.from_dict(
                language_context, f"{entry_path}.language_context"
            )
            if context.profile_id != profile_id:
                _fail(
                    f"{entry_path}.language_context", "profile does not match its state"
                )


def validate_social_attribution(data, registry_data) -> None:
    """Проверить все вложенные состояния до восстановления живого агента."""
    if not isinstance(data, dict):
        _fail("social_attribution", "expected a dictionary")
    schema_version = data.get("schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        _fail("social_attribution.schema_version", "unsupported schema version")
    if not isinstance(registry_data, dict):
        _fail("social_attribution", "social_registry is required")
    states = data.get("states")
    if not isinstance(states, dict):
        _fail("social_attribution.states", "expected a dictionary")
    expected_ids = set(registry_data.get("profiles", {}))
    if set(states) != expected_ids:
        _fail("social_attribution.states", "profile IDs must match social_registry")

    from src.core.checkpoint_validation import validate_checkpoint_state

    for profile_id, state in states.items():
        state_path = f"social_attribution.states.{profile_id}"
        if not isinstance(state, dict):
            _fail(state_path, "expected a dictionary")
        for field in _STATE_FIELDS:
            if (
                field in {"associative_lexicon", "response_experience"}
                and field not in state
            ):
                # Checkpoint этапов 1–4: новых личных контуров ещё не было.
                continue
            payload = state.get(field)
            if not isinstance(payload, dict):
                _fail(f"{state_path}.{field}", "expected a dictionary")
            try:
                if field == "associative_lexicon":
                    validate_associative_lexicon(payload, expected_scope="personal")
                    for record in payload["records"]:
                        if record["profile_id"] != profile_id:
                            _fail(
                                f"{state_path}.associative_lexicon",
                                "record profile does not match its state",
                            )
                elif field == "response_experience":
                    validate_response_experience(payload)
                    for response in payload["responses"]:
                        if response["plan"]["state"]["profile_id"] != profile_id:
                            _fail(
                                f"{state_path}.response_experience",
                                "response profile does not match its state",
                            )
                    for expression in payload["imitation"]["expressions"]:
                        if expression["profile_id"] != profile_id:
                            _fail(
                                f"{state_path}.response_experience",
                                "expression profile does not match its state",
                            )
                else:
                    validate_checkpoint_state({field: payload})
            except ValueError as error:
                raise ValueError(f"{state_path}.{error}") from error
        if schema_version >= 2 and "language" not in state:
            _fail(f"{state_path}.language", "required in schema version 2")
        language = state.get("language")
        if language is not None:
            validate_language_state(language, f"{state_path}.language")
            last = language["last_context"]
            if last is not None and last["profile_id"] != profile_id:
                _fail(f"{state_path}.language.last_context", "profile does not match")
        messages = state["user_interaction"].get("messages")
        if messages is not None:
            _validate_messages(
                messages, f"{state_path}.user_interaction.messages", profile_id
            )


class SocialAttribution:
    """Сохранять и активировать личный контекст текущего профиля."""

    def __init__(self, agent) -> None:
        self.agent = agent
        self.active_profile_id = agent.social_registry.current_profile_id
        self.states = {}
        self._language = default_language_state(legacy=True)
        self._legacy_default_pending = True

    def _capture(self, profile_id: str) -> None:
        if profile_id not in self.agent.social_registry.profiles:
            return
        self.states[profile_id] = {
            "user_model": self.agent.user_model.to_dict(),
            "dialogue_learning": self.agent.dialogue_learning.to_dict(),
            "associative_lexicon": self.agent.associative_lexicon.to_personal_dict(),
            "response_experience": self.agent.response_experience.to_dict(),
            "user_interaction": self.agent.user_interaction.to_personal_dict(),
            "language": deepcopy(self._language),
        }

    def capture_active(self) -> None:
        self._capture(self.active_profile_id)

    def _empty_state(self) -> dict:
        interaction = UserInteraction(agent_name=self.agent.name)
        return {
            "user_model": UserModel().to_dict(),
            "dialogue_learning": DialogueLearning().to_dict(),
            "associative_lexicon": AssociativeLexicon().to_personal_dict(),
            "response_experience": ResponseExperience().to_dict(),
            "user_interaction": interaction.to_personal_dict(),
            "language": default_language_state(legacy=False),
        }

    def _restore(self, profile_id: str) -> None:
        state = self.states.get(profile_id) or self._empty_state()
        self._legacy_default_pending = "language" not in state
        self._language = deepcopy(
            state.get("language") or default_language_state(legacy=True)
        )
        self.agent.user_model.load_from(state["user_model"])
        self.agent.dialogue_learning.load_from(state["dialogue_learning"])
        self.agent.associative_lexicon.load_personal_from(state["associative_lexicon"])
        self.agent.response_experience.load_from(state["response_experience"])
        self.agent.user_interaction.restore_personal_state(state["user_interaction"])
        self.agent.user_interaction.set_language_context(self._language["last_context"])

    def current_language_context(self) -> LanguageContext:
        last = self._language["last_context"]
        if last is not None:
            return LanguageContext.from_dict(last)
        stable = self._language["stable_dialogue_language"]
        if stable is not None and not self._legacy_default_pending:
            return LanguageContext(
                profile_id=self.active_profile_id,
                input_language="unknown",
                dialogue_language=stable,
                response_language="ru",
                source="stable_dialogue",
                confidence=None,
            )
        return legacy_language_context(self.active_profile_id)

    def resolve_language(self, text) -> LanguageContext:
        profile = self.agent.social_registry.current_profile()
        context, stable = resolve_language_context(
            text,
            profile_id=self.active_profile_id,
            preferred_language=profile["preferred_language"],
            stable_dialogue_language=self._language["stable_dialogue_language"],
            legacy_default=self._legacy_default_pending,
        )
        self._legacy_default_pending = False
        self._language["stable_dialogue_language"] = stable
        self._language["last_context"] = context.to_dict()
        self.agent.user_interaction.set_language_context(self._language["last_context"])
        return context

    def set_response_language(self, language) -> LanguageContext:
        """Зафиксировать фактическую realization в контексте текущей реплики."""
        if language not in {"ru", "en", "zh"}:
            raise ValueError("response_language: expected ru, en or zh")
        current = self.current_language_context()
        if language in {"en", "zh"} and current.dialogue_language != language:
            raise ValueError("response_language: response requires matching dialogue")
        context = LanguageContext(
            profile_id=current.profile_id,
            input_language=current.input_language,
            dialogue_language=current.dialogue_language,
            response_language=language,
            source=current.source,
            confidence=current.confidence,
        )
        self._language["last_context"] = context.to_dict()
        self.agent.user_interaction.set_language_context(self._language["last_context"])
        return context

    def set_stable_dialogue_language(self, language) -> None:
        """Явный внутренний switch; внешний текст этот метод не вызывает."""
        if language not in {"ru", "en", "zh"}:
            raise ValueError("stable_dialogue_language: expected ru, en or zh")
        self._legacy_default_pending = False
        self._language["stable_dialogue_language"] = language
        self._language["last_context"] = None
        self.agent.user_interaction.set_language_context(None)

    def _sync_attachment(self) -> None:
        attachment = getattr(self.agent, "attachment", None)
        if attachment is not None:
            registry = self.agent.social_registry
            attachment.set_active_profile(
                self.active_profile_id, registry.owner_profile_id
            )

    def sync_active_profile(self) -> bool:
        """Синхронизировать данные после авторизованной смены current_profile."""
        current = self.agent.social_registry.current_profile_id
        if current == self.active_profile_id:
            self._sync_attachment()
            return False
        self._capture(self.active_profile_id)
        self.active_profile_id = current
        self._restore(current)
        self._sync_attachment()
        return True

    def consolidate_language(self, cycle: int) -> dict:
        """Консолидировать каждый профиль без смены активного собеседника."""
        self.sync_active_profile()
        self.capture_active()
        report = {
            "profiles": 0,
            "forgotten_associations": 0,
            "expired_responses": 0,
            "pruned_responses": 0,
            "stale_response_links": 0,
        }
        for profile_id in sorted(self.agent.social_registry.profiles):
            state = self.states.get(profile_id)
            if state is None:
                state = self._empty_state()
                self.states[profile_id] = state
            if profile_id == self.active_profile_id:
                lexicon = self.agent.associative_lexicon
                experience = self.agent.response_experience
            else:
                lexicon = AssociativeLexicon()
                lexicon.load_personal_from(state["associative_lexicon"])
                experience = ResponseExperience()
                experience.load_from(state["response_experience"])

            lexicon_report = lexicon.consolidate(cycle)
            response_report = experience.consolidate(cycle)
            if profile_id == self.active_profile_id:
                self._capture(profile_id)
            else:
                state["associative_lexicon"] = lexicon.to_personal_dict()
                state["response_experience"] = experience.to_dict()

            report["profiles"] += 1
            for key in ("forgotten_associations",):
                report[key] += lexicon_report[key]
            for key in (
                "expired_responses",
                "pruned_responses",
                "stale_response_links",
            ):
                report[key] += response_report[key]
        return report

    def to_dict(self) -> dict:
        self.sync_active_profile()
        self.capture_active()
        for profile_id in self.agent.social_registry.profiles:
            if profile_id not in self.states:
                self.states[profile_id] = self._empty_state()
        return {"schema_version": SCHEMA_VERSION, "states": deepcopy(self.states)}

    def load_from(self, data) -> None:
        validate_social_attribution(data, self.agent.social_registry.to_dict())
        self.states = deepcopy(data["states"])
        current_profile_id = self.agent.social_registry.current_profile_id
        legacy_language = "language" not in self.states[current_profile_id]
        empty_lexicon = AssociativeLexicon().to_personal_dict()
        empty_experience = ResponseExperience().to_dict()
        for state in self.states.values():
            state.setdefault("associative_lexicon", deepcopy(empty_lexicon))
            state.setdefault("response_experience", deepcopy(empty_experience))
            state.setdefault("language", default_language_state(legacy=True))
        self.active_profile_id = current_profile_id
        self._restore(self.active_profile_id)
        self._legacy_default_pending = legacy_language
        self._sync_attachment()

    def load_legacy(self) -> None:
        """Отнести старый одиночный контур к owner, а не текущему гостю."""
        registry = self.agent.social_registry
        registry.current_profile_id = registry.owner_profile_id
        self.active_profile_id = registry.owner_profile_id
        self.states = {}
        self._language = default_language_state(legacy=True)
        self._legacy_default_pending = True
        self._capture(self.active_profile_id)
        self._sync_attachment()
