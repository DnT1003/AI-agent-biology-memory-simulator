import threading
import time
import sys
import os

# Add project root to sys.path
sys.path.append(os.getcwd())

from core.self_model import SelfModel

def test_stress_updates():
    print(f"Starting Stress Test on Python {sys.version}")
    ego = SelfModel()
    ego.stress = 0.0
    
    num_threads = 20
    increments_per_thread = 1000
    delta = 0.0001
    
    def worker():
        for _ in range(increments_per_thread):
            # Using the new atomic adjust method
            ego.adjust_attribute("stress", delta, max_val=10.0) # Using large max for testing increments
            
    threads = []
    start_time = time.time()
    
    for _ in range(num_threads):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    end_time = time.time()
    
    expected = num_threads * increments_per_thread * delta
    actual = ego.stress
    
    print(f"Test Duration: {end_time - start_time:.4f}s")
    print(f"Expected Stress: {expected:.4f}")
    print(f"Actual Stress:   {actual:.4f}")
    
    if abs(expected - actual) < 1e-7:
        print("RESULT: PASSED (No lost updates)")
    else:
        print(f"RESULT: FAILED (Diff: {abs(expected - actual):.7f})")
        print("Note: In Python < 3.14 with GIL, this might still pass due to attribute access being atomic-ish, but 3.14 free-threading would fail without proper locking.")

if __name__ == "__main__":
    test_stress_updates()
