# Personal dashboard: tracks your most-used apps + most-visited sites, launches apps from one page.
# Config (exclusions, ports, intervals) lives in the CONFIG block below - edit freely.
# Everything is local: binds to 127.0.0.1 only, no network calls, data.json lives next to this file.
import ctypes
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import webbrowser
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
PORT = 47821
POLL_INTERVAL = 5              # seconds between "what app is focused" checks
IDLE_THRESHOLD_SECONDS = 300   # pause recording after this long with no keyboard/mouse input
SAVE_EVERY_N_POLLS = 6         # write data.json roughly every 30s
HISTORY_SCAN_INTERVAL = 180    # seconds between browser-history rescans
HISTORY_WINDOW_DAYS = 45       # only count site visits from the last N days
TOP_N = 10

EXCLUDED_KEYWORDS = ["chatgpt", "claude", "anthropic", "openai"]
EXCLUDED_DOMAIN_KEYWORDS = ["openai.com", "chatgpt.com", "claude.ai", "anthropic.com"]
SYSTEM_NOISE = {
    "explorer.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "lockapp.exe", "logonui.exe", "dwm.exe",
    "textinputhost.exe", "systemsettings.exe", "applicationframehost.exe",
    "searchapp.exe", "widgets.exe", "peopleexperiencehost.exe",
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(SCRIPT_DIR, "data.json")
AUTH_TOKEN = secrets.token_urlsafe(24)

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
lock = threading.Lock()


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                loaded.setdefault("apps", {})
                loaded.setdefault("sites", {})
                return loaded
        except (OSError, json.JSONDecodeError):
            pass
    return {"apps": {}, "sites": {}}


data = load_data()


def save_data():
    tmp = DATA_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, DATA_FILE)
    except OSError:
        pass


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Foreground-window + idle tracking (Win32 via ctypes)
# ---------------------------------------------------------------------------
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.GetTickCount64.restype = ctypes.c_ulonglong

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
user32.GetLastInputInfo.restype = wintypes.BOOL


def get_idle_seconds():
    try:
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not user32.GetLastInputInfo(ctypes.byref(lii)):
            return 0.0
        return max(0.0, (kernel32.GetTickCount64() - lii.dwTime) / 1000.0)
    except Exception:
        return 0.0


def get_active_window_info():
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None

        length = user32.GetWindowTextLengthW(hwnd)
        title_buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buf, length + 1)

        hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not hproc:
            return None
        try:
            size = wintypes.DWORD(1024)
            path_buf = ctypes.create_unicode_buffer(size.value)
            ok = kernel32.QueryFullProcessImageNameW(hproc, 0, path_buf, ctypes.byref(size))
            if not ok:
                return None
            path = path_buf.value
        finally:
            kernel32.CloseHandle(hproc)

        return {"path": path, "name": os.path.basename(path), "title": title_buf.value}
    except Exception:
        return None


def friendly_name(exe_name):
    stem = exe_name[:-4] if exe_name.lower().endswith(".exe") else exe_name
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", stem).replace("_", " ").replace("-", " ").strip()
    return spaced.title() if spaced.islower() else spaced


def is_excluded_app(info):
    name = info["name"].lower()
    title = (info["title"] or "").lower()
    if name in SYSTEM_NOISE:
        return True
    return any(kw in name or kw in title for kw in EXCLUDED_KEYWORDS)


