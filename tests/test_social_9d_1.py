"""9D-1: ручной Telegram sandbox поверх frozen offline Bot API fixtures."""

from copy import deepcopy
import json
from pathlib import Path
import socket
import urllib.error

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.external_credentials import credential_target
from src.core.social_channels import SocialChannelManager
from src.core.social_registry import SocialRegistry
from src.core.telegram_channel import (
    MAX_WIRE_BYTES,
    TelegramChannelAdapter,
    TelegramChannelError,
    _urllib_transport,
    create_social_adapter,
)
from src.ui.web_dashboard import DASHBOARD_HTML

FIXTURES = Path(__file__).parent / "fixtures" / "social_9d_1"
RESPONSES = json.loads((FIXTURES / "responses.json").read_text(encoding="utf-8"))
CREDENTIAL_REF = credential_target("telegram")
FAKE_TOKEN = "synthetic-token-not-a-secret"


@pytest.fixture(autouse=True)
def isolated_offline_data(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "data"))

    def no_network(*args, **kwargs):
        raise AssertionError("9D-1 tests must remain offline")

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


class FrozenTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, *, url, payload, headers, timeout):
        self.calls.append(
            {
                "url": url,
                "payload": deepcopy(payload),
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        if not self.responses:
            raise AssertionError("unexpected Telegram transport call")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return deepcopy(response)


class FakeSocialAdapter:
    def __init__(self, updates=None):
        self.updates = deepcopy(updates or [])
        self.receive_calls = []
        self.send_calls = []

    def get_updates(self, *, offset, limit):
        self.receive_calls.append({"offset": offset, "limit": limit})
        return deepcopy(self.updates)

    def send(self, *, channel_id, conversation_id, message_id, in_reply_to, text):
        self.send_calls.append(
            {
                "channel_id": channel_id,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "in_reply_to": in_reply_to,
                "text": text,
            }
        )
        return {
            "status": "sent",
            "channel_id": channel_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "external_message_id": "900",
        }


def private_update(update_id=100):
    update = deepcopy(RESPONSES["private_text"]["result"][0])
    update["update_id"] = update_id
    return {
        "update_id": update_id,
        "kind": "private_text",
        "conversation_id": str(update["message"]["chat"]["id"]),
        "author_id": str(update["message"]["from"]["id"]),
        "message_id": str(update["message"]["message_id"]),
        "text": update["message"]["text"],
        "display_name": update["message"]["from"]["first_name"],
    }


def _manager():
    return SocialChannelManager(SocialRegistry())


def _create(manager, *, provider="telegram", account_id="424242"):
    result = manager.create_channel(provider=provider, account_id=account_id, cycle=0)
    assert result["status"] == "created"
    return result["channel_id"]


def _grant(manager, channel_id, *, receive=True, reply=True, scopes=None, cycle=1):
    result = manager.update_grant(
        channel_id,
        conversation_ids=scopes or ["777"],
        receive=receive,
        draft=True,
        reply=reply,
        max_messages=16,
        max_replies=4,
        min_interval_sec=0.0,
        cycle=cycle,
    )
    assert result["status"] == "updated"
    return result


def _adapter(transport, *, credential_calls=None):
    def load(reference):
        if credential_calls is not None:
            credential_calls.append(reference)
        return FAKE_TOKEN

    return TelegramChannelAdapter(
        credential_ref=CREDENTIAL_REF,
        account_id="424242",
        credential_loader=load,
        transport=transport,
        timeout=5.0,
    )


def _receive_with_fixture(manager, channel_id, transport):
    return manager.receive(channel_id, adapter=_adapter(transport), cycle=2)


def _approved(manager, channel_id, adapter):
    received = manager.receive(channel_id, adapter=adapter, cycle=2)
    assert received["status"] == "received"
    inbound_id = received["message_ids"][0]
    draft = manager.create_draft(channel_id, inbound_id, cycle=3)
    assert draft["status"] == "draft"
    edited = manager.edit_draft(draft["message_id"], "Exact owner reply", cycle=4)
    approved = manager.approve(edited["message_id"], cycle=5)
    assert approved["status"] == "approved"
    return approved


def test_telegram_channel_persists_only_reference_and_cursor_and_loads_legacy():
    manager = _manager()
    channel_id = _create(manager)
    channel = manager.get_channel(channel_id)

    assert channel["credential_ref"] == CREDENTIAL_REF
    assert channel["update_cursor"] is None
    encoded = json.dumps(manager.to_dict())
    assert FAKE_TOKEN not in encoded
    assert "token" not in encoded.lower()

    legacy = manager.to_dict()
    del legacy["channels"][0]["credential_ref"]
    del legacy["channels"][0]["update_cursor"]
    restored = _manager()
    restored.load_from(legacy, manager.registry.to_dict())
    assert restored.get_channel(channel_id)["credential_ref"] == CREDENTIAL_REF
    assert restored.get_channel(channel_id)["update_cursor"] is None


def test_non_telegram_channel_cannot_claim_cursor_or_credential_reference():
    manager = _manager()
    _create(manager, provider="fake", account_id="fixture-account")
    snapshot = manager.to_dict()
    snapshot["channels"][0]["credential_ref"] = CREDENTIAL_REF
    with pytest.raises(ValueError, match="credential_ref"):
        manager.load_from(snapshot, manager.registry.to_dict())

    snapshot = manager.to_dict()
    snapshot["channels"][0]["update_cursor"] = 10
    with pytest.raises(ValueError, match="update_cursor"):
        manager.load_from(snapshot, manager.registry.to_dict())


def test_adapter_loads_credential_lazily_and_maps_only_private_text():
    transport = FrozenTransport(RESPONSES["private_text"])
    credential_calls = []
    adapter = _adapter(transport, credential_calls=credential_calls)
    assert credential_calls == []

    updates = adapter.get_updates(offset=None, limit=16)

    assert credential_calls == [CREDENTIAL_REF]
    assert updates == [private_update()]
    call = transport.calls[0]
    assert call["url"].startswith("https://api.telegram.org/bot")
    assert call["url"].endswith("/getUpdates")
    assert call["payload"] == {
        "limit": 16,
        "timeout": 0,
        "allowed_updates": ["message"],
    }
    assert call["timeout"] == 5.0
    assert "token" not in call["headers"]


def test_manual_receive_quarantines_text_and_advances_cursor_without_reply():
    manager = _manager()
    channel_id = _create(manager)
    _grant(manager, channel_id)
    transport = FrozenTransport(RESPONSES["private_text"], RESPONSES["empty"])

    first = _receive_with_fixture(manager, channel_id, transport)
    second = _receive_with_fixture(manager, channel_id, transport)

    assert first["status"] == "received"
    assert first["received"] == 1
    assert first["update_cursor"] == 100
    assert second["status"] == "no_updates"
    assert transport.calls[1]["payload"]["offset"] == 101
    message = manager._message(first["message_ids"][0])
    assert message["claim_type"] == "external_social_claim"
    assert message["status"] == "quarantined"
    assert message["external_message_id"] == "10"
    assert manager.get_status()["sent"] == 0
    assert len(transport.calls) == 2


def test_replayed_update_is_duplicate_and_never_moves_cursor_backward():
    manager = _manager()
    channel_id = _create(manager)
    _grant(manager, channel_id)
    adapter = FakeSocialAdapter([private_update()])

    first = manager.receive(channel_id, adapter=adapter, cycle=2)
    second = manager.receive(channel_id, adapter=adapter, cycle=3)

    assert first["received"] == 1
    assert second["duplicates"] == 1
    assert second["update_cursor"] == 100
    assert len(manager.messages) == 1
    assert adapter.receive_calls[1]["offset"] == 101


def test_group_media_public_and_out_of_scope_are_acknowledged_without_profiles():
    manager = _manager()
    channel_id = _create(manager)
    _grant(manager, channel_id)
    owner = manager.registry.owner_profile_id
    updates = [
        {"update_id": 101, "kind": "ignored", "reason": "group"},
        {"update_id": 102, "kind": "ignored", "reason": "non_text"},
        {"update_id": 103, "kind": "ignored", "reason": "public_post"},
        private_update(104),
    ]
    updates[-1]["conversation_id"] = "888"
    adapter = FakeSocialAdapter(updates)

    result = manager.receive(channel_id, adapter=adapter, cycle=2)

    assert result["status"] == "received"
    assert result["received"] == 0
    assert result["ignored"] == 4
    assert result["update_cursor"] == 104
    assert manager.messages == []
    assert list(manager.registry.profiles) == [owner]


def test_malformed_update_and_transport_failure_do_not_advance_cursor():
    manager = _manager()
    channel_id = _create(manager)
    _grant(manager, channel_id)
    malformed = FakeSocialAdapter([{"kind": "private_text"}])

    invalid = manager.receive(channel_id, adapter=malformed, cycle=2)
    failed_transport = FrozenTransport(TelegramChannelError("timeout"))
    failed = _receive_with_fixture(manager, channel_id, failed_transport)

    assert invalid == {"status": "invalid_update", "error": "invalid_update"}
    assert failed == {"status": "transport_error", "error": "timeout"}
    assert manager.get_channel(channel_id)["update_cursor"] is None
    assert manager.messages == []


def test_receive_permission_revoke_stop_and_limit_are_checked_before_network():
    manager = _manager()
    channel_id = _create(manager)
    adapter = FakeSocialAdapter([private_update()])

    denied = manager.receive(channel_id, adapter=adapter, cycle=1)
    assert denied["status"] == "permission_denied"
    _grant(manager, channel_id, receive=False)
    assert (
        manager.receive(channel_id, adapter=adapter, cycle=2)["status"]
        == "permission_denied"
    )
    _grant(manager, channel_id, receive=True, cycle=3)
    manager.revoke(channel_id, cycle=4, reason="offline test")
    assert (
        manager.receive(channel_id, adapter=adapter, cycle=5)["status"]
        == "permission_denied"
    )
    _grant(manager, channel_id, cycle=6)
    manager.stop(channel_id, cycle=7, reason="offline test")
    assert (
        manager.receive(channel_id, adapter=adapter, cycle=8)["status"]
        == "channel_stopped"
    )
    assert adapter.receive_calls == []


def test_receive_rejects_wrong_provider_and_unbounded_limit_before_adapter():
    manager = _manager()
    channel_id = _create(manager, provider="fake", account_id="fixture-account")
    _grant(manager, channel_id, scopes=["777"])
    adapter = FakeSocialAdapter([private_update()])

    unsupported = manager.receive(channel_id, adapter=adapter, cycle=2)
    telegram_id = _create(manager)
    _grant(manager, telegram_id)
    invalid_limit = manager.receive(telegram_id, adapter=adapter, cycle=2, limit=1000)

    assert unsupported["status"] == "unsupported_provider"
    assert invalid_limit["status"] == "invalid_limit"
    assert adapter.receive_calls == []


def test_send_uses_only_exact_approved_revision_and_verifies_telegram_receipt():
    manager = _manager()
    channel_id = _create(manager)
    _grant(manager, channel_id)
    transport = FrozenTransport(RESPONSES["private_text"], RESPONSES["send_success"])
    adapter = _adapter(transport)
    approved = _approved(manager, channel_id, adapter)

    sent = manager.send(
        channel_id,
        approved["message_id"],
        adapter=adapter,
        cycle=6,
        now=100.0,
        expected_text_sha256=approved["text_sha256"],
        expected_grant_version=approved["grant_version"],
    )

    assert sent["status"] == "sent"
    assert sent["external_message_id"] == "900"
    payload = transport.calls[1]["payload"]
    assert payload == {
        "chat_id": 777,
        "text": "Exact owner reply",
        "reply_parameters": {"message_id": 10, "allow_sending_without_reply": False},
    }
    assert transport.calls[1]["url"].endswith("/sendMessage")


def test_telegram_receipt_mismatch_is_not_delivery_and_does_not_leak_details():
    manager = _manager()
    channel_id = _create(manager)
    _grant(manager, channel_id)
    transport = FrozenTransport(RESPONSES["private_text"], RESPONSES["send_wrong_chat"])
    adapter = _adapter(transport)
    approved = _approved(manager, channel_id, adapter)

    failed = manager.send(
        channel_id,
        approved["message_id"],
        adapter=adapter,
        cycle=6,
        now=100.0,
        expected_text_sha256=approved["text_sha256"],
        expected_grant_version=approved["grant_version"],
    )

    assert failed["status"] == "send_failed"
    assert manager.get_channel(channel_id)["sent_count"] == 0
    assert FAKE_TOKEN not in failed["error"]
    assert "888" not in failed["error"]


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (
            urllib.error.HTTPError("https://secret.invalid", 401, "secret", {}, None),
            "authentication_failed",
        ),
        (
            urllib.error.HTTPError("https://secret.invalid", 403, "secret", {}, None),
            "authentication_failed",
        ),
        (
            urllib.error.HTTPError("https://secret.invalid", 429, "secret", {}, None),
            "rate_limited",
        ),
        (TimeoutError("secret timeout detail"), "timeout"),
        (
            {"ok": False, "error_code": 403, "description": FAKE_TOKEN},
            "authentication_failed",
        ),
        ({"ok": True, "result": "not-a-list"}, "invalid_response"),
        (RESPONSES["malformed_private"], "invalid_update"),
    ],
)
def test_telegram_failures_have_bounded_safe_codes(response, code):
    transport = FrozenTransport(response)
    adapter = _adapter(transport)

    with pytest.raises(TelegramChannelError) as caught:
        adapter.get_updates(offset=None, limit=16)

    assert caught.value.code == code
    assert str(caught.value) == code
    assert FAKE_TOKEN not in str(caught.value)
    assert "secret" not in str(caught.value)


