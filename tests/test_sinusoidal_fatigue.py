import math
import random

print("Simulating 60 days of Fatigue Thresholds:")

for day in range(1, 61):
    base_fatigue_limit = 1.0 + 0.25 * math.sin((2 * math.pi / 30) * day)

    extreme_roll = random.random()
    is_extreme = ""
    if extreme_roll < 0.05:
        fatigue_critical = 2.0
        is_extreme = " (EXTREMELY STRONG)"
    elif extreme_roll < 0.15:
        fatigue_critical = 0.5
        is_extreme = " (EXTREMELY WEAK)"
    else:
        fatigue_critical = base_fatigue_limit

    print(f"Day {day:02d}: {fatigue_critical:.2f}{is_extreme}")
