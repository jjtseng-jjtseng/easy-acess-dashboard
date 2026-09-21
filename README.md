# Dashboard

A personal, local-only dashboard for the apps and sites you use most. Windows, Python 3, standard library only.
Everything binds to `127.0.0.1`; nothing leaves your machine.

There are two versions. They can run at the same time.

| | `dashboard.py` | `dashboard_time.py` |
|---|---|---|
| Shows | Your all-time top apps and sites | What you usually use *around this time of day* |
| Address | http://127.0.0.1:47821/ | http://127.0.0.1:47822/ |
| Data file | `data.json` | `time_data.json` |
| Starts at login | Yes (Startup shortcut) | No |

## Run

```
python dashboard_time.py             # start and open the page
pythonw dashboard_time.py --no-open  # start quietly in the background
```

Starting it a second time just exits if it's already running.

## Windows release

GitHub Releases provides a Windows x64 ZIP named Dashboard-Time-win-x64-vX.Y.Z.zip. Extract the complete
Dashboard-Time folder and run Dashboard-Time.exe; the _internal folder beside it is required.

The release does not include your activity history. A packaged copy keeps its own private data at
%LOCALAPPDATA%\Dashboard-Time\time_data.json, so it survives app upgrades without being committed to GitHub.
Each release also includes a .sha256 checksum file for the ZIP.

## The time-aware version

Each card says when you usually use it (`Usually 8–11 PM`, `Anytime`), the chance you'll use it around now, a
`▲ 2.1× usual` badge when now is busier than normal for it, and a 24-hour strip with the current hour highlighted.
The hour buttons and day picker at the top let you preview any time ("what about Saturday at 3 PM?").

- **Sites** are read from the last 45 days of Chrome/Edge (Default profile) history, using each visit's timestamp,
  so they're time-aware from the first run. When a site has a favicon in that same local browser cache, the page
  uses it; it never downloads an icon from the internet.
- **Apps** have no history to read, so they're tracked while focused (paused after 5 minutes idle) starting from
  the first run. Until about 3 days are collected they're ordered by overall use.
- Weekdays and weekends are learned separately; recent days count more than old ones.
- Claude and ChatGPT are excluded, as in the original.

## Files

- `dashboard_time.py` - entry point
- `timeaware/` - the parts: `config.py` (all settings), `tracker.py` and `winapi.py` (app tracking),
  `history.py` (browser history), `model.py` and `usual.py` (the time-of-day maths and labels),
  `snapshot.py`, `server.py`, `web/` (the served page, styles, and controls), `store.py` (saving)

## Tips

- Change ports, exclusions, history window, etc. in `timeaware/config.py`.
- To make apps start learning from scratch, stop it and delete `time_data.json`.
- Known quirk: launching `dashboard.py` twice on Windows leaves two copies serving the same port. The time-aware
  version guards against this; the original doesn't yet.
