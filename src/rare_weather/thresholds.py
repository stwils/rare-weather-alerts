"""Rarity Thresholds: percentiles of the daily-max Quality Score distribution
per (Spot, Phenomenon), computed from the backfill. Tier floors (settings.yaml)
keep spots where a phenomenon ~never occurs from alerting on noise."""

from __future__ import annotations

import json
from pathlib import Path


def quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 1.0
    idx = min(len(sorted_values) - 1, max(0, round(q * (len(sorted_values) - 1))))
    return sorted_values[idx]


def compute(daily_scores: dict, tiers: dict) -> dict:
    """daily_scores: {spot_id: {phenomenon: {date: [score, explain]}}}"""
    out: dict = {}
    for spot_id, phens in daily_scores.items():
        for phen, days in phens.items():
            values = sorted(float(v[0]) for v in days.values())
            entry = {
                "n_days": len(values),
                "notable": max(quantile(values, tiers["notable"]["percentile"]), tiers["notable"]["floor"]),
                "exceptional": max(
                    quantile(values, tiers["exceptional"]["percentile"]), tiers["exceptional"]["floor"]
                ),
                "raw_p98": quantile(values, tiers["notable"]["percentile"]),
                "raw_p995": quantile(values, tiers["exceptional"]["percentile"]),
            }
            out.setdefault(spot_id, {})[phen] = entry
    return out


def save(thresholds: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(thresholds, indent=1, sort_keys=True))


def load(path: Path) -> dict:
    return json.loads(path.read_text())
