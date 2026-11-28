const API = "";
let movies = [];
let seriesData = [];
let currentMovie = null;
let subsOn = true;
let currentSub = null;
let pollTimer = null;
let currentTab = "movies";
let currentCategory = "movie";

const $ = (id) => document.getElementById(id);

function catFromTab(tab) {
  if (tab === "series") return "series";
  return "movie";
}

function fmtTime(sec) {
  if (!sec || isNaN(sec)) return "0:00";
  sec = Math.floor(sec);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h > 0) return `${h}:${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`;
  return `${m}:${String(s).padStart(2,"0")}`;
}

async function api(path, opts) {
  const res = await fetch(API + path, opts);
  if (!res.ok) throw new Error(res.statusText);
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  return res;
}

function imgUrl(m, field) {
  const local = field === "poster" ? m.poster_local : m.backdrop_local;
  if (local) return `/api/file?path=${encodeURIComponent(local)}`;
  const remote = field === "poster" ? (m.poster_url || m._poster) : (m.backdrop_url || m._backdrop);
  return remote || "";
}

function showView(name) {
  $("libraryView").classList.add("hidden");
  $("detailView").classList.add("hidden");
  $("streamingView").classList.add("hidden");
  $("collectionView").classList.add("hidden");
  $("seriesView").classList.add("hidden");
  if (name === "library") $("libraryView").classList.remove("hidden");
  else if (name === "detail") $("detailView").classList.remove("hidden");
  else if (name === "streaming") $("streamingView").classList.remove("hidden");
  else if (name === "collection") $("collectionView").classList.remove("hidden");
  else if (name === "series") $("seriesView").classList.remove("hidden");
}

function switchTab(tab) {
  currentTab = tab;
  $("mediaCounter")?.setAttribute("data-active", tab);
  document.querySelectorAll(".source-switch").forEach((unit) => {
    const active = unit.dataset.tab === tab;
    unit.classList.toggle("is-active", active);
    const input = unit.querySelector("input");
    if (input) input.checked = active;
  });
  if (tab === "streaming") {
    currentCategory = "streaming";
    showView("streaming");
    loadWishlist();
  } else {
    currentCategory = catFromTab(tab);
    showView("library");
    loadFilterOptions();
    loadMovies();
  }
  mpResumeFromMedia();
}

function applyTheme(name) {
  const link = $("themeCss");
  const theme = name || "videoclub";
  document.body.dataset.theme = theme;
  if (link) link.href = `/static/theme-${theme}.css${theme === "videoclub" ? "?v=7" : ""}`;
}

function updateCabaClock() {
  const now = new Date();
  const parts = new Intl.DateTimeFormat("es-AR", {
    timeZone:"America/Argentina/Buenos_Aires", day:"2-digit", month:"2-digit", year:"numeric",
    hour:"2-digit", minute:"2-digit", hour12:false,
  }).formatToParts(now).reduce((out, part) => { out[part.type] = part.value; return out; }, {});
  $("weatherDate").textContent = `${parts.day}/${parts.month}/${parts.year}`;
  $("weatherTime").textContent = `${parts.hour}:${parts.minute}`;
}

function weatherVisual(code, isDay) {
  if ([1,2].includes(code)) return isDay ? "🌤️" : "☁️";
  if ([3,45,48].includes(code)) return "☁️";
  if ([51,53,55,56,57,61,63,65,66,67,80,81,82].includes(code)) return "🌧️";
  if ([71,73,75,77,85,86].includes(code)) return "🌨️";
  if ([95,96,99].includes(code)) return "⛈️";
  return isDay ? "☀️" : "🌙";
}

async function loadCabaWeather() {
  try {
    const url = "https://api.open-meteo.com/v1/forecast?latitude=-34.6037&longitude=-58.3816&current=temperature_2m,weather_code,is_day&timezone=America%2FArgentina%2FBuenos_Aires";
    const data = await fetch(url).then((res) => res.ok ? res.json() : Promise.reject(new Error("weather")));
    const current = data.current || {};
    $("weatherTemp").textContent = `${Math.round(Number(current.temperature_2m))} °C`;
    $("weatherIcon").textContent = weatherVisual(Number(current.weather_code), Number(current.is_day) === 1);
  } catch (e) {
    $("weatherTemp").textContent = "-- °C";
  }
}

updateCabaClock();
setInterval(updateCabaClock, 1000);
loadCabaWeather();
setInterval(loadCabaWeather, 10 * 60 * 1000);

const FONT_MAP = {
  system: '"Verdana", "Tahoma", sans-serif',
  standard: '"Verdana", "Tahoma", sans-serif',
  sans: 'Helvetica, Arial, sans-serif',
  serif: 'Georgia, "Times New Roman", serif',
  mono: '"Consolas", "Courier New", monospace',
};

function applyUiPrefs() {
  const size = parseInt($("sFontSize")?.value) || 15;
  const fam = $("sFontFamily")?.value || "system";
  document.documentElement.style.setProperty("--fs-base", size + "px");
  document.documentElement.style.setProperty("--font-ui", FONT_MAP[fam] || FONT_MAP.system);
  // persist locally for player.html subtitle prefs
  try { localStorage.setItem("mp_ui_font_size", String(size)); } catch (e) {}
}

async function loadConfig() {
  const cfg = await api("/api/config");
  $("sHost").value = cfg.host || "127.0.0.1";
  $("sPort").value = cfg.port || 8765;
  $("sSkip").value = cfg.skip_seconds || 10;
  $("sTmdbKey").value = cfg.tmdb_api_key || "";
  $("sTmdbSession").value = cfg.tmdb_session_id || "";
  const selectedTheme = cfg.theme || "videoclub";
  $("sTheme").value = selectedTheme;
  applyTheme(selectedTheme);
  $("sKiosk").checked = !!cfg.kiosk_mode;
  $("sFullscreen").checked = cfg.fullscreen !== false;
  $("sFontSize").value = cfg.ui_font_size || 15;
  $("sFontFamily").value = cfg.ui_font_family || "system";
  $("sMusicDir").value = cfg.music_dir || "";
  $("sScreensaver").value = cfg.screensaver_timeout || 5;
  $("sSubSize").value = cfg.sub_size || 28;
  $("sSubColor").value = cfg.sub_color || "#ffffff";
  applyUiPrefs();
  refreshLibLists();
  populateLibSelect();
}

async function refreshLibLists() {
  for (const cat of ["movie", "series"]) {
    const key = cat;
    const data = await api(`/api/libraries?category=${key}`);
    const listId = cat === "movie" ? "movieLibList" : "seriesLibList";
    const list = $(listId);
    if (!list) continue;
    list.innerHTML = "";
    (data.media_dirs || []).forEach((d) => {
      const div = document.createElement("div");
      div.className = "lib-item";
      div.innerHTML = `<span>${d}</span><button class="btn small" data-dir="${d}">Remove</button>`;
      div.querySelector("button").onclick = async () => {
        await api("/api/libraries", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({action:"remove", dir:d, category:key}) });
        refreshLibLists();
      };
      list.appendChild(div);
    });
  }
}

async function populateLibSelect() {
  // no-op placeholder; library select removed from header
}

async function updateCounter() {
  try {
    const d = await api("/api/counts");
    $("mediaCounter").innerHTML = `<span class="counter-item counter-movies">Movies: ${d.movies}</span><span class="counter-separator"> · </span><span class="counter-item counter-series">Series: ${d.series}</span>`;
  } catch (e) {}
}
async function loadFilterOptions() {
  try {
    const data = await api(`/api/filter_options?category=${currentCategory}`);
    const fill = (id, arr, label) => {
      const sel = $(id);
      if (!sel) return;
      const cur = sel.value;
      sel.innerHTML = `<option value="">All ${label}</option>`;
      (arr || []).forEach((v) => {
        const o = document.createElement("option");
        o.value = v; o.textContent = v;
        sel.appendChild(o);
      });
      sel.value = cur;
    };
    fill("fGenre", data.genres, "genres");
    fill("fCountry", data.countries, "countries");
    fill("fDirector", data.directors, "directors");
    fill("fActor", data.actors, "actors");
    fill("fYear", data.years, "years");
  } catch (e) {}
}

let viewMode = "grid";
let panelSideRight = true;

