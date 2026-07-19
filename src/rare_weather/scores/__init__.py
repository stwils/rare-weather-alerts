"""Quality Score models. Each module scores one Phenomenon, 0..1 per hour.

Contract per model module:
  ID, LABEL, EMOJI      identity
  SOURCE                backfill archive: "era5" | "forecast_archive"
  VARIABLES             Open-Meteo hourly variables it reads
  score_hours(h)        list of hourly scores; h maps variable -> list, plus
                        derived keys: "time" (epoch), "solar_elevation" (deg),
                        "local_hour" (0-23 in the configured timezone)
  explain(h, i)         one-line human explanation of hour i's score drivers
"""

from __future__ import annotations


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def tent(x: float, a: float, b: float, c: float, d: float) -> float:
    """0 below a, ramps to 1 over a..b, holds 1 over b..c, falls to 0 over c..d."""
    if x <= a or x >= d:
        return 0.0
    if x < b:
        return (x - a) / (b - a)
    if x <= c:
        return 1.0
    return (d - x) / (d - c)


def peak(x: float, ideal: float, width: float) -> float:
    """1.0 at ideal, falling linearly to 0 at ideal ± width. Unlike tent(),
    has no flat top — so days can't tie at the maximum, which would make
    top-percentile thresholds degenerate."""
    return clamp(1 - abs(x - ideal) / width)


def val(h: dict, key: str, i: int, default: float = 0.0) -> float:
    v = h[key][i]
    return default if v is None else float(v)


from . import fog, lenticular, storm_light, sunrise_sunset  # noqa: E402

MODELS = {m.ID: m for m in (fog, storm_light, sunrise_sunset, lenticular)}
