/* Dashboard / time client. It intentionally uses only browser APIs: the Python
   server remains the single source of truth for ranking and search. */
const TOKEN = window.TOKEN || "";
const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const state = {
  day: null,
  hour: null,
  data: null,
  dataSequence: 0,
  searchSequence: 0,
  searchTimer: 0,
  railTimer: 0,
};

const els = {
  announce: document.getElementById("announce"),
  apps: document.getElementById("apps"),
  appsCount: document.getElementById("appsCount"),
  appsSub: document.getElementById("appsSub"),
  caption: document.getElementById("caption"),
  days: document.getElementById("days"),
  dialMarker: document.getElementById("dialMarker"),
  dialSvg: document.getElementById("dialSvg"),
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
  signalIndex: document.getElementById("signalIndex"),
  signalKind: document.getElementById("signalKind"),
  signalName: document.getElementById("signalName"),
  signalRate: document.getElementById("signalRate"),
  signalRateLabel: document.getElementById("signalRateLabel"),
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

function timeText(hour, minute) {
  const h = Number(hour) % 24;
  const min = String(Number(minute || 0)).padStart(2, "0");
  return String((h % 12) || 12) + ":" + min + " " + (h < 12 ? "AM" : "PM");
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

function svgNode(tag, attributes) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attributes || {}).forEach(function (entry) {
    element.setAttribute(entry[0], String(entry[1]));
  });
  return element;
}

function polar(radius, hour) {
  const angle = ((Number(hour) * 15) - 90) * Math.PI / 180;
  return { x: 130 + radius * Math.cos(angle), y: 130 + radius * Math.sin(angle) };
}

function lineAtHour(hour, startRadius, endRadius, className) {
  const start = polar(startRadius, hour);
  const end = polar(endRadius, hour);
  return svgNode("line", { x1: start.x, y1: start.y, x2: end.x, y2: end.y, class: className });
}

function rhythmKind(dow) {
  return Number(dow) < 5 ? "weekday" : "weekend";
}

function renderDial(data) {
  const fragment = document.createDocumentFragment();
  fragment.appendChild(svgNode("circle", { cx: 130, cy: 130, r: 113, class: "dial-boundary" }));
  fragment.appendChild(svgNode("circle", { cx: 130, cy: 130, r: 87, class: "dial-boundary" }));

  for (let hour = 0; hour < 24; hour += 1) {
    const group = svgNode("g", { class: "dial-hour" });
    const value = clamp(Number((data.rhythm || [])[hour] || 0), 0, 1);
    if (hour === data.at.hour) group.classList.add("is-active");
    if (hour === data.today.hour) group.classList.add("is-now");
    group.appendChild(lineAtHour(hour, 114, hour % 3 === 0 ? 102 : 106, "hour-tick"));
    group.appendChild(lineAtHour(hour, 91, 86 - Math.round(value * 31), "hour-signal"));
    fragment.appendChild(group);
  }

  [0, 6, 12, 18].forEach(function (hour) {
    const point = polar(96, hour);
    const label = svgNode("text", { x: point.x, y: point.y, class: "dial-label" });
    label.textContent = String(hour).padStart(2, "0");
    fragment.appendChild(label);
  });

  const handHour = data.at.live
    ? data.today.hour + data.today.minute / 60
    : data.at.hour + .5;
  const tip = polar(83, handHour);
  fragment.appendChild(svgNode("line", { x1: 130, y1: 130, x2: tip.x, y2: tip.y, class: "needle" }));
  fragment.appendChild(svgNode("circle", { cx: tip.x, cy: tip.y, r: 3.5, class: "needle-tip" }));
  fragment.appendChild(svgNode("circle", { cx: 130, cy: 130, r: 6, class: "hub" }));
  els.dialSvg.replaceChildren(fragment);
  els.hours.setAttribute("aria-valuenow", String(data.at.hour));
  els.hours.setAttribute("aria-valuetext", hourText(data.at.hour) + ", " + rhythmKind(data.at.dow) + " rhythm");
}

