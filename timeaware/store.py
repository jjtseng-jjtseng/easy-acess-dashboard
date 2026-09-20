# Shared state + persistence for the time-aware dashboard.
#
# The unit of data is a "cell": one clock hour on one day, keyed "YYYY-MM-DD HH" in local time, holding
# seconds of focus (apps) or page visits (sites). Everything the model knows is derived from cells.
#   apps  - tracked live and saved to time_data.json
#   sites - rebuilt from the browser history on every scan and never saved (history is the source of truth)
import json
import os
import re
import threading
from datetime import date, datetime, timedelta, timezone

from . import config

lock = threading.Lock()
apps = {}            # exe path (lowercased) -> {path, name, seconds, sessions, last_seen, cells}
sites_meta = {}      # domain -> {domain, visits, last_visit (unix seconds)}
sites_model = None   # model.derive() output for the current browser history, swapped in whole
_dirty = False

_CELL_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}")


def cell_key(dt):
    return "%04d-%02d-%02d %02d" % (dt.year, dt.month, dt.day, dt.hour)


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _clean_entry(raw):
    """A well-formed app entry from whatever was on disk, or None."""
    try:
        cells = raw.get("cells") or {}
        return {
            "path": str(raw["path"]), "name": str(raw["name"]),
            "seconds": int(raw.get("seconds", 0)), "sessions": int(raw.get("sessions", 0)),
            "last_seen": raw.get("last_seen"),
            "cells": {k: int(v) for k, v in cells.items() if _CELL_RE.fullmatch(k)},
        }
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def load():
    loaded = _read_json(config.DATA_FILE)
    if loaded is None and os.path.exists(config.DATA_FILE):
        try:
            os.replace(config.DATA_FILE, config.DATA_FILE + ".corrupt")  # keep it rather than overwrite it
        except OSError:
            pass

    raw_apps = None
    if loaded is not None:
        raw_apps = loaded.get("apps")
    elif config.SEED_FROM_ORIGINAL:
        # First run: reuse the app list dashboard.py already learned so the page isn't empty on day one.
        # Those totals have no time-of-day in them; they only order the list until real hours are tracked.
        original = _read_json(config.ORIGINAL_DATA_FILE)
        raw_apps = original.get("apps") if original else None

    with lock:
        apps.clear()
        for raw in (raw_apps.values() if isinstance(raw_apps, dict) else []):
            entry = _clean_entry(raw)
            # Also drops helpers that were tracked (or seeded) before they were added to SYSTEM_NOISE.
            if entry and os.path.basename(entry["path"]).lower() not in config.SYSTEM_NOISE:
                apps[entry["path"].lower()] = entry
        _prune_locked()


def _prune_locked():
    cutoff = (date.today() - timedelta(days=config.APP_LOG_RETENTION_DAYS)).isoformat()
    for entry in apps.values():
        entry["cells"] = {k: v for k, v in entry["cells"].items() if k[:10] >= cutoff}


def save():
    global _dirty
    with lock:
        if not _dirty:
            return
        _prune_locked()
        payload = json.dumps({"version": 1, "apps": apps})
        _dirty = False
    tmp = config.DATA_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, config.DATA_FILE)
    except OSError:
        with lock:
            _dirty = True  # try again on the next save


def add_app_time(path, name, seconds, new_session, now):
    """Credit `seconds` of focus to an app for the clock hour containing `now` (a local datetime)."""
    global _dirty
    cell = cell_key(now)
    with lock:
        entry = apps.setdefault(path.lower(), {
            "path": path, "name": name, "seconds": 0, "sessions": 0, "last_seen": None, "cells": {},
        })
        entry["seconds"] += seconds
        entry["last_seen"] = datetime.now(timezone.utc).isoformat()
        if new_session:
            entry["sessions"] += 1
        entry["cells"][cell] = entry["cells"].get(cell, 0) + seconds
        _dirty = True


def set_sites(meta, derived):
    global sites_meta, sites_model
    with lock:
        sites_meta = meta
        sites_model = derived