async function loadMovies() {
  const params = new URLSearchParams();
  params.set("category", currentCategory);
  const q = ($("searchBox").value || "").trim();
  if (q) params.set("q", q);
  const g = $("fGenre").value; if (g) params.set("genre", g);
  const c = $("fCountry").value; if (c) params.set("country", c);
  const d = $("fDirector").value; if (d) params.set("director", d);
  const a = $("fActor").value; if (a) params.set("actor", a);
  const y = $("fYear").value; if (y) params.set("year", y);
  if ($("fSetsOnly")?.checked) params.set("sets", "1");
  params.set("sort", $("sortSelect").value || "title_asc");
  if (currentCategory === "series") {
    const data = await api("/api/series?" + params.toString());
    seriesData = data.series || [];
    if (viewMode === "grid") {
      $("grid").classList.remove("hidden");
      $("splitView").classList.add("hidden");
      renderSeriesGrid();
    } else {
      $("grid").classList.add("hidden");
      $("splitView").classList.remove("hidden");
      renderSplitView();
    }
    return;
  }
  const data = await api("/api/movies?" + params.toString());
  movies = data.movies || [];
  if (viewMode === "grid") {
    $("grid").classList.remove("hidden");
    $("splitView").classList.add("hidden");
    renderGrid();
  } else {
    $("grid").classList.add("hidden");
    $("splitView").classList.remove("hidden");
    renderSplitView();
  }
}

async function scan() {
  const btn = $("scanBtn");
  const orig = btn.textContent;
  btn.textContent = "Scanning...";
  btn.disabled = true;
  try {
    const url = `/api/scan?category=${encodeURIComponent(currentCategory)}`;
    await api(url);
    await loadFilterOptions();
    await loadMovies();
    updateCounter();
  } finally {
    btn.textContent = orig;
    btn.disabled = false;
  }
}

