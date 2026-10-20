"""Тест сохранения и восстановления чекпоинтов"""

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import build_state_from_agent, apply_state_to_agent, CheckpointSerializer

# Создаем агента и меняем его состояние
a = DigitalBeing('Test')
a.interoception.state.fatigue = 0.5
a.interoception.step(cognitive_load=0)
a.death_risk.integrity.corruption_accumulator = 0.2

# Запускаем несколько циклов
for _ in range(5):
    a.autonomous_tick()

# Сохраняем
state = build_state_from_agent(a)
print('Saved meta cycle_counter:', state.get('meta_learning', {}).get('cycle_counter'))
print('Saved death_risk corruption:', state.get('death_risk', {}).get('corruption_accumulator'))
print('Saved interoception fatigue:', state.get('interoception', {}).get('fatigue'))

serializer = CheckpointSerializer()
serializer.save(state, 'Test', 10)

# Восстанавливаем в новом агенте
b = DigitalBeing('Test2')
apply_state_to_agent(b, state)

print()
print('Restored meta cycle_counter:', b.meta_learner.cycle_counter)
print('Restored death_risk corruption:', b.death_risk.integrity.corruption_accumulator)
print('Restored interoception fatigue:', b.interoception.state.fatigue)
print('Restored continuous_time dilation:', b.continuous_time.subjective_time.dilation)