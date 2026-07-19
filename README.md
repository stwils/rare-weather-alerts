# Rare Weather Alerts

Pushes an alert when weather within 2.5 hours of Portland, OR is unusually
photogenic. "Rare" means a phenomenon's Quality Score is in the top percentile
of its own 10-year history at that Spot — see [CONTEXT.md](CONTEXT.md) for the
domain language and [docs/adr/](docs/adr/) for why.

**Phenomena**: fog · dramatic storm light · extreme sunrise/sunset · lenticular clouds
**Tiers**: Notable (top 2% of days) → normal push · Exceptional (top 0.5%) → bypasses Do Not Disturb

## Setup

```sh
python3 -m venv .venv && .venv/bin/pip install -e .
```

1. **Backfill** (once, ~10 min; cached in `data/raw/`):
   `rare-weather backfill` — writes `data/thresholds.json` and
   `data/greatest_hits.md`.
2. **Review** `data/greatest_hits.md` against your memory. Days you remember
   as epic that score low are bugs in `src/rare_weather/scores/*` — tune,
   then `rare-weather finish` (recomputes from cache, no refetch).
3. **Channels**: install the [ntfy](https://ntfy.sh) app and subscribe to a
   hard-to-guess topic; buy/install Pushover and create an application token.

   ```sh
   export NTFY_TOPIC=...  PUSHOVER_TOKEN=...  PUSHOVER_USER=...
   rare-weather test-notify
   ```
4. **Dry-run the live pass**: `rare-weather run --dry-run`, and
   `rare-weather status` for a read-only table of current scores vs
   thresholds — the tuning tool.

## Deploy

**GitHub Actions** (default): push this repo to GitHub, add `NTFY_TOPIC`,
`PUSHOVER_TOKEN`, `PUSHOVER_USER` as repository secrets. The workflow in
[.github/workflows/alerts.yml](.github/workflows/alerts.yml) runs hourly and
commits `state/state.json` back to persist Opportunity lifecycles.

**Docker (Mac or Synology)**: create a `.env` with the three secrets, then
`docker compose up -d`. State persists in `./state`. On Synology, use
Container Manager with this compose file.

## Editing spots and thresholds

- Spots: [config/spots.yaml](config/spots.yaml) — add/remove freely; new
  (Spot, Phenomenon) pairs need a `rare-weather backfill` pass before they alert.
- Tier percentiles, floors, merge gaps: [config/settings.yaml](config/settings.yaml).
- Tuning rule of thumb: more than ~2 alerts/week means thresholds are too loose.
