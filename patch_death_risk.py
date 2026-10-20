with open('src/core/death_risk.py', 'r') as f:
    content = f.read()

old = """    def _auto_repair(self, dt: float):
        repair_rate = 0.001 * dt
        for attr in ['cognitive_coherence', 'memory_consistency', 
                    'value_stability', 'social_coherence']:
            current = getattr(self, attr)
            if current < 1.0:
                setattr(self, attr, min(1.0, current + repair_rate))
        self.corruption_accumulator = max(0.0, self.corruption_accumulator - repair_rate * 10)

    def check_death(self) -> Optional[DeathCause]:"""

new = """    def _auto_repair(self, dt: float):
        repair_rate = 0.001 * dt
        for attr in ['cognitive_coherence', 'memory_consistency', 
                    'value_stability', 'social_coherence']:
            current = getattr(self, attr)
            if current < 1.0:
                setattr(self, attr, min(1.0, current + repair_rate))
        self.corruption_accumulator = max(0.0, self.corruption_accumulator - repair_rate * 10)

    def manual_repair(self, intensity: float = 1.0) -> Dict:
        \"\"\"Принудительное восстановление целостности (вызывается действием repair).
        
        Args:
            intensity: сила восстановления (1.0 = базовое)
            
        Returns:
            Словарь с изменениями по компонентам
        \"\"\"
        repair_rate = 0.05 * intensity  # 5% за раз, намного сильнее auto_repair
        changes = {}
        for attr in ['cognitive_coherence', 'memory_consistency',
                    'value_stability', 'metabolic_viability', 'social_coherence']:
            current = getattr(self, attr)
            if current < 1.0:
                new_val = min(1.0, current + repair_rate)
                changes[attr] = new_val - current
                setattr(self, attr, new_val)
        
        # Также снижаем коррупцию
        old_corruption = self.corruption_accumulator
        self.corruption_accumulator = max(0.0, self.corruption_accumulator - repair_rate * 5)
        changes['corruption_accumulator'] = old_corruption - self.corruption_accumulator
        
        logger.log(f"[DEATH_RISK] Manual repair: {changes}")
        return changes

    def check_death(self) -> Optional[DeathCause]:"""

content = content.replace(old, new)

with open('src/core/death_risk.py', 'w') as f:
    f.write(content)
print('Done')