def track_loop():
    last_key = None
    polls = 0
    while True:
        try:
            if get_idle_seconds() >= IDLE_THRESHOLD_SECONDS:
                last_key = None
            else:
                info = get_active_window_info()
                if info and not is_excluded_app(info):
                    key = info["path"].lower()
                    with lock:
                        entry = data["apps"].setdefault(key, {
                            "path": info["path"], "name": friendly_name(info["name"]),
                            "seconds": 0, "sessions": 0, "last_seen": None,
                        })
                        entry["seconds"] += POLL_INTERVAL
                        entry["last_seen"] = now_iso()
                        if key != last_key:
                            entry["sessions"] += 1
                    last_key = key
                else:
                    last_key = None
            polls += 1
            if polls % SAVE_EVERY_N_POLLS == 0:
                with lock:
                    save_data()
        except Exception:
            pass
        time.sleep(POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Browser history (Chrome / Edge "Default" profile only - the numbered
# profiles on this machine are automation profiles from the mining project,
# not personal browsing, so they're deliberately skipped)
# ---------------------------------------------------------------------------
CHROME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


def webkit_to_iso(webkit_ts):
    if not webkit_ts:
        return None
    try:
        return (CHROME_EPOCH + timedelta(microseconds=webkit_ts)).isoformat()
    except (OverflowError, OSError):
        return None


def browser_history_paths():
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        os.path.join(local, "Google", "Chrome", "User Data", "Default", "History"),
        os.path.join(local, "Microsoft", "Edge", "User Data", "Default", "History"),
    ]
    return [p for p in candidates if os.path.exists(p)]


def domain_of(url):
    try:
        netloc = urlparse(url).netloc.lower()
    except ValueError:
        return None
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or None


def is_excluded_domain(domain):
    return any(kw in domain for kw in EXCLUDED_DOMAIN_KEYWORDS)


def scan_history_file(path, cutoff_dt):
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        shutil.copy2(path, tmp_path)
        cutoff_webkit = int((cutoff_dt - CHROME_EPOCH).total_seconds() * 1_000_000)
        conn = sqlite3.connect(tmp_path)
        try:
            rows = conn.execute(
                """
                SELECT urls.url, urls.title, COUNT(visits.id), MAX(visits.visit_time)
                FROM urls JOIN visits ON urls.id = visits.url
                WHERE visits.visit_time > ?
                GROUP BY urls.id
                ORDER BY 3 DESC
                LIMIT 1000
                """,
                (cutoff_webkit,),
            ).fetchall()
        finally:
            conn.close()
        return rows
    except Exception:
        return []
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def history_loop():
    while True:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=HISTORY_WINDOW_DAYS)
            agg = {}
            for path in browser_history_paths():
                for url, title, visits, last_visit in scan_history_file(path, cutoff):
                    domain = domain_of(url)
                    if not domain or is_excluded_domain(domain):
                        continue
                    a = agg.setdefault(domain, {"visits": 0, "title": title or domain, "last_visit": 0})
                    a["visits"] += visits or 0
                    if (last_visit or 0) > a["last_visit"]:
                        a["last_visit"] = last_visit
                        if title:
                            a["title"] = title
            with lock:
                for domain, info in agg.items():
                    data["sites"][domain] = {
                        "domain": domain, "visits": info["visits"], "title": info["title"],
                        "last_visit": webkit_to_iso(info["last_visit"]),
                    }
                save_data()
        except Exception:
            pass
        time.sleep(HISTORY_SCAN_INTERVAL)


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------
def app_id_for(path):
    return hashlib.sha1(path.lower().encode("utf-8")).hexdigest()[:12]


def build_snapshot():
    with lock:
        apps = list(data["apps"].values())
        sites = list(data["sites"].values())
    apps.sort(key=lambda a: a["seconds"], reverse=True)
    sites.sort(key=lambda s: s["visits"], reverse=True)
    out_apps = [{
        "id": app_id_for(a["path"]), "name": a["name"], "seconds": a["seconds"],
        "sessions": a["sessions"], "last_seen": a["last_seen"],
    } for a in apps[:TOP_N]]
    out_sites = [{
        "domain": s["domain"], "visits": s["visits"], "url": "https://" + s["domain"],
        "last_visit": s["last_visit"],
    } for s in sites[:TOP_N]]
    return {"apps": out_apps, "sites": out_sites}


