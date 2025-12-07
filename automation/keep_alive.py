"""
Automation Helper: Keep Alive
Periodically refreshes the Saxo Bank access token to maintain the session.
Run this in a background session (e.g. tmux, screen, or systemd).
"""
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from data.scripts.saxo_auth import force_refresh

load_dotenv()

REFRESH_INTERVAL_MIN = 15


def main():
    print(f"[KeepAlive] Starting loop. Refresh every {REFRESH_INTERVAL_MIN} minutes.")

    while True:
        try:
            print(f"[KeepAlive] Refreshing token at {time.strftime('%Y-%m-%d %H:%M:%S')}...")
            force_refresh()
        except Exception as e:
            print(f"[KeepAlive] Error refreshing token: {e}")

        time.sleep(REFRESH_INTERVAL_MIN * 60)


if __name__ == "__main__":
    main()
