const API = "";
let movies = [];
let currentMovie = null;
let subsOn = true;
let currentSub = null;
let pollTimer = null;
let currentTab = "movies";
let currentCategory = "movie";

const $ = (id) => document.getElementById(id);

function catFromTab(tab) {
  if (tab === "series") return "series";
  if (tab === "musicals") return "musical";
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
  if (name === "library") $("libraryView").classList.remove("hidden");
  else if (name === "detail") $("detailView").classList.remove("hidden");
  else if (name === "streaming") $("streamingView").classList.remove("hidden");
  else if (name === "collection") $("collectionView").classList.remove("hidden");
}

function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  if (tab === "streaming") {
    currentCategory = "streaming";
    showView("streaming");
  } else {
    currentCategory = catFromTab(tab);
    showView("library");
    loadFilterOptions();
    loadMovies();
  }
}

function applyTheme(name) {
  const link = $("themeCss");
  if (link) link.href = `/static/theme-${name || "default"}.css`;
}

async function loadConfig() {
  const cfg = await api("/api/config");
  $("sHost").value = cfg.host || "127.0.0.1";
  $("sPort").value = cfg.port || 8765;
  $("sSkip").value = cfg.skip_seconds || 10;
  $("sTmdbKey").value = cfg.tmdb_api_key || "";
  $("sTheme").value = cfg.theme || "default";
  applyTheme(cfg.theme || "default");
  $("sKiosk").checked = !!cfg.kiosk_mode;
  $("sFullscreen").checked = cfg.fullscreen !== false;
  refreshLibLists();
  populateLibSelect();
}

async function refreshLibLists() {
  for (const cat of ["movie", "series", "musical"]) {
    const key = cat === "movie" ? "movie" : (cat === "series" ? "series" : "musical");
    const data = await api(`/api/libraries?category=${key}`);
    const listId = cat === "movie" ? "movieLibList" : (cat === "series" ? "seriesLibList" : "musicalLibList");
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
  params.set("sort", $("sortSelect").value || "title_asc");
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
    grid.appendChild(card);
  });
}

function escapeHtml(s){ return (s||"").replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

async function openDetail(m) {
  currentMovie = m;
  showView("detail");
  $("dTitle").textContent = m.title || m.name;
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
  const backdrop = imgUrl(m, "backdrop");
  $("dBackdrop").style.backgroundImage = backdrop ? `url(${backdrop})` : "";
  try {
    const data = await api(`/api/movie?path=${encodeURIComponent(m.path)}`);
    const dm = data.movie;
    if (dm) {
      if (dm.poster_local || dm.poster_url) $("dPoster").src = imgUrl(dm, "poster");
      if (dm.backdrop_local || dm.backdrop_url) {
        const b = imgUrl(dm, "backdrop");
        if (b) $("dBackdrop").style.backgroundImage = `url(${b})`;
      }
      $("dOverview").textContent = dm.overview || "";
      $("dRating").textContent = dm.rating ? `★ ${Number(dm.rating).toFixed(1)}` : "";
      $("dYear").textContent = dm.year || m.year || "";
      $("dRuntime").textContent = dm.runtime ? `${dm.runtime} min` : (m._duration ? fmtTime(m._duration) : "");
      $("dCountry").textContent = dm.country || "";
      $("dGenres").textContent = (dm.genres || []).join(", ");
      $("dDirector").innerHTML = dm.director ? `<strong>Director:</strong> ${escapeHtml(dm.director)}` : "";
      $("dCast").innerHTML = (dm.cast && dm.cast.length) ? `<strong>Cast:</strong> ${escapeHtml(dm.cast.join(", "))}` : "";
      $("dFileInfo").innerHTML = dm.file_info ? `<strong>File:</strong> ${escapeHtml(dm.file_info)}` : "";
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

$("backBtn").onclick = () => showView("library");
$("collBackBtn").onclick = () => showView("library");

// art picker
$("changeArtBtn").onclick = async () => {
  window._artTarget = "movie";
  $("artModal").classList.remove("hidden");
  $("artQuery").value = currentMovie ? (currentMovie.title || currentMovie.name || "") : "";
  await doArtSearch();
};
$("artClose").onclick = () => $("artModal").classList.add("hidden");
$("artFrameBtn").onclick = async () => {
  if (window._artTarget === "collection") {
    await api("/api/collection/art", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ collection: currentCollection }) });
    window._artTarget = null;
    $("artModal").classList.add("hidden");
    await loadMovies();
    openCollection($("collTitle").textContent, currentCollectionItems);
  } else {
    await api("/api/movie/art", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ path: currentMovie.path }) });
    $("artModal").classList.add("hidden");
    openDetail(currentMovie);
  }
};
$("artSearchBtn").onclick = doArtSearch;
$("artQuery").addEventListener("keydown", (e) => { if (e.key === "Enter") doArtSearch(); });

