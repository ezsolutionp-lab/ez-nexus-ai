@echo off
title EZ-NEXUS AI — Setup
echo ============================================
echo  EZ-NEXUS AI Platform - First-Time Setup
echo  Your AI Workforce for Business Growth(tm)
echo ============================================
echo.

echo [1/3] Setting up Python virtual environment...
cd /d "%~dp0backend"
python -m venv venv
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.10+ and retry.
    pause & exit /b 1
)
call venv\Scripts\activate.bat
echo Installing Python dependencies...
pip install -r requirements.txt
echo.

echo [2/3] Configuring environment...
if not exist .env (
    copy .env.example .env >nul
    echo Created backend\.env from template.
    echo.
    echo  ** IMPORTANT: Edit backend\.env and set ANTHROPIC_API_KEY **
    echo  Get your key at: https://console.anthropic.com
    echo.
) else (
    echo backend\.env already exists — skipping.
)
echo.

echo [3/3] Installing frontend dependencies...
cd /d "%~dp0frontend"
call npm install
if errorlevel 1 (
    echo ERROR: npm not found. Install Node.js 18+ and retry.
    pause & exit /b 1
)
echo.

echo ============================================
echo  Setup complete!
echo  Run START.bat to launch the platform.
echo ============================================
pause
