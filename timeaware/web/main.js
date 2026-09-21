/* Timebook client. Local data remains the source of truth; the clock only presents time. */
const TOKEN = window.TOKEN || "";
const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const state = {
  day: null,
  hour: null,
  data: null,
  dataSequence: 0,
  searchSequence: 0,
  searchTimer: 0,
};

const els = {
  announce: document.getElementById("announce"),
  apps: document.getElementById("apps"),
  appsCount: document.getElementById("appsCount"),
  appsSub: document.getElementById("appsSub"),
  caption: document.getElementById("caption"),
  clock: document.getElementById("dashboardClock"),
  days: document.getElementById("days"),
  dialMarker: document.getElementById("dialMarker"),
  find: document.getElementById("find"),
  hours: document.getElementById("hours"),
  learn: document.getElementById("learn"),
  lists: document.getElementById("lists"),
  nowBtn: document.getElementById("nowBtn"),
  nextHour: document.getElementById("nextHour"),
  prevHour: document.getElementById("prevHour"),
  results: document.getElementById("results"),
  resultsCount: document.getElementById("resultsCount"),
  resultsSub: document.getElementById("resultsSub"),
  resultRows: document.getElementById("resultRows"),
  signalAlt: document.getElementById("signalAlt"),
  signalName: document.getElementById("signalName"),
  signalState: document.getElementById("signalState"),
  signalWindow: document.getElementById("signalWindow"),
  sites: document.getElementById("sites"),
  sitesCount: document.getElementById("sitesCount"),
  sitesSub: document.getElementById("sitesSub"),
  status: document.getElementById("status"),
  statusText: document.getElementById("statusText"),
  theme: document.getElementById("theme"),
  viewDay: document.getElementById("viewDay"),
  viewTime: document.getElementById("viewTime"),
};

function node(tag, className, content) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (content !== undefined && content !== null) element.textContent = String(content);
  return element;
}

function clamp(value, low, high) {
  return Math.max(low, Math.min(high, value));
}

function hourText(hour, compact) {
  const h = Number(hour) % 24;
  const suffix = h < 12 ? "AM" : "PM";
  return String((h % 12) || 12) + (compact ? suffix.charAt(0).toLowerCase() : " " + suffix);
}

function timeText(hour, minute, second) {
  const h = Number(hour) % 24;
  const min = String(Number(minute || 0)).padStart(2, "0");
  const suffix = h < 12 ? "AM" : "PM";
  if (second === undefined || second === null) {
    return String((h % 12) || 12) + ":" + min + " " + suffix;
  }
  return String((h % 12) || 12) + ":" + min + ":" + String(Number(second || 0)).padStart(2, "0") + " " + suffix;
}

function relativeTime(iso) {
  if (!iso) return "never used";
  const timestamp = new Date(iso).getTime();
  if (!Number.isFinite(timestamp)) return "last use unknown";
  const seconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
  if (seconds < 60) return "used just now";
  if (seconds < 3600) return "used " + Math.floor(seconds / 60) + "m ago";
  if (seconds < 86400) return "used " + Math.floor(seconds / 3600) + "h ago";
  return "used " + Math.floor(seconds / 86400) + "d ago";
}

function announce(message) {
  els.announce.textContent = "";
  window.setTimeout(function () { els.announce.textContent = message; }, 20);
}

function setConnection(kind, message) {
  els.status.dataset.state = kind;
  els.statusText.textContent = message;
}

function apiUrl(path, extra) {
  const params = new URLSearchParams();
  params.set("token", TOKEN);
  Object.keys(extra || {}).forEach(function (key) {
    const value = extra[key];
    if (value !== null && value !== undefined && value !== "") params.set(key, String(value));
  });
  return path + "?" + params.toString();
}

async function readJson(path, extra) {
  const response = await fetch(apiUrl(path, extra), { cache: "no-store" });
  if (!response.ok) throw new Error("Request failed: " + response.status);
  return response.json();
}

function targetLabel(data) {
  if (data.at.live) return "around now";
  return "at " + hourText(data.at.hour) + " on " + DAYS[data.at.dow];
}

