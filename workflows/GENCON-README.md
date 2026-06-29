# Gen Con OPTCG availability monitor

Watches the Gen Con event catalog for One Piece Card Game (Bandai Japan) events
and pushes a phone notification when one flips from **SOLD OUT** to **available**.
Side Events are ignored. Runs hands-off on GitHub Actions.

## One-time setup

### 1. Discord notifications (via a channel webhook)
1. In Discord, pick (or make) a server and channel for the alerts.
2. Channel name → **Edit Channel → Integrations → Webhooks → New Webhook**.
3. Name it (e.g. "Gen Con bot"), then **Copy Webhook URL**. It looks like
   `https://discord.com/api/webhooks/<id>/<token>`.

Treat that URL like a password — anyone with it can post to your channel.

### 2. Create the repo
1. Make a new GitHub repo (private is fine and recommended).
2. Add these two files:
   - `gencon_monitor.py` at the repo root.
   - `.github/workflows/gencon-monitor.yml` (this is the `gencon-monitor.yml`
     file — create the folders and drop it in there).

### 3. Add your webhook as a secret
Repo → **Settings → Secrets and variables → Actions → New repository secret**:
- Name: `DISCORD_WEBHOOK`
- Value: the webhook URL you copied above

(If you also want phone push, add `NTFY_TOPIC` and uncomment its line in the
workflow's `env:` block — both channels can fire at once.)

### 4. Turn it on
- Push the files. The workflow runs on a schedule (~every 5–10 min in practice).
- Go to the **Actions** tab and click **Run workflow** once to test it now.
- Check the run log: it should report how many events it checked. The first
  run records the current state and won't alert; later runs alert on changes.

## Verifying the scraper works
GitHub runs headless, so you can't watch it. To sanity-check the selector,
run locally once:

```bash
pip install playwright
playwright install chromium
python gencon_monitor.py --debug
```

This prints each One Piece event with a `SOLD OUT` / `AVAILABLE` flag. If it
prints 0 events or junk, open the live catalog page in Chrome, inspect one
event row, and paste its wrapper selector into the `ROW_SELECTOR` line in
`gencon_monitor.py`. That's the only line likely to need adjusting.

## Notes
- **Cadence:** `*/5` is GitHub's practical floor and start times drift, so
  expect every 5–10 min. For faster (every 2 min) you'd run it locally via
  cron/launchd instead.
- **State:** `gencon_state.json` is cached between runs so you only get pinged
  on a real sold-out → available transition, not every run.
- **Politeness:** one scheduled hit every few minutes is a normal single-user
  load. Don't crank the cron way down.