function parseTmdbId(input) {
  input = (input || "").trim();
  if (!input) return null;
  // extract digits from URL or plain ID
  const m = input.match(/(\d+)/);
  return m ? parseInt(m[1]) : null;
}

$("artFetchBtn").onclick = async () => {
  const id = parseTmdbId($("artTmdbInput").value);
  if (!id) return;
  const data = await api(`/api/tmdb/details?id=${id}`);
  const d = data.details;
  if (!d) return;
  const preview = $("artPreview");
  preview.innerHTML = "";
  const card = document.createElement("div");
  card.className = "stream-card";
  card.innerHTML = `
    ${d.poster_url ? `<img src="${d.poster_url}" alt="" />` : ""}
    <div class="t">${escapeHtml(d.title)}</div>
    <div class="y">${d.year || ""}</div>`;
  card.style.cursor = "pointer";
  card.onclick = async () => {
    const backdrop = d.backdrop_url;
    const posterUrl = d.poster_url;
    if (window._artTarget === "collection") {
      await api("/api/collection/art", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ collection: currentCollection, poster_url: posterUrl, backdrop_url: backdrop }) });
      window._artTarget = null;
      $("artModal").classList.add("hidden");
      await loadMovies();
      openCollection($("collTitle").textContent, currentCollectionItems);
    } else {
      await api("/api/movie/art", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ path: currentMovie.path, poster_url: posterUrl, backdrop_url: backdrop }) });
      currentMovie.poster_url = posterUrl || currentMovie.poster_url;
      currentMovie.backdrop_url = backdrop || currentMovie.backdrop_url;
      $("artModal").classList.add("hidden");
      openDetail(currentMovie);
    }
  };
  preview.appendChild(card);
  // also show backdrop preview
  if (d.backdrop_url) {
    const b = document.createElement("img");
    b.src = d.backdrop_url;
    b.style.width = "100%";
    b.style.borderRadius = "8px";
    b.style.marginTop = "8px";
    preview.appendChild(b);
  }
};

async function doArtSearch() {
  const q = ($("artQuery").value || "").trim();
  if (!q) return;
  const data = await api(`/api/tmdb/results?title=${encodeURIComponent(q)}&year=${encodeURIComponent(currentMovie?.year || "")}`);
  const container = $("artResults");
  container.innerHTML = "";
  (data.results || []).forEach((r) => {
    const card = document.createElement("div");
    card.className = "stream-card";
    card.innerHTML = `
      ${r.poster ? `<img src="${r.poster}" alt="" />` : ""}
      <div class="t">${escapeHtml(r.title)}</div>
      <div class="y">${r.year || ""}</div>`;
    card.style.cursor = "pointer";
    card.onclick = async () => {
      let backdrop = r.backdrop;
      try {
        const dd = await api(`/api/tmdb/details?id=${r.id}`);
        if (dd.details && dd.details.backdrop_url) backdrop = dd.details.backdrop_url;
      } catch (e) {}
      const posterUrl = r.poster ? r.poster.replace("w342","w500") : null;
      if (window._artTarget === "collection") {
        await api("/api/collection/art", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ collection: currentCollection, poster_url: posterUrl, backdrop_url: backdrop }) });
        window._artTarget = null;
        $("artModal").classList.add("hidden");
        await loadMovies();
        openCollection($("collTitle").textContent, currentCollectionItems);
      } else {
        await api("/api/movie/art", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ path: currentMovie.path, poster_url: posterUrl, backdrop_url: backdrop }) });
        currentMovie.poster_url = posterUrl || currentMovie.poster_url;
        currentMovie.backdrop_url = backdrop || currentMovie.backdrop_url;
        $("artModal").classList.add("hidden");
        openDetail(currentMovie);
      }
    };
    container.appendChild(card);
  });
}
$("collBackBtn").onclick = () => showView("library");