function groupKey(m) {
  if (m.collection) return m.collection.split(/[\\/]/).pop() || m.collection;
  const name = (m.title || m.name || "").trim();
  // series episode: "Series Name S01E02 ..."
  let mm = name.match(/^(.+?)[\s._-]+S\d+E\d+/i);
  if (mm) return mm[1].replace(/[._]/g, " ").trim();
  // "Cap N" / "Cap. N" episodes
  mm = name.match(/^(.+?)[\s._-]*\[?Cap\.?\s*\d+/i);
  if (mm) return mm[1].replace(/[._]/g, " ").replace(/\s*\[.*$/, "").trim();
  // "01. Title" style
  mm = name.match(/^\d+[._\s-]+(.+)$/);
  // only group if there's a common prefix? skip; standalone
  return null;
}

function renderGrid() {
  const grid = $("grid");
  grid.innerHTML = "";
  $("emptyState").classList.toggle("hidden", movies.length > 0);
  // group movies
  const groups = new Map();
  movies.forEach((m) => {
    const k = groupKey(m);
    if (!k) {
      if (!groups.has("__single__" + m.path)) groups.set("__single__" + m.path, [m]);
      else groups.get("__single__" + m.path).push(m);
    } else {
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(m);
    }
  });
  const cards = [];
  groups.forEach((items, key) => {
    const card = document.createElement("div");
    card.className = "card";
    const isGroup = items.length > 1 && !key.startsWith("__single__");
    const first = items[0];
    let posterUrl = imgUrl(first, "poster");
    if (isGroup) {
      const cp = first.collection_poster_local || first.collection_poster_url;
      if (cp) posterUrl = first.collection_poster_local ? `/api/file?path=${encodeURIComponent(first.collection_poster_local)}` : first.collection_poster_url;
    }
    const title = isGroup ? key : (first.title || first.name);
    const year = isGroup ? `${items.length} items` : (first.year || "");
    card.innerHTML = `
      <img class="poster" src="${posterUrl}" alt="" loading="lazy" onerror="this.style.background='#000'" />
      <div class="card-title">${escapeHtml(title)}</div>
      <div class="card-year">${year}</div>`;
    card.onclick = () => {
      if (isGroup) openCollection(key, items);
      else openDetail(first);
    };
    cards.push({ card, item: first });
  });
  if (document.body.dataset.theme === "videoclub") renderGenreShelves(grid, cards);
  else cards.forEach(({ card }) => grid.appendChild(card));
}

function renderSeriesGrid() {
  const grid = $("grid");
  grid.innerHTML = "";
  $("emptyState").classList.toggle("hidden", seriesData.length > 0);
  const cards = [];
  seriesData.forEach((s) => {
    const card = document.createElement("div");
    card.className = "card";
    let posterUrl = s.poster_local ? `/api/file?path=${encodeURIComponent(s.poster_local)}` : (s.poster_url || "");
    const seasons = (s.seasons || []).length;
    const eps = (s.seasons || []).reduce((a, x) => a + (x.episodes || []).length, 0);
    card.innerHTML = `
      <img class="poster" src="${posterUrl}" alt="" loading="lazy" onerror="this.style.background='#000'" />
      <div class="card-title">${escapeHtml(s.name || s.key)}</div>
      <div class="card-year">${s.year || ""} · ${seasons} season(s) · ${eps} ep</div>`;
    card.onclick = () => openSeries(s);
    cards.push({ card, item: s });
  });
  if (document.body.dataset.theme === "videoclub") renderGenreShelves(grid, cards);
  else cards.forEach(({ card }) => grid.appendChild(card));
}

function itemGenres(item) {
  const genres = Array.isArray(item?.genres) ? item.genres.filter(Boolean) : [];
  return genres.length ? genres : ["Sin género"];
}

function appendShelf(container, label, entries) {
  if (!entries.length) return;
  const section = document.createElement("section");
  section.className = "genre-shelf";
  section.innerHTML = `<div class="shelf-header"><span class="shelf-label">${escapeHtml(label)}</span><span class="shelf-count">${entries.length} títulos</span></div><div class="shelf-row"></div>`;
  const row = section.querySelector(".shelf-row");
  entries.forEach(({ card }) => {
    const clone = card.cloneNode(true);
    clone.onclick = () => card.click();
    row.appendChild(clone);
  });
  container.appendChild(section);
}

function renderSingleShelf(container, cards, label) {
  const isStoreTheme = document.body.dataset.theme === "videoclub";
  container.classList.toggle("shelf-layout", isStoreTheme);
  if (isStoreTheme) appendShelf(container, label, cards);
  else cards.forEach(({ card }) => container.appendChild(card));
}

function renderGenreShelves(container, cards) {
  if (!cards.length) return;
  const shelves = new Map();
  cards.forEach((entry) => {
    itemGenres(entry.item).forEach((genre) => {
      if (!shelves.has(genre)) shelves.set(genre, []);
      shelves.get(genre).push(entry);
    });
  });
  [...shelves.entries()]
    .sort(([a], [b]) => a.localeCompare(b, "es"))
    .forEach(([genre, entries]) => appendShelf(container, genre, entries));
}

function escapeHtml(s){ return String(s ?? "").replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

async function openDetail(m) {
  currentMovie = m;
  showView("detail");
  $("dTitle").textContent = m.custom_title || m.title || m.name;
  $("dTagline").textContent = "";
  $("dEpisode").textContent = "";
  $("dYear").textContent = m.year || "";
  $("dPath").textContent = m.path;
  $("dPoster").src = imgUrl(m, "poster");
  $("dOverview").textContent = "";
  $("dRating").textContent = "";
  $("dRuntime").textContent = "";
  $("dRes").textContent = "";
  $("dCountry").textContent = "";
  $("dGenres").textContent = "";
  $("dDirector").textContent = "";
  $("dCast").textContent = "";
  $("dFileInfo").textContent = "";
  $("dResume").textContent = "";
  // startOver button removed
  const backdrop = imgUrl(m, "backdrop");
  $("dBackdrop").style.backgroundImage = backdrop ? `url(${backdrop})` : "";
  try {
    const data = await api(`/api/movie?path=${encodeURIComponent(m.path)}`);
    const dm = data.movie;
    if (dm) {
      if (dm.poster_local || dm.poster_url) $("dPoster").src = imgUrl(dm, "poster");
      if (dm.title) $("dTitle").textContent = dm.custom_title || dm.title;
      if (dm.season || dm.episode) {
        $("dEpisode").innerHTML = `<strong>Episode:</strong> S${String(dm.season||1).padStart(2,"0")}E${String(dm.episode||0).padStart(2,"0")}${dm.episode_title ? " · " + escapeHtml(dm.episode_title) : ""}`;
      }
      if (dm.backdrop_local || dm.backdrop_url) {
        const b = imgUrl(dm, "backdrop");
        if (b) $("dBackdrop").style.backgroundImage = `url(${b})`;
      }
      $("dOverview").textContent = dm.overview || "";
      $("dTagline").textContent = dm.tagline || "";
      const hasResume = !!(dm.resume_position && dm.resume_position > 10);
      // startOver removed
      $("dRating").textContent = dm.rating ? `★ ${Number(dm.rating).toFixed(1)}` : "";
      $("dYear").textContent = dm.year || m.year || "";
      $("dRuntime").textContent = dm.runtime ? `${dm.runtime} min` : (m._duration ? fmtTime(m._duration) : "");
      $("dCountry").textContent = dm.country || "";
      $("dGenres").textContent = (dm.genres || []).join(", ");
      $("dDirector").innerHTML = dm.director ? `<strong>Director:</strong> ${escapeHtml(dm.director)}` : "";
      $("dCast").innerHTML = (dm.cast && dm.cast.length) ? `<strong>Cast:</strong> ${escapeHtml(dm.cast.join(", "))}` : "";
      $("dFileInfo").innerHTML = dm.file_info ? `<strong>File:</strong> ${escapeHtml(dm.file_info)}` : "";
      if (dm.resume_position && dm.resume_position > 0) {
        $("dResume").innerHTML = `<strong>Resume:</strong> ${fmtTime(dm.resume_position)} (auto-resumes on Play)`;
      }
      // trailer
      const tr = $("dTrailer");
      tr.innerHTML = "";
      if (dm.trailer_key) {
        const iframe = document.createElement("iframe");
        iframe.src = `https://www.youtube.com/embed/${dm.trailer_key}`;
        iframe.allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture";
        iframe.allowFullscreen = true;
        tr.appendChild(iframe);
      }
      // cast photos
      const cp = $("dCastPhotos");
      cp.innerHTML = "";
      (dm.cast_full || []).forEach((c) => {
        if (!c.profile) return;
        const d = document.createElement("div");
        d.className = "cp";
        d.innerHTML = `<img src="${c.profile}" alt="" /><div>${escapeHtml(c.name)}</div>`;
        cp.appendChild(d);
      });
      // similar
      const sim = $("dSimilar");
      sim.innerHTML = "";
      (dm.similar || []).forEach((s) => {
        if (!s.poster) return;
        const card = document.createElement("div");
        card.className = "sc";
        card.style.cursor = "pointer";
        card.innerHTML = `<img src="${s.poster}" alt="" /><div class="t">${escapeHtml(s.title)}</div>`;
        card.onclick = () => {
          const base = currentCategory === "series" ? "https://www.themoviedb.org/tv/" : "https://www.themoviedb.org/movie/";
          if (s.id) window.open(base + s.id, "_blank");
        };
        sim.appendChild(card);
      });
      m._duration = dm.duration || m._duration;
    }
  } catch (e) {}
  try {
    const info = await api(`/api/probe?path=${encodeURIComponent(m.path)}`);
    if (info.width) $("dRes").textContent = `${info.width}×${info.height}`;
    if (!m._duration && info.duration) { $("dRuntime").textContent = fmtTime(info.duration); m._duration = info.duration; }
  } catch (e) {}
  // subtitles
  const subSel = $("subSelect");
  subSel.innerHTML = `<option value="">No subtitles</option>`;
  try {
    const sdata = await api(`/api/subtitles?path=${encodeURIComponent(m.path)}`);
    (sdata.subtitles || []).forEach((s) => {
      const o = document.createElement("option");
      o.value = s.path; o.textContent = s.label;
      subSel.appendChild(o);
    });
    if (sdata.subtitles && sdata.subtitles.length) {
      subSel.value = sdata.subtitles[0].path;
    }
  } catch (e) {}
  currentSub = subSel.value || null;
  subSel.onchange = () => { currentSub = subSel.value || null; };
}

$("backBtn").onclick = () => { showView("library"); mpResumeFromMedia(); };
$("collBackBtn").onclick = () => { showView("library"); mpResumeFromMedia(); };

// ---- Edit media modal ----
let editTarget = "movie";

function setEditStatus(msg, isError) {
  const el = $("editStatus");
  if (!el) return;
  el.textContent = msg || "";
  el.classList.toggle("error", !!isError);
}

function parseSearchQuery(raw) {
  let q = (raw || "").trim();
  let year = "";
  if (!q) return { title: "", year: "" };
  let m = q.match(/^(.*?)\s*[\(\[]\s*(\d{4})\s*[\)\]]\s*$/);
  if (m) {
    q = m[1].trim();
    year = m[2];
  } else {
    m = q.match(/^(.*?)[\s,–-]+(\d{4})\s*$/);
    if (m) {
      q = m[1].trim();
      year = m[2];
    }
  }
  return { title: q, year };
}

function parseTmdbRef(input) {
  const raw = (input || "").trim();
  if (!raw) return { id: null, language: null, mediaType: null };
  let language = null;
  const lm = raw.match(/[?&]language=([A-Za-z-]+)/);
  if (lm) language = lm[1];
  let mediaType = null;
  if (/(?:themoviedb\.org|\/)\/tv\//i.test(raw)) mediaType = "tv";
  else if (/(?:themoviedb\.org|\/)\/movie\//i.test(raw)) mediaType = "movie";
  const m = raw.match(/(\d+)/);
  return { id: m ? parseInt(m[1], 10) : null, language, mediaType };
}

function refreshOpenDetail() {
  if (currentMovie && !$("detailView").classList.contains("hidden")) {
    return openDetail(currentMovie);
  }
  if (currentMovie && !$("splitView").classList.contains("hidden")) {
    renderSplitDetail(currentMovie, $("splitDetail"));
  }
  return Promise.resolve();
}

async function applyTmdbToMovie(id, language, mediaType) {
  if (!currentMovie || !currentMovie.path) throw new Error("no movie selected");
  setEditStatus("Applying TMDB metadata…");
  const body = { path: currentMovie.path, tmdb_id: id, category: currentCategory, media_type: mediaType || "movie" };
  if (language) body.language = language;
  const ad = await api("/api/movie/apply_tmdb", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body) });
  if (!ad || ad.error) throw new Error((ad && ad.error) || "TMDB lookup failed");
  if (ad.movie) currentMovie = ad.movie;
  $("editNameInput").value = currentMovie.custom_title || currentMovie.title || currentMovie.name || "";
  setEditStatus(`Applied: ${currentMovie.title || currentMovie.name || ""}${currentMovie.year ? " (" + currentMovie.year + ")" : ""} — art and metadata updated.`);
  await loadMovies();
  await refreshOpenDetail();
  return currentMovie;
}

async function applyTmdbToCollection(id, language, mediaType) {
  const type = mediaType === "tv" ? "tv" : "movie";
  const qs = `?id=${encodeURIComponent(id)}&type=${type}${language ? "&language=" + encodeURIComponent(language) : ""}`;
  const data = await api(`/api/tmdb/details${qs}`);
  const d = data.details;
  if (!d) throw new Error("TMDB lookup failed");
  await api("/api/collection/art", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ collection: currentCollection, poster_url: d.poster_url, backdrop_url: d.backdrop_url }) });
  setEditStatus(`Applied art for ${d.title || ""}${d.year ? " (" + d.year + ")" : ""}.`);
  await loadMovies();
  if (!$("seriesView").classList.contains("hidden") && currentSeries) {
    openSeries(currentSeries);
  } else if (!$("collectionView").classList.contains("hidden") && currentCollectionItems) {
    openCollection($("collTitle").textContent, currentCollectionItems);
  }
  return d;
}

async function applyTmdbToSeries(id, language, mediaType) {
  if (!currentSeries) throw new Error("no series selected");
  setEditStatus("Applying TMDB metadata…");
  const body = { collection: currentSeries.key, tmdb_id: id, media_type: mediaType || "tv" };
  if (language) body.language = language;
  const ad = await api("/api/series/apply_tmdb", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body) });
  if (!ad || ad.error) throw new Error((ad && ad.error) || "TMDB lookup failed");
  const d = ad.details || {};
  $("editNameInput").value = d.title || currentSeries.name || "";
  setEditStatus(`Applied: ${d.title || ""}${d.year ? " (" + d.year + ")" : ""} — art and metadata updated.`);
  await loadMovies();
  const updated = (seriesData || []).find((s) => s.key === currentSeries.key);
  if (updated) openSeries(updated);
  return ad;
}

