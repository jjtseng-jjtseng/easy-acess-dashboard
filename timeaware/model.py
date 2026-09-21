# The time-of-day model.
#
# Every item (an app or a site) is boiled down to hits[168]: for each hour-of-the-week slot (slot 0 is
# Monday 00:00-01:00), how many days you used it in that slot, recent days counting more. active[168] is the
# same count for "you were around at all". hits / active is the chance you use the item in a slot given you're
# at the PC - the right question when you're looking at the dashboard - and it isn't skewed by one marathon day,
# because it counts days, not minutes.
#
# With little data a raw ratio is unreliable (2 uses in 2 days looks like 100%), so each hour's chance is shrunk
# level by level: this weekday leans on this kind of day (weekday/weekend), which leans on any day, which leans on
# the item's overall rate. As data piles up, the specific habit takes over.
import math
from datetime import date

from . import config, usual

SLOTS = 168


def derive(items, hit_amount, active_amount, today=None):
    """items: {key: {"cells": {"YYYY-MM-DD HH": amount}}} -> {"hits": {key: [168]}, "active": [168], "days": n}.

    A cell is a "hit" for an item once its amount reaches `hit_amount`, and an "active" hour once the amount
    summed over all items reaches `active_amount`.
    """
    today_ord = (today or date.today()).toordinal()
    parsed = {}  # "YYYY-MM-DD" -> (weekday, recency weight), or None for a malformed date

    def locate(cell):
        """(slot, recency weight) for a cell key, or None if the key is malformed."""
        day = cell[:10]
        if day not in parsed:
            try:
                d = date.fromisoformat(day)
                age = max(0, today_ord - d.toordinal())
                parsed[day] = (d.weekday(), 0.5 ** (age / config.RECENCY_HALF_LIFE_DAYS))
            except ValueError:
                parsed[day] = None
        info = parsed[day]
        hour = cell[11:13]
        if info is None or not hour.isdigit() or int(hour) > 23:
            return None
        return info[0] * 24 + int(hour), info[1]

    totals = {}
    hits = {}
    for key, item in items.items():
        row = [0.0] * SLOTS
        for cell, amount in item["cells"].items():
            totals[cell] = totals.get(cell, 0) + amount
            if amount >= hit_amount:
                spot = locate(cell)
                if spot:
                    row[spot[0]] += spot[1]
        hits[key] = row

    active = [0.0] * SLOTS
    days = set()
    for cell, amount in totals.items():
        if amount >= active_amount:
            spot = locate(cell)
            if spot:
                active[spot[0]] += spot[1]
                days.add(cell[:10])
    return {"hits": hits, "active": active, "days": len(days)}


class _Around:
    """How many (recency-weighted) days you were around in each hour, for one day of the week."""

    def __init__(self, active, dow):
        self.dow = dow
        self.kind_days = [d for d in range(7) if (d >= 5) == (dow >= 5)]  # weekdays with weekdays, weekend with weekend
        self.day = [active[dow * 24 + h] for h in range(24)]
        self.kind = [sum(active[d * 24 + h] for d in self.kind_days) for h in range(24)]
        self.every = [sum(active[d * 24 + h] for d in range(7)) for h in range(24)]

    def rate(self, hits, h, overall, k):
        """Chance you use an item during hour h on this weekday, given you're around.

        `k` is how many observations of the broader habit get mixed in: bigger is more cautious.
        """
        p = (sum(hits[d * 24 + h] for d in range(7)) + k * overall) / (self.every[h] + k)
        p = (sum(hits[d * 24 + h] for d in self.kind_days) + k * p) / (self.kind[h] + k)
        return (hits[self.dow * 24 + h] + k * p) / (self.day[h] + k)


def _proximity(hour):
    """[(hour, weight)] for the hours near a moment (`hour` is a float like 21.5), wrapping past midnight."""
    near = []
    for h in range(24):
        gap = abs(h + 0.5 - hour)
        gap = min(gap, 24 - gap)
        if gap <= 3 * config.HOUR_SIGMA:
            near.append((h, math.exp(-gap * gap / (2 * config.HOUR_SIGMA ** 2))))
    return near


def rhythm(derived, dow):
    """When you're around, hour by hour, on this kind of day (weekday or weekend), scaled 0..1."""
    kind = _Around(derived["active"], dow).kind
    peak = max(kind)
    return [round(v / peak, 3) for v in kind] if peak > 0 else [0.0] * 24


def top(derived, dow, hour, limit, tiebreak, keys=None):
    """The `limit` items you're most likely to use around (dow, hour), best first (only `keys`, if given).

    An item's score is its best hour near the moment, discounted the further that hour is from it, so a 9pm
    habit scores high at 9:30pm, less at 8:30pm, and nothing at noon. Each row has: key; rate (that score,
    read as a chance); lift (rate vs. the item's overall rate); evidence (days of data behind this hour);
    and the "usual" label plus 24-hour `spark` profile for that day of the week.
    `tiebreak` is {key: number} and orders items the model has no evidence about yet.
    """
    active = derived["active"]
    total_active = sum(active)
    around = _Around(active, dow)
    near = _proximity(hour)

    scored = []
    for key, hits in derived["hits"].items():
        if keys is not None and key not in keys:
            continue
        total = sum(hits)
        overall = total / total_active if total_active else 0.0
        rate = max((w * around.rate(hits, h, overall, config.PRIOR_STRENGTH) for h, w in near), default=0.0)
        scored.append((rate, tiebreak.get(key, 0), key, total, overall))
    scored.sort(reverse=True)

    evidence = around.kind[int(hour) % 24]
    rows = []
    for rate, _, key, total, overall in scored[:limit]:
        # The label and bars describe your history rather than predict, so they use the lighter prior.
        by_hour = [around.rate(derived["hits"][key], h, overall, config.PROFILE_PRIOR_STRENGTH) for h in range(24)]
        rows.append({
            "key": key, "rate": rate, "evidence": evidence,
            "lift": rate / overall if overall else None,
            **usual.describe(by_hour, around.kind, total),
        })
    return rows