function renderDays(data) {
  const fragment = document.createDocumentFragment();
  DAYS.forEach(function (day, index) {
    const button = node("button", "", day.slice(0, 3));
    button.type = "button";
    button.title = day;
    button.setAttribute("aria-label", "Show " + day);
    button.setAttribute("aria-pressed", String(index === data.at.dow));
    if (index === data.today.dow) button.dataset.today = "";
    button.addEventListener("click", function () {
      state.day = index;
      if (state.hour === null && state.data) state.hour = state.data.at.hour;
      refresh();
    });
    fragment.appendChild(button);
  });
  els.days.replaceChildren(fragment);
}

function prefersReducedMotion() {
  return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function previewEpoch(hour) {
  const preview = new Date();
  preview.setHours(Number(hour), 0, 0, 0);
  return preview.getTime();
}

function updateLiveReadout() {
  if (!state.data || !state.data.at.live || document.hidden) return;
  const now = new Date();
  els.viewTime.textContent = timeText(now.getHours(), now.getMinutes(), now.getSeconds());
}

function renderClock(data) {
  const clock = els.clock;
  const live = data.at.live;
  const displayHour = live ? new Date().getHours() : data.at.hour;

  if (clock && typeof clock.setEpochMs === "function") {
    if (live) {
      clock.syncToSystemTime();
      if (prefersReducedMotion()) clock.pause();
      else clock.resume();
    } else {
      clock.setEpochMs(previewEpoch(data.at.hour));
      clock.pause();
    }
  }

  els.viewDay.textContent = live ? "Live local time" : "Preview / " + DAYS[data.at.dow];
  els.viewTime.textContent = live
    ? timeText(new Date().getHours(), new Date().getMinutes(), new Date().getSeconds())
    : timeText(data.at.hour, 0, 0);
  els.dialMarker.textContent = live ? "now" : "selected hour";
  els.hours.setAttribute(
    "aria-label",
    (live ? "Local time" : "Selected time") + ": " + timeText(displayHour, live ? new Date().getMinutes() : 0, live ? new Date().getSeconds() : 0)
  );
}

function renderSignal(data) {
  const items = data.apps.concat(data.sites);
  const primary = items[0];
  const secondary = items.find(function (item, index) {
    return index > 0 && item.kind !== (primary && primary.kind);
  }) || items[1];
  const at = hourText(data.at.hour);

  els.signalState.textContent = data.at.live ? "At this time" : "At " + at;
  if (!primary) {
    els.signalName.textContent = "No pattern yet";
    els.signalWindow.textContent = "Keep using your computer normally. This note will become useful as history builds.";
    els.signalAlt.textContent = "";
    return;
  }

  const known = primary.likelihood !== null && primary.likelihood !== undefined;
  els.signalName.textContent = primary.name + (known ? " · " + Math.round(Number(primary.likelihood) * 100) + "%" : "");
  els.signalWindow.textContent = known
    ? (primary.usual || "A time window has not settled yet.")
    : "Most recorded while this time pattern is still learning.";
  els.signalAlt.textContent = secondary ? "Next: " + secondary.name : "";
}

function initials(item) {
  const source = String(item.name || item.domain || "?").trim();
  if (!source) return "?";
  if (item.kind === "site") return source.charAt(0);
  const words = source.split(/[\s._-]+/).filter(Boolean);
  if (words.length > 1) return words.slice(0, 2).map(function (word) { return word.charAt(0); }).join("");
  return source.slice(0, 2);
}

function identity(item) {
  const box = node("span", "row-identity", initials(item));
  if (item.kind !== "site" || !item.icon_key) return box;
  const image = document.createElement("img");
  image.src = apiUrl("/api/site-icon", { key: item.icon_key });
  image.alt = "";
  image.addEventListener("load", function () {
    box.textContent = "";
    box.appendChild(image);
  });
  return box;
}

function profile(item, activeHour) {
  if (!Array.isArray(item.spark)) return node("span", "profile-missing", "-");
  const graph = node("span", "profile");
  graph.title = item.usual || "Still learning this rhythm";
  item.spark.forEach(function (value, hour) {
    const bar = node("i");
    bar.style.height = Math.max(7, Math.round(Number(value || 0) * 100)) + "%";
    if (hour === activeHour) bar.dataset.active = "";
    graph.appendChild(bar);
  });
  return graph;
}

function metaText(item) {
  const usual = item.usual || "Still learning";
  if (item.kind === "app") return usual + " / " + relativeTime(item.last_seen);
  return usual + " / " + String(item.visits || 0) + " visits, " + relativeTime(item.last_visit);
}

function chance(item) {
  const box = node("span", "chance");
  if (item.likelihood === null || item.likelihood === undefined) {
    box.classList.add("chance--unknown");
    box.appendChild(node("span", "", "--"));
    box.appendChild(node("small", "", "learning"));
    return box;
  }
  box.appendChild(node("span", "", Math.round(Number(item.likelihood) * 100) + "%"));
  if (item.lift) box.appendChild(node("small", "", Number(item.lift).toFixed(1) + "x above"));
  return box;
}

function row(item, position, activeHour) {
  const isApp = item.kind === "app";
  const element = document.createElement(isApp ? "button" : "a");
  element.className = "data-row";
  element.dataset.kind = item.kind;
  if (isApp) {
    element.type = "button";
    element.setAttribute("aria-label", "Open " + item.name);
    element.addEventListener("click", function () { launchApp(item, element); });
  } else {
    element.href = item.url;
    element.target = "_blank";
    element.rel = "noopener";
    element.setAttribute("aria-label", "Open " + item.name + " in a new tab");
  }

  element.appendChild(node("span", "row-rank", String(position + 1).padStart(2, "0")));
  element.appendChild(identity(item));

  const copy = node("span", "row-copy");
  copy.appendChild(node("span", "row-name", item.name));
  const detail = node("span", "row-meta");
  detail.appendChild(node("span", "usual", metaText(item)));
  copy.appendChild(detail);
  element.appendChild(copy);
  element.appendChild(profile(item, activeHour));
  element.appendChild(chance(item));
  return element;
}

function empty(title, body) {
  const message = node("p", "empty");
  message.appendChild(node("strong", "", title));
  message.appendChild(document.createTextNode(body));
  return message;
}

function renderRows(container, items, activeHour, fallback) {
  if (!items.length) {
    container.replaceChildren(empty(fallback.title, fallback.body));
    return;
  }
  const fragment = document.createDocumentFragment();
  items.forEach(function (item, index) { fragment.appendChild(row(item, index, activeHour)); });
  container.replaceChildren(fragment);
}

function render(data) {
  state.data = data;
  renderDays(data);
  renderClock(data);
  renderSignal(data);

  if (data.at.live) {
    els.caption.textContent = "A real local clock. Use the arrows to inspect another hour.";
    els.nowBtn.hidden = true;
    setConnection("live", "tracking");
  } else {
    els.caption.textContent = "The clock is paused at the selected hour.";
    els.nowBtn.hidden = false;
    setConnection("live", "preview");
  }

  const signal = targetLabel(data);
  els.appsCount.textContent = String(data.apps.length);
  els.appsSub.textContent = signal;
  els.sitesCount.textContent = String(data.sites.length);
  els.sitesSub.textContent = data.sites_ready ? signal : "reading history";
  els.learn.hidden = !data.learning.apps;
  if (data.learning.apps) {
    els.learn.textContent = "Learning app rhythm: " + data.learning.app_days + " of " + data.learning.need_days +
      " days observed. Until then, apps stay ordered by overall use.";
  }

  renderRows(els.apps, data.apps, data.at.hour, {
    title: "No app signal yet",
    body: "Use your computer normally and this list will fill itself in."
  });
  renderRows(els.sites, data.sites, data.at.hour, data.sites_ready ? {
    title: "No recent sites",
    body: "No eligible sites were found in your local browser history."
  } : {
    title: "Reading browser history",
    body: "The first local scan can take a moment."
  });
}

async function launchApp(item, element) {
  if (element.dataset.opening === "true") return;
  element.dataset.opening = "true";
  element.disabled = true;
  announce("Opening " + item.name + ".");
  try {
    const response = await readJson("/launch", { id: item.id });
    if (response.ok) {
      announce(item.name + " opened.");
      element.dataset.opening = "opened";
    } else {
      announce("Could not open " + item.name + ". Its recorded path may no longer exist.");
    }
  } catch (error) {
    announce("Could not reach the local dashboard to open " + item.name + ".");
  }
  window.setTimeout(function () {
    delete element.dataset.opening;
    element.disabled = false;
  }, 900);
}

async function refresh() {
  const sequence = ++state.dataSequence;
  if (!state.data) setConnection("connecting", "connecting");
  try {
    const data = await readJson("/api/data", { dow: state.day, hour: state.hour });
    if (sequence !== state.dataSequence) return;
    render(data);
    if (els.find.value.trim()) query(els.find.value.trim(), true);
  } catch (error) {
    if (sequence !== state.dataSequence) return;
    setConnection("offline", "offline");
    if (!state.data) {
      els.apps.replaceChildren(empty("Local server unavailable", "Start dashboard_time.py, then refresh this page."));
      els.sites.replaceChildren();
    }
  }
}

function showNormal() {
  els.results.hidden = true;
  els.lists.hidden = false;
}

function renderSearch(results, queryText) {
  els.results.hidden = false;
  els.lists.hidden = true;
  els.resultsCount.textContent = String(results.length);
  els.resultsSub.textContent = 'for "' + queryText + '"';
  const activeHour = state.data ? state.data.at.hour : (new Date()).getHours();
  renderRows(els.resultRows, results, activeHour, {
    title: "No matches",
    body: "Try the beginning of an app name or domain."
  });
}

function query(value, immediate) {
  const text = String(value || "").trim();
  window.clearTimeout(state.searchTimer);
  if (!text) {
    state.searchSequence += 1;
    showNormal();
    return;
  }
  const perform = async function () {
    const sequence = ++state.searchSequence;
    try {
      const payload = await readJson("/api/find", { q: text, dow: state.day, hour: state.hour });
      if (sequence !== state.searchSequence || els.find.value.trim() !== text) return;
      renderSearch(payload.results || [], text);
    } catch (error) {
      if (sequence !== state.searchSequence) return;
      renderSearch([], text);
    }
  };
  if (immediate) perform();
  else state.searchTimer = window.setTimeout(perform, 150);
}

function setHour(hour) {
  state.hour = clamp(Number(hour), 0, 23);
  refresh();
}

function moveHour(delta) {
  const base = state.hour === null ? (state.data ? state.data.at.hour : new Date().getHours()) : state.hour;
  setHour((base + delta + 24) % 24);
}

function moveDay(delta) {
  const base = state.day === null ? (state.data ? state.data.at.dow : (new Date().getDay() + 6) % 7) : state.day;
  state.day = (base + delta + 7) % 7;
  if (state.hour === null && state.data) state.hour = state.data.at.hour;
  refresh();
}

function resetNow() {
  state.day = null;
  state.hour = null;
  refresh();
}

function isTextInput(target) {
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target.isContentEditable;
}

function installKeyboard() {
  document.addEventListener("keydown", function (event) {
    const typing = isTextInput(event.target);
    if (event.key === "Escape" && document.activeElement === els.find) {
      els.find.value = "";
      showNormal();
      els.find.blur();
      return;
    }
    if (typing) return;
    if (event.key === "/") {
      event.preventDefault();
      els.find.focus();
      return;
    }
    if (event.key.toLowerCase() === "n") {
      event.preventDefault();
      resetNow();
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      setHour(0);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      setHour(23);
      return;
    }
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      const delta = event.key === "ArrowLeft" ? -1 : 1;
      if (event.shiftKey) moveDay(delta);
      else moveHour(delta);
    }
  });
}