async function openEditModal(target) {
  editTarget = (target === "collection" || target === "series") ? target : "movie";
  const isMovie = editTarget === "movie";
  const isSeries = editTarget === "series";
  $("artModal").classList.remove("hidden");
  $("artResults").innerHTML = "";
  $("artPreview").innerHTML = "";
  $("artTmdbInput").value = "";
  $("editNameRow").classList.toggle("hidden", editTarget === "collection");
  $("artFrameBtn").classList.toggle("hidden", !isMovie);
  setEditStatus("");
  if (isMovie && currentMovie) {
    $("editNameInput").value = currentMovie.custom_title || currentMovie.title || currentMovie.name || "";
    $("artQuery").value = currentMovie.title || currentMovie.name || "";
  } else if (isSeries && currentSeries) {
    $("editNameInput").value = currentSeries.name || currentSeries.key || "";
    $("artQuery").value = currentSeries.name || "";
  } else {
    $("editNameInput").value = "";
    $("artQuery").value = currentSeries ? (currentSeries.name || "") : ((currentCollection || "").split(/[\\/]/).pop() || "");
  }
  if ($("artQuery").value) await doArtSearch();
}

$("changeArtBtn").onclick = () => openEditModal("movie");
$("artClose").onclick = () => $("artModal").classList.add("hidden");
$("artSaveCloseBtn").onclick = async () => {
  $("artModal").classList.add("hidden");
  await loadMovies();
  await refreshOpenDetail();
};
$("saveNameBtn").onclick = async () => {
  const name = ($("editNameInput").value || "").trim();
  if (!name) return;
  if (editTarget === "series") {
    if (!currentSeries) return;
    try {
      await api("/api/series/rename", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ collection: currentSeries.key, title: name }) });
      currentSeries.name = name;
      $("seriesTitle").textContent = name;
      setEditStatus("Name saved. TMDB art and metadata unchanged.");
      await loadMovies();
      const updated = (seriesData || []).find((s) => s.key === currentSeries.key);
      if (updated) openSeries(updated);
    } catch (e) {
      setEditStatus("Rename failed: " + e.message, true);
    }
    return;
  }
  if (!currentMovie) return;
  try {
    await api("/api/movie/rename", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ path: currentMovie.path, title: name }) });
    currentMovie.custom_title = name;
    currentMovie.title = name;
    setEditStatus("Name saved. TMDB art and metadata unchanged.");
    await loadMovies();
    await refreshOpenDetail();
  } catch (e) {
    setEditStatus("Rename failed: " + e.message, true);
  }
};
$("artFrameBtn").onclick = async () => {
  if (!currentMovie) return;
  try {
    await api("/api/movie/art", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ path: currentMovie.path }) });
    setEditStatus("Applied a frame from the movie.");
    await loadMovies();
    await refreshOpenDetail();
  } catch (e) {
    setEditStatus("Could not use a frame: " + e.message, true);
  }
};
$("artSearchBtn").onclick = doArtSearch;
$("artQuery").addEventListener("keydown", (e) => { if (e.key === "Enter") doArtSearch(); });

$("artGoogleBtn").onclick = () => {
  const q = ($("artGoogleQuery").value || "").trim() || (currentMovie ? (currentMovie.title || currentMovie.name || "") : "");
  if (!q) return;
  window.open("https://www.google.com/search?tbm=isch&q=" + encodeURIComponent(q + " movie poster"), "_blank");
};

$("artUrlBtn").onclick = async () => {
  const url = ($("artUrlInput").value || "").trim();
  if (!url) return;
  try {
    if (editTarget === "collection") {
      await api("/api/collection/art", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ collection: currentCollection, poster_url: url, backdrop_url: url }) });
      setEditStatus("Applied the image URL.");
      await loadMovies();
    } else {
      await api("/api/movie/art", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ path: currentMovie.path, poster_url: url, backdrop_url: url }) });
      currentMovie.poster_url = url;
      currentMovie.backdrop_url = url;
      setEditStatus("Applied the image URL.");
      await loadMovies();
      await refreshOpenDetail();
    }
  } catch (e) {
    setEditStatus("Could not apply the image URL: " + e.message, true);
  }
};

$("artFetchBtn").onclick = async () => {
  const ref = parseTmdbRef($("artTmdbInput").value);
  if (!ref.id) {
    setEditStatus("Paste a TMDB URL or numeric ID first.", true);
    return;
  }
  const mediaType = ref.mediaType || (editTarget === "series" ? "tv" : "movie");
  try {
    if (editTarget === "collection") await applyTmdbToCollection(ref.id, ref.language, mediaType);
    else if (editTarget === "series") await applyTmdbToSeries(ref.id, ref.language, mediaType);
    else await applyTmdbToMovie(ref.id, ref.language, mediaType);
  } catch (e) {
    setEditStatus("TMDB lookup failed: " + e.message, true);
  }
};

async function doArtSearch() {
  const raw = ($("artQuery").value || "").trim();
  if (!raw) {
    setEditStatus("Type a title to search TMDB.", true);
    return;
  }
  const parsed = parseSearchQuery(raw);
  const year = parsed.year || "";
  $("artResults").innerHTML = "";
  $("artPreview").innerHTML = "";
  setEditStatus("Searching TMDB (movies and series)…");
  let data;
  try {
    data = await api(`/api/tmdb/results?title=${encodeURIComponent(parsed.title)}&year=${encodeURIComponent(year)}`);
  } catch (e) {
    setEditStatus("TMDB search failed: " + e.message, true);
    return;
  }
  const results = data.results || [];
  if (!results.length) {
    setEditStatus(`No TMDB results for “${parsed.title}”${year ? " (" + year + ")" : ""}. Try the TMDB URL or ID below.`, true);
    return;
  }
  setEditStatus(`${results.length} result(s). Click one to apply its art and metadata.`);
  const container = $("artResults");
  results.forEach((r) => {
    const card = document.createElement("div");
    card.className = "stream-card";
    const kind = r.media_type === "tv" ? "Series" : "Movie";
    card.innerHTML = `
      ${r.poster ? `<img src="${r.poster}" alt="" />` : ""}
      <div class="t">${escapeHtml(r.title)}</div>
      <div class="y">${r.year || ""} · ${kind}</div>`;
    card.style.cursor = "pointer";
    card.onclick = async () => {
      try {
        if (editTarget === "collection") await applyTmdbToCollection(r.id, null, r.media_type);
        else if (editTarget === "series") await applyTmdbToSeries(r.id, null, r.media_type || "tv");
        else await applyTmdbToMovie(r.id, null, r.media_type || "movie");
      } catch (e) {
        setEditStatus("Apply failed: " + e.message, true);
      }
    };
    container.appendChild(card);
  });
}

let currentCollection = null;
let currentCollectionItems = null;
let currentSeries = null;
let currentSeason = null;

function openSeries(s) {
  currentSeries = s;
  currentSeason = null;
  showView("series");
  $("seriesTitle").textContent = s.name || s.key;
  $("seriesSeasons").classList.remove("hidden");
  $("seasonEpisodes").classList.add("hidden");
  const seasonsGrid = $("seriesSeasons");
  seasonsGrid.innerHTML = "";
  const seasonCards = [];
  (s.seasons || []).forEach((sn) => {
    const card = document.createElement("div");
    card.className = "card";
    let posterUrl = sn.poster_local ? `/api/file?path=${encodeURIComponent(sn.poster_local)}` : (sn.poster || "");
    if (!posterUrl) posterUrl = s.poster_local ? `/api/file?path=${encodeURIComponent(s.poster_local)}` : (s.poster_url || "");
    card.innerHTML = `
      <img class="poster" src="${posterUrl}" alt="" loading="lazy" onerror="this.style.background='#000'" />
      <div class="card-title">Season ${sn.season}${sn.name ? " - " + escapeHtml(sn.name) : ""}</div>
      <div class="card-year">${(sn.episodes || []).length} episodes</div>`;
    card.onclick = () => openSeason(sn);
    seasonCards.push({ card, item: sn });
  });
  renderSingleShelf(seasonsGrid, seasonCards, "Temporadas");
  // change art target collection = series key
  window._seriesArtCollection = s.key;
}

