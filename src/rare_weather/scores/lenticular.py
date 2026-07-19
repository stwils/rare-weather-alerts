"""Lenticular clouds — standing wave clouds over the Cascade volcanoes.

The shot: a stacked lens cloud capping the peak, in daylight, visible from
below. Needs strong cross-mountain flow near summit level (700 hPa ≈ 3 km),
moisture at that level (too dry: no cloud; saturated: overcast), and not much
low/mid cloud in the way.

Factors (multiplied):
  wave_wind  700 hPa wind ≥ ~30 km/h ramping to 60+
  moisture   700 hPa RH in the lens sweet spot
  view       low+mid cloud would hide the peak
  daylight   must be photographable

Known v1 limitations: wind direction vs terrain is ignored (westerly flow
dominates here), and stability is not checked. Backfill source is the
Historical Forecast API (2021+): ERA5 has no pressure-level variables.
"""

from __future__ import annotations

from . import clamp, peak, val

ID = "lenticular"
LABEL = "Lenticular"
EMOJI = "\N{CLOUD}️"
SOURCE = "forecast_archive"
VARIABLES = [
    "wind_speed_700hPa",
    "relative_humidity_700hPa",
    "cloud_cover_low",
    "cloud_cover_mid",
    "precipitation",
]


def _factors(h: dict, i: int) -> dict[str, float] | None:
    if h["solar_elevation"][i] <= 0:
        return None
    w700 = val(h, "wind_speed_700hPa", i)
    rh700 = val(h, "relative_humidity_700hPa", i)
    low = val(h, "cloud_cover_low", i)
    mid = val(h, "cloud_cover_mid", i)
    precip = val(h, "precipitation", i)
    return {
        "wave_wind": clamp((w700 - 30) / 50),  # 80+ km/h for full marks; no early plateau
        "moisture": peak(rh700, 67, 32),
        "view": clamp(1 - (0.6 * low + 0.5 * mid) / 100),
        "dry": 1.0 if precip < 1.0 else 0.3,
    }


def score_hours(h: dict) -> list[float]:
    out = []
    for i in range(len(h["time"])):
        f = _factors(h, i)
        if f is None:
            out.append(0.0)
            continue
        s = 1.0
        for v in f.values():
            s *= v
        out.append(s)
    return out


def explain(h: dict, i: int) -> str:
    return (
        f"700hPa wind {val(h, 'wind_speed_700hPa', i):.0f} km/h, "
        f"700hPa RH {val(h, 'relative_humidity_700hPa', i):.0f}%, "
        f"low/mid cloud {val(h, 'cloud_cover_low', i):.0f}/{val(h, 'cloud_cover_mid', i):.0f}%"
    )
