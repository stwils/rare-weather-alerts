"""Extreme sunrise/sunset — a colorful sky at civil twilight.

The shot: mid/high clouds acting as a canvas for under-lighting, with enough
of a clear gap that low sun can reach them. Scored only when the sun is within
a few degrees of the horizon.

Factors (multiplied):
  canvas     mid/high cloud in the sweet range — some cloud to light, not overcast
  low_clear  low cloud blocks both the sun path and the view
  twilight   how close the sun is to the horizon; colour lives near elevation 0
  dry        active precipitation at the spot ruins the window

Known v1 limitation: a single-column forecast can't see whether the horizon in
the sun's direction is clear 100 km away; expect some false positives when a
cloud deck sits just offshore/upwind.
"""

from __future__ import annotations

from . import clamp, peak, val

ID = "sunrise_sunset"
LABEL = "Sunrise/Sunset"
EMOJI = "\N{SUNSET OVER BUILDINGS}"
SOURCE = "era5"
VARIABLES = [
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "precipitation",
]


def _factors(h: dict, i: int) -> dict[str, float] | None:
    elev = h["solar_elevation"][i]
    if not (-7 <= elev <= 7):
        return None
    low = val(h, "cloud_cover_low", i)
    mid = val(h, "cloud_cover_mid", i)
    high = val(h, "cloud_cover_high", i)
    precip = val(h, "precipitation", i)
    # Peaked, not plateaued: a perfect canvas needs BOTH high cloud near 45%
    # and mid cloud near 35% — saturating one factor alone can't reach 1.0,
    # so the daily-score distribution stays continuous at the top.
    #
    # The weights sum to 1 rather than being clamped from 1.2. A clamp puts
    # back the flat top peak() exists to remove: taking the regional daily max
    # over 14 spots then landed on that plateau on 1.94% of backfilled days,
    # which made the Exceptional threshold compute to exactly 1.00 — ~4x the
    # intended push rate, with the winning spot chosen arbitrarily among ties.
    canvas = 0.62 * peak(high, 45, 45) + 0.38 * peak(mid, 35, 40)
    return {
        "canvas": canvas,
        "low_clear": clamp(1 - low / 65),
        # Colour is a civil-twilight phenomenon: it peaks around and just after
        # the sun crosses the horizon, not during the golden hour before it.
        # Continuous in solar elevation, which also guarantees the score can't
        # tie at the ceiling the way a boxed gate could.
        "twilight": peak(elev, -1.5, 10.0),
        "dry": 1.0 if precip < 0.5 else 0.2,
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
        f"cloud low/mid/high {val(h, 'cloud_cover_low', i):.0f}/"
        f"{val(h, 'cloud_cover_mid', i):.0f}/{val(h, 'cloud_cover_high', i):.0f}%, "
        f"sun {h['solar_elevation'][i]:.1f}°"
    )
