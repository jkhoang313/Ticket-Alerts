#!/usr/bin/env python3
"""
gencon_monitor.py
-----------------
Watches a Gen Con event-catalog search and alerts you when any matching event
flips from SOLD OUT -> available (or a brand-new available event appears).

The catalog page is JavaScript-rendered, so we drive a real (headless) browser
with Playwright instead of fetching HTML directly.

SETUP
-----
    pip install playwright
    playwright install chromium

RUN
---
    # First run: see what the scraper actually found and confirm selectors work
    python gencon_monitor.py --debug

    # Normal run (do this on a schedule, e.g. every 2-3 min via cron/launchd):
    python gencon_monitor.py

NOTIFICATIONS
-------------
Default notifier is ntfy.sh -- zero account needed:
  1. Install the "ntfy" app on your phone (iOS/Android).
  2. Subscribe to a hard-to-guess topic, e.g. "jackson-optcg-9f3k2".
  3. Set NTFY_TOPIC below to the same string.
Pushover and Discord alternatives are stubbed in send_notification().
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

# ----------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------
CATALOG_URL = (
    "https://www.gencon.com/event-catalog"
    "?search=one+piece+card+game&host=Bandai+Japan"
)

STATE_FILE = Path(__file__).with_name("gencon_state.json")

# How we detect a sold-out event. Gen Con puts the class "event_row_sold_out"
# on the row element when it's sold out, so we match that exact token in the
# row's outerHTML -- precise, no keyword guessing.
SOLD_OUT_MARKERS = ["event_row_sold_out"]

# Notifier config is read from environment variables (set these as GitHub
# repo secrets for the Actions workflow). For a quick local test you can also
# just hardcode the fallback strings on the right.

# --- ntfy (default) ---
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")   # e.g. "jackson-optcg-9f3k2"
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")

# --- Pushover (optional) ---
PUSHOVER_TOKEN = os.environ.get("PUSHOVER_TOKEN", "")   # app token
PUSHOVER_USER = os.environ.get("PUSHOVER_USER", "")     # user key

# --- Discord (optional) ---
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")  # webhook URL

# Be a polite single user, not a scraper farm.
PAGE_TIMEOUT_MS = 30_000


# ----------------------------------------------------------------------------
# SCRAPE
# ----------------------------------------------------------------------------
def fetch_events(debug: bool = False):
    """Return list of dicts: {key, title, when, sold_out}."""
    events = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        )
        page.set_default_timeout(PAGE_TIMEOUT_MS)
        page.goto(CATALOG_URL, wait_until="networkidle")

        # Give the catalog JS a moment to populate rows.
        page.wait_for_timeout(2500)

        # ---------------------------------------------------------------
        # SELECTOR -- THIS IS THE ONE LINE YOU MAY NEED TO TWEAK.
        # Open the live page in Chrome, right-click an event row ->
        # Inspect, and find the element that wraps ONE event (title +
        # time + price + the SOLD OUT overlay). Put its selector here.
        # Common candidates: ".event", ".event-row", "[class*='event']",
        # "article", "li[role='listitem']".
        # ---------------------------------------------------------------
        ROW_SELECTOR = "[class*='event']"

        rows = page.locator(ROW_SELECTOR)
        count = rows.count()

        if debug:
            print(f"[debug] matched {count} elements for selector "
                  f"{ROW_SELECTOR!r}")

        dumped = 0
        for i in range(count):
            row = rows.nth(i)
            try:
                text = (row.inner_text() or "").strip()
                # outerHTML includes the row element's OWN tag/class, where
                # "event_row_sold_out" lives -- inner_html would miss it.
                html = row.evaluate("el => el.outerHTML") or ""
            except Exception:
                continue
            if "one piece card game" not in text.lower():
                continue

            # Ignore "Side Event" listings -- only want the others (e.g. Treasure Cup).
            if "side event" in text.lower():
                continue

            # Detect sold-out from the exact class Gen Con stamps on sold-out
            # rows. We scan the row's outerHTML; with the sold-out-wins de-dup
            # below, it's enough for any matched copy (the row or a parent) to
            # carry the class.
            blob = html.lower()
            sold_out = any(m in blob for m in SOLD_OUT_MARKERS)

            # On --debug, dump the HTML of the first couple of matched events
            # so you can see EXACTLY how sold-out is encoded and tighten the
            # detector if needed.
            if debug and dumped < 2:
                print("\n[debug] ----- sample event HTML -----")
                print(html[:1500])
                print("[debug] -------------------------------\n")
                dumped += 1

            # Collapse the row text into a stable identity key. We use the
            # first ~3 non-empty lines (title + system + day/time), which
            # uniquely identifies a session regardless of price/duration.
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            # Drop any visible "SOLD OUT" line so the key is IDENTICAL whether
            # the event is sold out or available -- otherwise the diff can't
            # match the two states of the same event.
            lines = [ln for ln in lines
                     if "sold out" not in ln.lower()
                     and "soldout" not in ln.lower()]
            title = lines[0] if lines else "Unknown event"
            when = " | ".join(lines[1:4])
            key = (title + " | " + when).strip()

            events.append({
                "key": key,
                "title": title,
                "when": when,
                "sold_out": sold_out,
            })

        browser.close()

    # De-dupe by key (the [class*='event'] selector can match nested nodes).
    # Sold-out WINS: if any matched copy of this event shows the sold-out
    # marker, the event is sold out. This prevents a nested child node that
    # didn't capture the overlay from flipping a sold-out event to available.
    deduped = {}
    for e in events:
        if e["key"] in deduped:
            deduped[e["key"]]["sold_out"] |= e["sold_out"]
        else:
            deduped[e["key"]] = e

    result = list(deduped.values())
    if debug:
        print(f"[debug] {len(result)} unique One Piece events:")
        for e in result:
            flag = "SOLD OUT" if e["sold_out"] else "AVAILABLE"
            print(f"   [{flag}] {e['key']}")
    return result


# ----------------------------------------------------------------------------
# STATE
# ----------------------------------------------------------------------------
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ----------------------------------------------------------------------------
# NOTIFY
# ----------------------------------------------------------------------------
def send_notification(title: str, message: str):
    sent = False

    if NTFY_TOPIC:
        req = urllib.request.Request(
            f"{NTFY_SERVER}/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": "high",
                "Tags": "tada",
                "Click": CATALOG_URL,
            },
        )
        try:
            urllib.request.urlopen(req, timeout=10)
            sent = True
        except Exception as exc:
            print(f"[warn] ntfy failed: {exc}", file=sys.stderr)

    if PUSHOVER_TOKEN and PUSHOVER_USER:
        data = urllib.parse.urlencode({
            "token": PUSHOVER_TOKEN, "user": PUSHOVER_USER,
            "title": title, "message": message,
            "url": CATALOG_URL, "priority": 1,
        }).encode()
        try:
            urllib.request.urlopen(
                "https://api.pushover.net/1/messages.json", data=data, timeout=10)
            sent = True
        except Exception as exc:
            print(f"[warn] pushover failed: {exc}", file=sys.stderr)

    if DISCORD_WEBHOOK:
        data = json.dumps({"content": f"**{title}**\n{message}\n{CATALOG_URL}"}).encode()
        req = urllib.request.Request(
            DISCORD_WEBHOOK, data=data,
            headers={
                "Content-Type": "application/json",
                # Discord (behind Cloudflare) 403s the default Python-urllib
                # user agent, so set an explicit one.
                "User-Agent": "gencon-monitor/1.0 (+https://github.com)",
            })
        try:
            urllib.request.urlopen(req, timeout=10)
            sent = True
        except Exception as exc:
            print(f"[warn] discord failed: {exc}", file=sys.stderr)

    if not sent:
        print(f"[NOTIFY] {title}: {message}")  # fallback to stdout


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true",
                        help="print what was scraped, don't notify")
    args = parser.parse_args()

    events = fetch_events(debug=args.debug)
    if args.debug:
        return

    if not events:
        print("[warn] found 0 One Piece events -- selector may need fixing. "
              "Run with --debug.", file=sys.stderr)
        return

    prev = load_state()
    new_state = {}
    newly_available = []

    for e in events:
        new_state[e["key"]] = {"sold_out": e["sold_out"],
                               "title": e["title"], "when": e["when"]}
        was = prev.get(e["key"])
        # Transition: previously sold out (or never seen) -> now available
        if not e["sold_out"]:
            if was is None or was.get("sold_out") is True:
                newly_available.append(e)

    if newly_available:
        lines = [f"{e['title']} — {e['when']}" for e in newly_available]
        send_notification(
            title=f"🎴 {len(newly_available)} OPTCG event(s) available!",
            message="\n".join(lines),
        )

    save_state(new_state)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] checked {len(events)} events, "
          f"{len(newly_available)} newly available.")


if __name__ == "__main__":
    main()