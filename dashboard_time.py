# Time-aware personal dashboard: the same idea as dashboard.py, but it learns WHEN you use things.
# At 9pm it shows what you usually reach for around 9pm; each card says when you usually use it.
#
#   python dashboard_time.py            start it and open the page
#   python dashboard_time.py --no-open  start it quietly (e.g. at login)
#
# It runs on its own port and its own data file (time_data.json), so it can run next to dashboard.py.
# Settings live in timeaware/config.py; the pieces are in the timeaware/ folder.
# Everything is local: binds to 127.0.0.1 only, no network calls.
import sys
import threading
import webbrowser

from timeaware import config, history, server, store, tracker


def main():
    no_open = "--no-open" in sys.argv
    url = "http://127.0.0.1:%d/" % config.PORT
    try:
        httpd = server.Server(("127.0.0.1", config.PORT), server.Handler)
    except OSError:
        # Another instance is already listening (e.g. started at login) - just open it.
        if not no_open:
            webbrowser.open(url)
        return

    store.load()
    threading.Thread(target=tracker.track_loop, daemon=True).start()
    threading.Thread(target=history.history_loop, daemon=True).start()

    if not no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    finally:
        store.save()


if __name__ == "__main__":
    main()
