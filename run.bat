@echo off
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (
  py movie_player.py
) else (
  python movie_player.py
)
rem pause
exit