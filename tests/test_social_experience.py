"""Ожидание ответа не является состоявшимся полезным взаимодействием."""

from unittest.mock import Mock

from src.core.agent import DigitalBeing
from src.core.evolve_pipeline import make_attachment_tick


def test_pending_question_does_not_create_attachment():
    agent = DigitalBeing(name="PendingContact")
    agent.user_interaction.pending_questions = [{"id": 1, "answered": False}]
    before = agent.attachment.get_status()
    middleware = make_attachment_tick()
    for cycle in range(20):
        middleware(agent, cycle, {})
    assert agent.attachment.get_status() == before


def test_accepted_answer_records_one_contact_not_each_evolve():
    agent = DigitalBeing(name="AcceptedContact")
    agent.user_interaction.get_pending_question = Mock(side_effect=[{"id": 12, "question": "память"}, None])
    agent.user_interaction.submit_answer = Mock(return_value={"status": "answered"})
    agent.thinking._process_user_answer("Память сохраняет опыт")
    assert agent.attachment.get_or_create("user").interactions == 1
    agent.thinking._process_user_answer("Память сохраняет опыт")
    for cycle in range(5):
        make_attachment_tick()(agent, cycle, {})
    assert agent.attachment.get_or_create("user").interactions == 1


def test_rejected_answer_does_not_create_contact_or_knowledge():
    agent = DigitalBeing(name="RejectedContact")
    agent.user_interaction.get_pending_question = Mock(return_value={"id": 12, "question": "новая тема"})
    agent.user_interaction.submit_answer = Mock(return_value={"status": "not_found"})
    before = set(agent.mental_models.concepts)
    agent.thinking._process_user_answer("Ответ")
    assert not agent.attachment._attachments
    assert set(agent.mental_models.concepts) == before
