@echo off
setlocal
cd /d "%~dp0"
set "PIDFILE=%~dp0movie_player.pid"

if "%~1"=="" goto autostart
if /i "%~1"=="stop" goto stop
if /i "%~1"=="start" goto start
if /i "%~1"=="restart" goto restart
echo Usage: run.bat [start^|stop^|restart]
goto end

:autostart
set "ALREADY=0"
if exist "%PIDFILE%" (
  set /p OLD=<"%PIDFILE%"
  powershell -NoProfile -Command "if (Get-Process -Id %OLD% -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
  if %errorlevel%==0 set "ALREADY=1"
)
if "%ALREADY%"=="1" goto already_running_autostart
goto start

:already_running_autostart
echo MoviePlayer already running (PID %OLD%). Opening browser...
start "" "http://127.0.0.1:8765/"
goto end

:start
echo Starting MoviePlayer...
where py >nul 2>&1
if %errorlevel%==0 (
  powershell -NoProfile -Command "Start-Process -FilePath 'py' -ArgumentList '-3 movie_player.py' -WorkingDirectory '%~dp0' -WindowStyle Hidden -PassThru | Select-Object -ExpandProperty Id | Out-File -FilePath '%PIDFILE%' -Encoding ascii"
) else (
  powershell -NoProfile -Command "Start-Process -FilePath 'python' -ArgumentList 'movie_player.py' -WorkingDirectory '%~dp0' -WindowStyle Hidden -PassThru | Select-Object -ExpandProperty Id | Out-File -FilePath '%PIDFILE%' -Encoding ascii"
)
echo Started. The browser will open automatically.
goto end

:stop
if not exist "%PIDFILE%" goto stop_nopid
set /p PID=<"%PIDFILE%"
taskkill /PID %PID% /F >nul 2>&1
del "%PIDFILE%" >nul 2>&1
echo Stopped (PID %PID%).
goto end

:stop_nopid
echo No PID file found.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*movie_player.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
echo Stopped.
goto end

:restart
if exist "%PIDFILE%" (
  set /p PID=<"%PIDFILE%"
  taskkill /PID %PID% /F >nul 2>&1
  del "%PIDFILE%" >nul 2>&1
)
powershell -NoProfile -Command "Start-Sleep -Seconds 1" >nul 2>&1
goto start

:end
endlocal
exit /b 0