function openSeason(sn) {
  currentSeason = sn;
  $("seriesSeasons").classList.add("hidden");
  const epGrid = $("seasonEpisodes");
  epGrid.classList.remove("hidden");
  epGrid.innerHTML = "";
  const episodeCards = [];
  (sn.episodes || []).forEach((m) => {
    const card = document.createElement("div");
    card.className = "card";
    const posterUrl = imgUrl(m, "poster");
    const epTitle = m.episode_title || m.title || m.name;
    card.innerHTML = `
      <img class="poster" src="${posterUrl}" alt="" loading="lazy" onerror="this.style.background='#000'" />
      <div class="card-title">E${String(m.episode || "").padStart(2,"0")} ${escapeHtml(epTitle)}</div>
      <div class="card-year">${m.year || ""}</div>`;
    card.onclick = () => openDetail(m);
    episodeCards.push({ card, item: m });
  });
  renderSingleShelf(epGrid, episodeCards, "Episodios");
}

$("seriesBackBtn").onclick = () => {
  if (currentSeason) {
    currentSeason = null;
    $("seasonEpisodes").classList.add("hidden");
    $("seriesSeasons").classList.remove("hidden");
  } else {
    showView("library");
    loadMovies();
    mpResumeFromMedia();
  }
};

$("seriesChangeArtBtn").onclick = () => {
  if (!currentSeries) return;
  currentCollection = currentSeries.key;
  currentCollectionItems = (currentSeries.seasons || []).flatMap((s) => s.episodes || []);
  openEditModal("series");
};

function openCollection(title, items) {
  currentCollection = items && items[0] ? (items[0].collection || title) : title;
  currentCollectionItems = items;
  showView("collection");
  $("collTitle").textContent = title;
  const grid = $("collGrid");
  grid.innerHTML = "";
  const collectionCards = [];
  items.forEach((m) => {
    const card = document.createElement("div");
    card.className = "card";
    const posterUrl = imgUrl(m, "poster");
    card.innerHTML = `
      <img class="poster" src="${posterUrl}" alt="" loading="lazy" onerror="this.style.background='#000'" />
      <div class="card-title">${escapeHtml(m.title || m.name)}${m.year ? " (" + escapeHtml(m.year) + ")" : ""}</div>
      <div class="card-year">${m.file_info || ""}</div>`;
    card.onclick = () => openDetail(m);
    collectionCards.push({ card, item: m });
  });
  renderSingleShelf(grid, collectionCards, title);
}

$("collChangeArtBtn").onclick = () => openEditModal("collection");
$("playBtn").onclick = async () => {
  if (!currentMovie) return;
  mpPauseForMedia();
  const sub = $("subSelect").value || null;
  currentSub = sub;
  subsOn = !!sub;
  await api("/api/play", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ path: currentMovie.path, sub: subsOn ? sub : null }) });
  showPlayerBar(currentMovie);
  startPolling();
};
$("browserPlayBtn").onclick = () => {
  if (!currentMovie) return;
  window.open(`/player.html?path=${encodeURIComponent(currentMovie.path)}&sub=${encodeURIComponent($("subSelect").value||"")}`, "_blank");
};

function showPlayerBar(m) {
  $("playerBar").classList.remove("hidden");
  $("pbTitle").textContent = m.title || m.name;
  $("pbPoster").src = imgUrl(m, "poster");
  $("pbVol").value = 80;
}

async function refreshStatus() {
  try {
    const st = await api("/api/status");
    const playing = st.playing;
    const paused = st.paused;
    if (!playing && !paused) {
      $("playerBar").classList.add("hidden");
      mpResumeFromMedia();
    } else {
      $("playerBar").classList.remove("hidden");
    }
    $("pbPlayPause").textContent = (playing && !paused) ? "⏸" : "▶";
    $("pbCur").textContent = fmtTime(st.position);
    $("pbDur").textContent = fmtTime(st.duration);
    const seek = $("pbSeek");
    if (st.duration > 0) {
      seek.max = st.duration;
      if (document.activeElement !== seek) seek.value = st.position;
    }
    $("pbStatus").textContent = paused ? "Paused" : (playing ? "Playing" : "Stopped");
    $("pbSubToggle").textContent = `Subs: ${currentSub && subsOn ? "on" : "off"}`;
  } catch (e) {}
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(refreshStatus, 1000);
  refreshStatus();
}

$("pbPlayPause").onclick = async () => {
  const st = await api("/api/status");
  if (st.playing && !st.paused) {
    await api("/api/pause", { method:"POST", headers:{"Content-Type":"application/json"}, body:"{}" });
  } else if (st.paused) {
    await api("/api/resume", { method:"POST", headers:{"Content-Type":"application/json"}, body:"{}" });
  } else if (currentMovie) {
    const sub = subsOn ? currentSub : null;
    await api("/api/play", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ path: currentMovie.path, sub }) });
  }
  refreshStatus();
};
$("pbStop").onclick = async () => {
  await api("/api/stop", { method:"POST", headers:{"Content-Type":"application/json"}, body:"{}" });
  refreshStatus();
};
$("pbBack").onclick = async () => {
  const sk = parseInt($("sSkip")?.value) || 10;
  await api("/api/skip", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ delta: -sk }) });
  refreshStatus();
};
$("pbFwd").onclick = async () => {
  const sk = parseInt($("sSkip")?.value) || 10;
  await api("/api/skip", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ delta: sk }) });
  refreshStatus();
};
$("pbRew").onclick = async () => {
  await api("/api/skip", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ delta: -30 }) });
  refreshStatus();
};
$("pbFf").onclick = async () => {
  await api("/api/skip", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ delta: 30 }) });
  refreshStatus();
};
$("pbSeek").addEventListener("change", async (e) => {
  await api("/api/seek", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ pos: parseFloat(e.target.value) }) });
  refreshStatus();
});
$("pbVol").addEventListener("change", async (e) => {
  await api("/api/volume", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ volume: parseInt(e.target.value) }) });
});
$("pbSubToggle").onclick = async () => {
  subsOn = !subsOn;
  const st = await api("/api/status");
  await api("/api/stop", { method:"POST", headers:{"Content-Type":"application/json"}, body:"{}" });
  const sub = subsOn ? currentSub : null;
  await api("/api/play", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ path: currentMovie.path, sub, ss: st.position }) });
  refreshStatus();
};

// settings
function setUtilityState(id, active) {
  $(id)?.classList.toggle("is-pressed", !!active);
}
$("settingsBtn").onclick = async () => {
  $("settingsModal").classList.remove("hidden");
  setUtilityState("settingsBtn", true);
  await refreshLibLists();
  browseTo("");
};
$("sClose").onclick = () => { $("settingsModal").classList.add("hidden"); setUtilityState("settingsBtn", false); };
$("rescanBtn").onclick = async () => {
  const btn = $("rescanBtn");
  const orig = btn.textContent;
  btn.textContent = "Rescanning...";
  btn.disabled = true;
  try {
    for (const cat of ["movie", "series"]) {
      await api(`/api/scan?category=${cat}&force=1`);
    }
    await loadFilterOptions();
    await loadMovies();
    updateCounter();
  } finally {
    btn.textContent = orig;
    btn.disabled = false;
  }
};

