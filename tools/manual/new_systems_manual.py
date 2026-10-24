"""Тест новых систем (Этап 4)"""

from src.core.agent import DigitalBeing

def test_all_systems():
    a = DigitalBeing('Test')
    print("=== Starting 20 cycles ===")
    
    for i in range(20):
        r = a.autonomous_tick()
        if i % 5 == 0:
            integrity = r["death_risk"]["integrity"]["overall_integrity"]
            fatigue = r["interoception"]["fatigue"]
            needs_rest = r["interoception"]["needs_rest"]
            dilation = r["continuous_time"]["time_dilation"]
            fitness = r["meta_learning"]["current_fitness"]
            print(f'Cycle {i}: integrity={integrity:.3f}, fatigue={fatigue:.3f}, needs_rest={needs_rest}, dilation={dilation:.2f}, fitness={fitness:.3f}')
    
    print("=== Done ===")
    
    # Тест social cell
    print("\n=== Social Cell Test ===")
    a.social_cell.register_agent('user', {'goals': {'help': 0.8}})
    for _ in range(3):
        obs = {'action': 'help', 'reaction_to_us': 'trust', 'timestamp': 1}
        a.social_cell.observe_interaction('user', obs)
    pred = a.social_cell.predict_behavior('user')
    print(f"Predicted behavior: {pred}")
    
    # Тест capture_structural_state
    print("\n=== Structural State ===")
    state = a.capture_structural_state()
    print(f"Structural hash: {state['structural_hash']}")
    print(f"Integrity: {state['integrity_score']}")
    
    # Тест verify checkpoint
    print("\n=== Checkpoint Verification ===")
    a.death_risk.force_checkpoint()
    verify = a.death_risk.verify_integrity()
    print(f"Verified: {verify}")
    
    print("\n=== All tests passed! ===")

if __name__ == "__main__":
    test_all_systems()