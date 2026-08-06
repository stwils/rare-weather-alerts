"""Derive per-hour helper series (solar elevation, local time) for score models."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .solar import solar_elevation_deg


def prepare(
    hourly: dict, lat: float, lon: float, tz: str, barrier_bearing: float = 270.0
) -> dict:
    """Hourly series plus derived helpers. Most values are per-hour lists;
    `barrier_bearing` is a per-Spot scalar carried alongside them so terrain-aware
    models can read it without threading the Spot through the score contract."""
    h = dict(hourly)
    zi = ZoneInfo(tz)
    times = h["time"]
    h["solar_elevation"] = [solar_elevation_deg(lat, lon, t) for t in times]
    locals_ = [datetime.fromtimestamp(t, zi) for t in times]
    h["local_hour"] = [d.hour for d in locals_]
    h["local_date"] = [d.date().isoformat() for d in locals_]
    h["barrier_bearing"] = float(barrier_bearing)
    return h
