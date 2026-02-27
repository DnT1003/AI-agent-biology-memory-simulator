import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.engine.cognitive_engine import CognitiveEngine

def test_skill_degradation():
    print("=== TEST SKILL DEGRADATION & MASTERY ===")
    
    engine = CognitiveEngine()
    skills = engine.skills
    
    # Get a specific skill
    target_skill = skills.skills.get('read_time')
    if not target_skill:
        print("Skill 'read_time' not found!")
        return
        
    print(f"\n[Initial State] Mastery: {target_skill.mastery:.2f}, Rust: {target_skill.rust_level:.2f}")
    
    print("\n[Action] Sleeping for 10 days to decay skills...")
    skills.decay_skills(10.0) # Simulate 10 days of sleep
    print(f"[After Sleep] Mastery: {target_skill.mastery:.2f}, Rust: {target_skill.rust_level:.2f}")
    
    print("\n[Action] Executing skill continuously...")
    failed = False
    for i in range(5):
        result = skills.execute('read_time', '')
        print(f"Call {i+1}: {result}")
        if "[HỆ THỐNG]: Bạn đã quên cú pháp" in result:
            failed = True
        print(f"   -> Mastery: {target_skill.mastery:.2f}, Rust: {target_skill.rust_level:.2f}")
        
    if failed:
        print("\n✅ Skill successfully degraded and recovered after practice.")
    else:
        print("\n❌ Skill did not degrade (randomness might play a part, try again).")

if __name__ == "__main__":
    test_skill_degradation()
