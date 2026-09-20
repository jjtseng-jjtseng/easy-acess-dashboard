# Tiny local web server: the page, its JSON, and "open this app". Binds to 127.0.0.1 only.
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import config, snapshot, store

AUTH_TOKEN = secrets.token_urlsafe(24)


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
    with open(config.PAGE_FILE, "r", encoding="utf-8") as f:
        return f.read().replace("__TOKEN__", AUTH_TOKEN).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send(self, status, body=b"", content_type=None):
        self.send_response(status)
        if content_type:
            self.send_header("Content-Type", content_type)
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

        if parsed.path == "/":
            self._send(200, _page(), "text/html; charset=utf-8")
        elif parsed.path == "/favicon.ico":
            self._send(204)
        elif parsed.path in ("/api/data", "/launch"):
            if not secrets.compare_digest(arg("token").encode("utf-8"), AUTH_TOKEN.encode("utf-8")):
                self._json({"error": "forbidden"}, 403)
            elif parsed.path == "/launch":
                self._json({"ok": launch_app(arg("id"))})
            else:
                try:
                    self._json(snapshot.build(_bounded_int(arg("dow"), 0, 6), _bounded_int(arg("hour"), 0, 23)))
                except Exception:
                    self._json({"error": "internal"}, 500)
        else:
            self._send(404)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # HTTPServer turns on SO_REUSEADDR, which on Windows lets a second copy bind a port the first is still
    # listening on. Then the "already running" check in dashboard_time.py never fires and two servers (with
    # different auth tokens) split the page's requests between them.
    allow_reuse_address = False
