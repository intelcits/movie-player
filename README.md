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

## Features
- Scan library folders for movies (mkv, mp4, avi, mov, webm, ...)
- SQLite metadata database (`movieplayer.db`) with per-movie details: title, year, overview, genres, runtime, director, cast, country, rating, duration, codec.
- TMDB posters, backdrops, overviews, ratings, genres, cast, director, country (paste your TMDB v3 API key in Settings).
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
- "Change art" button: search TMDB for alternative posters/backdrops and pick one, or use a frame from the movie, or paste a TMDB URL/ID.
- Sort movies by title, year, or recently added.
- Streaming: Favorites/Wishlist (add/remove), click to search. TMDB Watchlist shown if session ID configured.
- Streaming: removed DuckDuckGo option; embedded player opens in new tab.
- Grid view or split view (list + detail side by side), with left/right panel choice.
- Tabs: Movies, Series, Streaming (Musicals merged into Movies).
- Server controls (Stop/Restart/Close) in a combo box in the top bar.
- Interactive run.bat/run.sh menu to start/stop/restart the service.
- Browser launch in kiosk (fullscreen) or maximized app mode with minimize/close controls.
- Streaming tab: search movies/TV shows (TMDB), watch via an embedded player (opens in a new tab), and search across streaming sites on DuckDuckGo.

## Settings
- Library folders: browse the filesystem and add folders (e.g. `D:\Torrent_Downloads`), or paste a path.
- TMDB API key, host, port, skip seconds.
- ffplay/ffprobe/ffmpeg paths (if not on PATH).

## Notes
- Playback runs in an FFplay window; the HTML panel controls it (seeking re-launches ffplay at the new position). The window is focused automatically.
- Add library folders in Settings, then Scan. First scan fetches TMDB metadata in parallel and may take a few minutes; later scans are fast (only changed files).
- "Rescan all metadata & art" button in Settings forces a full re-fetch (TMDB + thumbnails) for all categories.
- Streaming search uses an embedded player (vidsrc) by TMDB id and links to the FMHY site list.