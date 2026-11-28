#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MoviePlayer - local movie library player.
Backend: pure-Python (stdlib) HTTP server. Uses ffplay/ffprobe/ffmpeg.
Cross-platform: Windows 10 and Ubuntu 20.04.
Run: python movie_player.py   (opens http://127.0.0.1:8765)
"""
import http.server
import json
import os
import re
import shutil
import socketserver
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

try:
    import requests
    HAS_REQUESTS = True
except Exception:
    HAS_REQUESTS = False

HERE = Path(__file__).resolve().parent
CONFIG_DIR = HERE / "config"
DATA_DIR = HERE / "data"
CACHE_DIR = DATA_DIR / "cache"
LOG_DIR = DATA_DIR / "logs"
RUNTIME_DIR = DATA_DIR / "run"
CONFIG_FILE = CONFIG_DIR / "movie_player.conf.json"
LEGACY_CONFIG_FILE = HERE / "movie_player.conf.json"
LEGACY_CACHE_DIR = HERE / ".cache"
LEGACY_LOG_DIR = HERE / "logs"
LEGACY_PID_FILE = HERE / "movie_player.pid"
THUMB_DIR = CACHE_DIR / "thumbs"
VTT_DIR = CACHE_DIR / "vtt"
TMDB_CACHE_FILE = CACHE_DIR / "tmdb.json"
DB_PATH = DATA_DIR / "movieplayer.db"
IMAGES_DIR = CACHE_DIR / "images"
PID_FILE = RUNTIME_DIR / "movie_player.pid"

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".mpg", ".mpeg", ".wmv",
              ".flv", ".m2ts", ".mts", ".webm", ".ogv", ".ts", ".vob"}
SUB_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub"}
BROWSER_PLAYABLE = {".mp4", ".webm", ".ogv", ".m4v"}

DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 8765,
    "movie_dirs": [],
    "series_dirs": [],
    "tmdb_api_key": "",
    "tmdb_session_id": "",
    "tmdb_session_id": "",
    "ffplay_path": "ffplay",
    "ffprobe_path": "ffprobe",
    "ffmpeg_path": "ffmpeg",
    "volume": 80,
    "skip_seconds": 10,
    "theme": "default",
    "kiosk_mode": False,
    "fullscreen": True,
    "ui_font_size": 15,
    "ui_font_family": "system",
    "sub_size": 28,
    "sub_color": "#ffffff",
    "music_dir": "",
}


def migrate_legacy_layout():
    """Move the old root-level runtime layout into config/ and data/ safely."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists() and LEGACY_CONFIG_FILE.exists():
        try:
            shutil.copy2(LEGACY_CONFIG_FILE, CONFIG_FILE)
        except OSError:
            pass
    if LEGACY_CACHE_DIR.exists() and not CACHE_DIR.exists():
        try:
            shutil.move(str(LEGACY_CACHE_DIR), str(CACHE_DIR))
        except OSError:
            pass
    if LEGACY_LOG_DIR.exists() and not LOG_DIR.exists():
        try:
            shutil.move(str(LEGACY_LOG_DIR), str(LOG_DIR))
        except OSError:
            pass
    if LEGACY_PID_FILE.exists() and not PID_FILE.exists():
        try:
            shutil.move(str(LEGACY_PID_FILE), str(PID_FILE))
        except OSError:
            pass
    # Older V2 builds kept the SQLite file inside the cache directory.
    # Promote a populated database when the new data root is empty or absent.
    legacy_db = CACHE_DIR / "movieplayer.db"
    try:
        def has_movies(path):
            if not path.exists():
                return False
            conn = sqlite3.connect(str(path), timeout=5)
            try:
                return conn.execute("SELECT COUNT(*) FROM movies").fetchone()[0] > 0
            finally:
                conn.close()
        if has_movies(legacy_db) and not has_movies(DB_PATH):
            if DB_PATH.exists():
                backup = DATA_DIR / "movieplayer.db.empty-before-migration"
                if not backup.exists():
                    shutil.move(str(DB_PATH), str(backup))
                else:
                    DB_PATH.unlink()
            shutil.move(str(legacy_db), str(DB_PATH))
    except (OSError, sqlite3.Error):
        # Startup must remain usable even if a legacy file is locked or malformed.
        pass


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            cfg.update(data)
        except Exception:
            pass
    elif LEGACY_CONFIG_FILE.exists():
        try:
            data = json.loads(LEGACY_CONFIG_FILE.read_text(encoding="utf-8"))
            cfg.update(data)
        except Exception:
            pass
    # migrate old media_dirs -> movie_dirs
    if cfg.get("media_dirs") and not cfg.get("movie_dirs"):
        cfg["movie_dirs"] = list(cfg.get("media_dirs") or [])
    # migrate musical_dirs -> movie_dirs
    if cfg.get("musical_dirs"):
        for d in cfg.get("musical_dirs") or []:
            if d not in cfg.setdefault("movie_dirs", []):
                cfg["movie_dirs"].append(d)
    # migrate media_dirs -> movie_dirs
    if cfg.get("media_dirs") and not cfg.get("movie_dirs"):
        cfg["movie_dirs"] = list(cfg.get("media_dirs") or [])
    for k in ("movie_dirs", "series_dirs"):
        cfg.setdefault(k, [])
    cfg.setdefault("tmdb_session_id", "")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    VTT_DIR.mkdir(parents=True, exist_ok=True)
    return cfg


def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


migrate_legacy_layout()
CFG = load_config()
IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def db_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    return conn


def init_db():
    conn = db_conn()
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE NOT NULL,
            title TEXT,
            year TEXT,
            tmdb_id INTEGER,
            overview TEXT,
            genres TEXT,
            runtime INTEGER,
            director TEXT,
            cast TEXT,
            country TEXT,
            rating REAL,
            poster_url TEXT,
            backdrop_url TEXT,
            poster_local TEXT,
            backdrop_local TEXT,
            duration REAL,
            width INTEGER,
            height INTEGER,
            codec TEXT,
            audio TEXT,
            file_info TEXT,
            category TEXT,
            collection TEXT,
            resume_position REAL,
            tagline TEXT,
            trailer_key TEXT,
            cast_json TEXT,
            similar_json TEXT,
            collection_name TEXT,
            collection_id INTEGER,
            season INTEGER,
            episode INTEGER,
            episode_title TEXT,
            custom_title TEXT,
            tv_seasons_json TEXT,
            file_mtime REAL,
            scanned_at REAL,
            sub_count INTEGER DEFAULT 0
        )
        """)
        # migrate existing DBs
        cols = [r[1] for r in conn.execute("PRAGMA table_info(movies)").fetchall()]
        if "file_info" not in cols:
            conn.execute("ALTER TABLE movies ADD COLUMN file_info TEXT")
        if "category" not in cols:
            conn.execute("ALTER TABLE movies ADD COLUMN category TEXT")
        if "collection" not in cols:
            conn.execute("ALTER TABLE movies ADD COLUMN collection TEXT")
        if "resume_position" not in cols:
            conn.execute("ALTER TABLE movies ADD COLUMN resume_position REAL")
        # extra TMDB metadata
        for col in ("tagline", "trailer_key", "cast_json", "similar_json", "collection_name", "collection_id"):
            if col not in cols:
                conn.execute(f"ALTER TABLE movies ADD COLUMN {col} TEXT")
        # series / movie-set fields
        for col in ("season", "episode", "episode_title", "custom_title", "tv_seasons_json"):
            if col not in cols:
                conn.execute(f"ALTER TABLE movies ADD COLUMN {col} TEXT")
        if "season" in cols or True:
            # ensure integer typing not enforced by sqlite; leave as TEXT ok
            pass
        # migrate musical -> movie
        conn.execute("UPDATE movies SET category='movie' WHERE category='musical'")
        # streaming favorites
        conn.execute("""
        CREATE TABLE IF NOT EXISTS streaming_favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tmdb_id INTEGER,
            title TEXT,
            year TEXT,
            poster TEXT,
            media_type TEXT DEFAULT 'movie',
            added_at REAL
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_movies_title ON movies(title)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_movies_year ON movies(year)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_movies_country ON movies(country)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_movies_director ON movies(director)")
        # streaming sites cache
        conn.execute("""
        CREATE TABLE IF NOT EXISTS streaming_sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            url TEXT UNIQUE,
            description TEXT,
            category TEXT,
            alternates TEXT,
            rank TEXT,
            fetched_at REAL
        )
        """)
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(streaming_sites)").fetchall()}
        for col, definition in (("category", "TEXT"), ("alternates", "TEXT"), ("rank", "TEXT")):
            if col not in existing_cols:
                conn.execute(f"ALTER TABLE streaming_sites ADD COLUMN {col} {definition}")
        # collection-level art
        conn.execute("""
        CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            poster_url TEXT,
            backdrop_url TEXT,
            poster_local TEXT,
            backdrop_local TEXT,
            scanned_at REAL
        )
        """)
        conn.commit()
    finally:
        conn.close()


def migrate_legacy_cache_paths():
    """Rewrite cache paths stored by the pre-data-directory layout."""
    legacy_prefixes = (
        str(LEGACY_CACHE_DIR),
        str(HERE / "cache"),
    )
    new_prefix = str(CACHE_DIR)
    conn = db_conn()
    try:
        for table in ("movies", "collections"):
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for column in ("poster_local", "backdrop_local"):
                if column not in columns:
                    continue
                for legacy_prefix in legacy_prefixes:
                    conn.execute(
                        f"UPDATE {table} SET {column}=REPLACE({column}, ?, ?) "
                        f"WHERE {column} IS NOT NULL AND instr({column}, ?) > 0",
                        (legacy_prefix, new_prefix, legacy_prefix),
                    )
        conn.commit()
    finally:
        conn.close()


init_db()
migrate_legacy_cache_paths()

# ---------- TMDB cache ----------
_tmdb_cache = {}
if TMDB_CACHE_FILE.exists():
    try:
        _tmdb_cache = json.loads(TMDB_CACHE_FILE.read_text(encoding="utf-8"))
        # drop stale detail entries that predate cast/trailer/similar fields
        _tmdb_cache = {
            k: v for k, v in _tmdb_cache.items()
            if not (k.startswith("details|") and isinstance(v, dict) and "similar" not in v)
        }
    except Exception:
        _tmdb_cache = {}


_TMDB_CACHE_LOCK = threading.Lock()
_TMDB_SAVE_TS = [0.0]


