"""Derive per-hour helper series (solar elevation, local time) for score models."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .solar import solar_elevation_deg


def prepare(hourly: dict, lat: float, lon: float, tz: str) -> dict:
    h = dict(hourly)
    zi = ZoneInfo(tz)
    times = h["time"]
    h["solar_elevation"] = [solar_elevation_deg(lat, lon, t) for t in times]
    locals_ = [datetime.fromtimestamp(t, zi) for t in times]
    h["local_hour"] = [d.hour for d in locals_]
    h["local_date"] = [d.date().isoformat() for d in locals_]
    return h
