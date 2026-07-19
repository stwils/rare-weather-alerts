"""Backfill: score history per (Spot, Phenomenon), then derive Rarity
Thresholds and the greatest-hits review report.

Sources (forecast/backfill symmetry, ADR 0001):
  era5              10 years — fog, sunrise_sunset
  forecast_archive  2021-04+ (has CAPE, 700 hPa) — storm_light, lenticular

Raw API responses are cached per (spot, source, chunk) so reruns and formula
iterations don't refetch.
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path

from . import hours, openmeteo, thresholds
from .config import Settings, load_settings, load_spots
from .scores import MODELS

CHUNK_YEARS = {"era5": 2, "forecast_archive": 2}
ARCHIVE_LAG_DAYS = 7


def _chunks(start: str, source: str) -> list[tuple[str, str]]:
    end = date.today() - timedelta(days=ARCHIVE_LAG_DAYS)
    cur = date.fromisoformat(start)
    out = []
    step = CHUNK_YEARS[source]
    while cur < end:
        nxt = min(date(cur.year + step, cur.month, cur.day) - timedelta(days=1), end)
        out.append((cur.isoformat(), nxt.isoformat()))
        cur = nxt + timedelta(days=1)
    return out


def _fetch_cached(cache_dir: Path, spot, source: str, variables: list[str], start: str, end: str, tz: str) -> dict:
    cache = cache_dir / f"{spot.id}_{source}_{start}_{end}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    raw = openmeteo.fetch_archive(source, spot.latitude, spot.longitude, variables, start, end, tz)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(raw))
    time.sleep(0.4)  # be polite to the free tier
    return raw


def run() -> None:
    cfg: Settings = load_settings()
    spots = load_spots()
    tz = cfg.timezone
    cache_dir = cfg.path("raw_cache")
    starts = {
        "era5": cfg.raw["backfill"]["era5_start"],
        "forecast_archive": cfg.raw["backfill"]["forecast_archive_start"],
    }

    daily: dict = {}  # {spot: {phen: {date: [score, explain]}}}
    for spot in spots:
        by_source: dict[str, list[str]] = {}
        for phen in spot.phenomena:
            m = MODELS[phen]
            by_source.setdefault(m.SOURCE, []).extend(m.VARIABLES)

        for source, variables in by_source.items():
            variables = sorted(set(variables))
            phens = [p for p in spot.phenomena if MODELS[p].SOURCE == source]
            for start, end in _chunks(starts[source], source):
                print(f"{spot.id}: {source} {start}..{end}")
                raw = _fetch_cached(cache_dir, spot, source, variables, start, end, tz)
                h = hours.prepare(raw, spot.latitude, spot.longitude, tz)
                for phen in phens:
                    m = MODELS[phen]
                    scores = m.score_hours(h)
                    days = daily.setdefault(spot.id, {}).setdefault(phen, {})
                    for i, s in enumerate(scores):
                        d = h["local_date"][i]
                        if d not in days or s > days[d][0]:
                            days[d] = [round(s, 4), m.explain(h, i) if s > 0.2 else ""]

    scores_path = cfg.path("daily_scores")
    scores_path.parent.mkdir(parents=True, exist_ok=True)
    scores_path.write_text(json.dumps(daily))
    print(f"wrote {scores_path}")

    finish(daily)


def finish(daily: dict | None = None) -> None:
    """Compute thresholds + greatest hits from (possibly cached) daily scores."""
    cfg = load_settings()
    if daily is None:
        daily = json.loads(cfg.path("daily_scores").read_text())
    thr = thresholds.compute(daily, cfg.tiers)
    thresholds.save(thr, cfg.path("thresholds"))
    print(f"wrote {cfg.path('thresholds')}")
    _greatest_hits(daily, thr, cfg)


def _greatest_hits(daily: dict, thr: dict, cfg: Settings) -> None:
    spots = {s.id: s for s in load_spots()}
    lines = [
        "# Greatest hits — backfill review",
        "",
        "Top-scored days per Phenomenon across all Spots. Review against memory:",
        "days you remember as epic that are missing (or low) are score-model bugs.",
        "",
    ]
    for phen, model in MODELS.items():
        best_by_date: dict[str, tuple[float, str, str]] = {}
        for spot_id, phens in daily.items():
            for d, (score, explain) in phens.get(phen, {}).items():
                if d not in best_by_date or score > best_by_date[d][0]:
                    best_by_date[d] = (score, spot_id, explain)
        top = sorted(best_by_date.items(), key=lambda kv: kv[1][0], reverse=True)[:20]
        lines += [f"## {model.EMOJI} {model.LABEL}", ""]
        if not top or top[0][1][0] == 0:
            lines += ["_No scored days — check the model or data source._", ""]
            continue
        lines += ["| Date | Best spot | Score | Tier | Drivers |", "|---|---|---|---|---|"]
        for d, (score, spot_id, explain) in top:
            t = thr.get(spot_id, {}).get(phen, {})
            tier = (
                "EXCEPTIONAL"
                if score >= t.get("exceptional", 9)
                else "Notable"
                if score >= t.get("notable", 9)
                else "—"
            )
            lines.append(f"| {d} | {spots[spot_id].name} | {score:.2f} | {tier} | {explain} |")
        lines.append("")
    out = cfg.path("greatest_hits")
    out.write_text("\n".join(lines))
    print(f"wrote {out}")
