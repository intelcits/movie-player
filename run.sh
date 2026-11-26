#!/usr/bin/env bash
# MoviePlayer launcher for Ubuntu/Linux
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE" || exit 1
PIDFILE="$HERE/movie_player.pid"
LOGDIR="$HERE/logs"
LOGFILE="$LOGDIR/movie_player.log"

find_python() {
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
  elif command -v python >/dev/null 2>&1; then
    command -v python
  else
    return 1
  fi
}

read_pid() {
  [ -f "$PIDFILE" ] && tr -d '[:space:]' < "$PIDFILE"
}

is_running() {
  [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null
}

start_app() {
  OLD="$(read_pid || true)"
  if is_running "$OLD"; then
      echo "MoviePlayer already running (PID $OLD)."
      return
  fi
  rm -f "$PIDFILE"
  PY="$(find_python || true)"
  if [ -z "$PY" ]; then
    echo "Python 3 is required. Install it with: sudo apt install python3"
    return 1
  fi
  mkdir -p "$LOGDIR"
  echo "Starting MoviePlayer with $PY..."
  nohup "$PY" "$HERE/movie_player.py" >>"$LOGFILE" 2>&1 &
  LAUNCH_PID=$!
  sleep 2
  PID="$(read_pid || true)"
  if is_running "$PID"; then
    echo "Started (PID $PID). Log: $LOGFILE"
  elif is_running "$LAUNCH_PID"; then
    echo "MoviePlayer is still starting (PID $LAUNCH_PID). Log: $LOGFILE"
  else
    echo "MoviePlayer failed to start. Check: $LOGFILE"
    return 1
  fi
}

stop_app() {
  PID="$(read_pid || true)"
  if is_running "$PID"; then
    kill "$PID" 2>/dev/null || true
    for i in 1 2 3 4 5 6 7 8 9 10; do
      is_running "$PID" || break
      sleep 0.2
    done
    if is_running "$PID"; then kill -9 "$PID" 2>/dev/null || true; fi
    rm -f "$PIDFILE"
    echo "Stopped (PID $PID)."
  else
    rm -f "$PIDFILE"
    echo "MoviePlayer is not running."
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
