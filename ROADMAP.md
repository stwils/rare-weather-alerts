# Roadmap

Ordered by what most threatens the system's one job: telling the truth about
when it's worth driving somewhere. Each item states the evidence, not just the
idea. Domain terms are as defined in [CONTEXT.md](CONTEXT.md).

---

## Now — the system is currently mis-firing

### 1. Sunrise/sunset thresholds are degenerate

Measured over the 10-year backfill (regional daily-max, 14 spots, 3,664 days):

| Phenomenon | Notable (p98) | Exceptional (p99.5) | Days at exactly 1.00 |
|---|---|---|---|
| fog | 0.835 | 0.918 | 0 |
| lenticular | 0.814 | 0.940 | 3 (0.16%) |
| storm_light | 0.480 | 0.588 | 0 |
| **sunrise_sunset** | **0.994** | **1.000** | **71 (1.94%)** |

Two failures, both from the same cause:

- The Exceptional threshold is **1.0**, and 1.94% of days hit exactly 1.0 — so
  sunrise/sunset fires an Exceptional push on ~7 days/year instead of ~1.8, and
  every one of those days is *tied*, so the "best spot" picked for the push is
  arbitrary.
- The Notable band is 0.994–1.000. It is effectively empty: Notable and
  Exceptional are the same tier.

Root cause: `canvas = clamp(0.75 * peak(high, 45, 45) + 0.45 * peak(mid, 35, 40))`
in [sunrise_sunset.py:43](src/rare_weather/scores/sunrise_sunset.py:43) sums to a
max of 1.2 and then clamps — reintroducing exactly the flat top that `peak()` was
added to remove. The clamp is the bug; taking a regional max over 14 correlated
spots then guarantees *some* spot lands on the plateau most days.

Fix: make the factors multiplicative (or normalize the weights to sum to 1) so
1.0 requires every factor perfect, then re-run `rare-weather finish`. Item 6 is
the deeper fix — it adds a factor that actually discriminates.

### 2. One bad spot fetch kills the entire run

`_collect` in [pipeline.py:41](src/rare_weather/pipeline.py:41) loops 22 spots
with no error handling. Any spot that still fails after `_fetch`'s 5 retries
raises out of `run_once`, so the run publishes no dashboard, commits no state,
and sends nothing — because one of 22 requests failed. Catch per spot, score
what came back, and surface the gap on the dashboard.

### 3. Silent failure is indistinguishable from "nothing rare"

This project's failure mode is *quiet*, which is also what a calm week looks
like. If the hourly workflow breaks — API change, quota, malformed response —
nothing tells you. Worse, `digest` reads committed state and will cheerfully
report "nothing rare today" off a week-old file.

Add a staleness watchdog: if state is older than N hours, the digest says so
loudly and the dashboard shows a warning band instead of a stale board. Consider
a `failure` job on the workflow that pushes to ntfy.

### 4. The digest drifts an hour every winter

[digest.yml](.github/workflows/digest.yml) is `cron: "10 13 * * *"` — UTC, which
GitHub does not adjust for DST. That's 06:10 PDT in summer but 05:10 PST in
winter, i.e. it arrives before you'd want it for half the year. Fix by running
the workflow hourly and exiting unless the *local* hour matches (the Docker
daemon already does this via `RWA_DIGEST_HOUR`).

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
- **Remove `continue-on-error` from the three Pages steps** in
  [alerts.yml](.github/workflows/alerts.yml). It was scaffolding for before Pages
  was enabled; now it hides real deploy failures.
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