$("serverBtn").onclick = () => { $("serverModal").classList.remove("hidden"); setUtilityState("serverBtn", true); };
$("serverModalClose").onclick = () => { $("serverModal").classList.add("hidden"); setUtilityState("serverBtn", false); };
$("serverCloseBrowserBtn").onclick = () => window.close();
$("serverRestartBtn").onclick = async () => {
  if (!confirm("Restart the MoviePlayer server?")) return;
  $("serverModal").classList.add("hidden");
  try { await api("/api/restart", { method:"POST", headers:{"Content-Type":"application/json"}, body:"{}" }); } catch (err) {}
  document.body.innerHTML = "<div style='text-align:center;padding:60px;color:#fff;font-family:sans-serif'><h1>Restarting…</h1><p>Reload this page in a few seconds.</p></div>";
};
$("serverStopBtn").onclick = async () => {
  if (!confirm("Stop the MoviePlayer server and close the browser?")) return;
  $("serverModal").classList.add("hidden");
  try { await api("/api/shutdown", { method:"POST", headers:{"Content-Type":"application/json"}, body:"{}" }); } catch (err) {}
  setTimeout(() => window.close(), 800);
  document.body.innerHTML = "<div style='text-align:center;padding:60px;color:#fff;font-family:sans-serif'><h1>Server stopped.</h1><p>You can close this tab.</p></div>";
};
$("sSave").onclick = async () => {
  const cfg = {
    tmdb_api_key: $("sTmdbKey").value.trim(),
    tmdb_session_id: $("sTmdbSession").value.trim(),
    host: $("sHost").value.trim(),
    port: parseInt($("sPort").value),
    skip_seconds: parseInt($("sSkip").value),
    theme: $("sTheme").value,
    kiosk_mode: $("sKiosk").checked,
    fullscreen: $("sFullscreen").checked,
    ui_font_size: parseInt($("sFontSize").value) || 15,
    ui_font_family: $("sFontFamily").value,
    music_dir: $("sMusicDir").value.trim(),
    screensaver_timeout: parseInt($("sScreensaver").value) || 5,
    sub_size: parseInt($("sSubSize").value) || 28,
    sub_color: $("sSubColor").value || "#ffffff",
  };
  await api("/api/config", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(cfg) });
  try { localStorage.setItem("mp_sub_size", String(cfg.sub_size)); localStorage.setItem("mp_sub_color", cfg.sub_color); } catch(e){}
  applyTheme(cfg.theme);
  if (currentCategory === "movie" || currentCategory === "series") await loadMovies();
  applyUiPrefs();
  $("settingsModal").classList.add("hidden");
  window._ssTimeout = parseInt($("sScreensaver").value) || 5;
  if (typeof ssReset === "function") ssReset();
};

// folder browser
let selectedDir = null;
async function browseTo(p) {
  selectedDir = p || null;
  $("fbPath").value = p || "";
  const url = p ? `/api/browse?path=${encodeURIComponent(p)}` : "/api/browse";
  const data = await api(url);
  const container = $("fbDirs");
  container.innerHTML = "";
  if (p) {
    const parent = p.replace(/[\\\/][^\\\/]*$/, "") || (p.includes(":") ? p.split(":")[0]+":" : "");
    const up = document.createElement("div");
    up.className = "dir";
    up.textContent = "⬆ ..";
    up.onclick = () => browseTo(parent || "");
    container.appendChild(up);
  }
  (data.dirs || []).forEach((d) => {
    const div = document.createElement("div");
    div.className = "dir" + (d === selectedDir ? " sel" : "");
    div.title = d;
    const name = document.createElement("span");
    name.className = "dirname";
    name.textContent = "📁 " + (d.split(/[\\\/]/).pop() || d);
    name.onclick = () => { selectedDir = d; browseTo(d); };
    const addBtn = document.createElement("button");
    addBtn.className = "btn small";
    addBtn.textContent = "Add";
    addBtn.onclick = (e) => { e.stopPropagation(); selectedDir = d; $("fbPath").value = d; addFolder(d); };
    div.appendChild(name);
    div.appendChild(addBtn);
    container.appendChild(div);
  });
}
async function addFolder(d) {
  if (!d) return;
  const cat = $("fbCategory").value || "movie";
  if (cat === "music") {
    $("sMusicDir").value = d;
    return;
  }
  await api("/api/libraries", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({action:"add", dir:d, category:cat}) });
  refreshLibLists();
}
$("fbGo").onclick = () => browseTo($("fbPath").value.trim());
$("fbPath").addEventListener("keydown", (e) => { if (e.key === "Enter") browseTo($("fbPath").value.trim()); });
$("fbAdd").onclick = async () => {
  const typed = $("fbPath").value.trim();
  const d = typed || selectedDir;
  if (!d) return;
  await addFolder(d);
};

// filters
$("filtersToggle").onclick = () => $("filtersPanel").classList.toggle("hidden");

$("sortSelect").addEventListener("change", loadMovies);

$("viewToggle").onclick = () => {
  viewMode = viewMode === "grid" ? "split" : "grid";
  $("viewToggle").textContent = viewMode === "grid" ? "Split view" : "Grid view";
  $("panelSideToggle").classList.toggle("hidden", viewMode !== "split");
  loadMovies();
};

$("panelSideToggle").onclick = () => {
  panelSideRight = !panelSideRight;
  $("panelSideToggle").textContent = panelSideRight ? "Panel: right" : "Panel: left";
  const sv = $("splitView");
  sv.classList.toggle("right", !panelSideRight);
  renderSplitView();
};

function renderSplitView() {
  const list = $("splitList");
  const detail = $("splitDetail");
  list.innerHTML = "";
  detail.innerHTML = "<p style='color:var(--muted)'>Select a movie from the list.</p>";
  let items = movies;
  if (currentCategory === "series" && seriesData.length) {
    items = seriesData.flatMap((s) => (s.seasons || []).flatMap((sn) => (sn.episodes || [])));
  }
  items.forEach((m) => {
    const item = document.createElement("div");
    item.className = "split-item";
    item.textContent = (m.title || m.name) + (m.year ? " (" + m.year + ")" : "");
    item.onclick = () => {
      document.querySelectorAll(".split-item").forEach((x) => x.classList.remove("active"));
      item.classList.add("active");
      renderSplitDetail(m, detail);
    };
    list.appendChild(item);
  });
  if (items.length) {
    const firstItem = list.querySelector(".split-item");
    if (firstItem) firstItem.click();
  }
}

function renderSplitDetail(m, detail) {
  detail.innerHTML = "<p style='color:var(--muted)'>Loading…</p>";
  currentMovie = m;
  api(`/api/movie?path=${encodeURIComponent(m.path)}`).then((data) => {
    const dm = (data && data.movie) || m;
    currentMovie = dm;
    const poster = imgUrl(dm, "poster");
    const backdrop = imgUrl(dm, "backdrop");
    if (backdrop) {
      detail.style.backgroundImage = `url(${backdrop})`;
      detail.style.backgroundSize = "cover";
      detail.style.backgroundPosition = "center";
    } else {
      detail.style.backgroundImage = "";
    }
    const div = document.createElement("div");
    div.style.background = "rgba(15,17,21,.75)";
    div.style.padding = "16px";
    div.style.borderRadius = "8px";
    div.innerHTML = `
      <img class="sd-poster" src="${poster}" alt="" />
      <div class="sd-title">${escapeHtml(dm.custom_title || dm.title || m.title || m.name)}</div>
      <div class="sd-meta">${dm.year || m.year || ""} ${dm.file_info ? "· " + escapeHtml(dm.file_info) : ""}</div>
      <div class="sd-meta">${escapeHtml((dm.genres || m.genres || []).join(", "))}</div>
      <div class="sd-meta">${dm.director ? "Director: " + escapeHtml(dm.director) : ""}</div>
      <div class="sd-meta">${dm.country ? "Country: " + escapeHtml(dm.country) : ""}</div>
      <div class="sd-meta">${dm.rating ? "★ " + Number(dm.rating).toFixed(1) : ""}</div>
      <p class="tagline">${escapeHtml(dm.tagline || "")}</p>
      <p class="overview">${escapeHtml(dm.overview || "")}</p>
      ${dm.trailer_key ? `<div class="sd-meta"><a href="https://www.youtube.com/watch?v=${dm.trailer_key}" target="_blank" style="color:var(--accent2)">▶ Trailer</a></div>` : ""}
      <div class="sd-actions">
        <button class="btn primary" id="sdPlay">▶ Play</button>
        <button class="btn" id="sdBrowser">Browser play</button>
        <button class="btn" id="sdArt">✎ Edit</button>
      </div>`;
    detail.innerHTML = "";
    detail.appendChild(div);
    div.querySelector("#sdPlay").onclick = async () => {
      const sub = (dm.subtitles && dm.subtitles.length) ? dm.subtitles[0].path : (m.subtitles && m.subtitles[0] ? m.subtitles[0].path : null);
      currentSub = sub; subsOn = !!sub; currentMovie = dm;
      await api("/api/play", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ path: dm.path, sub: subsOn ? sub : null }) });
      showPlayerBar(dm); startPolling();
    };
    div.querySelector("#sdBrowser").onclick = () => {
      window.open(`/player.html?path=${encodeURIComponent(dm.path)}&sub=${encodeURIComponent((dm.subtitles&&dm.subtitles[0])?dm.subtitles[0].path:"")}`, "_blank");
    };
    div.querySelector("#sdArt").onclick = () => {
      currentMovie = dm;
      openEditModal("movie");
    };
  }).catch(() => {
    detail.innerHTML = "<p style='color:var(--muted)'>Failed to load details.</p>";
  });
}
$("fClear").onclick = () => {
  ["fGenre","fCountry","fDirector","fActor","fYear"].forEach((id) => { $(id).value = ""; });
  if ($("fSetsOnly")) $("fSetsOnly").checked = false;
  loadMovies();
};
["fGenre","fCountry","fDirector","fActor","fYear"].forEach((id) => {
  $(id).addEventListener("change", loadMovies);
});
if ($("fSetsOnly")) $("fSetsOnly").addEventListener("change", loadMovies);
$("searchBox").addEventListener("input", () => { clearTimeout(window._searchTimer); window._searchTimer = setTimeout(loadMovies, 300); toggleSearchClear(); });
function clearSearch() { $("searchBox").value = ""; toggleSearchClear(); loadMovies(); }
const _sc = $("searchClear"); if (_sc) _sc.onclick = clearSearch;
const _scb = $("searchClearBtn"); if (_scb) _scb.onclick = clearSearch;
toggleSearchClear();
function toggleSearchClear() { $("searchClear").classList.toggle("hidden", !($("searchBox").value || "").trim()); }
toggleSearchClear();

