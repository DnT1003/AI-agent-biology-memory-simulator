@echo off
setlocal
if /I "%~1"=="--print-chroma-path" goto :print_chroma_path

echo ===================================================
echo   AURA-FLASH: CHROMA DB REST SERVER (PHASE 4.1)
echo ===================================================
echo WARNING: Xin hay chac chan ban dang chay terminal nay
echo bang moi truong Python 3.12 (hoac thap hon), KHONG 
echo phai Python 3.14!
echo.
for /f "usebackq delims=" %%P in (`call "%~f0" --print-chroma-path`) do set "CHROMA_PATH=%%P"
if not defined CHROMA_PATH exit /b 1
echo Khoi tao Chroma DB tai: %CHROMA_PATH%
chroma run --path "%CHROMA_PATH%" --port 8000
pause
exit /b %ERRORLEVEL%

:print_chroma_path
python -B -c "import os, sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from core.runtime_paths import RuntimePaths; env=os.environ; paths=RuntimePaths.from_env(base_dir=Path(sys.argv[1]).resolve(), env=env); explicit=isinstance(env.get('AURA_DATA_DIR'), str) and bool(env['AURA_DATA_DIR'].strip()); print(paths.memory_chroma_dir if explicit else paths.data_dir / 'chroma_db')" "%~dp0.."
exit /b %ERRORLEVEL%
