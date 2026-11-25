#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone library scanner for MoviePlayer.

Scans the folders declared in movie_player.conf.json, enriches new/changed
files with TMDB metadata and art, and updates .cache/movieplayer.db.
It does NOT start the web server, so it can be run on demand or scheduled.

The script must live in the same folder as movie_player.py.

Examples:
    python scan_movies.py                    # movies and series, incremental
    python scan_movies.py --force            # re-fetch metadata and art
    python scan_movies.py --category movie   # movies only
    python scan_movies.py --category series  # series only
    python scan_movies.py --dry-run          # list files, change nothing
    python scan_movies.py --dir "D:\\Movies\\New" --category movie

Exit codes:
    0 = completed without errors
    1 = completed with one or more file errors
    2 = no configured directories to scan
    3 = another scan is already running
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import movie_player as mp  # noqa: E402


class ScanLock:
    """Cross-platform advisory lock so scheduled runs do not overlap."""

    def __init__(self, path):
        self.path = path
        self.fh = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a+")
        try:
            if os.path.getsize(self.path) == 0:
                self.fh.write(" ")
                self.fh.flush()
            self.fh.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.close()
            self.fh = None
            return False
        self.fh.seek(0)
        self.fh.truncate()
        self.fh.write("%d %s\n" % (os.getpid(), datetime.now().isoformat(timespec="seconds")))
        self.fh.flush()
        return True

    def release(self):
        if not self.fh:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            self.fh.close()
        except Exception:
            pass
        self.fh = None


def setup_logger(log_path, verbose=False):
    logger = logging.getLogger("scan_movies")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


def is_under(path, root):
    p = os.path.normcase(os.path.abspath(path))
    r = os.path.normcase(os.path.abspath(root))
    return p == r or p.startswith(r + os.sep)


def clean_missing_under(roots, logger):
    """Delete DB rows for files that no longer exist inside the scanned roots."""
    removed = []
    conn = mp.db_conn()
    try:
        for row in conn.execute("SELECT path FROM movies").fetchall():
            p = row["path"]
            if not any(is_under(p, root) for root in roots):
                continue
            if os.path.isfile(p):
                continue
            conn.execute("DELETE FROM movies WHERE path=?", (p,))
            removed.append(p)
        conn.commit()
    finally:
        conn.close()
    for p in removed:
        logger.info("REMOVED %s", p)
    return removed


