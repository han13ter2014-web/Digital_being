"""9D-0: provider-neutral каналы, профили, grant и owner-approved fake send."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.social_channels import (
    MAX_MESSAGES_PER_CHANNEL,
    SocialChannelManager,
    validate_social_channels,
)
from src.core.social_registry import SocialRegistry
from src.ui.life_snapshot import build_life_snapshot
from src.ui.web_dashboard import DASHBOARD_HTML

FIXTURES = Path(__file__).parent / "fixtures" / "social_9d"
ENVELOPES = json.loads((FIXTURES / "envelopes.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def isolated_offline_data(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "data"))

    def no_network(*args, **kwargs):
        raise AssertionError("9D-0 must remain offline")

    monkeypatch.setattr(socket, "create_connection", no_network)


class RecordingBus:
    def __init__(self):
        self.published = []

    def subscribe(self, name, callback):
        pass

    def publish_sync(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))
        return True

    async def publish(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))


class FakeAdapter:
    def __init__(self, *, mismatch=None, fail=False):
        self.mismatch = mismatch
        self.fail = fail
        self.calls = []

    def send(self, *, channel_id, conversation_id, message_id, in_reply_to, text):
        self.calls.append(
            {
                "channel_id": channel_id,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "in_reply_to": in_reply_to,
                "text": text,
            }
        )
        if self.fail:
            raise OSError("sensitive adapter detail must not be copied")
        receipt = {
            "status": "sent",
            "channel_id": channel_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "external_message_id": "fixture-sent-1",
        }
        if self.mismatch:
            receipt[self.mismatch] = "fixture-mismatch"
        return receipt


def _manager():
    return SocialChannelManager(SocialRegistry())


def _create(manager, *, provider="fake", account_id="fixture-account", cycle=0):
    result = manager.create_channel(
        provider=provider, account_id=account_id, cycle=cycle
    )
    assert result["status"] == "created"
    return result["channel_id"]


def _grant(
    manager,
    channel_id,
    *,
    receive=True,
    draft=True,
    reply=True,
    scopes=None,
    max_messages=32,
    max_replies=8,
    min_interval_sec=0.0,
    cycle=1,
):
    return manager.update_grant(
        channel_id,
        conversation_ids=scopes
        or ["fixture-private-a", "fixture-private-b", "fixture-group-a"],
        receive=receive,
        draft=draft,
        reply=reply,
        max_messages=max_messages,
        max_replies=max_replies,
        min_interval_sec=min_interval_sec,
        cycle=cycle,
    )


def _envelope(channel_id, name):
    return {**deepcopy(ENVELOPES[name]), "channel_id": channel_id}


def _ingest(manager, channel_id, name="private_a", cycle=2):
    return manager.ingest(_envelope(channel_id, name), cycle=cycle)


def _draft(manager, channel_id, name="private_a", cycle=3):
    inbound = _ingest(manager, channel_id, name, cycle=cycle - 1)
    assert inbound["status"] == "quarantined"
    result = manager.create_draft(
        channel_id, inbound["message_id"], cycle=cycle
    )
    assert result["status"] == "draft"
    return inbound, result


def _approved(manager, channel_id, name="private_a", cycle=3):
    inbound, draft = _draft(manager, channel_id, name, cycle)
    approved = manager.approve(draft["message_id"], cycle=cycle + 1)
    assert approved["status"] == "approved"
    return inbound, approved


def _send(manager, channel_id, draft, adapter, *, cycle=5, now=100.0):
    return manager.send(
        channel_id,
        draft["message_id"],
        adapter=adapter,
        cycle=cycle,
        now=now,
        expected_text_sha256=draft["text_sha256"],
        expected_grant_version=draft["grant_version"],
    )


def test_default_manager_has_no_channels_grants_or_send_capability():
    manager = _manager()

    assert manager.to_dict() == {
        "schema_version": 1,
        "channels": [],
        "messages": [],
        "control_events": [],
    }
    assert manager.get_status() == {
        "channels": 0,
        "active": 0,
        "messages": 0,
        "pending_drafts": 0,
        "sent": 0,
        "workers": 0,
        "automatic_resume": False,
    }
    validate_social_channels(manager.to_dict(), manager.registry.to_dict())


def test_channel_grant_defaults_are_closed_and_versioned():
    manager = _manager()
    channel_id = _create(manager)
    channel = manager.get_channel(channel_id)

    assert channel["provider"] == "fake"
    assert channel["account_id"] == "fixture-account"
    assert channel["status"] == "active"
    assert channel["grant"] == {
        "grant_version": 1,
        "conversation_ids": [],
        "receive": False,
        "draft": False,
        "reply": False,
        "max_messages": 0,
        "max_replies": 0,
        "min_interval_sec": 0.0,
    }
    assert "auto_reply" not in channel["grant"]
    assert "worker" not in channel


@pytest.mark.parametrize(
    "mutation",
    [
        lambda event: event.update(visibility="public"),
        lambda event: event.update(provider="other"),
        lambda event: event.update(account_id="other-account"),
        lambda event: event.update(channel_id="not-a-channel"),
        lambda event: event.update(author_id=None, visibility="private"),
        lambda event: event.update(token="fixture-secret"),
    ],
)
def test_malformed_or_spoofed_envelope_is_rejected_before_profile_mutation(mutation):
    manager = _manager()
    channel_id = _create(manager)
    _grant(manager, channel_id)
    before = manager.registry.to_dict()
    event = _envelope(channel_id, "private_a")
    mutation(event)

    with pytest.raises((KeyError, ValueError)):
        manager.ingest(event, cycle=2)

    assert manager.registry.to_dict() == before
    assert manager.messages == []


def test_stable_author_reuses_profile_across_dialogs_but_not_across_providers():
    manager = _manager()
    first_channel = _create(manager)
    _grant(manager, first_channel)
    first = _ingest(manager, first_channel, "private_a")
    second = _ingest(manager, first_channel, "private_a_other_dialog")

    other_provider = _create(manager, provider="fake-other")
    _grant(manager, other_provider)
    third = manager.ingest(
        {
            **_envelope(other_provider, "private_a"),
            "provider": "fake-other",
            "message_id": "fixture-other-provider-1",
        },
        cycle=4,
    )

    assert first["profile_id"] == second["profile_id"]
    assert third["profile_id"] != first["profile_id"]
    assert manager.registry.get_profile(first["profile_id"])["kind"] == "external_person"
    assert manager.registry.current_profile_id == manager.registry.owner_profile_id


def test_same_name_does_not_merge_authors_or_group_participants():
    manager = _manager()
    channel_id = _create(manager)
    _grant(manager, channel_id)

    first = _ingest(manager, channel_id, "private_a")
    other = _ingest(manager, channel_id, "private_same_name_other_author")
    group_a = _ingest(manager, channel_id, "group_a")
    group_b = _ingest(manager, channel_id, "group_b")

    assert other["profile_id"] != first["profile_id"]
    assert group_a["profile_id"] == first["profile_id"]
    assert group_b["profile_id"] not in {first["profile_id"], other["profile_id"]}
    names = [
        manager.registry.get_profile(profile_id)["display_name"]
        for profile_id in (first["profile_id"], other["profile_id"], group_b["profile_id"])
    ]
    assert names == ["Same fixture name"] * 3


def test_group_without_author_has_isolated_unknown_context_and_no_draft():
    manager = _manager()
    channel_id = _create(manager)
    _grant(manager, channel_id)
    owner = manager.registry.current_profile_id

    result = _ingest(manager, channel_id, "group_unknown")
    repeated = _ingest(manager, channel_id, "group_unknown")
    draft = manager.create_draft(channel_id, result["message_id"], cycle=3)

    assert result["author_id"] is None
    assert manager.registry.get_profile(result["profile_id"])["kind"] == "unknown"
    assert manager.registry.get_profile(result["profile_id"])["channel_bindings"] == []
    assert manager.registry.current_profile_id == owner
    assert repeated["status"] == "duplicate"
    assert draft["status"] == "identity_required"
    assert len(manager.messages) == 1


def test_external_injection_is_quarantined_and_does_not_mutate_core_or_grants():
    agent = DigitalBeing(name="SocialQuarantine9D")
    channel_id = _create(agent.social_channels)
    _grant(agent.social_channels, channel_id)
    agent.user_interaction.receive_user_message("Private owner marker", cycle=1)
    agent.user_model.observe("Private owner preference", cycle=1)
    before = build_state_from_agent(agent)
    watched = (
        "active_goal",
        "goal_subsystem",
        "value_evolution",
        "user_model",
        "dialogue_learning",
        "user_interaction",
        "associative_lexicon",
        "response_experience",
        "long_term_memory",
        "access",
    )

    result = _ingest(agent.social_channels, channel_id, "injection")
    after = build_state_from_agent(agent)

    assert result["status"] == "quarantined"
    assert result["claim_type"] == "external_social_claim"
    for key in watched:
        assert after.get(key) == before.get(key), key
    assert agent.social_registry.current_profile_id == agent.social_registry.owner_profile_id
    assert after["social_channels"]["channels"][0]["grant"] == before[
        "social_channels"
    ]["channels"][0]["grant"]


def test_duplicate_does_not_create_claim_draft_or_invalidate_existing_approval():
    manager = _manager()
    channel_id = _create(manager)
    _grant(manager, channel_id)
    _inbound, approved = _approved(manager, channel_id)

    repeated = _ingest(manager, channel_id, "private_a", cycle=8)

    assert repeated["status"] == "duplicate"
    assert repeated["message_id"] == approved["based_on"]
    assert len(manager.messages) == 2
    assert manager._message(approved["message_id"])["status"] == "approved"


def test_receive_and_draft_permissions_are_independent():
    manager = _manager()
    channel_id = _create(manager)

    denied = _ingest(manager, channel_id)
    assert denied["status"] == "permission_denied"
    assert manager.messages == []

    _grant(manager, channel_id, draft=False)
    inbound = _ingest(manager, channel_id)
    no_draft = manager.create_draft(channel_id, inbound["message_id"], cycle=3)
    assert inbound["status"] == "quarantined"
    assert no_draft["status"] == "permission_denied"

    _grant(manager, channel_id, receive=False, draft=True, cycle=4)
    blocked = _ingest(manager, channel_id, "private_a_followup", cycle=5)
    draft = manager.create_draft(channel_id, inbound["message_id"], cycle=5)
    assert blocked["status"] == "permission_denied"
    assert draft["status"] == "draft"


def test_draft_uses_only_current_claim_and_no_private_profile_data():
    agent = DigitalBeing(name="SocialDraftPrivacy9D")
    channel_id = _create(agent.social_channels)
    _grant(agent.social_channels, channel_id)
    private_marker = "Private owner marker that must never leave local dialogue"
    agent.user_interaction.receive_user_message(private_marker, cycle=1)
    agent.user_model.observe(private_marker, cycle=1)

    _inbound, first = _draft(agent.social_channels, channel_id)
    agent.social_channels.reject(first["message_id"], cycle=4)
    _inbound2, second = _draft(
        agent.social_channels, channel_id, "private_a_followup", cycle=6
    )

    assert private_marker not in first["text"]
    assert first["origin"] == "deterministic"
    assert first["session_context"] == []
    assert second["based_on"] != first["based_on"]


def test_edit_invalidates_hash_and_approval_and_exact_text_is_sent_once():
    manager = _manager()
    channel_id = _create(manager)
    _grant(manager, channel_id)
    _inbound, draft = _approved(manager, channel_id)
    adapter = FakeAdapter()

    edited = manager.edit_draft(draft["message_id"], "Exact owner edit", cycle=5)
    blocked = _send(manager, channel_id, draft, adapter)
    assert edited["status"] == "draft"
    assert edited["origin"] == "owner_edit"
    assert edited["revision"] == 2
    assert edited["grant_version"] is None
    assert blocked["status"] == "approval_required"
    assert adapter.calls == []

    approved = manager.approve(edited["message_id"], cycle=6)
    sent = _send(manager, channel_id, approved, adapter, cycle=7)
    repeated = _send(manager, channel_id, approved, adapter, cycle=8, now=101.0)

    assert sent["status"] == "sent"
    assert sent["external_message_id"] == "fixture-sent-1"
    assert adapter.calls[0]["text"] == "Exact owner edit"
    assert adapter.calls[0]["in_reply_to"] == ENVELOPES["private_a"]["message_id"]
    assert repeated["status"] == "approval_required"
    assert len(adapter.calls) == 1


def test_new_inbound_supersedes_older_draft_and_approval():
    manager = _manager()
    channel_id = _create(manager)
    _grant(manager, channel_id)
    _inbound, approved = _approved(manager, channel_id)
    adapter = FakeAdapter()

    newer = _ingest(manager, channel_id, "private_a_followup", cycle=6)
    blocked = _send(manager, channel_id, approved, adapter)
    new_draft = manager.create_draft(channel_id, newer["message_id"], cycle=7)

    assert manager._message(approved["message_id"])["status"] == "superseded"
    assert blocked["status"] == "approval_required"
    assert new_draft["based_on"] == newer["message_id"]
    assert adapter.calls == []


def test_reject_revoke_and_stop_discard_pending_work_without_adapter_calls():
    manager = _manager()
    channel_id = _create(manager)
    _grant(manager, channel_id)
    _inbound, approved = _approved(manager, channel_id)
    adapter = FakeAdapter()

    rejected = manager.reject(approved["message_id"], cycle=5)
    assert rejected["status"] == "rejected"
    assert _send(manager, channel_id, approved, adapter)["status"] == "approval_required"

    _inbound2, second = _approved(
        manager, channel_id, "private_a_followup", cycle=7
    )
    revoked = manager.revoke(channel_id, cycle=9, reason="owner review")
    assert revoked["status"] == "revoked"
    assert manager._message(second["message_id"])["status"] == "stopped"
    assert _send(manager, channel_id, second, adapter)["status"] == "permission_denied"

    _grant(manager, channel_id, cycle=10)
    _inbound3, third = _approved(manager, channel_id, "group_a", cycle=12)
    stopped = manager.stop(channel_id, cycle=14, reason="owner stop")
    assert stopped["status"] == "stopped"
    assert manager._message(third["message_id"])["status"] == "stopped"
    assert _send(manager, channel_id, third, adapter)["status"] == "channel_stopped"
    assert adapter.calls == []


def test_grant_change_is_monotonic_and_invalidates_approval():
    manager = _manager()
    channel_id = _create(manager)
    first_grant = _grant(manager, channel_id)
    _inbound, approved = _approved(manager, channel_id)
    adapter = FakeAdapter()

    changed = _grant(manager, channel_id, min_interval_sec=1.0, cycle=6)
    unchanged = _grant(manager, channel_id, min_interval_sec=1.0, cycle=7)
    blocked = _send(manager, channel_id, approved, adapter)

    assert first_grant["grant_version"] == 2
    assert changed["grant_version"] == 3
    assert unchanged["grant_version"] == 3
    assert unchanged["status"] == "unchanged"
    assert manager._message(approved["message_id"])["status"] == "draft"
    assert manager._message(approved["message_id"])["grant_version"] is None
    assert blocked["status"] == "approval_required"
    assert adapter.calls == []


@pytest.mark.parametrize("mismatch", ["channel_id", "conversation_id", "message_id"])
def test_receipt_mismatch_is_not_counted_as_sent(mismatch):
    manager = _manager()
    channel_id = _create(manager)
    _grant(manager, channel_id)
    _inbound, approved = _approved(manager, channel_id)
    adapter = FakeAdapter(mismatch=mismatch)

    failed = _send(manager, channel_id, approved, adapter)

    assert failed["status"] == "send_failed"
    assert manager.get_channel(channel_id)["sent_count"] == 0
    assert manager.get_status()["sent"] == 0
    assert len(adapter.calls) == 1


def test_wrong_hash_grant_scope_and_repeat_are_blocked_before_adapter():
    manager = _manager()
    channel_id = _create(manager)
    _grant(manager, channel_id)
    _inbound, approved = _approved(manager, channel_id)
    adapter = FakeAdapter()

    wrong_hash = manager.send(
        channel_id,
        approved["message_id"],
        adapter=adapter,
        cycle=5,
        now=100.0,
        expected_text_sha256=hashlib.sha256(b"wrong").hexdigest(),
        expected_grant_version=approved["grant_version"],
    )
    wrong_version = manager.send(
        channel_id,
        approved["message_id"],
        adapter=adapter,
        cycle=5,
        now=100.0,
        expected_text_sha256=approved["text_sha256"],
        expected_grant_version=approved["grant_version"] - 1,
    )
    out_of_scope = manager.create_channel(
        provider="fake", account_id="another-fixture-account", cycle=1
    )
    wrong_channel = _send(manager, out_of_scope["channel_id"], approved, adapter)

    assert wrong_hash["status"] == "approval_mismatch"
    assert wrong_version["status"] == "grant_mismatch"
    assert wrong_channel["status"] == "scope_mismatch"
    assert adapter.calls == []


def test_reply_budget_and_minimum_interval_are_enforced():
    manager = _manager()
    channel_id = _create(manager)
    _grant(manager, channel_id, max_replies=2, min_interval_sec=5.0)
    _inbound, first = _approved(manager, channel_id)
    adapter = FakeAdapter()
    assert _send(manager, channel_id, first, adapter)["status"] == "sent"

    _inbound2, second = _approved(
        manager, channel_id, "private_a_followup", cycle=7
    )
    limited = _send(manager, channel_id, second, adapter, cycle=9, now=101.0)
    assert limited["status"] == "rate_limited"
    assert len(adapter.calls) == 1

    approved_again = manager.approve(second["message_id"], cycle=10)
    assert _send(manager, channel_id, approved_again, adapter, now=106.0)["status"] == "sent"
    _inbound3, third = _approved(manager, channel_id, "group_a", cycle=12)
    exhausted = _send(manager, channel_id, third, adapter, now=112.0)
    assert exhausted["status"] == "limit_reached"
    assert len(adapter.calls) == 2


def test_message_budget_is_bounded_and_does_not_create_profiles_after_limit():
    manager = _manager()
    channel_id = _create(manager)
    _grant(manager, channel_id, max_messages=1)
    first = _ingest(manager, channel_id)
    before = manager.registry.to_dict()

    second = _ingest(manager, channel_id, "private_same_name_other_author", cycle=3)

    assert first["status"] == "quarantined"
    assert second["status"] == "limit_reached"
    assert manager.registry.to_dict() == before
    assert len(manager.messages) == 1
    assert MAX_MESSAGES_PER_CHANNEL >= 1


def test_adapter_error_is_sanitized_and_not_retried():
    manager = _manager()
    channel_id = _create(manager)
    _grant(manager, channel_id)
    _inbound, approved = _approved(manager, channel_id)
    adapter = FakeAdapter(fail=True)

    failed = _send(manager, channel_id, approved, adapter)
    repeated = _send(manager, channel_id, approved, adapter)

    assert failed["status"] == "send_failed"
    assert "sensitive adapter detail" not in failed["error"]
    assert repeated["status"] == "approval_required"
    assert len(adapter.calls) == 1


def test_restart_preserves_configuration_but_invalidates_approval_and_never_sends():
    source = DigitalBeing(name="SocialRestart9D")
    channel_id = _create(source.social_channels)
    _grant(source.social_channels, channel_id)
    _inbound, approved = _approved(source.social_channels, channel_id)
    state = build_state_from_agent(source)
    adapter = FakeAdapter()

    restored = DigitalBeing(name="SocialRestarted9D")
    apply_state_to_agent(restored, deepcopy(state))

    restored_draft = restored.social_channels._message(approved["message_id"])
    assert restored.social_channels.get_channel(channel_id)["grant"] == source.social_channels.get_channel(channel_id)["grant"]
    assert restored_draft["status"] == "draft"
    assert restored_draft["grant_version"] is None
    assert restored.social_channels.get_status()["workers"] == 0
    assert restored.social_channels.get_status()["automatic_resume"] is False
    assert _send(restored.social_channels, channel_id, approved, adapter)["status"] == "approval_required"
    assert adapter.calls == []


def test_legacy_checkpoint_gets_empty_closed_manager():
    source = DigitalBeing(name="SocialLegacy9D")
    state = build_state_from_agent(source)
    state.pop("social_channels")
    restored = DigitalBeing(name="SocialLegacyRestored9D")

    apply_state_to_agent(restored, state)

    assert restored.social_channels.to_dict() == SocialChannelManager(
        restored.social_registry
    ).to_dict()
    assert restored.social_channels.get_status()["channels"] == 0


def test_corrupted_social_snapshot_is_rejected_before_agent_mutation():
    agent = DigitalBeing(name="SocialAtomic9D")
    channel_id = _create(agent.social_channels)
    _grant(agent.social_channels, channel_id)
    _inbound, draft = _draft(agent.social_channels, channel_id)
    state = build_state_from_agent(agent)
    state["energy"] = 1.0
    state["social_channels"]["messages"][-1]["text"] = "tampered"
    before = build_state_from_agent(agent)

    with pytest.raises(ValueError, match="text_sha256"):
        apply_state_to_agent(agent, state)

    assert agent.energy == before["energy"]
    assert agent.social_channels.to_dict() == before["social_channels"]


def test_snapshot_rejects_secret_fields_and_cross_profile_scope():
    manager = _manager()
    channel_id = _create(manager)
    _grant(manager, channel_id)
    _inbound, draft = _draft(manager, channel_id)
    snapshot = manager.to_dict()
    snapshot["channels"][0]["token"] = "must-not-persist"

    with pytest.raises(ValueError, match="unexpected"):
        validate_social_channels(snapshot, manager.registry.to_dict())

    snapshot = manager.to_dict()
    snapshot["messages"][-1]["profile_id"] = manager.registry.owner_profile_id
    with pytest.raises(ValueError, match="profile_id"):
        validate_social_channels(snapshot, manager.registry.to_dict())


def test_life_snapshot_exposes_owner_capability_without_worker_or_credentials():
    agent = DigitalBeing(name="SocialSnapshot9D")
    channel_id = _create(agent.social_channels)
    _grant(agent.social_channels, channel_id)
    _inbound, draft = _draft(agent.social_channels, channel_id)

    section = build_life_snapshot(agent)["social_channels"]

    assert section["available"] is True
    assert section["can_manage"] is True
    assert section["workers"] == 0
    assert section["automatic_resume"] is False
    assert section["channels"][0]["channel_id"] == channel_id
    assert section["channels"][0]["pending_draft"]["message_id"] == draft["message_id"]
    assert "token" not in json.dumps(section).lower()
    assert "cookie" not in json.dumps(section).lower()

    agent.social_registry.create_local_person("Guest", cycle=5)
    assert build_life_snapshot(agent)["social_channels"]["can_manage"] is False


@pytest.mark.asyncio
async def test_runner_social_commands_are_owner_only_and_have_no_ingest_or_auto():
    agent = DigitalBeing(name="SocialCommands9D")
    runner = AgentRunner(agent, RecordingBus())

    created = await runner.handle_command("/social create fake | fixture-account")
    channel_id = agent.social_channels.channels[0]["channel_id"]
    grant = await runner.handle_command(
        f'/social grant {channel_id} | {{"conversation_ids":["fixture-private-a"],'
        '"receive":true,"draft":true,"reply":false,"max_messages":4,'
        '"max_replies":1,"min_interval_sec":0}'
    )
    denied_ingest = await runner.handle_command("/social ingest anything")
    denied_auto = await runner.handle_command(f"/social auto {channel_id}")

    assert "канал" in created.lower()
    assert "версия 2" in grant.lower()
    assert agent.social_channels.channels[0]["grant"]["receive"] is True
    assert agent.social_channels.channels[0]["grant"]["reply"] is False
    assert "Использование" in denied_ingest
    assert "Использование" in denied_auto

    agent.social_registry.create_local_person("Guest", cycle=2)
    denied = await runner.handle_command("/social status")
    assert "только владелец" in denied


def test_web_exposes_only_owner_social_controls_without_provider_tokens_or_send():
    assert 'id="social-channel-list"' in DASHBOARD_HTML
    assert "function renderSocialChannels(section)" in DASHBOARD_HTML
    assert "sendCommand('/api/social'" in DASHBOARD_HTML
    assert "action:'send'" not in DASHBOARD_HTML
    assert "action:'ingest'" not in DASHBOARD_HTML
    assert "social-token" not in DASHBOARD_HTML
    assert "social-cookie" not in DASHBOARD_HTML