def test_frozen_group_media_public_and_malformed_updates_are_classified_offline():
    grouped = _adapter(FrozenTransport(RESPONSES["mixed_out_of_scope"])).get_updates(
        offset=None, limit=16
    )
    public = _adapter(FrozenTransport(RESPONSES["public_post"])).get_updates(
        offset=None, limit=16
    )

    assert [item["kind"] for item in grouped] == ["ignored", "ignored", "private_text"]
    assert grouped[0]["reason"] == "group"
    assert grouped[1]["reason"] == "non_text"
    assert public == [{"update_id": 105, "kind": "ignored", "reason": "public_post"}]


def test_restart_preserves_cursor_but_invalidates_approval_and_never_calls_api():
    source = DigitalBeing(name="TelegramRestart9D1")
    channel_id = _create(source.social_channels)
    _grant(source.social_channels, channel_id)
    adapter = FakeSocialAdapter([private_update()])
    approved = _approved(source.social_channels, channel_id, adapter)
    state = build_state_from_agent(source)
    assert state["social_channels"]["channels"][0]["update_cursor"] == 100

    restored = DigitalBeing(name="TelegramRestored9D1")
    apply_state_to_agent(restored, deepcopy(state))

    channel = restored.social_channels.get_channel(channel_id)
    assert channel["credential_ref"] == CREDENTIAL_REF
    assert channel["update_cursor"] == 100
    assert (
        restored.social_channels._message(approved["message_id"])["status"] == "draft"
    )
    assert len(adapter.receive_calls) == 1
    assert adapter.send_calls == []