def scan(args, logger):
    started = time.time()
    started_at = datetime.now()
    categories = ["movie", "series"] if args.category == "all" else [args.category]

    if args.dir:
        if args.category == "all":
            logger.error("--dir requires --category movie or --category series.")
            return 2
        plan = [(args.category, args.dir)]
    else:
        plan = []
        for cat in categories:
            for d in mp.CFG.get(cat + "_dirs", []) or []:
                plan.append((cat, d))

    logger.info("=" * 78)
    logger.info("MoviePlayer standalone scan")
    logger.info("Started : %s", started_at.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("Config  : %s", mp.CONFIG_FILE)
    logger.info("Database: %s", mp.DB_PATH)
    logger.info("Mode    : category=%s force=%s dry-run=%s", args.category, args.force, args.dry_run)
    if not (mp.CFG.get("tmdb_api_key") or "").strip():
        logger.warning("TMDB API key is empty: metadata enrichment will be limited.")
    if not mp.HAS_REQUESTS:
        logger.warning("Python 'requests' is not installed: TMDB enrichment is disabled.")
    if (HERE / "movie_player.pid").exists():
        logger.warning("MoviePlayer appears to be running; the scan may overlap with the app.")
    for cat, d in plan:
        logger.info("Target  : [%s] %s", cat, d)
    if not plan:
        logger.error("No directories configured. Add folders in Settings or movie_player.conf.json.")
        return 2

    lock = None
    if not args.dry_run:
        lock = ScanLock(mp.CACHE_DIR / "scan.lock")
        if not lock.acquire():
            logger.error("Another scan is already running (lock: %s). Exiting.", lock.path)
            return 3

    stats = {"found": 0, "new": 0, "updated": 0, "skipped": 0, "errors": 0, "removed": 0}
    scanned_roots = []
    seen_paths = set()
    try:
        for cat, root in plan:
            root = mp.norm_path(root)
            if not root or not os.path.isdir(root):
                logger.error("Directory not found, skipped: %s", root)
                stats["errors"] += 1
                continue
            scanned_roots.append(root)
            logger.info("-" * 78)
            logger.info("Scanning [%s] %s", cat, root)
            try:
                entries = mp.scan_dir(root, cat)
            except Exception as exc:
                logger.exception("Failed to scan directory %s: %s", root, exc)
                stats["errors"] += 1
                continue
            logger.info("Found %d video file(s).", len(entries))

            for entry in entries:
                path = entry.get("path")
                stats["found"] += 1
                if path in seen_paths:
                    logger.warning("DUPLICATE %s (already handled)", path)
                    continue
                seen_paths.add(path)

                existing = mp.get_db_movie(path)
                if existing is None:
                    action = "NEW"
                elif args.force:
                    action = "UPDATE"
                elif existing.get("tmdb_id") and existing.get("file_mtime") == entry.get("mtime"):
                    action = "SKIP"
                else:
                    action = "UPDATE"

                title = entry.get("title") or entry.get("name") or "?"
                year = entry.get("year") or "?"
                stat_key = {"NEW": "new", "UPDATE": "updated", "SKIP": "skipped"}[action]
                if args.dry_run:
                    logger.info("DRY-RUN %-6s %s (%s) | %s", action, title, year, path)
                    stats[stat_key] += 1
                    continue

                try:
                    mp.enrich_entry(entry, cat, force=args.force)
                    stats[stat_key] += 1
                    logger.info("%-6s %s (%s) | %s", action,
                                entry.get("title") or title, entry.get("year") or year, path)
                    if args.verbose:
                        logger.debug("       subs=%s tmdb=%s", entry.get("sub_count"), entry.get("tmdb_id"))
                except Exception as exc:
                    stats["errors"] += 1
                    logger.exception("ERROR  %s | %s", path, exc)

        if not args.dry_run:
            removed = clean_missing_under(scanned_roots, logger)
            stats["removed"] = len(removed)
            mp.save_tmdb_cache(force=True)
    finally:
        if lock:
            lock.release()

    elapsed = time.time() - started
    logger.info("=" * 78)
    logger.info("Finished: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info(
        "Found %d | new %d | updated %d | skipped %d | removed %d | errors %d | %.1fs",
        stats["found"], stats["new"], stats["updated"], stats["skipped"],
        stats["removed"], stats["errors"], elapsed,
    )
    return 0 if stats["errors"] == 0 else 1


def main():
    parser = argparse.ArgumentParser(
        description="Scan MoviePlayer folders without starting the web server.",
    )
    parser.add_argument("--category", choices=["movie", "series", "all"], default="all",
                        help="What to scan (default: all = movies and series).")
    parser.add_argument("--force", action="store_true",
                        help="Re-fetch TMDB metadata and art even when the file is unchanged.")
    parser.add_argument("--dir", metavar="PATH",
                        help="Scan only this directory (also pass --category movie or series).")
    parser.add_argument("--dry-run", action="store_true",
                        help="List what would be scanned; do not write to the database.")
    parser.add_argument("--log-file", metavar="PATH",
                        help="Write the log to this file instead of logs/scan_<timestamp>.log.")
    parser.add_argument("--verbose", action="store_true",
                        help="Include extra per-file details in the log.")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    if args.log_file:
        log_path = Path(args.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        log_dir = HERE / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / ("scan_%s_%d.log" % (datetime.now().strftime("%Y%m%d_%H%M%S"), os.getpid()))

    logger = setup_logger(log_path, verbose=args.verbose)
    try:
        code = scan(args, logger)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user.")
        code = 130
    except Exception:
        logger.exception("Scan failed with an unexpected error.")
        code = 1
    finally:
        logger.info("Log file: %s", log_path)
        logging.shutdown()
    return code


if __name__ == "__main__":
    sys.exit(main())
