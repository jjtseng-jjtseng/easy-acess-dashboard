# Settings for the time-aware dashboard (dashboard_time.py) - edit freely, read once at startup.
# Everything is local: binds to 127.0.0.1 only, no network calls, data lives next to dashboard.py.
import os

# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------
PORT = 47822                   # dashboard.py uses 47821, so both versions can run side by side
POLL_INTERVAL = 5              # seconds between "what app is focused" checks
IDLE_THRESHOLD_SECONDS = 300   # pause recording after this long with no keyboard/mouse input
SAVE_EVERY_N_POLLS = 12        # write time_data.json roughly every 60s
HISTORY_SCAN_INTERVAL = 600    # seconds between browser-history rescans
HISTORY_WINDOW_DAYS = 45       # only count site visits from the last N days
APP_LOG_RETENTION_DAYS = 120   # forget per-hour app usage older than this
TOP_N = 10
SEED_FROM_ORIGINAL = True      # first run only: borrow app names/paths/totals from dashboard.py's data.json

# ---------------------------------------------------------------------------
# What counts as "you used it" during one clock hour on one day
# ---------------------------------------------------------------------------
APP_HIT_SECONDS = 60           # an app needs a minute of focus in an hour to count (also: "you were around")
SITE_HIT_VISITS = 1            # a site needs one page visit in an hour to count

# ---------------------------------------------------------------------------
# How the model looks around a moment in time
# ---------------------------------------------------------------------------
HOUR_SIGMA = 1.0               # hours; a 9:30pm habit still counts ~60% at 8:30pm and fades to nothing by noon
RECENCY_HALF_LIFE_DAYS = 30    # a day this old counts half as much as today, so habits can change
PRIOR_STRENGTH = 16.0          # ranking: "observations" of broader habits mixed in; backtested against your history
PROFILE_PRIOR_STRENGTH = 4.0   # labels and bars just describe your history, so they lean on broader habits far less
FULL_EVIDENCE = 6.0            # days of data before an hour counts as one you're really around for

# ---------------------------------------------------------------------------
# Labels ("Usually 8-11 PM")
# ---------------------------------------------------------------------------
MIN_HITS_FOR_PATTERN = 3.0     # need this many (recency-weighted) uses before naming a usual time
ANYTIME_CONTRAST = 1.5         # peak must beat your average likelihood by this much, else "Anytime"
PEAK_WINDOW_FRACTION = 0.7     # hours within this fraction of the peak belong to the usual window
SECOND_PEAK_FRACTION = 0.75    # a second window (say, morning AND evening) must be this close to the first
MAX_WINDOW_HOURS = 6
LIFT_SHOW = 1.5                # show "2.1x usual" only when it is at least this much above normal
LEARNING_DAYS = 3              # days of app tracking before the apps list counts as "learned"

# ---------------------------------------------------------------------------
# Exclusions (same as dashboard.py, plus local dev servers)
# ---------------------------------------------------------------------------
EXCLUDED_KEYWORDS = ["chatgpt", "claude", "anthropic", "openai"]
EXCLUDED_DOMAIN_KEYWORDS = ["openai.com", "chatgpt.com", "claude.ai", "anthropic.com"]
SYSTEM_NOISE = {
    "explorer.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "lockapp.exe", "logonui.exe", "dwm.exe",
    "textinputhost.exe", "systemsettings.exe", "applicationframehost.exe",
    "searchapp.exe", "widgets.exe", "peopleexperiencehost.exe",
    "pickerhost.exe", "shellhost.exe",  # file-dialog and shell helpers, not apps you chose to use
}

# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(PACKAGE_DIR)  # the Dashboard folder, next to dashboard.py
DATA_FILE = os.path.join(BASE_DIR, "time_data.json")
ORIGINAL_DATA_FILE = os.path.join(BASE_DIR, "data.json")
PAGE_FILE = os.path.join(PACKAGE_DIR, "page.html")