function installTheme() {
  let saved = "";
  try { saved = localStorage.getItem("dashboard-time-theme") || ""; } catch (error) { /* local storage is optional */ }
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
  function updateLabel() {
    const dark = document.documentElement.dataset.theme === "dark" ||
      (document.documentElement.dataset.theme === "auto" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    els.theme.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
    els.theme.title = dark ? "Switch to light theme" : "Switch to dark theme";
  }
  els.theme.addEventListener("click", function () {
    const root = document.documentElement;
    const dark = root.dataset.theme === "dark" ||
      (root.dataset.theme === "auto" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("dashboard-time-theme", root.dataset.theme); } catch (error) { /* optional */ }
    updateLabel();
  });
  updateLabel();
}

els.find.addEventListener("input", function () { query(els.find.value, false); });
els.nowBtn.addEventListener("click", resetNow);
els.prevHour.addEventListener("click", function () { moveHour(-1); });
els.nextHour.addEventListener("click", function () { moveHour(1); });
document.addEventListener("visibilitychange", function () {
  if (!document.hidden) {
    updateLiveReadout();
    if (state.data && state.data.at.live && els.clock && typeof els.clock.syncToSystemTime === "function") {
      els.clock.syncToSystemTime();
      if (!prefersReducedMotion()) els.clock.resume();
    }
  }
});
window.setInterval(updateLiveReadout, 1000);
installKeyboard();
installTheme();
refresh();
window.setInterval(refresh, 30000);

