# Watches which app is focused and credits it to the current clock hour (pauses when you're idle).
import time
from datetime import datetime

from . import config, store, winapi


def is_excluded_app(info):
    name = info["name"].lower()
    title = (info["title"] or "").lower()
    if name in config.SYSTEM_NOISE:
        return True
    return any(kw in name or kw in title for kw in config.EXCLUDED_KEYWORDS)


def track_loop():
    last_key = None
    polls = 0
    while True:
        try:
            if winapi.get_idle_seconds() >= config.IDLE_THRESHOLD_SECONDS:
                last_key = None
            else:
                info = winapi.get_active_window_info()
                if info and not is_excluded_app(info):
                    key = info["path"].lower()
                    store.add_app_time(
                        info["path"], winapi.friendly_name(info["name"]),
                        config.POLL_INTERVAL, key != last_key, datetime.now(),
                    )
                    last_key = key
                else:
                    last_key = None
            polls += 1
            if polls % config.SAVE_EVERY_N_POLLS == 0:
                store.save()
        except Exception:
            pass
        time.sleep(config.POLL_INTERVAL)
