# Turns an item's 24-hour likelihood profile into a "Usually 8-11 PM" label and a sparkline.
from . import config


def hour_text(h):
    return "%d %s" % ((h % 12) or 12, "AM" if h % 24 < 12 else "PM")


def window_text(lo, hi):
    """Hours lo..hi inclusive (the window may wrap past midnight), e.g. "8–11 PM" or "around 9 PM"."""
    if lo == hi:
        return "around " + hour_text(lo)
    end = (hi + 1) % 24  # hour `hi` runs until the top of the next hour
    if (lo < 12) == (end < 12):
        return "%d–%d %s" % ((lo % 12) or 12, (end % 12) or 12, "AM" if end < 12 else "PM")
    return "%s–%s" % (hour_text(lo), hour_text(end))


def find_windows(score):
    """Up to two (lo, hi) hour windows where `score` peaks, each grown outward while hours stay near the peak."""
    peak = max(score)
    windows, taken = [], set()
    for _ in range(2):
        free = [h for h in range(24) if h not in taken]
        if not free:
            break
        best = max(free, key=lambda i: score[i])
        if score[best] <= 0 or (windows and score[best] < config.SECOND_PEAK_FRACTION * peak):
            break
        lo = hi = best
        width = 1
        floor = config.PEAK_WINDOW_FRACTION * score[best]
        while width < config.MAX_WINDOW_HOURS:
            options = [(score[i], i, side) for i, side in (((lo - 1) % 24, -1), ((hi + 1) % 24, 1))
                       if i not in taken and score[i] >= floor]
            if not options:
                break
            _, i, side = max(options)
            if side < 0:
                lo = i
            else:
                hi = i
            width += 1
        windows.append((lo, hi))
        taken.update((lo - 2 + j) % 24 for j in range(width + 4))  # keep this peak's shoulders from counting as a 2nd peak
    return sorted(windows)


def _blur(values):
    """Light circular blur so a busy hour and its neighbours read as one habit, not a spiky mess."""
    return [0.25 * values[(h - 1) % 24] + 0.5 * values[h] + 0.25 * values[(h + 1) % 24] for h in range(24)]


def describe(by_hour_rate, evidence_by_hour, total_hits):
    """by_hour_rate[h]: chance you use the item in hour h when you're around; evidence_by_hour[h]: data behind it.

    Returns {"usual": text, "spark": 24 values scaled 0..1, or None when there's too little to say}.
    """
    # An hour you're rarely at the PC for shouldn't look like a "usual" time, however sure the maths is.
    presence = [min(1.0, n / config.FULL_EVIDENCE) for n in evidence_by_hour]
    score = _blur([r * p for r, p in zip(by_hour_rate, presence)])
    peak = max(score)
    if total_hits < config.MIN_HITS_FOR_PATTERN or peak <= 0:
        return {"usual": "Still learning when you use this", "spark": None}

    spark = [round(s / peak, 3) for s in score]
    around = [r for r, p in zip(by_hour_rate, presence) if p >= 0.5]
    if len(around) >= 3 and max(around) < config.ANYTIME_CONTRAST * (sum(around) / len(around)):
        return {"usual": "Anytime", "spark": spark}  # used about as much whenever you're on the PC
    windows = find_windows(score)
    return {"usual": "Usually " + " & ".join(window_text(lo, hi) for lo, hi in windows), "spark": spark}