@pytest.mark.asyncio
async def test_runner_receive_and_send_are_manual_owner_only_and_reuse_approval_checks():
    agent = DigitalBeing(name="TelegramCommands9D1")
    runner = AgentRunner(agent, RecordingBus())
    adapter = FakeSocialAdapter([private_update()])
    runner._social_adapter_factory = lambda *args, **kwargs: adapter

    created = await runner.handle_command("/social create telegram | 424242")
    channel_id = agent.social_channels.channels[0]["channel_id"]
    await runner.handle_command(
        f'/social grant {channel_id} | {{"conversation_ids":["777"],'
        '"receive":true,"draft":true,"reply":true,"max_messages":4,'
        '"max_replies":1,"min_interval_sec":0}'
    )
    received = await runner.handle_command(f"/social receive {channel_id}")
    inbound_id = agent.social_channels.messages[0]["message_id"]
    await runner.handle_command(f"/social draft {channel_id} {inbound_id}")
    draft_id = agent.social_channels.messages[-1]["message_id"]
    await runner.handle_command(f"/social approve {draft_id}")
    sent = await runner.handle_command(f"/social send {channel_id} {draft_id}")

    assert "канал" in created.lower()
    assert "принято" in received.lower()
    assert "отправлено" in sent.lower()
    assert len(adapter.receive_calls) == 1
    assert len(adapter.send_calls) == 1

    agent.social_registry.create_local_person("Guest", cycle=8)
    denied = await runner.handle_command(f"/social receive {channel_id}")
    denied_send = await runner.handle_command(f"/social send {channel_id} {draft_id}")
    assert "только владелец" in denied
    assert "только владелец" in denied_send
    assert len(adapter.receive_calls) == 1
    assert len(adapter.send_calls) == 1


