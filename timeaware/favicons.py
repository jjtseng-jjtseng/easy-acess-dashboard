# Local Chromium favicon reader. It deliberately reads only the Default Chrome
# and Edge favicon caches, never asks a site for an icon, and keeps the browser
# databases untouched.
from collections import OrderedDict
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time

from . import history

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_ICON_BYTES = 256 * 1024
ICON_CACHE_LIMIT = 128
INDEX_REFRESH_SECONDS = 600

_lock = threading.Lock()
_index = {}             # normalized domain -> (favicon database path, icon id)
_handles = {}           # opaque browser-visible id -> normalized domain
_handle_by_domain = {}
_blob_cache = OrderedDict()
_indexed_at = 0.0


def _paths():
    local = os.environ.get("LOCALAPPDATA", "")
    paths = [
        os.path.join(local, "Google", "Chrome", "User Data", "Default", "Favicons"),
        os.path.join(local, "Microsoft", "Edge", "User Data", "Default", "Favicons"),
    ]
    return [path for path in paths if os.path.isfile(path)]


def _connection(path):
    # immutable means SQLite will not create journal files or attempt any write
    # locks. It is especially important while Chrome has this database open.
    uri = Path(path).resolve().as_uri() + "?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def _better(candidate, previous):
    """True when candidate is the more useful compact row icon."""
    if previous is None:
        return True
    # Prefer a 32px-like bitmap, then the newer candidate. The source ordering
    # is handled by _scan_one so Chrome always wins over Edge when it has one.
    candidate_distance = abs(candidate[2] - 32) + abs(candidate[3] - 32)
    previous_distance = abs(previous[2] - 32) + abs(previous[3] - 32)
    return (candidate_distance, -candidate[4]) < (previous_distance, -previous[4])


def _scan_one(path):
    """Return the best icon location for each allowed domain in one cache."""
    chosen = {}
    try:
        conn = _connection(path)
        try:
            rows = conn.execute(
                """
                SELECT m.page_url, b.icon_id, b.width, b.height, b.last_updated
                FROM icon_mapping AS m
                JOIN favicon_bitmaps AS b ON b.icon_id = m.icon_id
                """
            )
            for page_url, icon_id, width, height, last_updated in rows:
                domain = history.domain_of(page_url)
                if not domain:
                    continue
                candidate = (path, int(icon_id), int(width or 0), int(height or 0), int(last_updated or 0))
                if _better(candidate, chosen.get(domain)):
                    chosen[domain] = candidate
        finally:
            conn.close()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return {}
    return chosen


def _refresh_locked():
    global _index, _indexed_at
    merged = {}
    # _paths intentionally lists Chrome first. A Chrome hit remains preferred
    # even when Edge happens to offer a bitmap closer to 32px.
    for path in _paths():
        source = _scan_one(path)
        for domain, candidate in source.items():
            if domain not in merged:
                merged[domain] = candidate
    _index = {domain: (candidate[0], candidate[1]) for domain, candidate in merged.items()}
    _indexed_at = time.monotonic()
    _blob_cache.clear()


def _ensure_index_locked():
    if time.monotonic() - _indexed_at >= INDEX_REFRESH_SECONDS:
        _refresh_locked()


def handle_for(domain):
    """An opaque id for a locally cached site icon, or None when unavailable."""
    with _lock:
        _ensure_index_locked()
        if domain not in _index:
            return None
        key = _handle_by_domain.get(domain)
        if key is None:
            key = secrets.token_urlsafe(12)
            _handle_by_domain[domain] = key
            _handles[key] = domain
        return key


def _read_blob(path, icon_id):
    try:
        conn = _connection(path)
        try:
            rows = conn.execute(
                "SELECT image_data, width, height, last_updated FROM favicon_bitmaps WHERE icon_id = ?",
                (icon_id,),
            )
            best = None
            for data, width, height, last_updated in rows:
                if not isinstance(data, bytes) or len(data) > MAX_ICON_BYTES or not data.startswith(PNG_MAGIC):
                    continue
                candidate = (data, int(width or 0), int(height or 0), int(last_updated or 0))
                if best is None:
                    best = candidate
                    continue
                candidate_distance = abs(candidate[1] - 32) + abs(candidate[2] - 32)
                best_distance = abs(best[1] - 32) + abs(best[2] - 32)
                if (candidate_distance, -candidate[3]) < (best_distance, -best[3]):
                    best = candidate
            return best[0] if best else None
        finally:
            conn.close()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return None


def png_for(handle):
    """Resolve a previously registered opaque handle to a safe local PNG blob."""
    with _lock:
        _ensure_index_locked()
        domain = _handles.get(handle)
        location = _index.get(domain) if domain else None
        if location is None:
            return None
        cached = _blob_cache.get(domain)
        if cached is not None:
            _blob_cache.move_to_end(domain)
            return cached
        data = _read_blob(location[0], location[1])
        if data is None:
            return None
        _blob_cache[domain] = data
        _blob_cache.move_to_end(domain)
        while len(_blob_cache) > ICON_CACHE_LIMIT:
            _blob_cache.popitem(last=False)
        return data
