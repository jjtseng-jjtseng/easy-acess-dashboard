# Tiny local web server: the page, its JSON, and "open this app". Binds to 127.0.0.1 only.
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import config, favicons, snapshot, store

AUTH_TOKEN = secrets.token_urlsafe(24)
TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}


def launch_app(app_id):
    with store.lock:
        path = next((e["path"] for e in store.apps.values() if snapshot.app_id_for(e["path"]) == app_id), None)
    if not path or not os.path.exists(path):
        return False
    try:
        os.startfile(path)  # noqa: S606 - only ever a path we recorded from real usage
        return True
    except OSError:
        return False


def _bounded_int(text, low, high):
    try:
        n = int(text)
    except ValueError:
        return None
    return n if low <= n <= high else None


def _page():
    with open(os.path.join(config.WEB_DIR, "index.html"), "r", encoding="utf-8") as f:
        return f.read().replace("__TOKEN__", AUTH_TOKEN).encode("utf-8")


def _asset(path):
    """(bytes, content type) for a file directly inside web/, or None. The name must appear in the directory
    listing, so a request can't reach anything outside that folder."""
    name = path.lstrip("/")
    ext = os.path.splitext(name)[1]
    if ext not in TYPES or name not in os.listdir(config.WEB_DIR):
        return None
    with open(os.path.join(config.WEB_DIR, name), "rb") as f:
        return f.read(), TYPES[ext]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send(self, status, body=b"", content_type=None, headers=None):
        self.send_response(status)
        if content_type:
            self.send_header("Content-Type", content_type)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(status, json.dumps(obj).encode("utf-8"), "application/json")

    def do_GET(self):
        # Only answer requests addressed to us by name; a web page can't trick the browser into asking
        # this server for data under some other hostname (DNS rebinding).
        host = self.headers.get("Host", "").lower()
        if host not in ("127.0.0.1:%d" % config.PORT, "localhost:%d" % config.PORT):
            self._json({"error": "forbidden"}, 403)
            return

        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        def arg(name):
            return (qs.get(name) or [""])[0]

        try:
            if parsed.path == "/":
                self._send(200, _page(), "text/html; charset=utf-8")
            elif parsed.path == "/favicon.ico":
                self._send(204)
            elif parsed.path in ("/api/data", "/api/find", "/api/site-icon", "/launch"):
                if not secrets.compare_digest(arg("token").encode("utf-8"), AUTH_TOKEN.encode("utf-8")):
                    self._json({"error": "forbidden"}, 403)
                elif parsed.path == "/launch":
                    self._json({"ok": launch_app(arg("id"))})
                elif parsed.path == "/api/site-icon":
                    icon = favicons.png_for(arg("key"))
                    if icon is None:
                        self._send(404)
                    else:
                        self._send(200, icon, "image/png", {"X-Content-Type-Options": "nosniff"})
                else:
                    dow, hour = _bounded_int(arg("dow"), 0, 6), _bounded_int(arg("hour"), 0, 23)
                    if parsed.path == "/api/data":
                        self._json(snapshot.build(dow, hour))
                    else:
                        self._json({"results": snapshot.find(arg("q"), dow, hour)})
            elif parsed.path.count("/") == 1 and (asset := _asset(parsed.path)):
                self._send(200, asset[0], asset[1])
            else:
                self._send(404)
        except Exception:
            self._json({"error": "internal"}, 500)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # HTTPServer turns on SO_REUSEADDR, which on Windows lets a second copy bind a port the first is still
    # listening on. Then the "already running" check in dashboard_time.py never fires and two servers (with
    # different auth tokens) split the page's requests between them.
    allow_reuse_address = False