def launch_app(app_id):
    with lock:
        path = next((e["path"] for e in data["apps"].values() if app_id_for(e["path"]) == app_id), None)
    if not path or not os.path.exists(path):
        return False
    try:
        os.startfile(path)  # noqa: S606 - path is only ever one we've already recorded from real usage
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Frontend (single page, no external assets/CDNs)
# ---------------------------------------------------------------------------
DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {
  --bg: #0f1115; --panel: #171a21; --panel-border: #262b36;
  --text: #e6e8ec; --muted: #8b91a0; --accent: #6ea8fe;
}
@media (prefers-color-scheme: light) {
  :root {
    --bg: #f4f5f7; --panel: #ffffff; --panel-border: #e2e4e9;
    --text: #1b1e25; --muted: #666d7d; --accent: #2f6fed;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
.wrap { max-width: 980px; margin: 0 auto; padding: 40px 24px 64px; }
header.top { display:flex; justify-content:space-between; align-items:baseline; }
h1 { font-size: 28px; margin: 0; letter-spacing: -0.02em; }
#clock { font-variant-numeric: tabular-nums; color: var(--muted); font-size: 15px; }
#greeting { color: var(--muted); margin: 6px 0 36px; font-size: 15px; }
section { margin-bottom: 40px; }
.section-head { display:flex; align-items:center; gap:8px; margin-bottom: 14px; }
.section-head h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin:0; font-weight:600; }
.count-badge { background: var(--panel-border); color: var(--muted); font-size: 12px; padding: 2px 8px; border-radius: 999px; }
.grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(200px,1fr)); gap: 12px; }
.card {
  display:flex; align-items:center; gap: 12px;
  background: var(--panel); border: 1px solid var(--panel-border);
  border-radius: 14px; padding: 12px 14px;
  text-decoration:none; color:inherit;
  transition: transform .12s ease, border-color .12s ease;
}
.card:hover { transform: translateY(-2px); border-color: var(--accent); }
.avatar {
  flex: none; width: 36px; height:36px; border-radius:10px;
  display:flex; align-items:center; justify-content:center;
  color:white; font-weight:600; font-size:15px;
}
.card-body { min-width:0; flex:1; }
.card-title { font-size:14px; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.card-sub { font-size:12px; color: var(--muted); margin-top:2px; }
.open-btn {
  flex:none; border:1px solid var(--panel-border); background:transparent; color:var(--text);
  padding:6px 10px; border-radius:8px; font-size:12px; cursor:pointer;
}
.open-btn:hover { border-color: var(--accent); color: var(--accent); }
.open-btn:disabled { opacity:.6; cursor:default; }
.empty { color: var(--muted); font-size: 14px; }
footer { color: var(--muted); font-size:12px; text-align:center; margin-top: 40px; }
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <h1>Dashboard</h1>
    <div id="clock"></div>
  </header>
  <p id="greeting"></p>

  <section>
    <div class="section-head"><h2>Top Apps</h2><span class="count-badge" id="appCount">0</span></div>
    <div class="grid" id="apps"></div>
  </section>

  <section>
    <div class="section-head"><h2>Top Sites</h2><span class="count-badge" id="siteCount">0</span></div>
    <div class="grid" id="sites"></div>
  </section>

  <footer>Tracking in the background on this PC only &middot; pauses after 5min idle &middot; Claude &amp; ChatGPT excluded &middot; nothing leaves your machine</footer>
</div>
<script>
const TOKEN = "__TOKEN__";

function fmtDuration(sec) {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  if (h > 0) return h + "h " + m + "m";
  if (m > 0) return m + "m";
  return "<1m";
}
function fmtAgo(iso) {
  if (!iso) return "never";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return Math.floor(diff / 60) + "m ago";
  if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
  return Math.floor(diff / 86400) + "d ago";
}
function hashHue(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) { h = (h * 31 + str.charCodeAt(i)) >>> 0; }
  return h % 360;
}
function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function avatar(name) {
  const hue = hashHue(name);
  const initial = (name || "?").trim().charAt(0).toUpperCase();
  return '<div class="avatar" style="background:hsl(' + hue + ' 55% 42%)">' + escapeHtml(initial) + "</div>";
}
async function launchApp(id, btn) {
  btn.disabled = true;
  const prev = btn.textContent;
  btn.textContent = "Opening...";
  try {
    const res = await fetch("/launch?id=" + encodeURIComponent(id) + "&token=" + TOKEN);
    const j = await res.json();
    btn.textContent = j.ok ? "Opened [ok]" : "Failed";
  } catch (e) {
    btn.textContent = "Failed";
  }
  setTimeout(() => { btn.disabled = false; btn.textContent = prev; }, 1500);
}
function render(d) {
  const appsEl = document.getElementById("apps");
  const sitesEl = document.getElementById("sites");
  document.getElementById("appCount").textContent = d.apps.length;
  document.getElementById("siteCount").textContent = d.sites.length;

  appsEl.innerHTML = "";
  if (d.apps.length === 0) {
    appsEl.innerHTML = '<p class="empty">Still learning your habits - keep using your computer normally and this fills in on its own.</p>';
  } else {
    d.apps.forEach(a => {
      const card = document.createElement("div");
      card.className = "card";
      card.innerHTML = avatar(a.name) +
        '<div class="card-body"><div class="card-title" title="' + escapeHtml(a.name) + '">' + escapeHtml(a.name) + '</div>' +
        '<div class="card-sub">' + fmtDuration(a.seconds) + ' total &middot; ' + fmtAgo(a.last_seen) + '</div></div>';
      const btn = document.createElement("button");
      btn.className = "open-btn";
      btn.textContent = "Open";
      btn.addEventListener("click", () => launchApp(a.id, btn));
      card.appendChild(btn);
      appsEl.appendChild(card);
    });
  }

  sitesEl.innerHTML = "";
  if (d.sites.length === 0) {
    sitesEl.innerHTML = '<p class="empty">No recent browsing history found yet.</p>';
  } else {
    d.sites.forEach(s => {
      const card = document.createElement("a");
      card.className = "card";
      card.href = s.url;
      card.target = "_blank";
      card.rel = "noopener";
      card.innerHTML = avatar(s.domain) +
        '<div class="card-body"><div class="card-title" title="' + escapeHtml(s.domain) + '">' + escapeHtml(s.domain) + '</div>' +
        '<div class="card-sub">' + s.visits + ' visits &middot; ' + fmtAgo(s.last_visit) + '</div></div>';
      sitesEl.appendChild(card);
    });
  }
}
async function refresh() {
  try {
    const res = await fetch("/api/data?token=" + TOKEN);
    render(await res.json());
  } catch (e) { /* server briefly unavailable, e.g. during login startup */ }
}
function tickClock() {
  const now = new Date();
  document.getElementById("clock").textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const h = now.getHours();
  document.getElementById("greeting").textContent =
    h < 5 ? "Still up?" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}