def test_provider_factory_is_fixed_to_telegram():
    adapter = create_social_adapter(
        "telegram",
        credential_ref=CREDENTIAL_REF,
        account_id="424242",
        credential_loader=lambda reference: FAKE_TOKEN,
        transport=FrozenTransport(RESPONSES["empty"]),
    )
    assert isinstance(adapter, TelegramChannelAdapter)
    with pytest.raises(TelegramChannelError, match="unsupported_provider"):
        create_social_adapter("fake", credential_ref=None, account_id="fixture")


def test_web_exposes_manual_telegram_controls_without_secret_input_or_automation():
    assert 'id="social-receive-once"' in DASHBOARD_HTML
    assert 'id="social-send-approved"' in DASHBOARD_HTML
    assert "socialChannelCommand('receive')" in DASHBOARD_HTML
    assert "socialChannelCommand('send'" in DASHBOARD_HTML
    assert "social-token" not in DASHBOARD_HTML
    assert "social-cookie" not in DASHBOARD_HTML
    assert "social auto" not in DASHBOARD_HTML
    assert "setInterval(()=>socialChannelCommand" not in DASHBOARD_HTML


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b"{not-json", "invalid_response"),
        (b"x" * (MAX_WIRE_BYTES + 1), "response_too_large"),
    ],
    ids=["malformed_json", "oversized"],
)
def test_raw_transport_rejects_malformed_json_and_oversized_response_offline(
    monkeypatch, raw, code
):
    class RawResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return raw[:limit]

    class FakeOpener:
        def open(self, request, timeout):
            return RawResponse()

    monkeypatch.setattr(
        "src.core.telegram_channel.urllib.request.build_opener",
        lambda *args: FakeOpener(),
    )

    with pytest.raises(TelegramChannelError) as caught:
        _urllib_transport(
            url="https://api.telegram.org/botSynthetic/getUpdates",
            payload={"limit": 1},
            headers={},
            timeout=1.0,
        )

    assert caught.value.code == code


def test_in_scope_limit_leaves_update_unacknowledged_for_later_review():
    manager = _manager()
    channel_id = _create(manager)
    _grant(manager, channel_id)
    grant = manager.get_channel(channel_id)["grant"]
    manager.update_grant(
        channel_id,
        conversation_ids=grant["conversation_ids"],
        receive=True,
        draft=True,
        reply=True,
        max_messages=0,
        max_replies=4,
        min_interval_sec=0.0,
        cycle=2,
    )
    adapter = FakeSocialAdapter([private_update()])

    result = manager.receive(channel_id, adapter=adapter, cycle=3)

    assert result["status"] == "limit_reached"
    assert result["update_cursor"] is None
    assert manager.messages == []
    assert len(adapter.receive_calls) == 1
