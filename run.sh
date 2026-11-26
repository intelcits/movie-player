#!/usr/bin/env bash
# MoviePlayer launcher
cd "$(dirname "$0")"
PIDFILE="$(pwd)/movie_player.pid"

start_app() {
  if [ -f "$PIDFILE" ]; then
    OLD=$(cat "$PIDFILE" 2>/dev/null)
    if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null; then
      echo "MoviePlayer already running (PID $OLD)."
      return
    fi
    rm -f "$PIDFILE"
  fi
  echo "Starting MoviePlayer..."
  if command -v python3 >/dev/null 2>&1; then PY=python3
  elif command -v python >/dev/null 2>&1; then PY=python
  else echo "Python not found."; return 1; fi
  nohup "$PY" movie_player.py >/dev/null 2>&1 &
  sleep 2
  if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    echo "Started (PID $PID). Opening browser..."
  else
    echo "Started. Opening browser..."
  fi
  # Browser is opened by MoviePlayer itself; do not call xdg-open here
  # to avoid launching multiple browsers on some Linux setups.
}

stop_app() {
  if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE" 2>/dev/null)
    if [ -n "$PID" ]; then
      kill "$PID" 2>/dev/null
      # wait briefly
      for i in 1 2 3 4 5; do kill -0 "$PID" 2>/dev/null || break; sleep 0.2; done
      kill -9 "$PID" 2>/dev/null
    fi
    rm -f "$PIDFILE"
    echo "Stopped (PID $PID)."
  else
    echo "No PID file. Trying pkill..."
    pkill -f "movie_player.py" 2>/dev/null
    echo "Done."
  fi
}

case "${1:-}" in
  start)   start_app ;;
  stop)    stop_app ;;
  restart) stop_app; sleep 1; start_app ;;
  menu)
    while true; do
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
        *) echo "Invalid choice" ;;
      esac
    done
    ;;
  "")      start_app ;;
  *)       echo "Usage: $0 [start|stop|restart|menu]"; exit 1 ;;
esac