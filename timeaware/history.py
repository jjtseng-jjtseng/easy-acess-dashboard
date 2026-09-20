# Browser history -> per-hour site visits. Chrome / Edge "Default" profile only, like dashboard.py (the
# numbered profiles on this machine are automation profiles from the mining project, not personal browsing).
# Unlike dashboard.py this keeps every visit's time of day, which is what makes sites time-aware on day one.
import os
import re
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime
from urllib.parse import urlparse

from . import config, model, store

WEBKIT_TO_UNIX = 11644473600  # seconds between Chrome's 1601 epoch and the Unix epoch
_HOST_RE = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+")

# Only count places you actually ended up:
#  - transition types 3 and 4 are subframe loads (embeds, ads): content on a page, not somewhere you went
#  - CHAIN_END (0x20000000) marks the last stop of a redirect chain; the rows before it are hops
#    (gmail.com on its way to mail.google.com), which would otherwise show up as a site of their own
QUERY = """
    SELECT urls.url, visits.visit_time
    FROM visits JOIN urls ON urls.id = visits.url
    WHERE visits.visit_time > ?
      AND (visits.transition & 255) NOT IN (3, 4)
      AND (visits.transition & 536870912) != 0
"""


def history_paths():
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        os.path.join(local, "Google", "Chrome", "User Data", "Default", "History"),
        os.path.join(local, "Microsoft", "Edge", "User Data", "Default", "History"),
    ]
    return [p for p in candidates if os.path.exists(p)]


def domain_of(url):
    """The site a URL belongs to, or None for anything that isn't a normal website you'd go to."""
    try:
        parts = urlparse(url)
        host = parts.hostname or ""
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    if host.startswith("www."):
        host = host[4:]
    if not _HOST_RE.fullmatch(host) or host.replace(".", "").isdigit():  # odd names, IP addresses, localhost
        return None
    if any(kw in host for kw in config.EXCLUDED_DOMAIN_KEYWORDS):
        return None
    return host


def _scan_file(path, cutoff_webkit, sites):
    """Add one browser's visits to `sites`. Returns False if the history couldn't be read."""
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        shutil.copy2(path, tmp)  # the browser keeps the live file locked
        conn = sqlite3.connect(tmp)
        try:
            domains = {}  # url -> domain (or None); most visits repeat a url we've already parsed
            for url, visit_time in conn.execute(QUERY, (cutoff_webkit,)):
                if url not in domains:
                    domains[url] = domain_of(url)
                domain = domains[url]
                if domain is None:
                    continue
                unix = visit_time / 1_000_000 - WEBKIT_TO_UNIX
                try:
                    cell = store.cell_key(datetime.fromtimestamp(unix))  # local time
                except (OverflowError, OSError, ValueError, TypeError):
                    continue
                site = sites.setdefault(domain, {"cells": {}, "visits": 0, "last_visit": 0})
                site["cells"][cell] = site["cells"].get(cell, 0) + 1
                site["visits"] += 1
                site["last_visit"] = max(site["last_visit"], unix)
        finally:
            conn.close()
        return True
    except Exception:
        return False
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


def rescan():
    """Rebuild the site model from browser history. Returns False (keeping the old data) if it couldn't."""
    paths = history_paths()
    cutoff = int((time.time() + WEBKIT_TO_UNIX - config.HISTORY_WINDOW_DAYS * 86400) * 1_000_000)
    sites = {}
    results = [_scan_file(p, cutoff, sites) for p in paths]
    if paths and not any(results):
        return False
    derived = model.derive(sites, config.SITE_HIT_VISITS, config.SITE_HIT_VISITS)
    meta = {d: {"domain": d, "visits": s["visits"], "last_visit": s["last_visit"]} for d, s in sites.items()}
    store.set_sites(meta, derived)
    return True


def history_loop():
    while True:
        try:
            ok = rescan()
        except Exception:
            ok = False
        time.sleep(config.HISTORY_SCAN_INTERVAL if ok else 30)
