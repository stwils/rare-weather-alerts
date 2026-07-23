# Rare Weather Alerts

Alerts when weather within 2.5 hours of Portland, OR is unusually photogenic.
"Rare" means a phenomenon's Quality Score is in the top percentile of its
10-year history — judged *regionally*, across all spots at once — see
[CONTEXT.md](CONTEXT.md) for the domain language and [docs/adr/](docs/adr/) for why.

**Phenomena**: fog · dramatic storm light · extreme sunrise/sunset · lenticular clouds

**How you hear about it** (three surfaces, loudest to quietest):
- **Exceptional** (regional top 0.5%, ~1×/month) → immediate high-priority push (does not bypass Do Not Disturb).
- **Digest** → one morning push listing the day's board, only when something's on it.
- **Dashboard** → a GitHub Pages page you tap into anytime; every Notable+ opportunity, plus the full board. Alerts deep-link to the relevant card.

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
4. **Dry-run the live pass**: `rare-weather run --dry-run`, `rare-weather digest
   --dry-run`, and `rare-weather status` for a read-only table of current scores
   vs regional thresholds — the tuning tool.

## Commands

| Command | Does |
|---|---|
| `rare-weather run` | Fetch, score, rebuild the dashboard, push any Exceptional change. Hourly. |
| `rare-weather digest` | One push summarizing today's board; silent if empty. Once each morning. |
| `rare-weather status` | Console table of live scores vs thresholds. |
| `rare-weather backfill` / `finish` | Rebuild history → thresholds + greatest hits (`finish` reuses the cache). |

## Deploy

**GitHub Actions** (default): add `NTFY_TOPIC` (+ optional `PUSHOVER_TOKEN`,
`PUSHOVER_USER`) as repository secrets, and set the `DASHBOARD_URL` repository
variable to the Pages URL. [alerts.yml](.github/workflows/alerts.yml) runs
hourly (fetch, dashboard publish to Pages, Exceptional pushes, commits
`state/state.json`); [digest.yml](.github/workflows/digest.yml) sends the
morning digest. Pages must be enabled with **Source: GitHub Actions**.

**Docker (Mac or Synology)**: create a `.env` with the secrets, then
`docker compose up -d`. The daemon runs hourly and fires the digest once a day
at `RWA_DIGEST_HOUR` (local, default 6). State persists in `./state`; the
dashboard is written to `./site` (serve it however you like).

## Editing spots and thresholds

- Spots: [config/spots.yaml](config/spots.yaml) — add/remove freely; new
  Phenomena need a `rare-weather backfill` pass before they alert.
- Tier percentiles, floors, merge/coalesce gaps: [config/settings.yaml](config/settings.yaml).
- Tuning rule of thumb: more than ~2 pushes/week means the Exceptional bar is too low.
