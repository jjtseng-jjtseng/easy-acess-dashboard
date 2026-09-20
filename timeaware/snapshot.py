# Builds the JSON the page shows: the apps and sites you're most likely to want around a given moment.
import hashlib
from datetime import datetime, timezone

from . import config, model, store


def app_id_for(path):
    return hashlib.sha1(path.lower().encode("utf-8")).hexdigest()[:12]


def _iso(unix):
    return datetime.fromtimestamp(unix, timezone.utc).isoformat() if unix else None


def _card(row):
    """What every card shows, whether it's an app or a site."""
    enough_days = row["evidence"] >= config.FULL_EVIDENCE / 2  # enough days behind this hour to quote a chance
    known = row["spark"] is not None and enough_days
    lift = row["lift"]
    return {
        "usual": row["usual"],
        "spark": row["spark"],
        "likelihood": round(row["rate"], 2) if known else None,
        "lift": round(lift, 1) if known and lift and lift >= config.LIFT_SHOW else None,
    }


def build(dow=None, hour=None):
    """dow: 0-6 (Monday is 0) or None for today; hour: 0-23 or None for right now."""
    now = datetime.now()
    at_dow = now.weekday() if dow is None else dow
    at_hour = now.hour + now.minute / 60 if hour is None else hour + 0.5

    with store.lock:
        app_model = model.derive(store.apps, config.APP_HIT_SECONDS, config.APP_HIT_SECONDS)
        app_meta = {key: {
            "id": app_id_for(e["path"]), "name": e["name"], "seconds": e["seconds"], "last_seen": e["last_seen"],
        } for key, e in store.apps.items()}
        site_model, site_meta = store.sites_model, store.sites_meta

    app_rows = model.top(app_model, at_dow, at_hour, config.TOP_N, {k: m["seconds"] for k, m in app_meta.items()})
    apps = [{
        "id": app_meta[r["key"]]["id"], "name": app_meta[r["key"]]["name"],
        "last_seen": app_meta[r["key"]]["last_seen"], **_card(r),
    } for r in app_rows]

    sites = []
    if site_model is not None:
        site_rows = model.top(site_model, at_dow, at_hour, config.TOP_N, {d: m["visits"] for d, m in site_meta.items()})
        sites = [{
            "domain": r["key"], "url": "https://" + r["key"], "visits": site_meta[r["key"]]["visits"],
            "last_visit": _iso(site_meta[r["key"]]["last_visit"]), **_card(r),
        } for r in site_rows]

    return {
        "at": {"dow": at_dow, "hour": int(at_hour) % 24, "live": dow is None and hour is None},
        "learning": {
            "apps": app_model["days"] < config.LEARNING_DAYS,
            "app_days": app_model["days"], "need_days": config.LEARNING_DAYS,
        },
        "sites_ready": site_model is not None,
        "apps": apps,
        "sites": sites,
    }