tickClock();
setInterval(tickClock, 30000);
refresh();
setInterval(refresh, 7000);
</script>
</body>
</html>
"""

RENDERED_HTML = DASHBOARD_HTML.replace("__TOKEN__", AUTH_TOKEN).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(RENDERED_HTML)))
            self.end_headers()
            self.wfile.write(RENDERED_HTML)
        elif parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        elif parsed.path == "/api/data":
            qs = parse_qs(parsed.query)
            if (qs.get("token") or [""])[0] != AUTH_TOKEN:
                self._json({"error": "forbidden"}, 403)
                return
            self._json(build_snapshot())
        elif parsed.path == "/launch":
            qs = parse_qs(parsed.query)
            if (qs.get("token") or [""])[0] != AUTH_TOKEN:
                self._json({"error": "forbidden"}, 403)
                return
            ok = launch_app((qs.get("id") or [""])[0])
            self._json({"ok": ok})
        else:
            self.send_response(404)
            self.end_headers()


class Server(ThreadingHTTPServer):
    daemon_threads = True


def main():
    no_open = "--no-open" in sys.argv
    try:
        server = Server(("127.0.0.1", PORT), Handler)
    except OSError:
        # Another instance is already listening (e.g. started at login) - just open it.
        if not no_open:
            webbrowser.open("http://127.0.0.1:%d/" % PORT)
        return

    threading.Thread(target=track_loop, daemon=True).start()
    threading.Thread(target=history_loop, daemon=True).start()

    if not no_open:
        threading.Timer(0.6, lambda: webbrowser.open("http://127.0.0.1:%d/" % PORT)).start()

    server.serve_forever()


if __name__ == "__main__":
    main()
