# Roadmap

Ordered by what most threatens the system's one job: telling the truth about
when it's worth driving somewhere. Each item states the evidence, not just the
idea. Domain terms are as defined in [CONTEXT.md](CONTEXT.md).

---

## Now — the system is currently mis-firing

### 1. Sunrise/sunset thresholds are degenerate — **fixed**

*See [Shipped](#shipped) at the foot of this file. Item 6 remains the deeper
fix: it adds a factor that discriminates on more than local cloud amounts.*

### 2–4. Trustworthy silence — **fixed**

*One bad spot fetch killing the run; silent failure reading as "nothing rare";
the digest drifting an hour every winter. See [Shipped](#shipped).*

---

## Next — make the scores trustworthy

### 5. A ground-truth loop

Every model is currently unvalidated hand-tuned physics. `data/greatest_hits.md`
exists to be reviewed against memory and never has been, and there is no path
for *live* alerts to teach the system anything. Nothing closes the loop.

Smallest useful version: a verdict per past Opportunity — was it worth going? —
recorded from the Recent History section and kept in state. Even a dozen labels
would expose which factor is miscalibrated, and it converts every alert from a
cost into training signal.

### 6. Horizon probe for sunrise/sunset

The module's own docstring names the blind spot: a single-column forecast can't
see whether the horizon *in the sun's direction* is clear 100 km away, which is
what actually decides whether a sunset lights up. Sample a second point ~100 km
along the sun's azimuth and require its low cloud to be broken.

This is the highest-value model change available: it fixes the documented
false-positive source **and** supplies the discriminating factor that item 1
needs to break the ties.

### 6b. Lenticular v2: wind direction and stability — **built**

Shipped 2026-08-06; see [docs/lenticular-v2.md](docs/lenticular-v2.md) for the
calibration and the honest scorecard, including a hypothesis that the data
refuted (there is no population of unstable days here to filter out — the
Cascade free troposphere is stably stratified in ~100% of hours).

Still open, deliberately deferred: Froude number (needs per-peak effective
obstacle heights), and which side of the summit the lens sits on. The tier
override from 2026-07-25 remains in place — deciding whether v2 has earned it
back needs verdict data (item 5), not another guess.

### 7. Lead Time is defined but not implemented

CONTEXT.md makes Lead Time a property of each Phenomenon, and Travel Radius the
thing it's judged against — but nothing in the code knows either. Every
phenomenon gets a flat 3-day window. Alerting on day-3 fog implies a skill the
forecast doesn't have. Give each model a `LEAD_TIME_HOURS` and don't raise an
Alert beyond it (the Dashboard can still show the whole window).

### 8. Alerts carry no confidence

CONTEXT.md says a Forecast Alert "carries a probability"; it doesn't. Two cheap
sources: multi-model agreement (Open-Meteo's `models=` parameter across
ICON/GFS/ECMWF for the same hours), or run-to-run stability — we refresh hourly,
so "this window has held for 6 straight runs" is already derivable from state
and is the more honest signal for a photographer deciding whether to commit.

### 9. Thresholds are frozen

`data/thresholds.json` was computed once and never updates. Worse, the inputs
to regenerate it — `data/raw/` (82 MB) and `daily_scores.json` — are gitignored
and exist only on this Mac, so CI *cannot* recompute them and every model tweak
requires a local re-run. Schedule an incremental monthly refresh, and decide
where the daily-scores cache lives so it isn't a single-machine dependency.

Open question worth an ADR: thresholds are annual, so alerts naturally cluster
in each phenomenon's season. That's probably right (you want the best fog of the
year, not "unusual fog for July") — but it should be a decision on the record
rather than an accident.

---

## Then — more useful in the field

### 10. "Leave by" times

Travel Radius is nominally drive-time, but no Spot records one, so nothing
checks that a window is *reachable*. Add `drive_minutes` per spot and show
"leave by 05:40" on each card — the single most actionable number an alert can
carry, and the thing you'd otherwise compute by hand at 5am.

### 11. Longer planning horizon for Notable

`forecast_days: 3`. Open-Meteo serves 16. Exceptional should stay short-range
(that's where skill lives), but seeing a promising day 5 out is what lets you
keep an evening free.

### 12. Dashboard depth

The hourly curve behind each Opportunity (when it peaks, how long it holds),
actual sunrise/sunset clock times at the spot, and a small map. Today a card
gives a window and one line of drivers; deciding *when within the window* to be
standing there is left to you.

### 13. Wildfire smoke as a modifier

A PNW summer reality the system is blind to: smoke both ruins clarity and
produces lurid sunsets. Open-Meteo's Air Quality API has PM2.5 and AOD. Right
model is a modifier on existing scores, not a new Phenomenon.

### 14. Aurora nowcast

CONTEXT.md already defines Nowcast Alert and names aurora as the motivating case
— the only phenomenon whose Lead Time is too short to forecast. NOAA SWPC's Kp
feed plus the existing cloud-cover scoring is most of the work. Genuinely rare,
high payoff, and the domain language is already written.

---

## Housekeeping

- **Hourly state commits will reach ~9,000/year on `main`.** Already 40+ of 63
  commits are `chore: update opportunity state`, and they caused repeated push
  rejections during development. Move state to an orphan branch, an Actions
  cache, or fold it into the published Pages artifact.
- ~~**Remove `continue-on-error` from the three Pages steps.**~~ Done
  2026-08-06, alongside splitting publishing into its own job — see Shipped.
- **Tests cover only the Opportunity lifecycle, and nothing runs them in CI.**
  No coverage of score models, threshold math, dashboard rendering, or digest
  text. Add pytest + a CI workflow.
- **Batch the Open-Meteo calls.** 22 sequential requests per run where
  comma-separated coordinates would do it in one or two — faster, kinder to the
  free tier, and fewer independent failure points (see item 2).
- **Archive can double-count.** An Opportunity that is cancelled and later
  re-detected lands in Recent History twice; dedupe on `(spot, phenomenon, start)`.
- **Small cleanups**: dead `others = ""` in
  [dashboard.py:148](src/rare_weather/dashboard.py:148); `_fmt_window` duplicated
  between `dashboard.py` and `pipeline.py`.
- **Lenticular can still tie at the ceiling** — 3 backfilled days score exactly
  1.00, because `wave_wind`, `moisture`, `view` and `dry` can all hit their
  maxima at once on integer-valued inputs. Harmless today (0.16% is well under
  the 0.5% cutoff, so the threshold is a healthy 0.94), but it's the same latent
  shape as item 1 and would bite if the spot list grew. A continuous factor —
  as `twilight` now does for sunrise/sunset — would close it.
- **Nothing guards against a degenerate threshold.** Item 1 was invisible until
  measured by hand. `thresholds.compute` should warn when a tier threshold sits
  at the distribution maximum, or when the Notable→Exceptional band collapses.

---

## Shipped

### Publishing can no longer block alerting — 2026-08-06

Found by accident: two hourly runs sat in `pending`/`waiting` for six hours
while a GitHub Pages deployment hung in `waiting` (GitHub-side; even the cancel
API was returning 502s). The cause on our side was that `environment:
github-pages` was declared at *job* level, so the Pages deployment queue gated
the entire job — fetch, scoring, pushes and the state commit included, none of
which involve Pages.

Split into two jobs: `run` carries no environment and does all the alerting;
`deploy` holds the environment and publishes. `continue-on-error` came off the
Pages steps at the same time — it was masking failures, and now a deploy failure
is both visible and harmless to alerting. The deploy job uses
`cancel-in-progress: true`, so a hung deployment is superseded by the next hour
rather than accumulating a queue.

The staleness watchdog from items 2–4 would have caught this within six hours;
this makes the underlying coupling go away.

### Trustworthy silence (items 2–4) — 2026-07-24

The system is calibrated to be quiet — roughly eight Exceptional pushes a year —
so a dead pipeline and a calm month produce the identical experience. Three
changes so that silence can be believed:

**A failed fetch no longer costs the pass, or fakes a cancellation.** `_collect`
now catches per spot. The subtle half is that a missing Spot previously looked
to `reconcile` exactly like a vanished forecast, so a network blip would have
pushed a *false cancellation* — `partition_unknown` holds those Opportunities
untouched instead, while still letting elapsed ones expire so nothing lingers
behind a Spot that stays down. Above `max_spot_failure_fraction` (34%) the pass
aborts without touching state rather than publishing a hollowed-out board.

**The digest reports outages.** It reads `updated` from state and, past
`stale_after_hours` (6), sends "not updating — the hourly pass hasn't succeeded
in N hours" instead of a reassuring "nothing rare today". The dashboard judges
freshness client-side, since a static page is read long after it's written, and
raises the same warning band on open.

**The morning briefing stopped drifting.** Cron is UTC and never shifts for
daylight saving, so the single 13:10 entry meant 06:10 in summer and 05:10 in
winter. Two cron entries now bracket both, and `digest` gates on the *local*
hour (`digest_hour`), so exactly one fires year-round.

### Sunrise/sunset thresholds are degenerate (item 1) — 2026-07-24

`canvas` summed two weighted `peak()` terms to a maximum of 1.2 and clamped,
reintroducing the flat top `peak()` exists to remove. Taking the regional daily
max over 14 correlated spots then landed on that plateau on **71 of 3,664 days
(1.94%)** — so the Exceptional threshold computed to exactly 1.00, sunrise/sunset
pushed ~4x its intended rate, and the spot named in each push was chosen
arbitrarily among ties.

Two changes in [sunrise_sunset.py](src/rare_weather/scores/sunrise_sunset.py):
the canvas weights now sum to 1 instead of being clamped, and a new `twilight`
factor weights the score by how close the sun is to the horizon — faithful to
the phenomenon (colour is a civil-twilight event, not a golden-hour one) and
continuous in solar elevation, so scores cannot tie at the ceiling.

Regional daily-max distribution, before → after:

| | Notable | Exceptional | Tier band | Days tied at max | Exceptional rate |
|---|---|---|---|---|---|
| before | 0.9942 | **1.0000** | 0.006 | 71 (1.94%) | 1.94% — ~7/yr |
| after | 0.6866 | 0.8086 | 0.122 | 1 | 0.52% — **1.9/yr** |

The other three phenomena are unchanged. Top-scoring days now sit at solar
elevation −1° to −2.5° with high cloud 40–50% and clear low cloud, spread across
seasons and spots.
