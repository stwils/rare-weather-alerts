"""Fog — photogenic morning fog / valley fog under a clear sky.

The shot: fog filling valleys or drifting through trees at and after sunrise,
ideally with clear sky above so low sun lights the fog. Scored only in the
dawn-to-late-morning window.

Factors (multiplied):
  saturation   air at/near saturation (small temp–dewpoint spread, high RH)
  calm         light wind, or fog shears out and mixes away
  clear above  mid/high cloud kills the light that makes fog glow
  clear night  radiation fog needs a mostly clear preceding night
  dry          rain ≠ fog
"""

from __future__ import annotations

from . import clamp, val

ID = "fog"
LABEL = "Fog"
EMOJI = "\N{FOG}"
SOURCE = "era5"
VARIABLES = [
    "temperature_2m",
    "dew_point_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "cloud_cover",
    "cloud_cover_mid",
    "cloud_cover_high",
    "precipitation",
]


def _factors(h: dict, i: int) -> dict[str, float] | None:
    elev = h["solar_elevation"][i]
    hour = h["local_hour"][i]
    if not (-8 <= elev <= 30) or hour >= 13:
        return None
    spread = val(h, "temperature_2m", i) - val(h, "dew_point_2m", i)
    rh = val(h, "relative_humidity_2m", i)
    wind = val(h, "wind_speed_10m", i)
    mid = val(h, "cloud_cover_mid", i)
    high = val(h, "cloud_cover_high", i)
    precip = val(h, "precipitation", i)

    night = [val(h, "cloud_cover", j) for j in range(max(0, i - 8), max(0, i - 2))]
    night_cc = sum(night) / len(night) if night else 50.0

    return {
        "saturation": clamp(1 - max(spread, 0.0) / 3) * clamp((rh - 88) / 12),
        "calm": clamp(1 - wind / 17),
        "clear_above": clamp(1 - 0.7 * mid / 100 - 0.3 * high / 100),
        "clear_night": clamp(1 - 0.7 * clamp((night_cc - 30) / 60)),
        "dry": 1.0 if precip < 0.3 else 0.0,
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
    spread = val(h, "temperature_2m", i) - val(h, "dew_point_2m", i)
    return (
        f"spread {spread:.1f}°C, RH {val(h, 'relative_humidity_2m', i):.0f}%, "
        f"wind {val(h, 'wind_speed_10m', i):.0f} km/h, "
        f"mid/high cloud {val(h, 'cloud_cover_mid', i):.0f}/{val(h, 'cloud_cover_high', i):.0f}%"
    )
