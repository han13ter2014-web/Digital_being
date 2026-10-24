"""Test synthesis flow end-to-end with ThinkingPipeline."""
from src.core.agent import DigitalBeing
from src.perception.user_interaction import UserInteraction

# Create agent
agent = DigitalBeing('TestBaby')

# First, let's simulate the decomposition by putting some sub-concepts into mental models
# This is what would happen during the agent's own thinking
agent.mental_models.encounter_concept(
    concept_name="понимаешь",
    context="test",
    outcome="Понимать — значит интегрировать информацию в свою модель мира и улавливать смысл.",
    valence=0.8
)
agent.mental_models.encounter_concept(
    concept_name="меня",
    context="test",
    outcome="Меня — это личность, субъект переживаний, обладающий самосознанием.",
    valence=0.8
)

# Now simulate what happens when the agent processes a user answer
# that completes all sub-questions for a complex question

# First, we need to simulate the thinking pipeline asking the sub-questions
# This mimics what _try_ask_user_about_complex does
result = agent.user_interaction.ask_user(
    question="Я изучаю концепцию 'Ты меня понимаешь?'. Мне сложно понять без внешней помощи. Можете кратко объяснить: что такое понимаешь?",
    context="Концепция: Ты меня понимаешь?, под-запросы: что такое понимаешь; что такое меня",
    cycle=100,
    complex_question="Ты меня понимаешь?",
    sub_questions=["что такое понимаешь", "что такое меня"],
    sub_question_index=0
)
print('First ask result:', result)

pending = agent.user_interaction.get_pending_question()
print('Pending:', pending['question'][:60] + '...')

# NOW use the actual thinking pipeline's callback
# This is what _process_user_answer passes to submit_answer
def on_synthesis(q, a):
    print(f'\n>>> SYNTHESIS TRIGGERED for: {q}')
    print(f'>>> Sub-answers: {a}')
    # Call the actual synthesis method
    agent.thinking._synthesize_complex_question(q, a)

# Submit answer to first sub-question
answer_result = agent.user_interaction.submit_answer(
    pending['id'],
    'Понимать — значит улавливать смысл слов.',
    on_synthesis_needed=on_synthesis
)
print('Answer 1 result:', answer_result)

# Check if next sub-question was queued
pending2 = agent.user_interaction.get_pending_question()
print('Pending after answer 1:', pending2['question'][:60] + '...' if pending2 else 'None')

# Submit answer to second sub-question
if pending2:
    answer_result2 = agent.user_interaction.submit_answer(
        pending2['id'],
        'Меня — это личность или субъект.',
        on_synthesis_needed=on_synthesis
    )
    print('Answer 2 result:', answer_result2)

print('\n=== Checking mental models after synthesis ===')
# Check if the complex question was synthesized into mental models
complex_node = agent.mental_models.concepts.get("Ты меня понимаешь?")
if complex_node:
    print(f'SUCCESS! Complex question synthesized:')
    # Use definition_hypothesis or latest experience
    definition = complex_node.definition_hypothesis or (
        complex_node.experiences[-1]["outcome"] if complex_node.experiences else ""
    )
    print(f'  Definition: {definition[:150]}...')
    print(f'  Confidence: {complex_node.confidence:.0%}')
    # Note: ConceptNode doesn't have valence directly, it's in experiences
    latest_valence = complex_node.experiences[-1]["valence"] if complex_node.experiences else "N/A"
    print(f'  Latest valence: {latest_valence}')
else:
    print('Complex question NOT yet in mental models (synthesis runs asynchronously)')

print('\nQuestion history:')
for h in agent.user_interaction.question_history:
    print(f'  Q: {h["question"][:60]}...')
    print(f'  A: {h["answer"][:60]}...')