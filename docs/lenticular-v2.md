# Lenticular model v2 — wind direction and stability

Plan, not a decision. When it's built, the decision goes in an ADR.

## Why

The v1 model scores four factors — 700 hPa wind speed, 700 hPa humidity, low/mid
cloud in the way, and dryness — and its own docstring names what it omits:
wind *direction* relative to terrain, and atmospheric *stability*. Both are
load-bearing physics, not refinements:

- **Stability is what makes the wave exist.** Mountain lee waves need a stable
  layer near summit level. Strong flow over Hood in a well-mixed, neutral
  airmass produces turbulence and ragged cumulus, not a lens. v1 cannot tell the
  two apart, so it happily scores a windy unstable day as a lenticular day.
- **Direction decides whether the flow is crossing the barrier at all.** v1
  treats 80 km/h as 80 km/h regardless of bearing, and assumes westerly flow
  because that dominates here. Southerly flow parallel to the Cascade crest
  makes a poor wave; v1 scores it identically.

Consequence: v1 is *noisy in both directions*. It over-rates windy unstable days
and under-rates days where the wave is well-formed but the wind speed is
moderate. This is the main argument for the threshold coming down a notch in the
meantime — the score's errors are symmetric, so a lower bar buys real days as
well as false ones.

## Data — verified available, symmetry holds

ADR 0001 requires that anything the live forecast uses, the backfill archive can
also serve. Probed both endpoints at Mt. Hood; all of these return on **both**
`api.open-meteo.com/v1/forecast` and
`historical-forecast-api.open-meteo.com/v1/forecast`:

```
wind_direction_700hPa   wind_direction_500hPa   wind_speed_500hPa
temperature_850hPa      temperature_700hPa      temperature_500hPa
geopotential_height_700hPa   lifted_index   boundary_layer_height
```

So v2 is buildable without changing data sources or shortening the 2021+ history.

## Proposed factors

Replacing `wave_wind` with three, keeping `moisture`, `view` and `dry`:

**1. Stability** — the missing precondition. Potential temperature
θ = T·(1000/p)^0.286 at 850, 700 and 500 hPa; stability is dθ/dp across the
summit-straddling layer. Score rises with increasing θ through the layer and
collapses toward neutral. `lifted_index` is a cheap cross-check (positive = stable)
and worth carrying in `explain()` even if it doesn't enter the score.

**2. Cross-barrier flow** — the component of the 700 hPa wind perpendicular to
the local barrier, rather than raw speed. The Cascade crest runs roughly N–S, so
the cross-barrier component is approximately the westerly component; a per-spot
`barrier_bearing` in spots.yaml keeps this honest and adjustable rather than
hard-coding "west is right".

**3. Directional coherence** — a standing wave needs the flow to hold its
bearing with height. Penalise large 700→500 hPa directional shear (beyond
~30–40°). This is cheap and discriminating, and it's the factor most likely to
kill v1's false positives.

**Deliberately out of scope for v2:** Froude number (U/Nh) is the physically
right framing and would need summit elevations and an effective obstacle height
per peak — worth it only once the three factors above are validated, or it
becomes impossible to attribute a change to any one cause.

## Two problems to fix alongside

**Viewpoints are tagged as lenticular spots.** `government-camp` and
`hood-river` both carry the `lenticular` tag, but neither is a mountain — they're
places you stand. CONTEXT.md's own definition says a Spot is the photographic
subject ("Mt. Hood for lenticulars") and that choosing a viewpoint is the
photographer's job. Scoring lenticular at Hood River samples the air over a town
in the Gorge, 50 km from the peak.

This isn't cosmetic. Today, Government Camp reads 0.57 while Mt. Hood reads 0.45
*for what would be the same physical cloud* — and the regional daily max, which
is what the thresholds are percentiles of, takes the higher one. Six lenticular
"spots" are really four mountains plus two near-duplicate columns, which inflates
the regional max and therefore the thresholds. Untagging both is the fix; it
changes the baseline, so it belongs in the same re-backfill as v2 rather than
being done separately.

**The raw cache ignores the variable list.** `_fetch_cached` keys on
`{spot}_{source}_{start}_{end}` only — nothing about which variables were
requested. Add a variable to a model and the cache silently returns the *old*
response without the new field, and scoring dies on a `KeyError` at `val()`.
A crash rather than silent corruption, but it will look mystifying. Fix first:
hash the sorted variable list into the cache filename. Otherwise the v2 backfill
requires manually purging `data/raw/*_forecast_archive_*`.

## Sequence

1. Fix the cache key (above) — it blocks everything else.
2. Untag `government-camp` and `hood-river` for lenticular.
3. Add the new variables to `VARIABLES`; write `explain()` output for them
   *before* scoring with them, so a backfill shows the raw numbers on known days.
4. Add the three factors one at a time, re-running `rare-weather backfill`
   between each and diffing the lenticular section of `greatest_hits.md`. One
   factor at a time or the effect of each is unattributable.
5. Check the ceiling: v1 has 3 backfilled days scoring exactly 1.00. More
   multiplied factors makes that less likely, but confirm rather than assume —
   a threshold that lands on a tie is the item 1 failure all over again.
6. Reconsider the tier override. It exists to compensate for a model known to be
   noisy; if v2 is sharper, the bar should go back up. That decision needs the
   verdict data from roadmap item 5, not a guess.

Cost: ~18 archive requests (6 spots × 3 chunks), a few minutes of scoring.

## How we'll know it worked

Not "the scores went up". The test is *discrimination*: the top-20 lenticular days
in `greatest_hits.md` should change composition, dropping windy-but-unstable days
and promoting days with moderate wind and a strong inversion. Without ground
truth (roadmap item 5) that judgement is still mine and yours reading a table —
which is precisely why the verdict loop matters more than any single model fix.