def save_tmdb_cache(force=False):
    try:
        with _TMDB_CACHE_LOCK:
            now = time.time()
            if not force and now - _TMDB_SAVE_TS[0] < 3:
                return
            _TMDB_SAVE_TS[0] = now
            TMDB_CACHE_FILE.write_text(json.dumps(_tmdb_cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def tool_path(name):
    # name like 'ffplay' -> config key ffplay_path
    key = name + "_path"
    p = CFG.get(key, name)
    return p if p else name


# ---------- helpers ----------
def norm_path(p):
    if p is None:
        return None
    p = str(p).strip().strip('"').strip("'")
    if not p:
        return None
    try:
        return str(Path(p).expanduser().resolve())
    except Exception:
        return p


_RELEASE_JUNK = re.compile(
    r'\b(?:2160p|1440p|1080p|720p|576p|480p|4k|uhd|bluray|blu-ray|brrip|bdrip|bdremux|webrip|'
    r'web-dl|webdl|web|hdrip|dvdrip|dvdscr|hdtv|pdtv|sdtv|x264|x265|h\.?264|h\.?265|hevc|avc|'
    r'aac\d?(?:\.\d)?|ac3|eac3|dts(?:-hd)?|truehd|atmos|ddp?[257][\.\s][01]|[257][\.\s][01]|'
    r'10bit|8bit|hdr10?|dv|remux|proper|repack|extended|unrated|uncut|remastered|directors?[\.\s]?cut|'
    r'multi|dual|subs?|subbed|dubbed|amzn|dsnp|hmax|atvp|nf|yts(?:\.mx)?|rarbg|anoXmous|ozlem|tgx|'
    r'pmedia|www\.[^\s]+)\b',
    re.I,
)
_LEADING_NUM = re.compile(r'^\d{1,3}[\.\-_](?=[A-Za-z])')
_BOND_PREFIX = re.compile(r'^(?:007[\s._-]*james[\s._-]*bond|james[\s._-]*bond[\s._-]*007)[\s._-]*', re.I)
_BRACKET_JUNK = re.compile(r'\((?:[^)]*(?:1080p|720p|bluray|x264|x265|director|extended|unrated|remastered|dubbed|subbed|5[\.\s]1|7[\.\s]1)[^)]*)\)', re.I)


def _clean_name(text):
    text = re.sub(r'\[[^\]]*\]', ' ', text or '')
    text = re.sub(r'\{[^}]*\}', ' ', text)
    text = _BRACKET_JUNK.sub(' ', text)
    text = _BOND_PREFIX.sub('', text)
    text = _LEADING_NUM.sub('', text)
    text = text.replace('_', ' ').replace('.', ' ')
    text = _RELEASE_JUNK.sub(' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip(' .-_:[](){}')


def _find_year(text):
    """Prefer a year in parentheses/brackets, otherwise the last standalone year."""
    m = re.search(r'[\(\[]\s*((?:19|20)\d{2})\s*[\)\]]', text)
    if m:
        return m.group(1), m.start(), m.end()
    years = list(re.finditer(r'\b(?:19\d{2}|20\d{2})\b', text))
    if years:
        m = years[-1]
        return m.group(0), m.start(), m.end()
    return None, -1, -1


_EP_PATTERNS = [
    (re.compile(r'\bS(\d{1,2})[\s._-]*E(\d{1,3})\b', re.I), 'sxxexx'),
    (re.compile(r'\bT(\d{1,2})[\s._-]*E(\d{1,3})\b', re.I), 'sxxexx'),
    (re.compile(r'\b(\d{1,2})x(\d{1,3})\b'), 'sxxexx'),
    (re.compile(r'\bCap(?:[ií]tulo)?\.?\s*(\d{3,4})\b', re.I), 'capnum'),
    (re.compile(r'\bCap(?:[ií]tulo)?\.?\s*(\d{1,2})\b', re.I), 'cap'),
    (re.compile(r'\b(?:Episodio|Episode|Ep)\.?\s*(\d{1,4})\b', re.I), 'ep'),
    (re.compile(r'(?:^|[\s._-])E(\d{1,3})(?:[\s._-]|$)', re.I), 'ep'),
]


def parse_episode_info(stem):
    """Return season/episode/series/episode_title for a series filename, or None."""
    for rx, kind in _EP_PATTERNS:
        m = rx.search(stem)
        if not m:
            continue
        if kind == 'sxxexx':
            season, episode = int(m.group(1)), int(m.group(2))
        elif kind == 'capnum':
            digits = m.group(1)
            if len(digits) == 3:
                season, episode = int(digits[0]), int(digits[1:])
            else:
                season, episode = int(digits[:2]), int(digits[2:])
        else:
            season, episode = 1, int(m.group(1))
        base = stem[:m.start()]
        rest = stem[m.end():]
        return {
            "season": season or 1,
            "episode": episode,
            "series": _clean_name(base) or None,
            "episode_title": _clean_name(rest) or None,
        }
    return None


def clean_series_name(name):
    name = name or ''
    name = re.sub(r'\[[^\]]*\]', ' ', name)
    name = re.sub(r'\{[^}]*\}', ' ', name)
    name = re.sub(r'\((?:19|20)\d{2}(?:\s*[-\u2013]\s*(?:19|20)\d{2})?\)', ' ', name)
    name = _clean_name(name)
    name = re.sub(r'\s+', ' ', name).strip(' .-_:')
    return name


def parse_title_year(filename):
    stem = Path(filename).stem
    year, start, end = _find_year(stem)
    if year:
        title = _clean_name(stem[:start])
        if not title:
            title = _clean_name(stem[end:])
    else:
        title = _clean_name(stem)
    return title or _clean_name(stem) or stem, year


def find_subtitles(video_path):
    vp = Path(video_path)
    folder = vp.parent
    vstem = vp.stem
    subs = []
    # same folder
    for f in folder.iterdir():
        if f.is_file() and f.suffix.lower() in SUB_EXTS:
            sstem = f.stem
            if sstem == vstem or sstem.startswith(vstem + ".") or sstem.startswith(vstem + " "):
                subs.append(str(f))
    # subs/subtitles subfolder
    for sub in ("subs", "subtitles", "sub"):
        d = folder / sub
        if d.is_dir():
            for f in d.iterdir():
                if f.is_file() and f.suffix.lower() in SUB_EXTS:
                    sstem = f.stem
                    if sstem == vstem or sstem.startswith(vstem):
                        subs.append(str(f))
    # de-dup
    seen = set()
    out = []
    for s in subs:
        if s not in seen:
            seen.add(s)
            out.append(s)
    out.sort()
    return out


def sub_label(path):
    name = Path(path).name
    # guess language from suffix like .es.srt
    stem = Path(path).stem
    parts = stem.split(".")
    if len(parts) > 1:
        lang = parts[-1]
        if len(lang) <= 6 and lang.isalpha():
            return f"{name} ({lang})"
    return name


def scan_dir(root, category=None):
    root = norm_path(root)
    results = []
    if not root or not os.path.isdir(root):
        return results
    # first pass: collect video files
    video_files = []
    for dp, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in VIDEO_EXTS:
                full = os.path.join(dp, f)
                video_files.append((dp, f, full, ext))
    # recursive folder video counts (each file contributes to every ancestor)
    folder_counts = {}
    for dp, f, full, ext in video_files:
        rel = os.path.relpath(dp, root)
        if rel == ".":
            continue
        cum = ""
        for part in rel.split(os.sep):
            cum = os.path.join(cum, part) if cum else part
            folder_counts[cum] = folder_counts.get(cum, 0) + 1
    is_series = (category or "").lower() == "series"
    for dp, f, full, ext in video_files:
        rel = os.path.relpath(dp, root)
        # highest ancestor folder that contains more than one video
        collection = None
        if rel != ".":
            cum = ""
            for part in rel.split(os.sep):
                cum = os.path.join(cum, part) if cum else part
                if collection is None and folder_counts.get(cum, 0) > 1:
                    collection = cum
        subs = find_subtitles(full)
        try:
            mtime = os.path.getmtime(full)
        except OSError:
            mtime = None
        entry = {
            "path": full,
            "name": f,
            "size": os.path.getsize(full),
            "ext": ext,
            "browser_playable": ext in BROWSER_PLAYABLE,
            "subtitles": [{"path": s, "label": sub_label(s)} for s in subs],
            "sub_count": len(subs),
            "mtime": mtime,
            "collection": collection,
            "category": category,
        }
        if is_series:
            ep = parse_episode_info(Path(f).stem)
            folder_name = clean_series_name(Path(collection).name) if collection else ""
            parsed_title, parsed_year = parse_title_year(f)
            series_title = folder_name or (ep or {}).get("series") or parsed_title
            series_year = None
            if collection:
                ym = re.search(r'((?:19|20)\d{2})', Path(collection).name)
                if ym:
                    series_year = ym.group(1)
            if not series_year:
                series_year = parsed_year
            entry.update({
                "title": series_title,
                "year": series_year,
                "season": (ep or {}).get("season") or 1,
                "episode": (ep or {}).get("episode"),
                "episode_title": (ep or {}).get("episode_title"),
            })
        else:
            title, year = parse_title_year(f)
            entry["title"] = title
            entry["year"] = year
        results.append(entry)
    results.sort(key=lambda x: ((x.get("title") or x["name"]).lower(), x.get("season") or 0, x.get("episode") or 0))
    return results


def get_db_movie(path):
    conn = db_conn()
    try:
        row = conn.execute("SELECT * FROM movies WHERE path=?", (path,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def upsert_movie_db(data):
    conn = db_conn()
    try:
        _cols = ["path", "title", "custom_title", "year", "tmdb_id", "overview", "genres",
                 "runtime", "director", "cast", "country", "rating", "poster_url", "backdrop_url",
                 "poster_local", "backdrop_local", "resume_position", "tagline", "trailer_key",
                 "cast_json", "similar_json", "collection_name", "collection_id", "duration",
                 "width", "height", "codec", "audio", "file_info", "category", "collection",
                 "season", "episode", "episode_title", "tv_seasons_json", "file_mtime",
                 "scanned_at", "sub_count"]
        vals = [
            data.get("path"),
            data.get("title"),
            data.get("custom_title"),
            data.get("year"),
            data.get("tmdb_id"),
            data.get("overview"),
            json.dumps(data.get("genres") or []),
            data.get("runtime"),
            data.get("director"),
            json.dumps(data.get("cast") or []),
            data.get("country"),
            data.get("rating"),
            data.get("poster_url"),
            data.get("backdrop_url"),
            data.get("poster_local"),
            data.get("backdrop_local"),
            data.get("resume_position"),
            data.get("tagline"),
            data.get("trailer_key"),
            json.dumps(data.get("cast_full") or (data.get("cast_json") and json.loads(data.get("cast_json")) or [])),
            json.dumps(data.get("similar") or (data.get("similar_json") and json.loads(data.get("similar_json")) or [])),
            data.get("collection_name"),
            data.get("collection_id"),
            data.get("duration"),
            data.get("width"),
            data.get("height"),
            data.get("codec"),
            data.get("audio"),
            data.get("file_info"),
            data.get("category"),
            data.get("collection"),
            data.get("season"),
            data.get("episode"),
            data.get("episode_title"),
            json.dumps(data.get("tv_seasons") or (data.get("tv_seasons_json") and json.loads(data.get("tv_seasons_json")) or [])),
            data.get("mtime"),
            time.time(),
            data.get("sub_count", 0),
        ]
        quoted = ['"cast"' if c == "cast" else c for c in _cols]
        collist = ", ".join(quoted)
        placeholders = ", ".join(["?"] * len(_cols))
        update = ", ".join(f'{q}=excluded.{q}' for q in quoted if q != "path")
        sql = f"INSERT INTO movies ({collist}) VALUES ({placeholders}) ON CONFLICT(path) DO UPDATE SET {update}"
        conn.execute(sql, vals)
        conn.commit()
    finally:
        conn.close()


def clean_missing_movies():
    conn = db_conn()
    try:
        rows = conn.execute("SELECT path FROM movies").fetchall()
        for r in rows:
            if not os.path.isfile(r["path"]):
                conn.execute("DELETE FROM movies WHERE path=?", (r["path"],))
        conn.commit()
    finally:
        conn.close()


def get_collection(name):
    if not name:
        return None
    conn = db_conn()
    try:
        row = conn.execute("SELECT * FROM collections WHERE name=?", (name,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def upsert_collection(name, poster_url=None, backdrop_url=None, poster_local=None, backdrop_local=None):
    if not name:
        return
    conn = db_conn()
    try:
        existing = conn.execute("SELECT * FROM collections WHERE name=?", (name,)).fetchone()
        if existing:
            conn.execute("""UPDATE collections SET
                poster_url=COALESCE(?,poster_url), backdrop_url=COALESCE(?,backdrop_url),
                poster_local=COALESCE(?,poster_local), backdrop_local=COALESCE(?,backdrop_local),
                scanned_at=? WHERE name=?""",
                (poster_url, backdrop_url, poster_local, backdrop_local, time.time(), name))
        else:
            conn.execute("""INSERT INTO collections (name,poster_url,backdrop_url,poster_local,backdrop_local,scanned_at)
                            VALUES (?,?,?,?,?,?)""",
                         (name, poster_url, backdrop_url, poster_local, backdrop_local, time.time()))
        conn.commit()
    finally:
        conn.close()


def enrich_entry(entry, category=None, force=False):
    path = entry["path"]
    entry["category"] = category or entry.get("category")
    mtime = entry.get("mtime")
    existing = get_db_movie(path)
    # decide if TMDB fetch needed
    need_fetch = True
    if not force and existing and existing.get("tmdb_id") and mtime is not None and existing.get("file_mtime") == mtime:
        need_fetch = False
    # only probe when we fetch or when the DB has no probe data
    if need_fetch or not existing or not existing.get("file_info"):
        info = ffprobe_info(path)
        entry["duration"] = info.get("duration")
        entry["width"] = info.get("width")
        entry["height"] = info.get("height")
        entry["codec"] = info.get("codec")
        entry["audio"] = info.get("audio")
        entry["audio_channels"] = info.get("audio_channels")
        entry["file_info"] = compute_file_info(info)
    else:
        info = {}
        entry["duration"] = existing.get("duration")
        entry["width"] = existing.get("width")
        entry["height"] = existing.get("height")
        entry["codec"] = existing.get("codec")
        entry["audio"] = existing.get("audio")
        entry["audio_channels"] = existing.get("audio_channels")
        entry["file_info"] = existing.get("file_info")
    # load from db if no fetch
    if not need_fetch and existing:
        # reuse already-probed info for file_info (cheap)
        entry["duration"] = info.get("duration") or existing.get("duration")
        entry["width"] = info.get("width") or existing.get("width")
        entry["height"] = info.get("height") or existing.get("height")
        entry["codec"] = info.get("codec") or existing.get("codec")
        entry["audio"] = info.get("audio") or existing.get("audio")
        entry["audio_channels"] = info.get("audio_channels") or existing.get("audio_channels")
        entry["file_info"] = compute_file_info(info) or existing.get("file_info")
        entry["tmdb_id"] = existing.get("tmdb_id")
        entry["title"] = existing.get("title") or entry.get("title")
        entry["year"] = existing.get("year") or entry.get("year")
        entry["overview"] = existing.get("overview")
        entry["tagline"] = existing.get("tagline")
        entry["trailer_key"] = existing.get("trailer_key")
        try:
            entry["genres"] = json.loads(existing.get("genres") or "[]")
        except Exception:
            entry["genres"] = []
        entry["runtime"] = existing.get("runtime")
        entry["director"] = existing.get("director")
        try:
            entry["cast"] = json.loads(existing.get("cast") or "[]")
        except Exception:
            entry["cast"] = []
        try:
            entry["cast_full"] = json.loads(existing.get("cast_json") or "[]")
        except Exception:
            entry["cast_full"] = []
        try:
            entry["similar"] = json.loads(existing.get("similar_json") or "[]")
        except Exception:
            entry["similar"] = []
        entry["country"] = existing.get("country")
        entry["rating"] = existing.get("rating")
        entry["poster_url"] = existing.get("poster_url")
        entry["backdrop_url"] = existing.get("backdrop_url")
        entry["poster_local"] = existing.get("poster_local")
        entry["backdrop_local"] = existing.get("backdrop_local")
        entry["collection_name"] = existing.get("collection_name")
        entry["collection_id"] = existing.get("collection_id")
        entry["resume_position"] = existing.get("resume_position")
        entry["season"] = existing.get("season")
        entry["episode"] = existing.get("episode")
        entry["episode_title"] = existing.get("episode_title")
        entry["custom_title"] = existing.get("custom_title")
        try:
            entry["tv_seasons"] = json.loads(existing.get("tv_seasons_json") or "[]")
        except Exception:
            entry["tv_seasons"] = []
        if force:
            entry["poster_local"] = cache_image(entry.get("poster_url"), force=True)
            entry["backdrop_local"] = cache_image(entry.get("backdrop_url"), force=True)
            if not entry.get("poster_local"):
                entry["poster_local"] = make_thumb(path)
            if not entry.get("backdrop_local"):
                entry["backdrop_local"] = entry.get("poster_local") or make_thumb(path)
        else:
            entry["poster_local"] = existing.get("poster_local")
            entry["backdrop_local"] = existing.get("backdrop_local")
            if not entry.get("poster_local"):
                entry["poster_local"] = make_thumb(path)
            if not entry.get("backdrop_local"):
                entry["backdrop_local"] = entry.get("poster_local") or make_thumb(path)
    else:
        # TMDB fetch
        title = entry.get("title")
        year = entry.get("year")
        entry["resume_position"] = existing.get("resume_position") if existing else None
        entry["custom_title"] = existing.get("custom_title") if existing else None
        entry["season"] = entry.get("season")
        entry["episode"] = entry.get("episode")
        entry["episode_title"] = entry.get("episode_title")
        if not entry.get("season"):
            entry["season"] = existing.get("season") if existing else None
        if not entry.get("episode"):
            entry["episode"] = existing.get("episode") if existing else None
        if not entry.get("episode_title"):
            entry["episode_title"] = existing.get("episode_title") if existing else None
        if category == "series":
            search_res = tmdb_search_tv(title, year)
            tmdb_id = search_res.get("id") if search_res else None
            details = tmdb_details_tv(tmdb_id) if tmdb_id else None
        else:
            search_res = tmdb_search(title, year)
            tmdb_id = search_res.get("id") if search_res else None
            details = tmdb_details(tmdb_id) if tmdb_id else None
        if details:
            entry["tmdb_id"] = details.get("tmdb_id")
            entry["title"] = details.get("title") or entry.get("title")
            if details.get("year"):
                entry["year"] = details.get("year")
            entry["overview"] = details.get("overview")
            entry["genres"] = details.get("genres") or []
            entry["runtime"] = details.get("runtime")
            entry["director"] = details.get("director")
            entry["cast"] = details.get("cast") or []
            entry["country"] = details.get("country")
            entry["rating"] = details.get("rating")
            entry["poster_url"] = details.get("poster_url")
            entry["backdrop_url"] = details.get("backdrop_url")
            entry["tagline"] = details.get("tagline")
            entry["trailer_key"] = details.get("trailer_key")
            entry["cast_full"] = details.get("cast_full") or []
            entry["similar"] = details.get("similar") or []
            entry["collection_name"] = details.get("collection_name")
            entry["collection_id"] = details.get("collection_id")
            entry["tv_seasons"] = details.get("tv_seasons") or []
        else:
            entry["tmdb_id"] = tmdb_id
            entry["overview"] = search_res.get("overview") if search_res else None
            entry["poster_url"] = search_res.get("poster") if search_res else None
            entry["backdrop_url"] = search_res.get("backdrop") if search_res else None
            entry["genres"] = []
            entry["cast"] = []
            entry["country"] = None
            entry["director"] = None
            entry["runtime"] = None
            entry["rating"] = search_res.get("rating") if search_res else None
        # cache images
        entry["poster_local"] = cache_image(entry.get("poster_url"), force=force)
        entry["backdrop_local"] = cache_image(entry.get("backdrop_url"), force=force)
        # fallback to a frame from the movie if no art
        if not entry.get("poster_local"):
            entry["poster_local"] = make_thumb(path)
        if not entry.get("backdrop_local"):
            entry["backdrop_local"] = entry.get("poster_local") or make_thumb(path)
    # upsert DB
    upsert_movie_db({
        "path": path,
        "title": entry.get("title"),
        "year": entry.get("year"),
        "tmdb_id": entry.get("tmdb_id"),
        "overview": entry.get("overview"),
        "genres": entry.get("genres"),
        "runtime": entry.get("runtime"),
        "director": entry.get("director"),
        "cast": entry.get("cast"),
        "country": entry.get("country"),
        "rating": entry.get("rating"),
        "poster_url": entry.get("poster_url"),
        "backdrop_url": entry.get("backdrop_url"),
        "poster_local": entry.get("poster_local"),
        "backdrop_local": entry.get("backdrop_local"),
        "resume_position": entry.get("resume_position"),
        "tagline": entry.get("tagline"),
        "trailer_key": entry.get("trailer_key"),
        "cast_full": entry.get("cast_full"),
        "similar": entry.get("similar"),
        "collection_name": entry.get("collection_name"),
        "collection_id": entry.get("collection_id"),
        "season": entry.get("season"),
        "episode": entry.get("episode"),
        "episode_title": entry.get("episode_title"),
        "custom_title": entry.get("custom_title"),
        "tv_seasons": entry.get("tv_seasons"),
        "duration": entry.get("duration"),
        "width": entry.get("width"),
        "height": entry.get("height"),
        "codec": entry.get("codec"),
        "audio": entry.get("audio"),
        "file_info": entry.get("file_info"),
        "category": entry.get("category"),
        "collection": entry.get("collection"),
        "mtime": mtime,
        "sub_count": entry.get("sub_count", 0),
    })
    # normalize lists
    entry.setdefault("genres", [])
    entry.setdefault("cast", [])
    return entry


def ffprobe_info(path):
    cmd = [tool_path("ffprobe"), "-v", "error", "-analyzeduration", "1000000", "-probesize", "500000",
           "-show_format", "-show_streams", "-of", "json", path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        data = json.loads(r.stdout or "{}")
    except Exception as e:
        return {"error": str(e)}
    info = {"path": path, "duration": None, "width": None, "height": None, "codec": None, "audio": None, "audio_channels": None}
    fmt = data.get("format") or {}
    if fmt.get("duration"):
        try:
            info["duration"] = float(fmt["duration"])
        except ValueError:
            pass
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and info["width"] is None:
            info["width"] = s.get("width")
            info["height"] = s.get("height")
            info["codec"] = s.get("codec_name")
        if s.get("codec_type") == "audio" and info["audio"] is None:
            info["audio"] = s.get("codec_name")
            info["audio_channels"] = s.get("channels")
    return info


def compute_file_info(info):
    w = info.get("width") or 0
    h = info.get("height") or 0
    if w >= 3840:
        res = "4K (2160p)"
    elif w >= 2560:
        res = "1440p"
    elif w >= 1920:
        res = "1080p"
    elif w >= 1280:
        res = "720p"
    elif w > 0:
        res = f"{w}x{h}"
    else:
        res = ""
    audio = (info.get("audio") or "").upper()
    ch = info.get("audio_channels")
    if audio and ch:
        if ch >= 6:
            audio = f"{audio} 5.1"
        elif ch == 2:
            audio = f"{audio} 2.0"
        else:
            audio = f"{audio} {ch}ch"
    parts = [p for p in (res, audio) if p]
    return " · ".join(parts)


def tmdb_search(title, year):
    key = (CFG.get("tmdb_api_key") or "").strip()
    if not key or not HAS_REQUESTS:
        return None
    cache_key = f"{title}|{year or ''}"
    if cache_key in _tmdb_cache:
        return _tmdb_cache[cache_key]
    params = {"api_key": key, "query": title, "include_adult": "false", "language": "en-US"}
    if year:
        params["year"] = year
    for _attempt in range(3):
        try:
            r = requests.get("https://api.themoviedb.org/3/search/movie", params=params, timeout=12)
            if r.status_code == 429:
                time.sleep(2)
                continue
            data = r.json()
            break
        except Exception as e:
            return {"error": str(e)}
    else:
        return None
    res = data.get("results") or []
    # Fallback: drop the year filter if it produced nothing.
    if not res and year:
        params.pop("year", None)
        for _attempt in range(3):
            try:
                r = requests.get("https://api.themoviedb.org/3/search/movie", params=params, timeout=12)
                if r.status_code == 429:
                    time.sleep(2)
                    continue
                data = r.json()
                break
            except Exception as e:
                return {"error": str(e)}
        else:
            return None
        res = data.get("results") or []
    if not res:
        _tmdb_cache[cache_key] = None
        save_tmdb_cache()
        return None
    m = res[0]
    out = {
        "id": m.get("id"),
        "title": m.get("title"),
        "year": (m.get("release_date") or "")[:4],
        "overview": m.get("overview"),
        "rating": m.get("vote_average"),
        "poster": ("https://image.tmdb.org/t/p/w500" + m["poster_path"]) if m.get("poster_path") else None,
        "backdrop": ("https://image.tmdb.org/t/p/w1280" + m["backdrop_path"]) if m.get("backdrop_path") else None,
    }
    _tmdb_cache[cache_key] = out
    save_tmdb_cache()
    return out


def tmdb_search_tv(name, year):
    key = (CFG.get("tmdb_api_key") or "").strip()
    if not key or not HAS_REQUESTS:
        return None
    cache_key = "tvsearch|" + str(name) + "|" + str(year or "")
    if cache_key in _tmdb_cache:
        return _tmdb_cache[cache_key]
    params = {"api_key": key, "query": name, "include_adult": "false", "language": "en-US"}
    if year:
        try:
            params["first_air_date_year"] = int(str(year)[:4])
        except Exception:
            pass
    for _attempt in range(3):
        try:
            r = requests.get("https://api.themoviedb.org/3/search/tv", params=params, timeout=12)
            if r.status_code == 429:
                time.sleep(2)
                continue
            data = r.json()
            break
        except Exception as e:
            return {"error": str(e)}
    else:
        return None
    res = data.get("results") or []
    # Fallback: drop the year filter if it produced nothing.
    if not res and "first_air_date_year" in params:
        params.pop("first_air_date_year", None)
        for _attempt in range(3):
            try:
                r = requests.get("https://api.themoviedb.org/3/search/tv", params=params, timeout=12)
                if r.status_code == 429:
                    time.sleep(2)
                    continue
                data = r.json()
                break
            except Exception as e:
                return {"error": str(e)}
        else:
            return None
        res = data.get("results") or []
    if not res:
        _tmdb_cache[cache_key] = None
        save_tmdb_cache()
        return None
    m = res[0]
    out = {
        "id": m.get("id"),
        "title": m.get("name"),
        "year": (m.get("first_air_date") or "")[:4],
        "overview": m.get("overview"),
        "rating": m.get("vote_average"),
        "poster": ("https://image.tmdb.org/t/p/w500" + m["poster_path"]) if m.get("poster_path") else None,
        "backdrop": ("https://image.tmdb.org/t/p/w1280" + m["backdrop_path"]) if m.get("backdrop_path") else None,
    }
    _tmdb_cache[cache_key] = out
    save_tmdb_cache()
    return out


def tmdb_details_tv(tv_id):
    key = (CFG.get("tmdb_api_key") or "").strip()
    if not key or not HAS_REQUESTS or not tv_id:
        return None
    cache_key = "tvd|" + str(tv_id)
    if cache_key in _tmdb_cache:
        return _tmdb_cache[cache_key]
    data = {}
    cred = {}
    videos = {}
    similar = {}
    for _attempt in range(3):
        try:
            r = requests.get("https://api.themoviedb.org/3/tv/" + str(tv_id), params={"api_key": key, "language": "en-US"}, timeout=12)
            if r.status_code == 429:
                time.sleep(2); continue
            data = r.json()
            r2 = requests.get("https://api.themoviedb.org/3/tv/" + str(tv_id) + "/credits", params={"api_key": key}, timeout=12)
            if r2.status_code == 429:
                time.sleep(2); continue
            cred = r2.json() if r2.status_code == 200 else {}
            try:
                r3 = requests.get("https://api.themoviedb.org/3/tv/" + str(tv_id) + "/videos", params={"api_key": key, "language": "en-US"}, timeout=12)
                if r3.status_code == 200:
                    videos = r3.json()
            except Exception:
                pass
            try:
                r4 = requests.get("https://api.themoviedb.org/3/tv/" + str(tv_id) + "/similar", params={"api_key": key, "language": "en-US"}, timeout=12)
                if r4.status_code == 200:
                    similar = r4.json()
            except Exception:
                pass
            break
        except Exception as e:
            return {"error": str(e)}
    genres = [g.get("name") for g in (data.get("genres") or []) if g.get("name")]
    countries = [c for c in (data.get("origin_country") or [])]
    creators = [c.get("name") for c in (data.get("created_by") or []) if c.get("name")]
    director = ", ".join(creators) if creators else None
    cast = []
    cast_full = []
    for c in (cred.get("cast") or [])[:18]:
        if c.get("name"):
            cast.append(c.get("name"))
            cast_full.append({
                "name": c.get("name"),
                "character": c.get("character"),
                "profile": ("https://image.tmdb.org/t/p/w185" + c["profile_path"]) if c.get("profile_path") else None,
            })
    poster_path = data.get("poster_path")
    backdrop_path = data.get("backdrop_path")
    poster_url = ("https://image.tmdb.org/t/p/w500" + poster_path) if poster_path else None
    backdrop_url = ("https://image.tmdb.org/t/p/w1280" + backdrop_path) if backdrop_path else None
    trailer_key = None
    for v in (videos.get("results") or []):
        if v.get("site") == "YouTube" and v.get("type") in ("Trailer", "Teaser"):
            trailer_key = v.get("key")
            break
    similar_list = []
    for m in (similar.get("results") or [])[:12]:
        if m.get("name"):
            similar_list.append({
                "id": m.get("id"),
                "title": m.get("name"),
                "year": (m.get("first_air_date") or "")[:4],
                "poster": ("https://image.tmdb.org/t/p/w185" + m["poster_path"]) if m.get("poster_path") else None,
            })
    seasons = []
    for s in (data.get("seasons") or []):
        if (s.get("season_number") or 0) == 0:
            continue
        sp = s.get("poster_path")
        seasons.append({
            "season": s.get("season_number"),
            "name": s.get("name"),
            "poster": ("https://image.tmdb.org/t/p/w342" + sp) if sp else None,
            "episode_count": s.get("episode_count"),
        })
    out = {
        "tmdb_id": data.get("id"),
        "title": data.get("name"),
        "year": (data.get("first_air_date") or "")[:4],
        "overview": data.get("overview"),
        "tagline": data.get("tagline"),
        "genres": genres,
        "runtime": (data.get("episode_run_time") or [None])[0],
        "director": director,
        "cast": cast,
        "cast_full": cast_full,
        "country": ", ".join(countries) if countries else None,
        "rating": data.get("vote_average"),
        "poster_url": poster_url,
        "backdrop_url": backdrop_url,
        "trailer_key": trailer_key,
        "similar": similar_list,
        "collection_name": data.get("name"),
        "collection_id": data.get("id"),
        "tv_seasons": seasons,
    }
    _tmdb_cache[cache_key] = out
    save_tmdb_cache()
    return out

def cache_image(url, force=False):
    if not url:
        return None
    try:
        import hashlib
        h = hashlib.sha1(url.encode()).hexdigest()
        ext = ".jpg"
        low = url.lower()
        if ".png" in low:
            ext = ".png"
        elif ".webp" in low:
            ext = ".webp"
        out = IMAGES_DIR / (h + ext)
        if force and out.exists():
            try:
                out.unlink()
            except Exception:
                pass
        if out.exists() and out.stat().st_size > 0:
            return str(out)
        if not HAS_REQUESTS:
            return None
        r = requests.get(url, timeout=20)
        if r.status_code == 200 and r.content:
            out.write_bytes(r.content)
            return str(out)
    except Exception:
        pass
    return None


def parse_tmdb_ref(value):
    """Extract a TMDB id and optional language from an id or a TMDB URL."""
    s = str(value or "").strip()
    if not s:
        return None, None
    lang = None
    lm = re.search(r"[?&]language=([A-Za-z-]+)", s)
    if lm:
        lang = lm.group(1)
    m = re.search(r"(\d+)", s)
    return (int(m.group(1)) if m else None), lang


def tmdb_details(tmdb_id, language=None):
    key = (CFG.get("tmdb_api_key") or "").strip()
    if not key or not HAS_REQUESTS or not tmdb_id:
        return None
    lang = (language or "en-US").strip() or "en-US"
    cache_key = f"details_v4|{tmdb_id}|{lang}"
    if cache_key in _tmdb_cache:
        return _tmdb_cache[cache_key]
    data = {}
    cred = {}
    videos = {}
    similar = {}
    for _attempt in range(3):
        try:
            r = requests.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}", params={"api_key": key, "language": lang}, timeout=12)
            if r.status_code == 429:
                time.sleep(2); continue
            data = r.json()
            r2 = requests.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}/credits", params={"api_key": key}, timeout=12)
            if r2.status_code == 429:
                time.sleep(2); continue
            cred = r2.json() if r2.status_code == 200 else {}
            # videos (trailers)
            try:
                r3 = requests.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}/videos", params={"api_key": key, "language": lang}, timeout=12)
                if r3.status_code == 200:
                    videos = r3.json()
            except Exception:
                pass
            # similar
            try:
                r4 = requests.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}/similar", params={"api_key": key}, timeout=12)
                if r4.status_code == 200:
                    similar = r4.json()
            except Exception:
                pass
            break
        except Exception as e:
            return {"error": str(e)}
    genres = [g.get("name") for g in (data.get("genres") or []) if g.get("name")]
    countries = [c.get("name") for c in (data.get("production_countries") or []) if c.get("name")]
    director = None
    for c in (cred.get("crew") or []):
        if c.get("job") == "Director":
            director = c.get("name")
            break
    cast = [c.get("name") for c in (cred.get("cast") or [])[:12] if c.get("name")]
    poster_path = data.get("poster_path")
    backdrop_path = data.get("backdrop_path")
    poster_url = ("https://image.tmdb.org/t/p/w500" + poster_path) if poster_path else None
    backdrop_url = ("https://image.tmdb.org/t/p/w1280" + backdrop_path) if backdrop_path else None
    # trailer key (fall back to English videos when the localized list has none)
    trailer_key = None
    for v in (videos.get("results") or []):
        if v.get("site") == "YouTube" and v.get("type") in ("Trailer", "Teaser"):
            trailer_key = v.get("key")
            break
    if not trailer_key and lang != "en-US":
        try:
            rv = requests.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}/videos",
                              params={"api_key": key, "language": "en-US"}, timeout=12)
            if rv.status_code == 200:
                for v in (rv.json().get("results") or []):
                    if v.get("site") == "YouTube" and v.get("type") in ("Trailer", "Teaser"):
                        trailer_key = v.get("key")
                        break
        except Exception:
            pass
    # cast with photos
    cast_full = []
    for c in (cred.get("cast") or [])[:18]:
        if c.get("name"):
            cast_full.append({
                "name": c.get("name"),
                "character": c.get("character"),
                "profile": ("https://image.tmdb.org/t/p/w185" + c["profile_path"]) if c.get("profile_path") else None,
            })
    # similar movies
    similar_list = []
    for m in (similar.get("results") or [])[:12]:
        if m.get("title"):
            similar_list.append({
                "id": m.get("id"),
                "title": m.get("title"),
                "year": (m.get("release_date") or "")[:4],
                "poster": ("https://image.tmdb.org/t/p/w185" + m["poster_path"]) if m.get("poster_path") else None,
            })
    # collection
    coll = data.get("belongs_to_collection")
    collection_name = coll.get("name") if coll else None
    collection_id = coll.get("id") if coll else None
    out = {
        "tmdb_id": data.get("id"),
        "title": data.get("title"),
        "year": (data.get("release_date") or "")[:4],
        "overview": data.get("overview"),
        "tagline": data.get("tagline"),
        "genres": genres,
        "runtime": data.get("runtime"),
        "director": director,
        "cast": [c["name"] for c in cast_full],
        "cast_full": cast_full,
        "country": ", ".join(countries) if countries else None,
        "rating": data.get("vote_average"),
        "poster_url": poster_url,
        "backdrop_url": backdrop_url,
        "trailer_key": trailer_key,
        "similar": similar_list,
        "collection_name": collection_name,
        "collection_id": collection_id,
    }
    _tmdb_cache[cache_key] = out
    save_tmdb_cache()
    return out


def make_thumb(video_path):
    vp = Path(video_path)
    key = str(vp) + "|" + str(vp.stat().st_mtime if vp.exists() else 0)
    import hashlib
    h = hashlib.sha1(key.encode()).hexdigest()
    out = THUMB_DIR / (h + ".jpg")
    if out.exists() and out.stat().st_size > 0:
        return str(out)
    # probe duration for seek point
    info = ffprobe_info(video_path)
    dur = info.get("duration") or 0
    ss = min(30.0, dur * 0.1) if dur else 5
    cmd = [tool_path("ffmpeg"), "-y", "-ss", str(ss), "-i", video_path,
           "-vframes", "1", "-q:v", "3", str(out)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=120)
    except Exception:
        pass
    if out.exists() and out.stat().st_size > 0:
        return str(out)
    return None


def escape_sub_path(p):
    p = p.replace("\\", "/")
    # escape drive colon
    if len(p) > 1 and p[1] == ":":
        p = p[0] + "\\:" + p[2:]
    # escape single quotes
    p = p.replace("'", "\\'")
    return p


def convert_sub_to_vtt(sub_path):
    sp = Path(sub_path)
    if sp.suffix.lower() == ".vtt":
        return str(sp)
    import hashlib
    key = str(sp) + "|" + str(sp.stat().st_mtime if sp.exists() else 0)
    h = hashlib.sha1(key.encode()).hexdigest()
    out = VTT_DIR / (h + ".vtt")
    if out.exists() and out.stat().st_size > 0:
        return str(out)
    cmd = [tool_path("ffmpeg"), "-y", "-i", str(sp), str(out)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=120)
    except Exception:
        pass
    if out.exists() and out.stat().st_size > 0:
        return str(out)
    # fallback: manual srt->vtt
    try:
        text = sp.read_text(encoding="utf-8", errors="replace")
        # basic conversion
        lines = text.splitlines()
        out_lines = ["WEBVTT", ""]
        for line in lines:
            if "-->" in line:
                line = line.replace(",", ".")
            out_lines.append(line)
        out.write_text("\n".join(out_lines), encoding="utf-8")
        return str(out)
    except Exception:
        return None


# ---------- server handle ----------
HTTPD = None
SHUTDOWN_REQUESTED = False

# ---------- playback state ----------
PLAYBACK = {
    "proc": None,
    "gen": 0,
    "path": None,
    "sub": None,
    "pos": 0.0,        # base position of current segment
    "volume": CFG.get("volume", 80),
    "paused": False,
    "playing": False,
    "duration": 0.0,
    "segment_start": 0.0,
    "monitor": None,
}


def _kill_proc(proc):
    if proc is None:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def current_position():
    if not PLAYBACK["playing"]:
        return PLAYBACK["pos"]
    if PLAYBACK["paused"]:
        return PLAYBACK["pos"]
    import time
    return PLAYBACK["pos"] + (time.monotonic() - PLAYBACK["segment_start"])


def _focus_ffplay():
    time.sleep(1.5)
    title = "MoviePlayer"
    try:
        if os.name == "nt":
            import ctypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            SW_RESTORE = 9
            SW_SHOW = 5
            HWND_TOP = 0
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_SHOWWINDOW = 0x0040
            ASFW_ANY = -1
            # allow any process to set foreground
            try:
                user32.AllowSetForegroundWindow(ASFW_ANY)
            except Exception:
                pass
            hwnd = None
            # find by exact title first
            for _ in range(30):
                hwnd = user32.FindWindowW(None, title)
                if hwnd:
                    break
                # enumerate windows as fallback
                if hwnd is None:
                    found = {"h": None}
                    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
                    def cb(h, _):
                        buf = ctypes.create_unicode_buffer(256)
                        user32.GetWindowTextW(h, buf, 256)
                        t = buf.value
                        if t and title.lower() in t.lower():
                            found["h"] = h
                            return False
                        return True
                    user32.EnumWindows(cb, 0)
                    hwnd = found["h"]
                if hwnd:
                    break
                time.sleep(0.3)
            if not hwnd:
                return
            # restore & focus
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.ShowWindow(hwnd, SW_SHOW)
            fg = user32.GetForegroundWindow()
            if fg and fg != hwnd:
                fg_tid = user32.GetWindowThreadProcessId(fg, None)
                cur_tid = kernel32.GetCurrentThreadId()
                if fg_tid and fg_tid != cur_tid:
                    user32.AttachThreadInput(fg_tid, cur_tid, True)
            user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
            if fg and fg != hwnd:
                fg_tid = user32.GetWindowThreadProcessId(fg, None)
                cur_tid = kernel32.GetCurrentThreadId()
                if fg_tid and fg_tid != cur_tid:
                    user32.AttachThreadInput(fg_tid, cur_tid, False)
        else:
            for cmd in (["xdotool", "search", "--name", title, "windowactivate"],
                        ["wmctrl", "-a", title]):
                try:
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                    return
                except Exception:
                    continue
    except Exception:
        pass


def ass_color(hex_color):
    h = (hex_color or "#ffffff").lstrip("#").strip()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return "&H00FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return ("&H00" + b + g + r).upper()


def _launch_ffplay(path, sub, pos, volume, gen):
    cmd = [tool_path("ffplay"), "-window_title", "MoviePlayer",
           "-autoexit", "-ss", f"{pos:.3f}", "-volume", str(int(volume))]
    if sub:
        esc = escape_sub_path(sub)
        sub_size = int(CFG.get("sub_size") or 28)
        sub_color = ass_color(CFG.get("sub_color") or "#ffffff")
        cmd += ["-vf", f"subtitles='{esc}':force_style='FontSize={sub_size},PrimaryColour={sub_color},OutlineColour=&H00000000,BorderStyle=1,Outline=2'"]
    cmd += [path]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return None
    PLAYBACK["proc"] = proc
    PLAYBACK["gen"] = gen
    # bring ffplay window to foreground
    threading.Thread(target=_focus_ffplay, daemon=True).start()
    # monitor
    def monitor(p, g):
        try:
            p.wait()
        except Exception:
            pass
        # only update if still current generation
        if PLAYBACK["gen"] == g and PLAYBACK["proc"] is p:
            # process ended: finished vs. closed mid-way
            if PLAYBACK["playing"] and not PLAYBACK["paused"]:
                end_pos = current_position()
                dur = PLAYBACK["duration"]
                if dur and end_pos >= dur - 5:
                    PLAYBACK["pos"] = dur
                    if PLAYBACK["path"]:
                        try:
                            _save_resume_position(PLAYBACK["path"], 0.0)
                        except Exception:
                            pass
                else:
                    PLAYBACK["pos"] = end_pos
                    if PLAYBACK["path"] and end_pos > 10:
                        try:
                            _save_resume_position(PLAYBACK["path"], end_pos)
                        except Exception:
                            pass
            PLAYBACK["playing"] = False
            PLAYBACK["paused"] = False
            PLAYBACK["proc"] = None
    t = threading.Thread(target=monitor, args=(proc, gen), daemon=True)
    t.start()
    PLAYBACK["monitor"] = t
    return proc


def _save_resume_position(path, pos):
    try:
        conn = db_conn()
        conn.execute("UPDATE movies SET resume_position=? WHERE path=?", (float(pos), path))
        conn.commit()
        conn.close()
    except Exception:
        pass


def do_play(path, sub=None, ss=None, volume=None):
    path = norm_path(path)
    if not path or not os.path.isfile(path):
        return {"error": "file not found"}
    # resume from saved position if not explicitly seeking
    auto_resume = False
    if ss is None:
        try:
            existing = get_db_movie(path)
            rp = existing.get("resume_position") if existing else None
            if rp and rp > 10:
                ss = rp
                auto_resume = True
        except Exception:
            pass
    # kill existing
    _kill_proc(PLAYBACK["proc"])
    PLAYBACK["proc"] = None
    if volume is not None:
        PLAYBACK["volume"] = int(volume)
    # new file?
    if path != PLAYBACK["path"]:
        PLAYBACK["pos"] = 0.0
        PLAYBACK["duration"] = 0.0
        PLAYBACK["sub"] = None
    PLAYBACK["path"] = path
    if sub is not None:
        PLAYBACK["sub"] = sub if sub else None
    if ss is not None:
        PLAYBACK["pos"] = float(ss)
    if PLAYBACK["duration"] == 0.0:
        info = ffprobe_info(path)
        if info.get("duration"):
            PLAYBACK["duration"] = info["duration"]
    pos = PLAYBACK["pos"]
    if pos < 0:
        pos = 0.0
    if PLAYBACK["duration"] and pos > PLAYBACK["duration"]:
        pos = PLAYBACK["duration"]
    # nearly finished: start from the beginning instead of resuming
    if auto_resume and PLAYBACK["duration"] and pos > PLAYBACK["duration"] - 120:
        pos = 0.0
    PLAYBACK["pos"] = pos
    gen = PLAYBACK["gen"] + 1
    proc = _launch_ffplay(path, PLAYBACK["sub"], pos, PLAYBACK["volume"], gen)
    if proc is None:
        return {"error": "ffplay not found. Check ffplay_path in settings."}
    import time
    PLAYBACK["segment_start"] = time.monotonic()
    PLAYBACK["paused"] = False
    PLAYBACK["playing"] = True
    return playback_status()


def do_pause():
    if not PLAYBACK["playing"] or PLAYBACK["paused"]:
        return playback_status()
    PLAYBACK["pos"] = current_position()
    _save_resume_position(PLAYBACK["path"], PLAYBACK["pos"])
    _kill_proc(PLAYBACK["proc"])
    PLAYBACK["proc"] = None
    PLAYBACK["paused"] = True
    PLAYBACK["playing"] = True
    return playback_status()


def do_resume():
    if not PLAYBACK["paused"]:
        return playback_status()
    PLAYBACK["paused"] = False
    gen = PLAYBACK["gen"] + 1
    proc = _launch_ffplay(PLAYBACK["path"], PLAYBACK["sub"], PLAYBACK["pos"], PLAYBACK["volume"], gen)
    if proc is None:
        PLAYBACK["paused"] = True
        return {"error": "ffplay not found"}
    import time
    PLAYBACK["segment_start"] = time.monotonic()
    PLAYBACK["playing"] = True
    return playback_status()


def do_stop():
    if PLAYBACK["path"]:
        try:
            _save_resume_position(PLAYBACK["path"], current_position())
        except Exception:
            pass
    _kill_proc(PLAYBACK["proc"])
    PLAYBACK["proc"] = None
    PLAYBACK["playing"] = False
    PLAYBACK["paused"] = False
    PLAYBACK["pos"] = 0.0
    # reset resume position on full stop? keep it so user can resume later
    return playback_status()


def do_seek(pos):
    if not PLAYBACK.get("path"):
        return playback_status()
    try:
        pos = float(pos)
    except (TypeError, ValueError):
        return {"error": "bad position"}
    if pos < 0:
        pos = 0.0
    if PLAYBACK["duration"] and pos > PLAYBACK["duration"]:
        pos = PLAYBACK["duration"]
    was_playing = PLAYBACK["playing"] and not PLAYBACK["paused"]
    PLAYBACK["pos"] = pos
    _kill_proc(PLAYBACK["proc"])
    PLAYBACK["proc"] = None
    if was_playing:
        gen = PLAYBACK["gen"] + 1
        proc = _launch_ffplay(PLAYBACK["path"], PLAYBACK["sub"], pos, PLAYBACK["volume"], gen)
        if proc is None:
            PLAYBACK["playing"] = False
            return {"error": "ffplay not found"}
        import time
        PLAYBACK["segment_start"] = time.monotonic()
        PLAYBACK["playing"] = True
        PLAYBACK["paused"] = False
    else:
        PLAYBACK["paused"] = PLAYBACK["playing"]  # keep paused state
        # if was paused, remain paused at new pos
        PLAYBACK["playing"] = PLAYBACK["playing"]
    return playback_status()


def do_volume(vol):
    try:
        vol = int(vol)
    except (TypeError, ValueError):
        return {"error": "bad volume"}
    vol = max(0, min(100, vol))
    PLAYBACK["volume"] = vol
    CFG["volume"] = vol
    save_config(CFG)
    if PLAYBACK["playing"] and not PLAYBACK["paused"] and PLAYBACK["path"]:
        # relaunch at current pos
        pos = current_position()
        PLAYBACK["pos"] = pos
        _kill_proc(PLAYBACK["proc"])
        PLAYBACK["proc"] = None
        gen = PLAYBACK["gen"] + 1
        proc = _launch_ffplay(PLAYBACK["path"], PLAYBACK["sub"], pos, vol, gen)
        if proc is None:
            return {"error": "ffplay not found"}
        import time
        PLAYBACK["segment_start"] = time.monotonic()
    return playback_status()


def do_skip(delta):
    pos = current_position() + float(delta)
    return do_seek(pos)


def playback_status():
    # persist resume position periodically while playing
    try:
        if PLAYBACK["playing"] and not PLAYBACK["paused"] and PLAYBACK["path"]:
            now = time.monotonic()
            if now - PLAYBACK.get("last_save", 0) > 30:
                pos = current_position()
                if pos > 10:
                    _save_resume_position(PLAYBACK["path"], pos)
                PLAYBACK["last_save"] = now
    except Exception:
        pass
    return {
        "playing": PLAYBACK["playing"],
        "paused": PLAYBACK["paused"],
        "path": PLAYBACK["path"],
        "sub": PLAYBACK["sub"],
        "position": current_position(),
        "duration": PLAYBACK["duration"],
        "volume": PLAYBACK["volume"],
    }


# ---------- folder browsing ----------
def list_drives():
    out = []
    if os.name == "nt":
        for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            d = f"{c}:\\"
            if os.path.isdir(d):
                out.append(d)
    else:
        out.append("/")
        home = str(Path.home())
        if home not in out:
            out.append(home)
    return out


def parse_fmhy_streaming_sites(text):
    """Parse only the Streaming Sites section, preserving each Markdown row."""
    metadata_labels = {"discord", "telegram", "status", "mirrors", "invite", "subreddit", "github",
                       "note", "4k note", "4k guide", "available countries", "clones", "extension",
                       "grading page"}
    metadata_hosts = ("discord.", "discord.com", "telegram.", "t.me/", "rentry.", "github.com/",
                      "reddit.com/", "fmhy-grading.")
    sites = []
    in_section = False
    category = "Streaming"
    for line in text.splitlines():
        line = line.strip()
        if line == "# ► Streaming Sites":
            in_section = True
            continue
        if in_section and line.startswith("# "):
            break
        if not in_section:
            continue
        if line.startswith("## "):
            category = re.sub(r"^##\s*[▷►]\s*", "", line).strip() or "Streaming"
            continue
        if category.lower() == "stream lounges":
            continue
        if not line.startswith("* ") or line.startswith("* **Note"):
            continue
        row = line[2:].strip()
        rank_match = re.match(r"([🌟⭐🌐]+)\s*", row)
        rank = rank_match.group(1) if rank_match else ""
        if rank:
            row = row[rank_match.end():]
        row_parts = re.split(r"\s+-\s+", row, maxsplit=1)
        link_part = row_parts[0]
        description = row_parts[1].strip() if len(row_parts) == 2 else ""
        links = re.findall(r"\[([^\]]+)\]\((https?://[^)]+)\)", link_part)
        if not links:
            continue
        usable = []
        for label, url in links:
            label = re.sub(r"[*_]+", "", label).strip()
            low_label = label.lower()
            low_url = url.lower()
            if low_label in metadata_labels or any(host in low_url for host in metadata_hosts):
                continue
            usable.append({"label": label, "url": url})
        if not usable:
            continue
        joined_labels = " ".join(link["label"] for link in usable).lower()
        if any(term in joined_labels for term in ("twitch", "youtube", "channel", "multireddit", "random streams")):
            continue
        # The first link is the named site; subsequent links stay grouped as mirrors/alternates.
        main = usable[0]
        clean_description = description
        def clean_description_link(match):
            label = re.sub(r"[*_]+", "", match.group(1)).strip()
            url = match.group(2).lower()
            if label.lower() in metadata_labels or any(host in url for host in metadata_hosts):
                return ""
            return label
        clean_description = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", clean_description_link, clean_description)
        clean_description = re.sub(r"\*+", "", clean_description)
        clean_description = re.sub(r"\s*/\s*(?=/|$)", " ", clean_description)
        clean_description = re.sub(r"\s{2,}", " ", clean_description).strip(" /")
        sites.append({"name": main["label"], "url": main["url"], "description": clean_description,
                      "category": category, "alternates": usable[1:], "rank": rank})
    return sites


def fetch_streaming_sites(force=False):
    conn = db_conn()
    try:
        rows = conn.execute("SELECT MAX(fetched_at) AS fetched_at, COUNT(*) AS total, SUM(category IS NULL) AS legacy FROM streaming_sites").fetchone()
        if rows and not force and not rows["legacy"] and (time.time() - (rows["fetched_at"] or 0)) < 86400:
            # already cached
            pass
        else:
            # fetch
            url = "https://raw.githubusercontent.com/wiki/fmhy/FMHY/Streaming.md"
            try:
                r = requests.get(url, timeout=20) if HAS_REQUESTS else None
                text = r.text if (r and r.status_code == 200) else ""
            except Exception:
                text = ""
            if not text:
                # try github page
                try:
                    r = requests.get("https://github.com/fmhy/FMHY/wiki/Streaming", timeout=20)
                    text = r.text if (r and r.status_code == 200) else ""
                except Exception:
                    text = ""
            sites = parse_fmhy_streaming_sites(text)
            # store
            conn.execute("DELETE FROM streaming_sites")
            now = time.time()
            for site in sites:
                conn.execute("""INSERT OR IGNORE INTO streaming_sites
                    (name,url,description,category,alternates,rank,fetched_at)
                    VALUES (?,?,?,?,?,?,?)""",
                    (site["name"], site["url"], site["description"], site["category"],
                     json.dumps(site["alternates"], ensure_ascii=False), site["rank"], now))
            conn.commit()
    finally:
        conn.close()


def get_streaming_sites():
    fetch_streaming_sites()
    conn = db_conn()
    try:
        rows = conn.execute("SELECT name,url,description,category,alternates,rank FROM streaming_sites ORDER BY id").fetchall()
        sites = []
        for row in rows:
            site = dict(row)
            try:
                site["alternates"] = json.loads(site.get("alternates") or "[]")
            except Exception:
                site["alternates"] = []
            sites.append(site)
        return sites
    finally:
        conn.close()


def get_custom_streaming_sites():
    sites = CFG.get("custom_streaming_sites", []) or []
    return [s for s in sites if isinstance(s, dict) and s.get("name") and s.get("url")]


def add_custom_streaming_site(name, url):
    sites = get_custom_streaming_sites()
    if not any(s["url"].rstrip("/").lower() == url.rstrip("/").lower() for s in sites):
        sites.append({"name": name.strip(), "url": url.strip()})
        CFG["custom_streaming_sites"] = sites
        save_config(CFG)
    return sites


def remove_custom_streaming_site(url):
    sites = [s for s in get_custom_streaming_sites() if s["url"].rstrip("/").lower() != url.rstrip("/").lower()]
    CFG["custom_streaming_sites"] = sites
    save_config(CFG)
    return sites


def get_favorites():
    conn = db_conn()
    try:
        rows = conn.execute("SELECT * FROM streaming_favorites ORDER BY added_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def add_favorite(tmdb_id, title, year, poster, media_type="movie"):
    conn = db_conn()
    try:
        # avoid dup
        existing = conn.execute("SELECT id FROM streaming_favorites WHERE tmdb_id=? AND media_type=?", (tmdb_id, media_type)).fetchone()
        if existing:
            return dict(existing)
        conn.execute("INSERT INTO streaming_favorites (tmdb_id,title,year,poster,media_type,added_at) VALUES (?,?,?,?,?,?)",
                     (tmdb_id, title, year, poster, media_type, time.time()))
        conn.commit()
    finally:
        conn.close()


def remove_favorite(tmdb_id, media_type="movie"):
    conn = db_conn()
    try:
        conn.execute("DELETE FROM streaming_favorites WHERE tmdb_id=? AND media_type=?", (tmdb_id, media_type))
        conn.commit()
    finally:
        conn.close()


def tmdb_watchlist():
    key = (CFG.get("tmdb_api_key") or "").strip()
    sess = (CFG.get("tmdb_session_id") or "").strip()
    if not key or not sess or not HAS_REQUESTS:
        return []
    try:
        # get account id
        r = requests.get("https://api.themoviedb.org/3/account", params={"api_key": key, "session_id": sess}, timeout=12)
        acc = r.json()
        acc_id = acc.get("id")
        if not acc_id:
            return []
        out = []
        for mt in ("movies", "tv"):
            endpoint = "movies" if mt == "movies" else "tv"
            r = requests.get(f"https://api.themoviedb.org/3/account/{acc_id}/watchlist/{endpoint}",
                             params={"api_key": key, "session_id": sess, "sort_by": "created_at.desc"}, timeout=12)
            for m in (r.json().get("results") or [])[:40]:
                out.append({
                    "id": m.get("id"),
                    "title": m.get("title") or m.get("name"),
                    "year": (m.get("release_date") or m.get("first_air_date") or "")[:4],
                    "poster": ("https://image.tmdb.org/t/p/w342" + m["poster_path"]) if m.get("poster_path") else None,
                    "media_type": "movie" if mt == "movies" else "tv",
                })
        return out
    except Exception:
        return []


def list_dirs(path):
    if not path:
        return list_drives()
    p = norm_path(path)
    if not p or not os.path.isdir(p):
        return []
    out = []
    try:
        for entry in sorted(os.scandir(p), key=lambda e: e.name.lower()):
            if entry.is_dir() and not entry.name.startswith("."):
                out.append(entry.path)
    except Exception:
        pass
    return out


# ---------- HTTP handler ----------
class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, TimeoutError):
            pass

    def handle_error(self, request, client_address):
        pass

    def _send(self, code, body=b"", content_type="text/plain; charset=utf-8", headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _serve_file(self, path, download_name=None):
        path = norm_path(path)
        if not path or not os.path.isfile(path):
            self._send(404, "not found")
            return
        size = os.path.getsize(path)
        # content type
        ext = os.path.splitext(path)[1].lower()
        mime = {
            ".html": "text/html; charset=utf-8",
            ".htm": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm",
            ".ogv": "video/ogg", ".mp3": "audio/mpeg", ".wav": "audio/wav",
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".gif": "image/gif", ".svg": "image/svg+xml",
            ".vtt": "text/vtt; charset=utf-8",
            ".srt": "application/x-subrip; charset=utf-8",
            ".txt": "text/plain; charset=utf-8",
        }.get(ext, "application/octet-stream")
        # Range support
        rng = self.headers.get("Range")
        start = 0
        end = size - 1
        status = 200
        if rng and rng.startswith("bytes="):
            try:
                spec = rng[6:].split(",")[0]
                if "-" in spec:
                    a, b = spec.split("-", 1)
                    if a:
                        start = int(a)
                    if b:
                        end = int(b)
                if start > end or start >= size:
                    self._send(416, "range not satisfiable")
                    return
                status = 206
            except Exception:
                start = 0
                end = size - 1
                status = 200
        length = end - start + 1
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
        }
        if status == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        if download_name:
            headers["Content-Disposition"] = f'attachment; filename="{download_name}"'
        self.send_response(status)
        self.send_header("Content-Type", mime)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(path, "rb") as f:
                f.seek(start)
                remaining = length
                chunk = 65536
                while remaining > 0:
                    data = f.read(min(chunk, remaining))
                    if not data:
                        break
                    self.wfile.write(data)
                    remaining -= len(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self._serve_file(str(HERE / "static" / "index.html"))
            return
        if path.startswith("/static/"):
            name = path[len("/static/"):]
            # safe
            name = name.lstrip("/")
            fpath = HERE / "static" / name
            if fpath.is_file():
                # mime by ext
                ext = fpath.suffix.lower()
                mime = {
                    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                    ".js": "application/javascript; charset=utf-8", ".json": "application/json",
                    ".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml",
                }.get(ext, "application/octet-stream")
                self._serve_file(str(fpath))
                return
            self._send(404, "not found")
            return
        if path == "/player.html":
            self._serve_static("player.html", "text/html; charset=utf-8")
            return

        if path == "/api/config":
            self._json(dict(CFG))
            return
        if path == "/api/libraries":
            category = (qs.get("category", ["movie"])[0] or "movie").lower()
            key = category + "_dirs"
            self._json({"media_dirs": CFG.get(key, []), "category": category})
            return
        if path == "/api/browse":
            p = qs.get("path", [None])[0]
            if p is not None:
                p = urllib.parse.unquote(p)
            dirs = list_dirs(p)
            self._json({"path": p, "dirs": dirs})
            return
        if path == "/api/scan":
            category = qs.get("category", [None])[0]
            force = qs.get("force", ["0"])[0] in ("1", "true", "yes")
            d = qs.get("dir", [None])[0]
            if d is not None:
                d = urllib.parse.unquote(d)
            if d:
                dirs_to_scan = [d]
            else:
                key = (category or "movie") + "_dirs"
                dirs_to_scan = CFG.get(key, [])
            cat = category or "movie"
            results = []
            for root in dirs_to_scan:
                rp = norm_path(root)
                if rp and os.path.isdir(rp):
                    results.extend(scan_dir(rp, cat))
            # de-dup by path
            seen = set()
            uniq = []
            for r in results:
                if r["path"] in seen:
                    continue
                seen.add(r["path"])
                uniq.append(r)
            # enrich + store metadata (TMDB etc.) in parallel
            from concurrent.futures import ThreadPoolExecutor, as_completed
            errors = []
            def _enrich(e):
                try:
                    enrich_entry(e, cat, force=force)
                except Exception as ex:
                    e.setdefault("genres", [])
                    e.setdefault("cast", [])
                    errors.append(f"{os.path.basename(e.get('path') or '?')}: {ex}")
                return e
            with ThreadPoolExecutor(max_workers=5) as ex:
                futures = [ex.submit(_enrich, e) for e in uniq]
                for f in as_completed(futures):
                    pass
            clean_missing_movies()
            save_tmdb_cache(force=True)
            self._json({"movies": uniq, "count": len(uniq), "errors": errors[:20]})
            return
        if path == "/api/probe":
            p = qs.get("path", [None])[0]
            if p is None:
                self._json({"error": "missing path"}, 400)
                return
            p = urllib.parse.unquote(p)
            self._json(ffprobe_info(p))
            return
        if path == "/api/thumb":
            p = qs.get("path", [None])[0]
            if p is None:
                self._send(404, "missing path")
                return
            p = urllib.parse.unquote(p)
            t = make_thumb(p)
            if t and os.path.isfile(t):
                self._serve_file(t)
            else:
                self._send(404, "no thumb")
            return
        if path == "/api/tmdb":
            title = qs.get("title", [""])[0]
            year = qs.get("year", [""])[0]
            title = urllib.parse.unquote(title)
            self._json({"result": tmdb_search(title, year or None)})
            return
        if path == "/api/tmdb/results":
            title = urllib.parse.unquote(qs.get("title", [""])[0] or "").strip()
            year = (qs.get("year", [""])[0] or "").strip() or None
            # Accept "Title (Year)" / "Title, Year" in the title box.
            if title:
                m = re.match(r"^(.*?)\s*[\(\[]\s*(\d{4})\s*[\)\]]\s*$", title)
                if m:
                    title = m.group(1).strip()
                    year = year or m.group(2)
                elif not year:
                    m = re.match(r"^(.*?)[\s,]+(\d{4})\s*$", title)
                    if m:
                        title = m.group(1).strip()
                        year = m.group(2)
            key = (CFG.get("tmdb_api_key") or "").strip()
            out = []
            if key and HAS_REQUESTS and title:
                def _search(url, params, media_type):
                    try:
                        r = requests.get(url, params=params, timeout=12)
                        if r.status_code != 200:
                            return []
                        items = []
                        for m in (r.json().get("results") or [])[:12]:
                            name = m.get("title") if media_type == "movie" else m.get("name")
                            date = m.get("release_date") if media_type == "movie" else m.get("first_air_date")
                            items.append({
                                "id": m.get("id"),
                                "title": name,
                                "year": (date or "")[:4],
                                "overview": m.get("overview"),
                                "rating": m.get("vote_average"),
                                "media_type": media_type,
                                "popularity": m.get("popularity") or 0,
                                "poster": ("https://image.tmdb.org/t/p/w342" + m["poster_path"]) if m.get("poster_path") else None,
                                "backdrop": ("https://image.tmdb.org/t/p/w780" + m["backdrop_path"]) if m.get("backdrop_path") else None,
                            })
                        return items
                    except Exception:
                        return []
                base = {"api_key": key, "query": title, "include_adult": "false", "language": "en-US"}
                movie_params = dict(base)
                tv_params = dict(base)
                if year:
                    movie_params["year"] = year
                    tv_params["first_air_date_year"] = year
                out = _search("https://api.themoviedb.org/3/search/movie", movie_params, "movie")
                out += _search("https://api.themoviedb.org/3/search/tv", tv_params, "tv")
                # Fallback: if a year filter yielded nothing, retry without it.
                if not out and year:
                    out = _search("https://api.themoviedb.org/3/search/movie", dict(base), "movie")
                    out += _search("https://api.themoviedb.org/3/search/tv", dict(base), "tv")
                out.sort(key=lambda x: -(x.get("popularity") or 0))
            self._json({"results": out})
            return
        if path == "/api/tmdb/details":
            tid, lang = parse_tmdb_ref(qs.get("id", [""])[0])
            lang = (qs.get("language", [""])[0] or "").strip() or lang
            mtype = (qs.get("type", [""])[0] or qs.get("media_type", [""])[0] or "movie").strip().lower()
            if not tid:
                d = None
            elif mtype == "tv":
                d = tmdb_details_tv(tid)
            else:
                d = tmdb_details(tid, lang)
            self._json({"details": d})
            return
        if path == "/api/subtitles":
            p = qs.get("path", [None])[0]
            if p is None:
                self._json({"error": "missing path"}, 400)
                return
            p = urllib.parse.unquote(p)
            subs = find_subtitles(p)
            self._json({"subtitles": [{"path": s, "label": sub_label(s)} for s in subs]})
            return
        if path == "/api/vtt":
            p = qs.get("path", [None])[0]
            if p is None:
                self._send(404, "missing path")
                return
            p = urllib.parse.unquote(p)
            v = convert_sub_to_vtt(p)
            if v and os.path.isfile(v):
                self._serve_file(v)
            else:
                self._send(404, "no vtt")
            return
        if path == "/api/file":
            p = qs.get("path", [None])[0]
            if p is None:
                self._send(404, "missing path")
                return
            p = urllib.parse.unquote(p)
            self._serve_file(p)
            return
        if path == "/api/status":
            self._json(playback_status())
            return
        if path == "/api/music/list":
            d = (CFG.get("music_dir") or "").strip()
            tracks = []
            if d and os.path.isdir(d):
                for root, _, files in os.walk(d):
                    for fn in files:
                        if fn.lower().endswith(".mp3"):
                            tracks.append({"name": os.path.splitext(fn)[0], "path": os.path.join(root, fn)})
            self._json({"tracks": tracks, "dir": d})
            return
        if path == "/api/movies":
            # filters from query
            q = (qs.get("q", [""])[0] or "").strip().lower()
            country = (qs.get("country", [""])[0] or "").strip().lower()
            director = (qs.get("director", [""])[0] or "").strip().lower()
            actor = (qs.get("actor", [""])[0] or "").strip().lower()
            genre = (qs.get("genre", [""])[0] or "").strip().lower()
            year = (qs.get("year", [""])[0] or "").strip()
            category = (qs.get("category", [""])[0] or "").strip().lower()
            sort = (qs.get("sort", ["title_asc"])[0] or "title_asc").strip().lower()
            sets_only = qs.get("sets", ["0"])[0] in ("1", "true", "yes")
            conn = db_conn()
            try:
                rows = conn.execute("SELECT * FROM movies ORDER BY title").fetchall()
                # load collection art
                coll_rows = conn.execute("SELECT * FROM collections").fetchall()
            finally:
                conn.close()
            coll_map = {dict(c)["name"]: dict(c) for c in coll_rows}
            rlist = [dict(r) for r in rows]
            if sort == "title_desc":
                rlist.sort(key=lambda r: (r.get("title") or "").lower(), reverse=True)
            elif sort == "year_asc":
                rlist.sort(key=lambda r: (r.get("year") or ""))
            elif sort == "year_desc":
                rlist.sort(key=lambda r: (r.get("year") or ""), reverse=True)
            elif sort in ("recent", "recently_added", "newest"):
                rlist.sort(key=lambda r: (r.get("scanned_at") or 0), reverse=True)
            else:
                rlist.sort(key=lambda r: (r.get("title") or "").lower())
            rows = rlist
            out = []
            for r in rows:
                r = dict(r) if not isinstance(r, dict) else r
                if not os.path.isfile(r["path"]):
                    continue
                if category and (r.get("category") or "movie").lower() != category:
                    continue
                coll = r.get("collection")
                if coll and coll in coll_map:
                    c = coll_map[coll]
                    r["collection_poster_url"] = c.get("poster_url")
                    r["collection_backdrop_url"] = c.get("backdrop_url")
                    r["collection_poster_local"] = c.get("poster_local")
                    r["collection_backdrop_local"] = c.get("backdrop_local")
                # parse lists
                try:
                    genres = json.loads(r.get("genres") or "[]")
                except Exception:
                    genres = []
                try:
                    cast = json.loads(r.get("cast") or "[]")
                except Exception:
                    cast = []
                r["genres"] = genres
                r["cast"] = cast
                # filters
                title_l = (r.get("title") or "").lower()
                if q and q not in title_l:
                    continue
                if country:
                    _cs = [c.strip().lower() for c in (r.get("country") or "").split(",") if c.strip()]
                    if country not in _cs:
                        continue
                if director and director not in (r.get("director") or "").lower():
                    continue
                if actor and not any(actor in (c or "").lower() for c in cast):
                    continue
                if genre and not any(genre in (g or "").lower() for g in genres):
                    continue
                if year and str(r.get("year") or "") != year:
                    continue
                if sets_only and not (r.get("collection")):
                    continue
                try:
                    r["countries"] = [c.strip() for c in (r.get("country") or "").split(",") if c.strip()]
                except Exception:
                    r["countries"] = []
                out.append(r)
            self._json({"movies": out, "count": len(out)})
            return
        pass
        if path == "/api/movie":
            p = qs.get("path", [None])[0]
            if p is None:
                self._json({"error": "missing path"}, 400)
                return
            p = urllib.parse.unquote(p)
            m = get_db_movie(p)
            if m:
                try:
                    m["genres"] = json.loads(m.get("genres") or "[]")
                except Exception:
                    m["genres"] = []
                try:
                    m["cast"] = json.loads(m.get("cast") or "[]")
                except Exception:
                    m["cast"] = []
                try:
                    m["cast_full"] = json.loads(m.get("cast_json") or "[]")
                except Exception:
                    m["cast_full"] = []
                try:
                    m["similar"] = json.loads(m.get("similar_json") or "[]")
                except Exception:
                    m["similar"] = []
            self._json({"movie": m})
            return
        if path == "/api/series":
            q = (qs.get("q", [""])[0] or "").strip().lower()
            genre = (qs.get("genre", [""])[0] or "").strip().lower()
            country = (qs.get("country", [""])[0] or "").strip().lower()
            actor = (qs.get("actor", [""])[0] or "").strip().lower()
            year = (qs.get("year", [""])[0] or "").strip()
            conn = db_conn()
            try:
                rows = conn.execute("SELECT * FROM movies WHERE category='series'").fetchall()
                coll_rows = conn.execute("SELECT * FROM collections").fetchall()
            finally:
                conn.close()
            coll_map = {dict(c)["name"]: dict(c) for c in coll_rows}
            episodes = []
            for r in rows:
                r = dict(r)
                if not os.path.isfile(r["path"]):
                    continue
                try:
                    r["genres"] = json.loads(r.get("genres") or "[]")
                except Exception:
                    r["genres"] = []
                try:
                    r["cast"] = json.loads(r.get("cast") or "[]")
                except Exception:
                    r["cast"] = []
                try:
                    r["cast_full"] = json.loads(r.get("cast_json") or "[]")
                except Exception:
                    r["cast_full"] = []
                try:
                    r["similar"] = json.loads(r.get("similar_json") or "[]")
                except Exception:
                    r["similar"] = []
                try:
                    r["tv_seasons"] = json.loads(r.get("tv_seasons_json") or "[]")
                except Exception:
                    r["tv_seasons"] = []
                title_l = (r.get("title") or "").lower()
                et_l = (r.get("episode_title") or "").lower()
                if q and q not in title_l and q not in et_l:
                    continue
                if genre and not any(genre in (g or "").lower() for g in r["genres"]):
                    continue
                if country:
                    cs = [c.strip().lower() for c in (r.get("country") or "").split(",") if c.strip()]
                    if country not in cs:
                        continue
                if actor and not any(actor in (c or "").lower() for c in r["cast"]):
                    continue
                if year and str(r.get("year") or "") != year:
                    continue
                episodes.append(r)
            groups = {}
            for r in episodes:
                key = r.get("collection") or r.get("title")
                g = groups.setdefault(key, {
                    "key": key,
                    "name": r.get("custom_title") or r.get("title"),
                    "year": r.get("year"),
                    "poster_url": r.get("poster_url"),
                    "poster_local": r.get("poster_local"),
                    "backdrop_url": r.get("backdrop_url"),
                    "backdrop_local": r.get("backdrop_local"),
                    "tmdb_id": r.get("tmdb_id"),
                    "overview": r.get("overview"),
                    "rating": r.get("rating"),
                    "genres": r.get("genres") or [],
                    "country": r.get("country"),
                    "director": r.get("director"),
                    "trailer_key": r.get("trailer_key"),
                    "cast_full": r.get("cast_full") or [],
                    "tv_seasons": r.get("tv_seasons") or [],
                    "_seasons": {},
                })
                if key in coll_map:
                    c = coll_map[key]
                    g["poster_url"] = g["poster_url"] or c.get("poster_url")
                    g["poster_local"] = g["poster_local"] or c.get("poster_local")
                    g["backdrop_url"] = g["backdrop_url"] or c.get("backdrop_url")
                    g["backdrop_local"] = g["backdrop_local"] or c.get("backdrop_local")
                if not g["tv_seasons"]:
                    g["tv_seasons"] = r.get("tv_seasons") or []
                sn = int(r.get("season") or 1)
                g["_seasons"].setdefault(sn, []).append(r)
            out_series = []
            for key, g in groups.items():
                season_poster_map = {s.get("season"): s.get("poster") for s in (g["tv_seasons"] or [])}
                season_name_map = {s.get("season"): s.get("name") for s in (g["tv_seasons"] or [])}
                seasons = []
                for sn in sorted(g["_seasons"]):
                    eps = sorted(g["_seasons"][sn], key=lambda r: (r.get("episode") or 0))
                    seasons.append({
                        "season": sn,
                        "name": season_name_map.get(sn),
                        "poster": season_poster_map.get(sn) or g["poster_url"],
                        "poster_local": g["poster_local"],
                        "backdrop_url": g["backdrop_url"],
                        "backdrop_local": g["backdrop_local"],
                        "episodes": eps,
                    })
                g["seasons"] = seasons
                del g["_seasons"]
                out_series.append(g)
            out_series.sort(key=lambda g: (g.get("name") or "").lower())
            self._json({"series": out_series, "count": len(out_series)})
            return
        if path == "/api/counts":
            conn = db_conn()
            try:
                mc = conn.execute("SELECT COUNT(*) c FROM movies WHERE category='movie'").fetchone()["c"]
                sc = conn.execute("SELECT COUNT(DISTINCT COALESCE(collection,title)) c FROM movies WHERE category='series'").fetchone()["c"]
            finally:
                conn.close()
            self._json({"movies": mc, "series": sc})
            return
        if path == "/api/streaming/sites":
            force = (qs.get("refresh", ["0"])[0] or "0") == "1"
            if force:
                fetch_streaming_sites(force=True)
            sites = get_streaming_sites()
            self._json({"sites": sites, "count": len(sites)})
            return
        if path == "/api/streaming/custom-sites":
            sites = get_custom_streaming_sites()
            self._json({"sites": sites, "count": len(sites)})
            return
        if path == "/api/streaming/favorites":
            self._json({"favorites": get_favorites()})
            return
        if path == "/api/streaming/watchlist":
            self._json({"watchlist": tmdb_watchlist()})
            return
        if path == "/api/streaming/search":
            q = urllib.parse.unquote(qs.get("q", [""])[0] or "")
            # TMDB search for movie and tv
            results = {"movies": [], "tv": []}
            key = (CFG.get("tmdb_api_key") or "").strip()
            if key and HAS_REQUESTS and q:
                try:
                    r = requests.get("https://api.themoviedb.org/3/search/movie", params={"api_key": key, "query": q}, timeout=12)
                    results["movies"] = r.json().get("results", [])[:10]
                    r2 = requests.get("https://api.themoviedb.org/3/search/tv", params={"api_key": key, "query": q}, timeout=12)
                    results["tv"] = r2.json().get("results", [])[:10]
                except Exception:
                    pass
            sites = get_streaming_sites() + get_custom_streaming_sites()
            # build a multi-site search URL via duckduckgo (keep short to avoid query length limits)
            site_filter = " OR ".join(f"site:{urllib.parse.urlparse(s['url']).netloc}" for s in sites[:6])
            ddg = "https://duckduckgo.com/?q=" + urllib.parse.quote(f"{q} ({site_filter})")
            self._json({"query": q, "tmdb": results, "sites": sites, "duckduckgo": ddg})
            return
        if path == "/api/filter_options":
            category = (qs.get("category", [""])[0] or "").strip().lower()
            conn = db_conn()
            try:
                if category:
                    rows = conn.execute('SELECT country,director,genres,"cast",year FROM movies WHERE category=?', (category,)).fetchall()
                else:
                    rows = conn.execute('SELECT country,director,genres,"cast",year FROM movies').fetchall()
                rows = [dict(r) for r in rows]
            finally:
                conn.close()
            countries = set()
            directors = set()
            genres = set()
            actors = set()
            years = set()
            for r in rows:
                if r.get("country"):
                    for _c in str(r["country"]).replace("/", ",").split(","):
                        _c = _c.strip()
                        if _c:
                            countries.add(_c)
                if r.get("director"):
                    directors.add(r["director"])
                if r.get("year"):
                    years.add(r["year"])
                try:
                    for g in json.loads(r.get("genres") or "[]"):
                        genres.add(g)
                except Exception:
                    pass
                try:
                    for a in json.loads(r.get("cast") or "[]"):
                        actors.add(a)
                except Exception:
                    pass
            self._json({
                "countries": sorted(countries),
                "directors": sorted(directors),
                "genres": sorted(genres),
                "actors": sorted(actors),
                "years": sorted(years, reverse=True),
            })
            return

        self._send(404, "not found")

    def do_POST(self):
        global SHUTDOWN_REQUESTED
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            data = {}

        if path == "/api/config":
            # update config (merge)
            for k, v in data.items():
                if k == "tmdb_api_key" and "..." in str(v):
                    continue
                CFG[k] = v
            save_config(CFG)
            self._json({"ok": True})
            return
        if path == "/api/libraries":
            action = data.get("action")
            category = (data.get("category") or "movie").lower()
            key = category + "_dirs"
            CFG.setdefault(key, [])
            d = norm_path(data.get("dir"))
            if action == "add" and d:
                if d not in CFG[key]:
                    CFG[key].append(d)
                save_config(CFG)
            elif action == "remove" and d:
                CFG[key] = [x for x in CFG.get(key, []) if norm_path(x) != d]
                save_config(CFG)
            self._json({"media_dirs": CFG.get(key, []), "category": category})
            return
        if path == "/api/movie/art":
            p = norm_path(data.get("path"))
            poster_url = data.get("poster_url")
            backdrop_url = data.get("backdrop_url")
            if not p:
                self._json({"error": "missing path"}, 400)
                return
            existing = get_db_movie(p) or {}
            if poster_url is None and backdrop_url is None:
                tl = make_thumb(p)
                poster_local = tl
                backdrop_local = tl
            else:
                poster_local = cache_image(poster_url) if poster_url else existing.get("poster_local")
                backdrop_local = cache_image(backdrop_url) if backdrop_url else existing.get("backdrop_local")
                if not backdrop_local and poster_local:
                    backdrop_local = poster_local
            conn = db_conn()
            try:
                conn.execute("""UPDATE movies SET poster_url=?, backdrop_url=?, poster_local=?, backdrop_local=?, scanned_at=? WHERE path=?""",
                             (poster_url, backdrop_url, poster_local, backdrop_local, time.time(), p))
                conn.commit()
            finally:
                conn.close()
            m = get_db_movie(p)
            if m:
                try:
                    m["genres"] = json.loads(m.get("genres") or "[]")
                except Exception:
                    m["genres"] = []
                try:
                    m["cast"] = json.loads(m.get("cast") or "[]")
                except Exception:
                    m["cast"] = []
                try:
                    m["cast_full"] = json.loads(m.get("cast_json") or "[]")
                except Exception:
                    m["cast_full"] = []
                try:
                    m["similar"] = json.loads(m.get("similar_json") or "[]")
                except Exception:
                    m["similar"] = []
            self._json({"movie": m})
            return
        if path == "/api/collection/art":
            collection = data.get("collection")
            poster_url = data.get("poster_url")
            backdrop_url = data.get("backdrop_url")
            if not collection:
                self._json({"error": "missing collection"}, 400)
                return
            if poster_url is None and backdrop_url is None:
                conn = db_conn()
                try:
                    row = conn.execute("SELECT path FROM movies WHERE collection=? LIMIT 1", (collection,)).fetchone()
                finally:
                    conn.close()
                tl = make_thumb(row["path"]) if row else None
                upsert_collection(collection, poster_local=tl, backdrop_local=tl)
            else:
                poster_local = cache_image(poster_url) if poster_url else None
                backdrop_local = cache_image(backdrop_url) if backdrop_url else None
                if not backdrop_local and poster_local:
                    backdrop_local = poster_local
                upsert_collection(collection, poster_url=poster_url, backdrop_url=backdrop_url,
                                 poster_local=poster_local, backdrop_local=backdrop_local)
            self._json({"ok": True, "collection": get_collection(collection)})
            return
        if path == "/api/movie/rename":
            p = norm_path(data.get("path"))
            new_name = (data.get("title") or "").strip()
            if not p or not new_name:
                self._json({"error": "missing"}, 400)
                return
            conn = db_conn()
            try:
                conn.execute("UPDATE movies SET custom_title=?, title=? WHERE path=?", (new_name, new_name, p))
                conn.commit()
            finally:
                conn.close()
            m = get_db_movie(p)
            if m:
                try:
                    m["genres"] = json.loads(m.get("genres") or "[]")
                except Exception:
                    m["genres"] = []
                try:
                    m["cast"] = json.loads(m.get("cast") or "[]")
                except Exception:
                    m["cast"] = []
                try:
                    m["cast_full"] = json.loads(m.get("cast_json") or "[]")
                except Exception:
                    m["cast_full"] = []
                try:
                    m["similar"] = json.loads(m.get("similar_json") or "[]")
                except Exception:
                    m["similar"] = []
            self._json({"movie": m})
            return
        if path == "/api/series/rename":
            key = data.get("collection") or data.get("key")
            new_name = (data.get("title") or "").strip()
            if not key or not new_name:
                self._json({"error": "missing"}, 400)
                return
            conn = db_conn()
            try:
                conn.execute("UPDATE movies SET custom_title=?, title=? WHERE collection=? AND category='series'", (new_name, new_name, key))
                conn.commit()
            finally:
                conn.close()
            self._json({"ok": True, "name": new_name})
            return
        if path == "/api/series/apply_tmdb":
            key = data.get("collection") or data.get("key")
            tmdb_id, url_lang = parse_tmdb_ref(data.get("tmdb_id"))
            lang = (data.get("language") or "").strip() or url_lang
            mtype = (data.get("media_type") or "tv").strip().lower()
            if not key or not tmdb_id:
                self._json({"error": "missing"}, 400)
                return
            details = tmdb_details(tmdb_id, lang) if mtype == "movie" else tmdb_details_tv(tmdb_id)
            if not details or details.get("error"):
                self._json({"error": "tmdb not found"}, 404)
                return
            poster_local = cache_image(details.get("poster_url"))
            backdrop_local = cache_image(details.get("backdrop_url"))
            if not backdrop_local and poster_local:
                backdrop_local = poster_local
            conn = db_conn()
            try:
                row = conn.execute("SELECT tv_seasons_json FROM movies WHERE collection=? AND category='series' LIMIT 1", (key,)).fetchone()
                existing_seasons = row["tv_seasons_json"] if row else None
                if details.get("tv_seasons") is not None:
                    seasons_json = json.dumps(details.get("tv_seasons"))
                else:
                    seasons_json = existing_seasons or "[]"
                conn.execute("""UPDATE movies SET tmdb_id=?, title=?, custom_title=NULL, year=?, overview=?, genres=?, runtime=?,
                    director=?, "cast"=?, country=?, rating=?, poster_url=?, backdrop_url=?, poster_local=?,
                    backdrop_local=?, tagline=?, trailer_key=?, cast_json=?, similar_json=?,
                    collection_name=?, collection_id=?, scanned_at=?, tv_seasons_json=?
                    WHERE collection=? AND category='series'""",
                    (details.get("tmdb_id"), details.get("title"), details.get("year"), details.get("overview"),
                     json.dumps(details.get("genres") or []), details.get("runtime"), details.get("director"),
                     json.dumps(details.get("cast") or []), details.get("country"), details.get("rating"),
                     details.get("poster_url"), details.get("backdrop_url"), poster_local, backdrop_local,
                     details.get("tagline"), details.get("trailer_key"), json.dumps(details.get("cast_full") or []),
                     json.dumps(details.get("similar") or []), details.get("collection_name"), details.get("collection_id"),
                     time.time(), seasons_json, key))
                conn.commit()
            finally:
                conn.close()
            upsert_collection(key, poster_url=details.get("poster_url"), backdrop_url=details.get("backdrop_url"),
                              poster_local=poster_local, backdrop_local=backdrop_local)
            self._json({"ok": True, "details": details})
            return
        if path == "/api/movie/apply_tmdb":
            p = norm_path(data.get("path"))
            tmdb_id, url_lang = parse_tmdb_ref(data.get("tmdb_id"))
            lang = (data.get("language") or "").strip() or url_lang
            if not p or not tmdb_id:
                self._json({"error": "missing"}, 400)
                return
            existing = get_db_movie(p) or {}
            cat = (data.get("category") or existing.get("category") or "movie").lower()
            mtype = (data.get("media_type") or "").strip().lower()
            if mtype == "tv" or (not mtype and cat == "series"):
                details = tmdb_details_tv(tmdb_id)
            else:
                details = tmdb_details(tmdb_id, lang)
            if not details or details.get("error"):
                self._json({"error": "tmdb not found"}, 404)
                return
            poster_local = cache_image(details.get("poster_url"))
            backdrop_local = cache_image(details.get("backdrop_url"))
            if not backdrop_local and poster_local:
                backdrop_local = poster_local
            conn = db_conn()
            try:
                conn.execute("""UPDATE movies SET tmdb_id=?, title=?, custom_title=NULL, year=?, overview=?, genres=?, runtime=?,
                    director=?, "cast"=?, country=?, rating=?, poster_url=?, backdrop_url=?, poster_local=?,
                    backdrop_local=?, tagline=?, trailer_key=?, cast_json=?, similar_json=?,
                    collection_name=?, collection_id=?, scanned_at=?, tv_seasons_json=? WHERE path=?""",
                    (details.get("tmdb_id"), details.get("title"), details.get("year"), details.get("overview"),
                     json.dumps(details.get("genres") or []), details.get("runtime"), details.get("director"),
                     json.dumps(details.get("cast") or []), details.get("country"), details.get("rating"),
                     details.get("poster_url"), details.get("backdrop_url"), poster_local, backdrop_local,
                     details.get("tagline"), details.get("trailer_key"), json.dumps(details.get("cast_full") or []),
                     json.dumps(details.get("similar") or []), details.get("collection_name"), details.get("collection_id"),
                     time.time(), json.dumps(details.get("tv_seasons") or []), p))
                conn.commit()
            finally:
                conn.close()
            m = get_db_movie(p)
            if m:
                try:
                    m["genres"] = json.loads(m.get("genres") or "[]")
                except Exception:
                    m["genres"] = []
                try:
                    m["cast"] = json.loads(m.get("cast") or "[]")
                except Exception:
                    m["cast"] = []
                try:
                    m["cast_full"] = json.loads(m.get("cast_json") or "[]")
                except Exception:
                    m["cast_full"] = []
                try:
                    m["similar"] = json.loads(m.get("similar_json") or "[]")
                except Exception:
                    m["similar"] = []
                try:
                    m["tv_seasons"] = json.loads(m.get("tv_seasons_json") or "[]")
                except Exception:
                    m["tv_seasons"] = []
                m["display_title"] = m.get("custom_title") or m.get("title")
            self._json({"movie": m})
            return
        if path == "/api/play":
            res = do_play(data.get("path"), data.get("sub"), data.get("ss"), data.get("volume"))
            self._json(res)
            return
        if path == "/api/pause":
            self._json(do_pause())
            return
        if path == "/api/resume":
            self._json(do_resume())
            return
        if path == "/api/stop":
            self._json(do_stop())
            return
        if path == "/api/seek":
            self._json(do_seek(data.get("pos", 0)))
            return
        if path == "/api/skip":
            self._json(do_skip(data.get("delta", CFG.get("skip_seconds", 10))))
            return
        if path == "/api/volume":
            self._json(do_volume(data.get("volume", CFG.get("volume", 80))))
            return
        if path == "/api/streaming/favorite":
            add_favorite(data.get("tmdb_id"), data.get("title"), data.get("year"), data.get("poster"), data.get("media_type", "movie"))
            self._json({"ok": True})
            return
        if path == "/api/streaming/unfavorite":
            remove_favorite(data.get("tmdb_id"), data.get("media_type", "movie"))
            self._json({"ok": True})
            return
        if path == "/api/streaming/custom-sites":
            action_url = str(data.get("url") or "").strip()
            if self.command == "POST":
                if data.get("action") == "remove":
                    if not action_url:
                        self._json({"error": "url is required"}, 400)
                        return
                    sites = remove_custom_streaming_site(action_url)
                    self._json({"ok": True, "sites": sites})
                    return
                name = str(data.get("name") or "").strip()
                if not name or not re.match(r"^https?://", action_url, re.I):
                    self._json({"error": "name and http(s) url are required"}, 400)
                    return
                sites = add_custom_streaming_site(name, action_url)
                self._json({"ok": True, "sites": sites})
                return
        if path == "/api/shutdown":
            do_stop()
            SHUTDOWN_REQUESTED = True
            def _shutdown():
                time.sleep(0.5)
                try:
                    if HTTPD is not None:
                        HTTPD.shutdown()
                except Exception:
                    pass
            threading.Thread(target=_shutdown, daemon=True).start()
            self._json({"ok": True})
            return
        if path == "/api/restart":
            do_stop()
            # spawn a new instance
            try:
                subprocess.Popen([sys.executable, os.path.abspath(__file__)],
                                 cwd=os.path.dirname(os.path.abspath(__file__)),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            except Exception:
                pass
            SHUTDOWN_REQUESTED = True
            def _restart_shutdown():
                time.sleep(1.0)
                try:
                    if HTTPD is not None:
                        HTTPD.shutdown()
                except Exception:
                    pass
            threading.Thread(target=_restart_shutdown, daemon=True).start()
            self._json({"ok": True})
            return

        self._json({"error": "not found"}, 404)

    def _serve_static(self, name, ctype):
        fpath = HERE / name
        if fpath.is_file():
            self._serve_file(str(fpath))
        else:
            self._send(404, "missing " + name)


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def open_browser(url):
    kiosk = bool(CFG.get("kiosk_mode", False))
    fullscreen = bool(CFG.get("fullscreen", True))
    # try chrome/edge with app/kiosk mode
    candidates = []
    if os.name == "nt":
        for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                  r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                  r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"):
            if os.path.isfile(p):
                candidates.append(p)
    else:
        for name in ("google-chrome", "chromium-browser", "chromium", "microsoft-edge", "brave-browser", "brave"):
            w = shutil.which(name)
            if w:
                candidates.append(w)
    for exe in candidates:
        try:
            args = [exe]
            if kiosk:
                args += ["--kiosk", url]
            else:
                args += ["--app=" + url]
                if fullscreen:
                    args += ["--start-fullscreen"]
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except Exception:
            continue
    # fallback
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass


def write_pid_file():
    try:
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass


def remove_pid_file():
    try:
        if PID_FILE.exists() and PID_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
            PID_FILE.unlink()
    except Exception:
        pass


def main():
    global HTTPD
    write_pid_file()
    host = CFG.get("host", "127.0.0.1")
    port = int(CFG.get("port", 8765))
    httpd = ThreadingServer((host, port), Handler)
    HTTPD = httpd
    url = f"http://{host}:{port}/"
    print(f"MoviePlayer running at {url}")
    print("Press Ctrl+C to stop.")
    threading.Thread(target=lambda: (time.sleep(1.0), open_browser(url)), daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        do_stop()
        remove_pid_file()
        httpd.server_close()


if __name__ == "__main__":
    main()
