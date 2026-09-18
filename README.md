# Rare Weather Alerts

Alerts when weather within 2.5 hours of Portland, OR is unusually photogenic.
"Rare" means a phenomenon's Quality Score is in the top percentile of its
10-year history — judged *regionally*, across all spots at once — see
[CONTEXT.md](CONTEXT.md) for the domain language, [docs/adr/](docs/adr/) for why,
and [ROADMAP.md](ROADMAP.md) for what's known-wrong and what's next.

**Phenomena**: fog · dramatic storm light · extreme sunrise/sunset · lenticular clouds

**How you hear about it** (three surfaces, loudest to quietest):
- **Exceptional** (regional top 0.5%, ~1×/month) → immediate high-priority push (does not bypass Do Not Disturb).
- **Digest** → one morning push listing the day's board ("nothing rare today" when empty), sent by the first alert pass after 06:00. A separate **watchdog** pushes "not updating" if the pipeline goes stale — so silence always means something definite.
- **Dashboard** → a GitHub Pages page you tap into anytime; every Notable+ opportunity, the full board, and a 72h history of past opportunities (cancelled / ended). Alerts deep-link to the relevant card.

## Setup

```sh
python3 -m venv .venv && .venv/bin/pip install -e .
```

1. **Backfill** (once, ~10 min; cached in `data/raw/`):
   `rare-weather backfill` — writes `data/thresholds.json` and
   `data/greatest_hits.md`.
2. **Review** `data/greatest_hits.md` against your memory. Days you remember
   as epic that score low are bugs in `src/rare_weather/scores/*` — tune, then
   re-run `rare-weather backfill`: it re-scores 10 years out of the `data/raw/`
   cache, so it's fast and fetches only days added since the last pass.
   (`rare-weather finish` is the weaker move — it recomputes thresholds from
   *already-scored* days, so it won't pick up a model change.)
3. **Channels**: install the [ntfy](https://ntfy.sh) app and subscribe to a
   hard-to-guess topic; buy/install Pushover and create an application token.

   ```sh
   export NTFY_TOPIC=...  PUSHOVER_TOKEN=...  PUSHOVER_USER=...
   rare-weather test-notify
   ```
4. **Dry-run the live pass**: `rare-weather run --dry-run`, `rare-weather digest
   --dry-run`, `rare-weather watchdog --dry-run`, and `rare-weather status` for
   a read-only table of current scores vs regional thresholds — the tuning tool.

## Commands

| Command | Does |
|---|---|
| `rare-weather run` | Fetch, score, rebuild the dashboard, push any Exceptional change — and send the morning digest if it's due. Hourly. |
| `rare-weather digest` | Send today's board now, from committed state (an outage notice instead, if that state is stale). |
| `rare-weather watchdog` | Push an outage notice only if state is stale; silent otherwise. |
| `rare-weather status` | Console table of live scores vs thresholds. |
| `rare-weather backfill` | Re-score 10 years from the `data/raw/` cache → thresholds + greatest hits. Run after any score-model change. |
| `rare-weather finish` | Recompute thresholds from already-scored days. Only for changing tier percentiles/floors. |

## Deploy

**GitHub Actions** (default): add `NTFY_TOPIC` (+ optional `PUSHOVER_TOKEN`,
`PUSHOVER_USER`) as repository secrets, and set the `DASHBOARD_URL` repository
variable to the Pages URL. [alerts.yml](.github/workflows/alerts.yml) runs
hourly (fetch, Exceptional pushes, the morning digest, commits
`state/state.json`, then publishes the dashboard in a separate job);
[watchdog.yml](.github/workflows/watchdog.yml) twice a day pushes only if state
has gone stale; [digest.yml](.github/workflows/digest.yml) is a manual "send me
the board now" button. Pages must be enabled with **Source: GitHub Actions**.

GitHub runs scheduled workflows late and sparsely — in practice the "hourly"
cron fires ~6×/day with gaps up to ~13h. Nothing here depends on punctuality,
but if you want true hourly cadence, the Docker option below provides it.

**Docker (Mac or Synology)**: create a `.env` with the secrets, then
`docker compose up -d`. The daemon runs hourly; the first pass after
`digest_hour` (local, default 6) sends the digest. There's no watchdog in this
mode — a daemon can't report its own death — so glance at the dashboard's
"updated" line now and then. State persists in `./state`; the
dashboard is written to `./site` (serve it however you like).

## Editing spots and thresholds

- Spots: [config/spots.yaml](config/spots.yaml) — add/remove freely; new
  Phenomena need a `rare-weather backfill` pass before they alert.
- Tier percentiles, floors, merge/coalesce gaps: [config/settings.yaml](config/settings.yaml).
  `tier_overrides` lowers or raises the bar for one phenomenon — the tiers say
  how often you want interrupting, and that isn't the same answer for each.
  Changing percentiles only needs `rare-weather finish`, not a full backfill.
- Health knobs, same file: `digest_hour` (local; the first pass on or after it
  sends the digest), `stale_after_hours` (default 18 — when a quiet board starts
  being reported as an outage; keep it above GitHub's longest normal gap), and
  `max_spot_failure_fraction` (how many spots may fail before a pass aborts
  rather than publishing a partial board).
- Tuning rule of thumb: more than ~2 pushes/week means the Exceptional bar is too low.
