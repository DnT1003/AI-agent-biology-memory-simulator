import subprocess
import sys
from colorama import Fore, Style

def run_test(script_path):
    print(f"\n{Fore.YELLOW}🚀 Running: {script_path}{Style.RESET_ALL}")
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = "d:\\python\\PythonProject15"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            env=env,
            capture_output=True,
            encoding="utf-8",
            check=True
        )
        print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"{Fore.RED}❌ FAILED: {script_path}{Style.RESET_ALL}")
        print(f"STDOUT:\n{e.stdout}")
        print(f"STDERR:\n{e.stderr}")
        return False

def main():
    print(f"{Fore.CYAN}==========================================")
    print("🌟 FINAL SYSTEM AUDIT - SPRINT A, B, C, D 🌟")
    print(f"=========================================={Style.RESET_ALL}")
    
    tests = [
        "tests/verify_a1_decay.py",
        "tests/verify_a2_sleep_logic.py",
        "tests/verify_b1_social.py",
        "tests/verify_b2_budgeting.py",
        "tests/verify_b3_fog.py",
        "tests/verify_c1_reflection.py",
        "tests/verify_c2_dopamine.py",
        "tests/verify_d1_storage.py"
    ]
    
    results = {}
    for test in tests:
        results[test] = run_test(test)
        
    print(f"\n{Fore.CYAN}--- FINAL REPORT ---{Style.RESET_ALL}")
    all_passed = True
    for test, passed in results.items():
        status = f"{Fore.GREEN}PASSED{Style.RESET_ALL}" if passed else f"{Fore.RED}FAILED{Style.RESET_ALL}"
        print(f"{test}: {status}")
        if not passed:
            all_passed = False
            
    if all_passed:
        print(f"\n{Fore.LIGHTGREEN_EX}🏆 ALL SYSTEMS GO! Aura is fully evolved and stable.{Style.RESET_ALL}")
    else:
        print(f"\n{Fore.LIGHTRED_EX}⚠️ Some systems require attention. Check logs above.{Style.RESET_ALL}")

if __name__ == "__main__":
    main()
