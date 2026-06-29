# Treasure Cup ticket monitor

Pings the Play LATAM tournament page on a schedule and sends a Discord alert
when registration flips from **sold out** to **open**.

Target: https://playlatam.net/tournaments/ZOskOf/EN

## How it works

The page is server-rendered, so the sold-out notice
(`Registrations for this tournament are sold out.`) is in the raw HTML. The
script does a plain `requests.get()` — no headless browser needed.

Each run classifies the page as `sold_out`, `available`, or `unknown`, then:

- alerts **only** on the `sold_out -> available` transition (no repeat spam),
- treats an unrecognized page as `unknown` and stays silent (no false alarms
  if the site errors or changes layout),
- records the last known status in `state.json`, committed back to the repo so
  the next run knows what changed.

## Setup

1. Create a new GitHub repo and add these files (keep the paths):
   - `check_tickets.py`
   - `.github/workflows/monitor.yml`
   - `state.json`

2. Make a Discord webhook: Server Settings -> Integrations -> Webhooks ->
   New Webhook -> Copy Webhook URL.

3. In the repo: Settings -> Secrets and variables -> Actions -> New repository
   secret. Name it `DISCORD_WEBHOOK_URL`, paste the webhook URL.

4. Open the Actions tab and enable workflows if prompted. Use "Run workflow"
   on the monitor to confirm it works (check the logs and your Discord channel).

## Tuning

- **Interval**: edit the `cron` in `monitor.yml`. `*/5 * * * *` is every 5 min.
- **Language**: defaults to the `/EN` page. Override with a `TOURNAMENT_URL`
  env var if you want ES/PT (the script already recognizes all three sold-out
  strings).

## GitHub Actions caveats (worth knowing)

- 5 minutes is the **minimum** cron interval GitHub allows.
- Scheduled runs are **best-effort** — under load they get delayed (sometimes
  15+ min) or skipped entirely. Fine for a casual heads-up, not ideal for a
  hard ticket-drop race.
- Scheduled workflows **auto-disable after 60 days** with no repo activity.

If you want tighter, more reliable timing, the macOS `launchd` setup you used
for the Gen Con monitor (every 120s) would beat Actions here — same script,
just run locally with the two env vars set.
