#!/usr/bin/env bash
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
  python3 movie_player.py
elif command -v python >/dev/null 2>&1; then
  python movie_player.py
else
  echo "Python not found. Please install Python 3.8+."
  exit 1
fi