function renderSignal(data) {
  const items = data.apps.concat(data.sites);
  const primary = items[0];
  const secondary = items.find(function (item, index) {
    return index > 0 && item.kind !== (primary && primary.kind);
  }) || items[1];
  const kind = rhythmKind(data.at.dow);
  els.signalState.textContent = data.at.live ? kind + " signal" : "preview signal";
  els.signalIndex.textContent = String(data.at.hour).padStart(2, "0") + ":00";

  if (!primary) {
    els.signalKind.textContent = "Activity signal";
    els.signalName.textContent = "No signal yet";
    els.signalRate.textContent = "--";
    els.signalRateLabel.textContent = "learning";
    els.signalWindow.textContent = "Keep using your computer normally; this clock will gain a useful rhythm.";
    els.signalAlt.textContent = "No secondary signal yet";
    return;
  }

  const known = primary.likelihood !== null && primary.likelihood !== undefined;
  els.signalKind.textContent = known
    ? "Likely next " + (primary.kind === "app" ? "app" : "site")
    : "Top recorded " + (primary.kind === "app" ? "app" : "site");
  els.signalName.textContent = primary.name;
  els.signalRate.textContent = known ? Math.round(Number(primary.likelihood) * 100) + "%" : "--";
  els.signalRateLabel.textContent = known ? "match" : "learning";
  els.signalWindow.textContent = known
    ? (primary.usual || "No time window established yet.")
    : "Ranking by recorded use while this timing pattern is still learning.";
  els.signalAlt.textContent = secondary
    ? secondary.name + (secondary.usual ? " / " + secondary.usual : "")
    : "No secondary signal yet";
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
  renderDial(data);
  renderSignal(data);

  if (data.at.live) {
    els.viewDay.textContent = "Live / " + rhythmKind(data.at.dow) + " rhythm";
    els.viewTime.textContent = timeText(data.today.hour, data.today.minute);
    els.dialMarker.textContent = "now";
    els.caption.textContent = "The orange hand marks the current minute. Inner bars show peak-normalized " +
      rhythmKind(data.at.dow) + " activity by hour.";
    els.nowBtn.hidden = true;
    setConnection("live", "tracking");
  } else {
    els.viewDay.textContent = "Preview / " + DAYS[data.at.dow];
    els.viewTime.textContent = hourText(data.at.hour);
    els.dialMarker.textContent = "selected hour";
    els.caption.textContent = "This is the " + rhythmKind(data.at.dow) + " rhythm. Drag or click the dial to inspect " +
      "another hour; use Shift with arrows to change the day.";
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

function setHour(hour, deferred) {
  state.hour = clamp(Number(hour), 0, 23);
  window.clearTimeout(state.railTimer);
  if (deferred) {
    state.railTimer = window.setTimeout(refresh, 90);
  } else {
    refresh();
  }
}

function hourAtPointer(event) {
  const rect = els.hours.getBoundingClientRect();
  const x = event.clientX - (rect.left + rect.width / 2);
  const y = event.clientY - (rect.top + rect.height / 2);
  const degrees = (Math.atan2(y, x) * 180 / Math.PI + 450) % 360;
  return Math.floor(degrees / 15 + .5) % 24;
}

function moveHour(delta) {
  const base = state.hour === null ? (state.data ? state.data.at.hour : new Date().getHours()) : state.hour;
  setHour((base + delta + 24) % 24, false);
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
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      const delta = event.key === "ArrowLeft" ? -1 : 1;
      if (event.shiftKey) moveDay(delta);
      else moveHour(delta);
    }
  });
}

function installRail() {
  let dragging = false;
  els.hours.addEventListener("pointerdown", function (event) {
    dragging = true;
    els.hours.setPointerCapture(event.pointerId);
    setHour(hourAtPointer(event), true);
    event.preventDefault();
  });
  els.hours.addEventListener("pointermove", function (event) {
    if (dragging) setHour(hourAtPointer(event), true);
  });
  function finish(event) {
    if (!dragging) return;
    dragging = false;
    window.clearTimeout(state.railTimer);
    setHour(hourAtPointer(event), false);
  }
  els.hours.addEventListener("pointerup", finish);
  els.hours.addEventListener("pointercancel", finish);
  els.hours.addEventListener("keydown", function (event) {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      moveHour(event.key === "ArrowLeft" ? -1 : 1);
    } else if (event.key === "Home") {
      event.preventDefault();
      setHour(0, false);
    } else if (event.key === "End") {
      event.preventDefault();
      setHour(23, false);
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
installKeyboard();
installRail();
installTheme();
refresh();
window.setInterval(refresh, 30000);
