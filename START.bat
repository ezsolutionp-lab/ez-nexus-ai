@echo off
title EZ-NEXUS AI — Launcher
echo ============================================
echo  EZ-NEXUS AI Platform
echo  Your AI Workforce for Business Growth(tm)
echo ============================================
echo.

if not exist "%~dp0backend\venv\Scripts\activate.bat" (
    echo Virtual environment not found. Run SETUP.bat first.
    pause & exit /b 1
)

echo Starting Backend API  ^>  http://localhost:8000
start "EZ-NEXUS Backend" cmd /k "cd /d "%~dp0backend" && call venv\Scripts\activate.bat && uvicorn app.main:app --reload --port 8000"

timeout /t 3 /nobreak >nul

echo Starting Frontend App ^>  http://localhost:5173
start "EZ-NEXUS Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

timeout /t 5 /nobreak >nul

echo Opening browser...
start "" http://localhost:5173

echo.
echo  Backend:  http://localhost:8000
echo  Frontend: http://localhost:5173
echo  API Docs: http://localhost:8000/docs
echo.
echo Close the backend/frontend windows to stop the servers.
pause
