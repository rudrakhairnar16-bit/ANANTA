@echo off
setlocal enabledelayedexpansion

title ANANTA Multi-Agent Production Engine
color 0B

echo ===============================================================================
echo                     ANANTA MULTI-AGENT PRODUCTION ENGINE                       
echo                "The Gods Remember. Humanity Forgets." (2042)                   
echo ===============================================================================
echo.

cd /d "%~dp0"

echo [1/4] Checking Python environment...
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo [ERROR] Python is not installed or not in system PATH.
    echo Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)
python -c "import sys; print(f'Python Version: {sys.version.split()[0]} (OK)')"

echo.
echo [2/4] Verifying core dependencies...
python -c "import pydantic, pydantic_settings, dotenv, httpx, jinja2, tenacity, yaml, pytest" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [INFO] Installing required dependencies...
    pip install -e ".[dev]"
    if %ERRORLEVEL% NEQ 0 (
        color 0C
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
)
echo Core Python dependencies verified.

echo.
echo [3/4] Checking Ollama Local AI Service...
python -c "import httpx; r = httpx.get('http://127.0.0.1:11434/api/tags', timeout=2.0); sys.exit(0 if r.status_code == 200 else 1)" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] Ollama is active on http://127.0.0.1:11434
    python -c "import httpx; r = httpx.get('http://127.0.0.1:11434/api/tags', timeout=2.0); models = [m['name'] for m in r.json().get('models', [])]; print('Available Models:', ', '.join(models) if models else 'None')"
) else (
    echo [INFO] Starting local Ollama service in background...
    start /B ollama serve >nul 2>&1
    timeout /t 2 >nul
    python -c "import httpx; r = httpx.get('http://127.0.0.1:11434/api/tags', timeout=3.0); sys.exit(0 if r.status_code == 200 else 1)" >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        echo [OK] Ollama service started successfully.
    ) else (
        echo [WARN] Ollama service not responding. Falling back to deterministic Mock Provider mode.
    )
)

echo.
echo [4/4] Engine Ready!
echo ===============================================================================
echo Select an execution mode:
echo   [1] Run Concurrent 19-Stage Pipeline (Sample Episode 01)
echo   [2] Run Sequential 19-Stage Pipeline (Sample Episode 01)
echo   [3] Run Complete Test Suite (Pytest)
echo   [4] Launch Interactive Python Shell
echo   [5] Exit
echo ===============================================================================
echo.

set /p choice="Enter your choice (1-5) [default: 1]: "
if "%choice%"=="" set choice=1

if "%choice%"=="1" (
    echo.
    echo Running Concurrent Pipeline...
    python -m pipeline.concurrent_orchestrator --brief shared/episode_01.json --workers 4
    echo.
    echo Pipeline execution completed. Check outputs/ folder for generated artifacts.
    pause
    exit /b 0
)

if "%choice%"=="2" (
    echo.
    echo Running Sequential Pipeline...
    python -m pipeline.orchestrator_v2 --brief shared/episode_01.json
    echo.
    echo Pipeline execution completed. Check outputs/ folder for generated artifacts.
    pause
    exit /b 0
)

if "%choice%"=="3" (
    echo.
    echo Running Full Test Suite...
    python -m pytest -v
    pause
    exit /b 0
)

if "%choice%"=="4" (
    echo.
    echo Entering Python environment...
    python
    exit /b 0
)

if "%choice%"=="5" (
    exit /b 0
)

echo Invalid choice.
pause