let currentCollection = null;
let currentCollectionItems = null;
function openCollection(title, items) {
  currentCollection = items && items[0] ? (items[0].collection || title) : title;
  currentCollectionItems = items;
  showView("collection");
  $("collTitle").textContent = title;
  const grid = $("collGrid");
  grid.innerHTML = "";
  items.forEach((m) => {
    const card = document.createElement("div");
    card.className = "card";
    const posterUrl = imgUrl(m, "poster");
    card.innerHTML = `
      <img class="poster" src="${posterUrl}" alt="" loading="lazy" onerror="this.style.background='#000'" />
      <div class="card-title">${escapeHtml(m.title || m.name)}</div>
      <div class="card-year">${m.file_info || m.year || ""}</div>`;
    card.onclick = () => openDetail(m);
    grid.appendChild(card);
  });
}

$("collChangeArtBtn").onclick = async () => {
  if (!currentCollection) return;
  $("artModal").classList.remove("hidden");
  $("artQuery").value = currentCollection.split(/[\\/]/).pop() || currentCollection;
  // override the art picker to target the collection
  window._artTarget = "collection";
  await doArtSearch();
};
// patch doArtSearch result click to handle collection target
const _origDoArtSearch = doArtSearch;
doArtSearch = async function() {
  await _origDoArtSearch();
  // re-bind clicks with collection handling
  document.querySelectorAll("#artResults .stream-card").forEach((card, idx) => {
    // already bound; nothing extra
  });
};

$("playBtn").onclick = async () => {
  if (!currentMovie) return;
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
$("settingsBtn").onclick = async () => {
  $("settingsModal").classList.remove("hidden");
  await refreshLibLists();
  browseTo("");
};
$("sClose").onclick = () => $("settingsModal").classList.add("hidden");
$("rescanBtn").onclick = async () => {
  const btn = $("rescanBtn");
  const orig = btn.textContent;
  btn.textContent = "Rescanning...";
  btn.disabled = true;
  try {
    for (const cat of ["movie", "series", "musical"]) {
      await api(`/api/scan?category=${cat}&force=1`);
    }
    await loadFilterOptions();
    await loadMovies();
  } finally {
    btn.textContent = orig;
    btn.disabled = false;
  }
};

$("serverCombo").addEventListener("change", async (e) => {
  const val = e.target.value;
  if (!val) return;
  e.target.value = "";
  if (val === "closeBrowser") {
    window.close();
  } else if (val === "restartServer") {
    if (!confirm("Restart the MoviePlayer server?")) return;
    try { await api("/api/restart", { method:"POST", headers:{"Content-Type":"application/json"}, body:"{}" }); } catch (err) {}
    document.body.innerHTML = "<div style='text-align:center;padding:60px;color:#fff;font-family:sans-serif'><h1>Restarting…</h1><p>Reload this page in a few seconds.</p></div>";
  } else if (val === "stopServer") {
    if (!confirm("Stop the MoviePlayer server and close the browser?")) return;
    try { await api("/api/shutdown", { method:"POST", headers:{"Content-Type":"application/json"}, body:"{}" }); } catch (err) {}
    setTimeout(() => window.close(), 800);
    document.body.innerHTML = "<div style='text-align:center;padding:60px;color:#fff;font-family:sans-serif'><h1>Server stopped.</h1><p>You can close this tab.</p></div>";
  }
});
$("sSave").onclick = async () => {
  const cfg = {
    tmdb_api_key: $("sTmdbKey").value.trim(),
    host: $("sHost").value.trim(),
    port: parseInt($("sPort").value),
    skip_seconds: parseInt($("sSkip").value),
    theme: $("sTheme").value,
    kiosk_mode: $("sKiosk").checked,
    fullscreen: $("sFullscreen").checked,
  };
  await api("/api/config", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(cfg) });
  $("settingsModal").classList.add("hidden");
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
  movies.forEach((m) => {
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
  if (movies.length) {
    const firstItem = list.querySelector(".split-item");
    if (firstItem) firstItem.click();
  }
}

function renderSplitDetail(m, detail) {
  detail.innerHTML = "";
  const poster = imgUrl(m, "poster");
  const backdrop = imgUrl(m, "backdrop");
  if (backdrop) {
    detail.style.backgroundImage = `url(${backdrop})`;
    detail.style.backgroundSize = "cover";
    detail.style.backgroundPosition = "center";
  }
  const div = document.createElement("div");
  div.style.background = "rgba(15,17,21,.75)";
  div.style.padding = "16px";
  div.style.borderRadius = "8px";
  div.innerHTML = `
    <img class="sd-poster" src="${poster}" alt="" />
    <div class="sd-title">${escapeHtml(m.title || m.name)}</div>
    <div class="sd-meta">${m.year || ""} ${m.file_info ? "· " + escapeHtml(m.file_info) : ""}</div>
    <div class="sd-meta">${escapeHtml((m.genres || []).join(", "))}</div>
    <div class="sd-meta">${m.director ? "Director: " + escapeHtml(m.director) : ""}</div>
    <div class="sd-meta">${m.country ? "Country: " + escapeHtml(m.country) : ""}</div>
    <p class="overview">${escapeHtml(m.overview || "")}</p>
    <div class="sd-actions">
      <button class="btn primary" id="sdPlay">▶ Play</button>
      <button class="btn" id="sdBrowser">Browser play</button>
    </div>`;
  detail.appendChild(div);
  detail.querySelector("#sdPlay").onclick = async () => {
    const sub = (m.subtitles && m.subtitles.length) ? m.subtitles[0].path : null;
    currentSub = sub; subsOn = !!sub; currentMovie = m;
    await api("/api/play", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ path: m.path, sub: subsOn ? sub : null }) });
    showPlayerBar(m); startPolling();
  };
  detail.querySelector("#sdBrowser").onclick = () => {
    window.open(`/player.html?path=${encodeURIComponent(m.path)}&sub=${encodeURIComponent((m.subtitles&&m.subtitles[0])?m.subtitles[0].path:"")}`, "_blank");
  };
  currentMovie = m;
  // fetch subtitles
  api(`/api/subtitles?path=${encodeURIComponent(m.path)}`).then((sdata) => {
    if (sdata.subtitles && sdata.subtitles.length) {
      currentSub = sdata.subtitles[0].path;
      subsOn = true;
    }
  }).catch(()=>{});
}
$("fClear").onclick = () => {
  ["fGenre","fCountry","fDirector","fActor","fYear"].forEach((id) => { $(id).value = ""; });
  loadMovies();
};
["fGenre","fCountry","fDirector","fActor","fYear"].forEach((id) => {
  $(id).addEventListener("change", loadMovies);
});
$("searchBox").addEventListener("input", () => { clearTimeout(window._searchTimer); window._searchTimer = setTimeout(loadMovies, 300); });

