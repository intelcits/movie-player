@echo off
setlocal
cd /d "%~dp0"
set "PIDFILE=%~dp0movie_player.pid"

:menu
echo.
echo === MoviePlayer ===
echo 1. Start
echo 2. Stop
echo 3. Restart
echo 4. Exit
set "choice="
set /p choice="Choose (1-4): "
if "%choice%"=="1" goto start
if "%choice%"=="2" goto stop
if "%choice%"=="3" goto restart
if "%choice%"=="4" goto end
goto menu

:start
if exist "%PIDFILE%" goto checkrunning
goto dostart

:checkrunning
set /p OLD=<"%PIDFILE%"
tasklist /FI "PID eq %OLD%" 2>nul | find "%OLD%" >nul
if %errorlevel%==0 (
  echo Already running (PID %OLD%).
  goto menu
)
del "%PIDFILE%" >nul 2>&1

:dostart
echo Starting MoviePlayer...
powershell -NoProfile -Command "Start-Process -FilePath 'python' -ArgumentList 'movie_player.py' -WorkingDirectory '%~dp0' -WindowStyle Hidden -PassThru | Select-Object -ExpandProperty Id | Out-File -FilePath '%PIDFILE%' -Encoding ascii"
timeout /t 2 /nobreak >nul
set /p PID=<"%PIDFILE%"
echo Started (PID %PID%). Opening browser...
start "" "http://127.0.0.1:8765/"
goto menu

:stop
if not exist "%PIDFILE%" goto stopfallback
set /p PID=<"%PIDFILE%"
taskkill /PID %PID% /F >nul 2>&1
del "%PIDFILE%" >nul 2>&1
echo Stopped (PID %PID%).
goto menu

:stopfallback
echo No PID file. Trying to find process...
for /f "tokens=2" %%a in ('tasklist /FI "IMAGENAME eq python.exe" /FO LIST ^| find "PID:"') do taskkill /PID %%a /F >nul 2>&1
echo Stopped.
goto menu

:restart
if exist "%PIDFILE%" (
  set /p PID=<"%PIDFILE%"
  taskkill /PID %PID% /F >nul 2>&1
  del "%PIDFILE%" >nul 2>&1
)
timeout /t 1 /nobreak >nul
goto dostart

:end
endlocal
exit /b 0