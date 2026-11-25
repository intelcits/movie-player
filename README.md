# MoviePlayer

A smart, easy local movie player with an HTML control panel.
Uses `ffplay` (playback), `ffprobe` (metadata) and `ffmpeg` (thumbnails, subtitles conversion).

## Requirements
- Python 3.8+
- ffmpeg / ffprobe / ffplay on PATH (or set paths in Settings)
- (Optional) TMDB v3 API key for posters, backdrops, cast, etc.

## Run
Windows 10:
```
run.bat
```
Ubuntu 20.04:
```
chmod +x run.sh
./run.sh
```
Or directly:
```
python movie_player.py
```
Then open http://127.0.0.1:8765

## Standalone scan (no app required)

`scan_movies.py` scans the folders declared in `movie_player.conf.json`, enriches new or changed files, and updates the SQLite database **without starting the web server**. It can be run on demand or scheduled. By default it scans **both movies and series**; use `--category` to restrict it.

Keep `scan_movies.py` in the same folder as `movie_player.py`.

```
python scan_movies.py                    # movies and series, incremental (fast)
python scan_movies.py --force            # re-fetch metadata and art
python scan_movies.py --category movie   # movies only
python scan_movies.py --category series  # series only
python scan_movies.py --dry-run          # list files, change nothing
python scan_movies.py --dir "D:\\New" --category movie   # scan one folder only
```

Each run writes a UTF-8 log to `logs/scan_<date>_<time>_<pid>.log` and also prints it to the console. The log lists every file with `NEW`, `UPDATE`, `SKIP` or `REMOVED`, plus a final summary (counts, errors, elapsed time). Exit codes: `0` success, `1` file errors, `2` no folders configured, `3` another scan is already running.

Scheduling examples:
```
# Windows Task Scheduler (daily at 03:00)
schtasks /Create /TN "MoviePlayer Scan" /SC DAILY /ST 03:00 /TR "\"C:\Python313\python.exe\" \"C:\tools\AI\OpenCode\Test\movie-player\scan_movies.py\""

# cron (Linux, daily at 03:00)
0 3 * * * cd /opt/movie-player && /usr/bin/python3 scan_movies.py
```

Notes:
- A lock prevents two scheduled scans from overlapping. The app may stay open; SQLite WAL handles the shared database.
- Missing files are removed from the DB only inside the folders that were scanned successfully; an offline drive is never treated as "deleted".
- Use `--force` occasionally if TMDB metadata or art needs a refresh.

## Features
- Scan library folders for movies (mkv, mp4, avi, mov, webm, ...)
- SQLite metadata database (`movieplayer.db`) with per-movie details: title, year, overview, genres, runtime, director, cast, country, rating, duration, codec.
- TMDB posters, backdrops, overviews, taglines, ratings, genres, cast, director, country (paste your TMDB v3 API key in Settings).
- Rich detail view: tagline, YouTube trailer embed, cast photos, and a "similar movies" strip from TMDB.
- Better title parsing (strips release tags, codecs, brackets, audio channels, leading numbering, and James Bond branding).
- Editable names: rename a movie or series from the ✎ Edit modal ("Save name"); the name changes without touching TMDB art or metadata.
- Split view now mirrors the detail view (metadata, trailer link, ✎ Edit).
- Series browse: Series → Season (with season cover) → Episode (with episode name and cover).
- Movie sets filter: "Movie sets only" checkbox; collection view shows each movie as `Title (Year)`.
- Country filter lists one country per line (coproductions still match).
- Search box has an explicit clear (×) button.
- Interface font size and font family settings.
- Subtitle size and color settings (ffplay force_style + browser player ::cue).
- Movies/Series counters in the top bar.
- Cached metadata images (`.cache/images/`) so they are not re-downloaded.
- On scan, deleted files are removed from the DB and changed files are re-enriched.
- When TMDB has no poster, a frame from the movie (ffmpeg thumbnail) is used as fallback art.
- Filters: name, country, director, year, actor, genre.
- ffprobe duration/resolution/codec info.
- ffmpeg thumbnails.
- External subtitle files (.srt/.ass/.vtt) auto-detected (same basename) and overlaid via ffplay.
- Browser-side preview player for mp4/webm (with SRT converted to VTT).
- Control panel: Play/Pause/Stop, Rewind/Forward (±skip and ±30s), seek bar, volume, subtitle toggle. ffplay window is brought to the foreground on play.
- Controls hide automatically when playback stops or finishes.
- Movie detail view uses the backdrop art as a visible background.
- Choose from 4 UI themes (Default, Kodi, Plex, Media Center) in Settings.
- "✎ Edit" modal: search TMDB by title or `title (year)`; click a result to apply its full metadata and art. "Fetch & Apply" accepts a TMDB URL or numeric ID (a `?language=es` URL also fetches localized metadata). "Save name" only renames; "Save & Close" refreshes the detail view. Google Images and direct image URLs are also supported.
- Sort movies by title, year, or recently added.
- Streaming: Favorites/Wishlist (add/remove), click to search. TMDB Watchlist shown if session ID configured.
- Streaming: embedded player opens in a new tab.
- Grid view or split view (list + detail side by side), with left/right panel choice.
- Tabs: Movies, Series, Streaming (Musicals merged into Movies).
- Server controls (Stop/Restart/Close) in a combo box in the top bar.
- Interactive run.bat/run.sh menu to start/stop/restart the service.
- Browser launch in fullscreen (windowed fullscreen, controls stay usable) or maximized app mode.
- Streaming tab: search movies/TV shows (TMDB), watch via an embedded player (opens in a new tab).

## Settings
- Library folders: browse the filesystem and add folders (e.g. `D:\Torrent_Downloads`), or paste a path.
- TMDB API key, TMDB session ID (optional, for watchlist), host, port, skip seconds.
- ffplay/ffprobe/ffmpeg paths (if not on PATH).

## Notes
- Playback runs in an FFplay window; the HTML panel controls it (seeking re-launches ffplay at the new position). The window is focused automatically.
- Add library folders in Settings, then Scan. First scan fetches TMDB metadata in parallel (5 workers, WAL-enabled SQLite) and may take a few minutes; later scans are fast (only changed files).
- "Rescan all metadata & art" button in Settings forces a full re-fetch (TMDB + thumbnails) for all categories.
- Streaming search uses an embedded player (vidsrc) by TMDB id and links to the FMHY site list.