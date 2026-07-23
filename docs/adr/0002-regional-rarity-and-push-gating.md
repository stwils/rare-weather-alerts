# Rarity is judged regionally, and only Exceptional pushes

The first design computed a Rarity Threshold per (Spot, Phenomenon) at top 2% /
0.5%, and pushed whenever *any* Spot crossed. Because a dozen-plus Spots share
each Phenomenon and are weather-correlated but not identical, the "at least one
Spot crosses" rate is far higher than the per-Spot percentile: measured over the
10-year backfill, that produced ~2.7 pushes/week (fog fired ~55 days/year,
sunrise/sunset ~59) — well past the "rare should feel rare" bar the tool exists
to hold.

Two decisions fix it:

1. **Regional Rarity.** Thresholds are now percentiles of the *regional daily
   maximum* score (max across all Spots sharing a Phenomenon), so "top 2%" means
   top 2% of days a photographer actually experiences. Opportunities are still
   detected per Spot (the alert names the best one), but tiering compares to the
   regional threshold.

2. **Push gating.** Only Exceptional (regional top 0.5%) raises a live push
   (~0.2/week measured). Notable Opportunities surface on the Dashboard (pull)
   and in one daily Digest (push), never as their own interruption.

## Consequences

- `thresholds.json` gains a `_regional` block (used for tiering) alongside
  per-Spot percentiles (kept for the `status` view only).
- Requires a delivery surface for the Notable tier that isn't a push — hence the
  GitHub Pages Dashboard and the daily Digest were built alongside this change.
- Re-tuning a score model still just needs `rare-weather finish` (recompute from
  cached daily scores); the regional rollup happens there.