// source console: one physical switch can be ON at a time
document.querySelectorAll(".source-switch input").forEach((input) => {
  input.addEventListener("change", () => {
    const unit = input.closest(".source-switch");
    if (!unit) return;
    switchTab(unit.dataset.tab);
  });
});

// scan
$("scanBtn").onclick = scan;

// auto load
loadConfig().then(() => {
  loadFilterOptions();
  loadMovies();
  updateCounter();
  if (typeof mpLoadTracks === "function") mpLoadTracks();
  window._ssTimeout = parseInt($("sScreensaver").value) || 5;
  if (typeof ssLoadImages === "function") { ssLoadImages().then(() => { if (typeof ssReset === "function") ssReset(); }); }
});

// streaming
async function renderStreamCards(container, items, onPlay, onFav) {
  container.innerHTML = "";
  items.forEach((it) => {
    const card = document.createElement("div");
    card.className = "stream-card";
    const title = it.title || it.name;
    const year = it.year || (it.release_date || it.first_air_date || "").slice(0,4);
    const poster = it.poster || (it.poster_path ? `https://image.tmdb.org/t/p/w342${it.poster_path}` : "");
    card.innerHTML = `
      ${poster ? `<img src="${poster}" alt="" />` : ""}
      <div class="t">${escapeHtml(title)}</div>
      <div class="y">${year || ""}</div>`;
    card.style.cursor = "pointer";
    if (onPlay) {
      card.querySelector("img")?.addEventListener("click", (ev) => { ev.stopPropagation(); onPlay(it, title, year); });
      card.querySelector(".t")?.addEventListener("click", (ev) => { ev.stopPropagation(); onPlay(it, title, year); });
    }
    if (onFav) {
      const btn = document.createElement("button");
      btn.className = "btn small fav-btn";
      btn.textContent = "✕ Remove";
      btn.addEventListener("click", async (ev) => { ev.stopPropagation(); await onFav(it); loadWishlist(); });
      card.appendChild(btn);
    }
    container.appendChild(card);
  });
}

async function loadWishlist() {
  try {
    const favData = await api("/api/streaming/favorites");
    const wlData = await api("/api/streaming/watchlist");
    const favItems = (favData.favorites || []).map((f) => ({ id: f.tmdb_id, title: f.title, year: f.year, poster: f.poster, _type: f.media_type || "movie", _fav: true }));
    const wlItems = (wlData.watchlist || []).map((w) => ({ id: w.id, title: w.title, year: w.year, poster: w.poster, _type: w.media_type || "movie", _wl: true }));
    renderStreamCards($("wishlistResults"), favItems, (it, title, year) => {
      $("streamQuery").value = title;
      doStreamSearch();
    }, async (it) => {
      await api("/api/streaming/unfavorite", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ tmdb_id: it.id, media_type: it._type }) });
    });
    renderStreamCards($("tmdbWatchlist"), wlItems, (it, title, year) => {
      $("streamQuery").value = title;
      doStreamSearch();
    });
  } catch (e) {}
}

function renderSiteList(container, sites, removable) {
  container.innerHTML = "";
  if (!sites.length) {
    container.innerHTML = `<div class="empty">${removable ? "Todavía no agregaste sitios." : "No se pudo cargar la lista de FMHY."}</div>`;
    return;
  }
  let currentCategory = null;
  sites.forEach((site) => {
    if (!removable && site.category && site.category !== currentCategory) {
      currentCategory = site.category;
      const heading = document.createElement("h4");
      heading.className = "stream-site-category";
      heading.textContent = currentCategory;
      container.appendChild(heading);
    }
    const row = document.createElement("div");
    row.className = "site";
    const info = document.createElement("div");
    info.className = "site-info";
    if (site.rank) {
      const rank = document.createElement("span");
      rank.className = "site-rank";
      rank.textContent = site.rank;
      info.appendChild(rank);
    }
    const link = document.createElement("a");
    link.href = site.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = site.name || site.url;
    link.style.fontWeight = "700";
    info.appendChild(link);
    (site.alternates || []).forEach((alternate, index) => {
      const separator = document.createTextNode(index === 0 ? " · " : ", ");
      const alt = document.createElement("a");
      alt.href = alternate.url;
      alt.target = "_blank";
      alt.rel = "noopener noreferrer";
      alt.textContent = alternate.label || String(index + 2);
      info.append(separator, alt);
    });
    const url = document.createElement("div");
    url.className = "site-url";
    url.textContent = site.description || (removable ? site.url : "");
    if (url.textContent) info.appendChild(url);
    row.appendChild(info);
    if (removable) {
      const remove = document.createElement("button");
      remove.className = "btn small site-remove";
      remove.textContent = "Quitar";
      remove.onclick = async () => {
        await api("/api/streaming/custom-sites", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({ action:"remove", url:site.url }) });
        loadStreamingSites();
      };
      row.appendChild(remove);
    }
    container.appendChild(row);
  });
}

async function loadStreamingSites(refresh = false) {
  try {
    const query = refresh ? "?refresh=1" : "";
    const official = await api(`/api/streaming/sites${query}`);
    renderSiteList($("streamSites"), official.sites || [], false);
  } catch (e) {
    renderSiteList($("streamSites"), [], false);
  }
  try {
    const custom = await api("/api/streaming/custom-sites");
    renderSiteList($("customStreamSites"), custom.sites || [], true);
  } catch (e) {
    renderSiteList($("customStreamSites"), [], true);
  }
}

async function doStreamSearch() {
  const q = ($("streamQuery").value || "").trim();
  if (!q) return;
  const progress = $("streamProgress");
  const results = $("streamResults");
  const player = $("streamPlayer");
  progress.classList.add("active");
  results.innerHTML = "";
  player.classList.add("hidden");
  player.innerHTML = "";
  let data;
  try {
    data = await api(`/api/streaming/search?q=${encodeURIComponent(q)}`);
  } finally {
    progress.classList.remove("active");
  }
  const movies = (data.tmdb.movies || []);
  const tv = (data.tmdb.tv || []);
  const all = [...movies.map((m) => ({...m, _type:"movie"})), ...tv.map((t) => ({...t, _type:"tv"}))];
  all.forEach((it) => {
    const card = document.createElement("div");
    card.className = "stream-card";
    const title = it.title || it.name;
    const year = (it.release_date || it.first_air_date || "").slice(0,4);
    const poster = it.poster_path ? `https://image.tmdb.org/t/p/w342${it.poster_path}` : "";
    card.innerHTML = `
      ${poster ? `<img src="${poster}" alt="" />` : ""}
      <div class="t">${escapeHtml(title)}</div>
      <div class="y">${year} ${it._type === "tv" ? "· TV" : ""}</div>
      <button class="btn small fav-btn">♥ Favorite</button>`;
    card.style.cursor = "pointer";
    card.querySelector("img")?.addEventListener("click", (ev) => { ev.stopPropagation(); openStreamPlayer(it, title, year); });
    card.querySelector(".t")?.addEventListener("click", (ev) => { ev.stopPropagation(); openStreamPlayer(it, title, year); });
    card.querySelector(".fav-btn").addEventListener("click", async (ev) => {
      ev.stopPropagation();
      await api("/api/streaming/favorite", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ tmdb_id: it.id, title, year, poster: it.poster_path ? `https://image.tmdb.org/t/p/w342${it.poster_path}` : null, media_type: it._type }) });
      loadWishlist();
    });
    results.appendChild(card);
  });
  loadStreamingSites();
}

