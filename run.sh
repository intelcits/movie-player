#!/usr/bin/env bash
cd "$(dirname "$0")"
PIDFILE="$(pwd)/movie_player.pid"

menu() {
  echo ""
  echo "=== MoviePlayer ==="
  echo "1. Start"
  echo "2. Stop"
  echo "3. Restart"
  echo "4. Exit"
  read -rp "Choose (1-4): " choice
  case "$choice" in
    1) start_app ;;
    2) stop_app ;;
    3) stop_app; sleep 1; start_app ;;
    4) exit 0 ;;
    *) echo "Invalid choice"; menu ;;
  esac
}

start_app() {
  if [ -f "$PIDFILE" ]; then
    OLD=$(cat "$PIDFILE")
    if kill -0 "$OLD" 2>/dev/null; then
      echo "Already running (PID $OLD)."
      menu; return
    fi
  fi
  echo "Starting MoviePlayer..."
  if command -v python3 >/dev/null 2>&1; then PY=python3; elif command -v python >/dev/null 2>&1; then PY=python; else echo "Python not found"; menu; return; fi
  nohup "$PY" movie_player.py >/dev/null 2>&1 &
  echo $! > "$PIDFILE"
  sleep 2
  PID=$(cat "$PIDFILE")
  echo "Started (PID $PID). Opening browser..."
  if command -v xdg-open >/dev/null 2>&1; then xdg-open "http://127.0.0.1:8765/" >/dev/null 2>&1 & fi
  menu
}

stop_app() {
  if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    kill "$PID" 2>/dev/null
    rm -f "$PIDFILE"
    echo "Stopped (PID $PID)."
  else
    echo "No PID file. Trying pkill..."
    pkill -f movie_player.py 2>/dev/null
    echo "Done."
  fi
  menu
}

menu