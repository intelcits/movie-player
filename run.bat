@echo off
setlocal
cd /d "%~dp0"
set "PIDFILE=%~dp0movie_player.pid"

if "%~1"=="" goto autostart
if /i "%~1"=="stop" goto stop
if /i "%~1"=="start" goto start
if /i "%~1"=="restart" goto restart
if /i "%~1"=="menu" goto menu
echo Usage: run.bat [start^|stop^|restart^|menu]
goto end

:autostart
set "ALREADY=0"
if exist "%PIDFILE%" (
  set /p OLD=<"%PIDFILE%"
  tasklist /FI "PID eq %OLD%" 2>nul | find "%OLD%" >nul
  if %errorlevel%==0 set "ALREADY=1"
)
if "%ALREADY%"=="1" goto already_running
goto start

:already_running
echo MoviePlayer already running (PID %OLD%). Opening browser...
start "" "http://127.0.0.1:8765/"
goto end

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
set "ALREADY=0"
if exist "%PIDFILE%" (
  set /p OLD=<"%PIDFILE%"
  tasklist /FI "PID eq %OLD%" 2>nul | find "%OLD%" >nul
  if %errorlevel%==0 set "ALREADY=1"
)
if "%ALREADY%"=="1" goto already_running_start
echo Starting MoviePlayer...
where py >nul 2>&1
if %errorlevel%==0 (
  powershell -NoProfile -Command "Start-Process -FilePath 'py' -ArgumentList '-3 movie_player.py' -WorkingDirectory '%~dp0' -WindowStyle Hidden -PassThru | Select-Object -ExpandProperty Id | Out-File -FilePath '%PIDFILE%' -Encoding ascii"
) else (
  powershell -NoProfile -Command "Start-Process -FilePath 'python' -ArgumentList 'movie_player.py' -WorkingDirectory '%~dp0' -WindowStyle Hidden -PassThru | Select-Object -ExpandProperty Id | Out-File -FilePath '%PIDFILE%' -Encoding ascii"
)
timeout /t 2 /nobreak >nul
set /p PID=<"%PIDFILE%"
echo Started (PID %PID%). Opening browser...
start "" "http://127.0.0.1:8765/"
goto end

:stop
if not exist "%PIDFILE%" (
  echo No PID file. Trying to find process...
  for /f "tokens=2" %%a in ('tasklist /FI "IMAGENAME eq python.exe" /FO LIST ^| find "PID:"') do taskkill /PID %%a /F >nul 2>&1
  echo Stopped.
  goto end
)
set /p PID=<"%PIDFILE%"
taskkill /PID %PID% /F >nul 2>&1
del "%PIDFILE%" >nul 2>&1
echo Stopped (PID %PID%).
goto end

:restart
if exist "%PIDFILE%" (
  set /p PID=<"%PIDFILE%"
  taskkill /PID %PID% /F >nul 2>&1
  del "%PIDFILE%" >nul 2>&1
)
timeout /t 1 /nobreak >nul
goto start

:already_running_start
echo Already running (PID %OLD%). Opening browser...
start "" "http://127.0.0.1:8765/"
goto end

:end
endlocal
exit /b 0