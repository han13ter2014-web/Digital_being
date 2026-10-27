"""Выбор конкретной работы не уничтожает другую и сохраняет причину оставления."""

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import build_state_from_agent, apply_state_to_agent


def test_select_previous_draft_and_keep_both_after_restore():
    agent = DigitalBeing(name="CatalogChoice")
    agent.act("create_draft", intention={"params": {"draft_mode": "new"}})
    first = dict(agent._creative_draft)
    agent.act("create_draft", intention={"params": {"draft_mode": "new"}})
    second = dict(agent._creative_draft)
    agent.act("create_draft", intention={"params": {"draft_id": first["id"]}})
    assert agent._creative_draft["id"] == first["id"]
    assert agent._creative_draft["revision"] == 2
    agent.leave_creative_draft("хочу оставить как есть")
    state = build_state_from_agent(agent)
    apply_state_to_agent(agent, state)
    catalog = {item["id"]: item for item in agent.list_creative_drafts()}
    assert len(catalog) == 2
    assert catalog[first["id"]]["leave_reason"] == "хочу оставить как есть"
    assert catalog[second["id"]]["revision"] == 1
    agent.act("create_draft", intention={"params": {"draft_id": second["id"]}})
    assert agent._creative_draft["revision"] == 2


def test_catalog_listing_does_not_expose_mutable_internal_state():
    agent = DigitalBeing(name="CatalogCopy")
    agent.act("create_draft")
    listed = agent.list_creative_drafts()
    listed[0]["theme"] = "changed"
    assert agent.list_creative_drafts()[0]["theme"] != "changed"
