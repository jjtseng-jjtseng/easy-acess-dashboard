# Builds the JSON the page shows: the apps and sites you're most likely to want around a given moment.
import hashlib
from datetime import datetime, timezone

from . import config, favicons, model, store


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


def _app_row(row, meta):
    m = meta[row["key"]]
    return {"kind": "app", "id": m["id"], "name": m["name"], "last_seen": m["last_seen"], **_card(row)}


def _site_row(row, meta):
    m = meta[row["key"]]
    result = {
        "kind": "site", "domain": row["key"], "name": row["key"], "url": "https://" + row["key"],
        "visits": m["visits"], "last_visit": _iso(m["last_visit"]), **_card(row),
    }
    # The browser gets only an opaque per-process handle, not a favicon-database
    # path or a queryable history domain.
    if icon_key := favicons.handle_for(row["key"]):
        result["icon_key"] = icon_key
    return result


def _context(dow, hour):
    """The moment being asked about, plus a consistent read of the apps and sites."""
    now = datetime.now()
    with store.lock:
        app_model = model.derive(store.apps, config.APP_HIT_SECONDS, config.APP_HIT_SECONDS)
        app_meta = {key: {
            "id": app_id_for(e["path"]), "name": e["name"], "seconds": e["seconds"], "last_seen": e["last_seen"],
        } for key, e in store.apps.items()}
        site_model, site_meta = store.sites_model, store.sites_meta
    return {
        "now": now,
        "dow": now.weekday() if dow is None else dow,
        "hour": now.hour + now.minute / 60 if hour is None else hour + 0.5,
        "live": dow is None and hour is None,
        "apps": (app_model, app_meta),
        "sites": (site_model, site_meta),
    }


def build(dow=None, hour=None):
    """dow: 0-6 (Monday is 0) or None for today; hour: 0-23 or None for right now."""
    ctx = _context(dow, hour)
    app_model, app_meta = ctx["apps"]
    site_model, site_meta = ctx["sites"]
    now = ctx["now"]

    app_rows = model.top(app_model, ctx["dow"], ctx["hour"], config.TOP_N, {k: m["seconds"] for k, m in app_meta.items()})
    sites = []
    if site_model is not None:
        site_rows = model.top(site_model, ctx["dow"], ctx["hour"], config.TOP_N, {d: m["visits"] for d, m in site_meta.items()})
        sites = [_site_row(r, site_meta) for r in site_rows]

    # The bars behind the time strip: whichever model has seen you around more (usually the 45 days of history).
    around = max((m for m in (app_model, site_model) if m is not None), key=lambda m: sum(m["active"]))
    return {
        "at": {"dow": ctx["dow"], "hour": int(ctx["hour"]) % 24, "live": ctx["live"]},
        "today": {"dow": now.weekday(), "hour": now.hour, "minute": now.minute},
        "rhythm": model.rhythm(around, ctx["dow"]),
        "learning": {
            "apps": app_model["days"] < config.LEARNING_DAYS,
            "app_days": app_model["days"], "need_days": config.LEARNING_DAYS,
        },
        "sites_ready": site_model is not None,
        "apps": [_app_row(r, app_meta) for r in app_rows],
        "sites": sites,
    }


def _match_rank(name, query):
    """0 if the query starts the name or one of its words, 1 if it's just inside, None if absent."""
    low = name.lower()
    i = low.find(query)
    if i < 0:
        return None
    return 0 if i == 0 or not low[i - 1].isalnum() else 1


def find(query, dow=None, hour=None, limit=12):
    """Apps and sites whose name contains the query, word-start matches first, then likeliest for the moment."""
    q = query.strip().lower()[:60]
    if not q:
        return []
    ctx = _context(dow, hour)
    found = []
    for kind, (mdl, meta) in (("app", ctx["apps"]), ("site", ctx["sites"])):
        if mdl is None:
            continue
        name_of = (lambda k: meta[k]["name"]) if kind == "app" else (lambda k: k)
        rank = {k: r for k in meta if (r := _match_rank(name_of(k), q)) is not None}
        if not rank:
            continue
        weight = {k: meta[k]["seconds"] if kind == "app" else meta[k]["visits"] for k in rank}
        keep = set(sorted(rank, key=lambda k: (rank[k], -weight[k]))[:limit * 3])
        for r in model.top(mdl, ctx["dow"], ctx["hour"], len(keep), weight, keys=keep):
            row = _app_row(r, meta) if kind == "app" else _site_row(r, meta)
            found.append((rank[r["key"]], -r["rate"], row))
    # Keep this deterministic without falling through to a dict comparison
    # when two matches happen to have the same rank and likelihood.
    found.sort(key=lambda t: (t[0], t[1], t[2]["name"].lower()))
    return [row for _, _, row in found[:limit]]