function openStreamPlayer(it, title, year) {
  const player = $("streamPlayer");
  player.classList.remove("hidden");
  const tmdbId = it.id;
  const type = it._type === "tv" ? "tv" : "movie";
  const embedUrl = type === "tv"
    ? `https://vidsrc.to/embed/tv/${tmdbId}/1/1`
    : `https://vidsrc.to/embed/movie/${tmdbId}`;
  // open directly in a new tab (avoids the in-frame bot check)
  window.open(embedUrl, "_blank");
  player.innerHTML = `
    <div class="player-bar-row">
      <strong style="color:#fff">${escapeHtml(title)} ${year ? "("+year+")" : ""}</strong>
      <span style="color:var(--muted);margin-left:12px;">Opened player in a new tab.</span>
      <a href="${embedUrl}" target="_blank" rel="noopener" style="color:var(--accent2);margin-left:auto;">Re-open player</a>
    </div>`;
  player.scrollIntoView({ behavior: "smooth" });
}
$("streamSearchBtn").onclick = doStreamSearch;
$("streamQuery").addEventListener("keydown", (e) => { if (e.key === "Enter") doStreamSearch(); });
$("refreshStreamSites").onclick = () => loadStreamingSites(true);
$("customSiteForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const name = $("customSiteName").value.trim();
  const url = $("customSiteUrl").value.trim();
  if (!name || !/^https?:\/\//i.test(url)) return;
  await api("/api/streaming/custom-sites", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({ name, url }) });
  $("customSiteName").value = "";
  $("customSiteUrl").value = "";
  loadStreamingSites();
});
loadStreamingSites();
// ---- Mini MP3 player ----
const mpAudio = new Audio();
mpAudio.volume = 0.5;
let mpTracks = [];
let mpIndex = -1;
let mpPausedByMedia = false;

function mpPauseForMedia() {
  if (!mpAudio.paused) {
    mpAudio.pause();
    mpPausedByMedia = true;
  }
}
function mpResumeFromMedia() {
  if (mpPausedByMedia) {
    mpPausedByMedia = false;
    if (mpTracks.length) mpAudio.play().catch(() => {});
  }
}

function mpSetTrack(name) {
  const text = document.querySelector("#mpTrack .mp-track-text");
  if (text) text.textContent = name;
  const track = $("mpTrack");
  if (track) {
    // toggle scroll if overflow
    requestAnimationFrame(() => {
      const inner = track.querySelector(".mp-track-text");
      if (inner && inner.scrollWidth > track.clientWidth) track.classList.add("scrolling");
      else track.classList.remove("scrolling");
    });
  }
}
function mpPickRandom() {
  if (!mpTracks.length) return null;
  let i = Math.floor(Math.random() * mpTracks.length);
  if (mpTracks.length > 1 && i === mpIndex) i = (i + 1) % mpTracks.length;
  mpIndex = i;
  return mpTracks[i];
}

async function mpLoadTracks() {
  try {
    const data = await api("/api/music/list");
    mpTracks = data.tracks || [];
  } catch (e) {
    mpTracks = [];
  }
  if (!mpTracks.length) {
    mpSetTrack("No tracks");
    return;
  }
  const t = mpPickRandom();
  mpAudio.src = `/api/file?path=${encodeURIComponent(t.path)}`;
  mpSetTrack(t.name);
  mpAudio.play().catch(() => {});
}

$("mpPlayPause").onclick = () => {
  if (mpAudio.paused) { mpAudio.play().catch(() => {}); $("mpPlayPause").textContent = "\u25B6"; }
  else { mpAudio.pause(); $("mpPlayPause").textContent = "\u25B6"; }
};
$("mpTrack").addEventListener("dblclick", () => {
  const t = mpPickRandom();
  if (!t) return;
  mpAudio.src = `/api/file?path=${encodeURIComponent(t.path)}`;
  mpSetTrack(t.name);
  mpAudio.play().catch(() => {});
});
mpAudio.addEventListener("play", () => { $("mpPlayPause").textContent = "\u23F8"; });
mpAudio.addEventListener("pause", () => { $("mpPlayPause").textContent = "\u25B6"; });
mpAudio.addEventListener("ended", () => {
  const t = mpPickRandom();
  if (!t) return;
  mpAudio.src = `/api/file?path=${encodeURIComponent(t.path)}`;
  mpSetTrack(t.name);
  mpAudio.play().catch(() => {});
});
// ---- Mini player drag + minimize ----
(function() {
  const player = $("miniPlayer");
  const minBtn = $("mpMinimize");
  if (!player) return;
  let dragging = false, ox = 0, oy = 0;
  // restore position
  try {
    const pos = JSON.parse(localStorage.getItem("mp_player_pos") || "null");
    if (pos) { player.style.left = pos.x + "px"; player.style.top = pos.y + "px"; player.style.right = "auto"; player.style.bottom = "auto"; }
  } catch (e) {}
  player.addEventListener("mousedown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "BUTTON") return;
    dragging = true;
    const r = player.getBoundingClientRect();
    ox = e.clientX - r.left;
    oy = e.clientY - r.top;
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    player.style.left = (e.clientX - ox) + "px";
    player.style.top = (e.clientY - oy) + "px";
    player.style.right = "auto";
    player.style.bottom = "auto";
  });
  window.addEventListener("mouseup", () => {
    if (dragging) {
      dragging = false;
      try { localStorage.setItem("mp_player_pos", JSON.stringify({ x: parseInt(player.style.left), y: parseInt(player.style.top) })); } catch (e) {}
    }
  });
  if (minBtn) {
    minBtn.addEventListener("click", () => {
      player.classList.toggle("minimized");
      minBtn.textContent = player.classList.contains("minimized") ? "+" : "_";
    });
  }
})();
// ---- Screensaver ----
let ssImages = [];
let ssTimer = null;
let ssActive = false;
let ssInterval = null;
const ssAnims = ["ss-fade","ss-zoom","ss-slide-left","ss-slide-right"];

async function ssLoadImages() {
  try {
    const data = await api("/api/art/list");
    ssImages = data.images || [];
  } catch (e) { ssImages = []; }
}

function ssShowNext() {
  const overlay = document.getElementById("screensaver");
  if (!overlay || !ssImages.length) return;
  const img = document.createElement("img");
  const path = ssImages[Math.floor(Math.random() * ssImages.length)];
  img.src = `/api/file?path=${encodeURIComponent(path)}`;
  img.className = ssAnims[Math.floor(Math.random() * ssAnims.length)];
  overlay.innerHTML = "";
  overlay.appendChild(img);
  requestAnimationFrame(() => { img.classList.add("active"); });
}

function ssStart() {
  if (ssActive || !ssImages.length) return;
  ssActive = true;
  const overlay = document.getElementById("screensaver");
  overlay.classList.remove("hidden");
  ssShowNext();
  ssInterval = setInterval(ssShowNext, 6000);
}

function ssReset() {
  if (ssActive) {
    ssActive = false;
    const overlay = document.getElementById("screensaver");
    overlay.classList.add("hidden");
    overlay.innerHTML = "";
    if (ssInterval) { clearInterval(ssInterval); ssInterval = null; }
  }
  if (ssTimer) clearTimeout(ssTimer);
  const mins = (window._ssTimeout || 5);
  ssTimer = setTimeout(ssStart, mins * 60 * 1000);
}

["mousemove","mousedown","keydown","touchstart","wheel","click"].forEach((ev) => {
  window.addEventListener(ev, ssReset, { passive: true });
  document.addEventListener(ev, ssReset, { passive: true });
});

// init
const _ssOrigLoadConfig = null;
