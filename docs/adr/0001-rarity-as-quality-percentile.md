# Rarity is a percentile on photographic quality, not a category of weather

The project is named "rare-weather-alerts", but the launch phenomena (fog, dramatic storm light, extreme sunrise/sunset, lenticular clouds) are mostly not rare weather — sunsets happen daily, and fog is common near the coast. What the user actually wants alerts for is *photographic quality that occasionally spikes*. We therefore decided: every Phenomenon gets a Quality Score, and an Opportunity exists when that score crosses a percentile threshold of its own historical distribution at that Spot (Notable = top 2% of days, Exceptional = top 0.5%). This replaces the earlier category model ("locally rare condition" vs "intrinsically rare phenomenon") because it unifies all phenomena under one mechanism, makes "rare" precise and tunable, and automatically calibrates per location (coastal fog needs a higher bar than desert fog).

## Consequences

- Each phenomenon needs a quality *model*, not just a detector.
- Percentiles require a real distribution, so a ~10-year historical backfill (Open-Meteo ERA5 archive) per (Spot, Phenomenon) is a prerequisite for honest thresholds — chosen over hand-tuned absolute thresholds and over self-calibration from live scores (cold start of a season or more).