// tabs
document.querySelectorAll(".tab-btn").forEach((b) => {
  b.addEventListener("click", () => switchTab(b.dataset.tab));
});

// scan
$("scanBtn").onclick = scan;

// auto load
loadConfig().then(() => {
  loadFilterOptions();
  loadMovies();
});

// streaming
async function doStreamSearch() {
  const q = ($("streamQuery").value || "").trim();
  if (!q) return;
  const progress = $("streamProgress");
  const results = $("streamResults");
  const sitesDiv = $("streamSites");
  const player = $("streamPlayer");
  progress.classList.add("active");
  results.innerHTML = "";
  sitesDiv.innerHTML = "";
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
      <div class="y">${year} ${it._type === "tv" ? "· TV" : ""}</div>`;
    card.style.cursor = "pointer";
    card.onclick = () => openStreamPlayer(it, title, year);
    results.appendChild(card);
  });
  sitesDiv.innerHTML = "";
  if (data.duckduckgo) {
    const a = document.createElement("a");
    a.className = "ddg-link";
    a.href = data.duckduckgo;
    a.target = "_blank";
    a.textContent = "Search across all streaming sites on DuckDuckGo →";
    sitesDiv.appendChild(a);
  }
  const wiki = document.createElement("a");
  wiki.className = "ddg-link";
  wiki.href = "https://github.com/fmhy/FMHY/wiki/Streaming";
  wiki.target = "_blank";
  wiki.textContent = "Browse all streaming sites (FMHY wiki) →";
  wiki.style.marginLeft = "16px";
  sitesDiv.appendChild(wiki);
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
api("/api/streaming/sites").catch(()=>{});