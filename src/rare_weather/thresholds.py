"""Rarity Thresholds.

Rarity is judged *regionally*, not per-spot: for each Phenomenon we take the
daily maximum score across every applicable Spot, and the thresholds are
percentiles of that regional-max distribution. This fixes the volume problem
where per-spot top-2% thresholds, fired whenever *any* of a dozen correlated
spots crossed, produced a far-higher-than-2% felt rate (see ADR 0002).

Tier percentiles are global, with optional per-Phenomenon overrides
(`tier_overrides` in settings.yaml) — see `tier_params`.

Output shape:
  {
    "_regional": {phenomenon: {notable, exceptional, raw_notable, raw_exceptional,
                               percentiles, n_days}},
    "_by_spot":  {spot: {phenomenon: {p98, p995, n_days}}}   # display only
  }
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


def quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 1.0
    idx = min(len(sorted_values) - 1, max(0, round(q * (len(sorted_values) - 1))))
    return sorted_values[idx]


def tier_params(tiers: dict, overrides: dict | None, phenomenon: str, tier: str) -> dict:
    """Tier settings for one Phenomenon: the global tier, with any per-Phenomenon
    override merged over it. Overrides exist because the tiers are a statement
    about how often you want to be interrupted, and that answer isn't the same
    for every Phenomenon — a rarer, more reliable one earns a lower bar."""
    return {**tiers[tier], **(overrides or {}).get(phenomenon, {}).get(tier, {})}


def compute(daily_scores: dict, tiers: dict, overrides: dict | None = None) -> dict:
    """daily_scores: {spot_id: {phenomenon: {date: [score, explain]}}}"""
    # Regional daily-max per phenomenon.
    regional_days: dict[str, dict[str, float]] = defaultdict(dict)
    for phens in daily_scores.values():
        for phen, days in phens.items():
            dst = regional_days[phen]
            for d, (score, _) in days.items():
                s = float(score)
                if d not in dst or s > dst[d]:
                    dst[d] = s

    regional: dict[str, dict] = {}
    for phen, days in regional_days.items():
        values = sorted(days.values())
        n = tier_params(tiers, overrides, phen, "notable")
        e = tier_params(tiers, overrides, phen, "exceptional")
        q_n, q_e = quantile(values, n["percentile"]), quantile(values, e["percentile"])
        regional[phen] = {
            "notable": max(q_n, n["floor"]),
            "exceptional": max(q_e, e["floor"]),
            "raw_notable": q_n,
            "raw_exceptional": q_e,
            "percentiles": [n["percentile"], e["percentile"]],
            "n_days": len(values),
        }

    by_spot: dict = {}
    for spot_id, phens in daily_scores.items():
        for phen, days in phens.items():
            values = sorted(float(v[0]) for v in days.values())
            by_spot.setdefault(spot_id, {})[phen] = {
                "p98": quantile(values, tiers["notable"]["percentile"]),
                "p995": quantile(values, tiers["exceptional"]["percentile"]),
                "n_days": len(values),
            }

    return {"_regional": regional, "_by_spot": by_spot}


def regional_for(thresholds: dict, phenomenon: str) -> dict | None:
    return thresholds.get("_regional", {}).get(phenomenon)


def save(thresholds: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(thresholds, indent=1, sort_keys=True))


def load(path: Path) -> dict:
    return json.loads(path.read_text())
