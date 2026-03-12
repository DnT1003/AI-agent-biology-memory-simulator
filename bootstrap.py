import os
import subprocess
import sys
import shutil

def run_command(cmd):
    print(f"Executing: {cmd}")
    try:
        subprocess.check_call(cmd, shell=True)
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {e}")
        return False
    return True

def is_venv_valid(venv_path):
    python_exe = os.path.join(venv_path, "Scripts", "python.exe") if os.name == "nt" else os.path.join(venv_path, "bin", "python")
    if not os.path.exists(python_exe):
        return False
    try:
        # Check if python can actually run
        subprocess.check_call([python_exe, "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

def main():
    print("=== Aura Bootstrap & Recovery Tool ===")
    
    force_recreate = "--force" in sys.argv
    
    # Standard venvs to manage
    venvs = [".venv", ".venv_aura"]
    
    for venv in venvs:
        if os.path.exists(venv):
            if force_recreate or not is_venv_valid(venv):
                print(f"Removing broken or old venv: {venv}")
                shutil.rmtree(venv, ignore_errors=True)
        
        if not os.path.exists(venv):
            print(f"Creating virtual environment: {venv}")
            if not run_command(f"{sys.executable} -m venv {venv}"):
                print(f"Failed to create {venv}. Please ensure Python 3.12+ is installed.")
                continue
    
    # 2. Install dependencies (standard .venv for engine)
    pip_path = os.path.join(".venv", "Scripts", "pip.exe") if os.name == "nt" else os.path.join(".venv", "bin", "pip")
    if os.path.exists(pip_path):
        print("Installing main engine dependencies...")
        run_command(f"{pip_path} install .")
    
    # 3. Install SLM dependencies (.venv_aura for Torch/GPU work)
    pip_aura = os.path.join(".venv_aura", "Scripts", "pip.exe") if os.name == "nt" else os.path.join(".venv_aura", "bin", "pip")
    if os.path.exists(pip_aura):
        print("Installing SLM (Torch) dependencies...")
        # Since we use pyproject.toml now, we can install the same set or specialized ones
        run_command(f"{pip_aura} install .")

    # 4. Setup .env if not exists
    if not os.path.exists(".env"):
        print("Initializing .env from .env.example...")
        if os.path.exists(".env.example"):
            shutil.copy(".env.example", ".env")
        else:
            with open(".env", "w") as f:
                f.write("API_KEY=your_gemini_key_here\nMODEL_NAME=gemini-3.0-flash\n")

    print("\n[SUCCESS] Aura environment is repaired/initialized!")
    print("1. Run services: .\\start_services.ps1")
    print("2. Run Aura: .\\.venv\\Scripts\\python.exe main.py")
    print("3. Eval SLM: .\\.venv_aura\\Scripts\\python.exe scripts/eval_slm.py")

if __name__ == "__main__":
    main()
