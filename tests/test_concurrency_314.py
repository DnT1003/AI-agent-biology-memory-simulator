import sys
from concurrent.futures import ThreadPoolExecutor
import time
import threading

def metabolism_task():
    print("Metabolism loop: High-frequency checking drives...")
    for i in range(5):
        time.sleep(0.5)
        print(f"  Metabolism tick {i+1} at {time.time()}")

def llm_cog_task():
    print("LLM Task: Artificial heavy processing (JSON parsing)...")
    # Simulate heavy GIL-locking work in standard builds
    start = time.time()
    while time.time() - start < 2:
        pass # Busy wait
    print(f"LLM Task completed at {time.time()}")

print(f"Running on Python {sys.version}")
print(f"Free-threaded mode: {getattr(sys, '_is_free_threaded', lambda: False)()}")

# In standard Python, llm_cog_task (busy wait) will block metabolism_task or slow it down
# In free-threaded Python, they should run independently on separate cores.

with ThreadPoolExecutor(max_workers=2) as executor:
    executor.submit(metabolism_task)
    executor.submit(llm_cog_task)

print("Test finished.")
