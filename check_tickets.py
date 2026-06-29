#!/usr/bin/env python3
"""
Monitor a Play LATAM tournament page for registration availability.

Sends a Discord notification when the tournament flips from SOLD OUT to OPEN.
Designed to run on a schedule (e.g. GitHub Actions cron).

The page is server-rendered, so the "sold out" notice is present in the raw
HTML. No headless browser is needed -- a plain HTTP GET is enough.
"""

import json
import os
import sys
from pathlib import Path

import requests

# --- Config -----------------------------------------------------------------
# /EN gives the English markers. Override via env var if you ever want ES/PT.
TOURNAMENT_URL = os.environ.get(
    "TOURNAMENT_URL", "https://playlatam.net/tournaments/ZOskOf/EN"
)
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
STATE_FILE = Path(os.environ.get("STATE_FILE", "state.json"))
REQUEST_TIMEOUT = 20

# Strings that mean "still sold out", across the site's three languages.
SOLD_OUT_MARKERS = (
    "Registrations for this tournament are sold out.",
    "Las inscripciones para este torneo se encuentran agotadas.",
    "As inscrições para este torneio estão esgotadas.",
)
# Confirms we actually loaded the tournament page (not an error page/redirect).
PAGE_ANCHOR = "Treasure Cup August 2026"

HEADERS = {
    # A real-browser UA avoids the Cloudflare 403 that bare clients can hit.
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_html() -> str:
    resp = requests.get(TOURNAMENT_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def classify(html: str) -> str:
    """Return 'available', 'sold_out', or 'unknown'."""
    if PAGE_ANCHOR not in html:
        return "unknown"  # page didn't load as expected -- don't trust it
    if any(marker in html for marker in SOLD_OUT_MARKERS):
        return "sold_out"
    return "available"


def load_previous_state() -> str:
    try:
        return json.loads(STATE_FILE.read_text())["status"]
    except Exception:
        return "sold_out"  # safe default: assume it was sold out before


def save_state(status: str) -> None:
    STATE_FILE.write_text(json.dumps({"status": status}, indent=2) + "\n")


def notify(message: str) -> None:
    if not DISCORD_WEBHOOK_URL:
        print("WARNING: DISCORD_WEBHOOK_URL not set -- skipping notification.")
        return
    r = requests.post(
        DISCORD_WEBHOOK_URL, json={"content": message}, timeout=REQUEST_TIMEOUT
    )
    r.raise_for_status()
    print("Discord notification sent.")


def main() -> int:
    try:
        html = fetch_html()
    except Exception as exc:
        print(f"ERROR fetching page: {exc}")
        return 0  # don't fail the workflow on a transient network hiccup

    status = classify(html)
    previous = load_previous_state()
    print(f"Previous: {previous} | Current: {status}")

    if status == "unknown":
        print("Page structure not recognized -- leaving state unchanged, no alert.")
        return 0

    # Only alert on the sold_out -> available transition (avoids spam).
    if status == "available" and previous != "available":
        notify(
            "\U0001F39F\uFE0F **Treasure Cup August 2026 - registration may be OPEN!**\n"
            f"{TOURNAMENT_URL}\n"
            "(The 'sold out' notice is gone. Grab it fast.)"
        )

    if status != previous:
        save_state(status)
        print(f"State updated: {previous} -> {status}")
    else:
        print("No change.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
