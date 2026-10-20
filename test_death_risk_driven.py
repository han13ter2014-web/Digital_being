"""Тест Death Risk driven behavior"""

from src.core.agent import DigitalBeing

a = DigitalBeing('Test')

# Устанавливаем критическую целостность
a.death_risk.integrity.cognitive_coherence = 0.2
a.death_risk.integrity.memory_consistency = 0.2
a.death_risk.integrity.value_stability = 0.2
a.death_risk.integrity.metabolic_viability = 0.2
a.death_risk.integrity.social_coherence = 0.2

a.energy = 100
a.interoception.state.fatigue = 0.8
a.interoception.step(cognitive_load=0)

print(f'Initial integrity: {a.death_risk.integrity.compute_overall_integrity():.3f}')
print(f'Initial fatigue: {a.interoception.state.fatigue:.3f}')

for i in range(5):
    r = a.autonomous_tick()
    dr = r.get("death_risk", {})
    integrity = dr.get("integrity", {}).get("overall_integrity", dr.get("overall_integrity", 0))
    action = r.get("active_inference", {}).get("action_result") or r.get("action")
    fatigue = r.get("interoception", {}).get("fatigue", 0)
    print(f'Cycle {i}: action={action}, integrity={integrity:.3f}, fatigue={fatigue:.3f}')