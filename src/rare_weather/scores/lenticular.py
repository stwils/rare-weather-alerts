"""Lenticular clouds — standing wave clouds over the Cascade volcanoes.

The shot: a stacked lens cloud capping the peak, in daylight, visible from
below. Needs strong cross-mountain flow near summit level (700 hPa ≈ 3 km),
moisture at that level (too dry: no cloud; saturated: overcast), and not much
low/mid cloud in the way.

Factors (multiplied):
  stability  potential temperature rising through 850->700 hPa — the stable
             layer that lets a standing wave exist at all
  cross      700 hPa wind *component across the barrier*, not raw speed
  coherence  flow holding its bearing 700->500 hPa; a turning wind won't
             organise into a standing wave
  moisture   700 hPa RH in the lens sweet spot
  view       low+mid cloud would hide the peak
  dry        precipitation means a different sky

v2 (see docs/lenticular-v2.md) added the first three. v1 scored raw 700 hPa
wind speed and nothing else dynamical, so it rated windy *unstable* days —
turbulent, ragged cumulus — identically to well-formed wave days, and missed
waves at moderate wind speeds. Curve breakpoints below are set from the
measured 2021+ climatology at the four volcanoes, not chosen by eye.

Still not modelled: Froude number (needs a per-peak effective obstacle
height), and which side of the summit the lens sits on. Backfill source is the
Historical Forecast API (2021+): ERA5 has no pressure-level variables.
"""

from __future__ import annotations

import math

from . import clamp, peak, val

ID = "lenticular"
LABEL = "Lenticular"
EMOJI = "\N{CLOUD}️"
SOURCE = "forecast_archive"
VARIABLES = [
    "wind_speed_700hPa",
    "wind_direction_700hPa",
    "wind_speed_500hPa",
    "wind_direction_500hPa",
    "relative_humidity_700hPa",
    "temperature_850hPa",
    "temperature_700hPa",
    "temperature_500hPa",
    "cloud_cover_low",
    "cloud_cover_mid",
    "precipitation",
]

KAPPA = 0.2857  # R/cp for dry air


def theta(temp_c: float, pressure_hpa: float) -> float:
    """Potential temperature (K): the temperature a parcel would have brought
    adiabatically to 1000 hPa. Constant with height means neutral; increasing
    with height means stable — which is the precondition for a standing wave."""
    return (temp_c + 273.15) * (1000.0 / pressure_hpa) ** KAPPA


def stability_k(h: dict, i: int, lower_hpa: int = 700, upper_hpa: int = 500) -> float:
    """Potential-temperature increase across a layer (K); higher = more stable.

    Defaults to 700->500 hPa — above the summits, where the wave propagates.
    (850->700 straddles the summits and is available for comparison.)
    """
    return theta(val(h, f"temperature_{upper_hpa}hPa", i), upper_hpa) - theta(
        val(h, f"temperature_{lower_hpa}hPa", i), lower_hpa
    )


def cross_barrier(h: dict, i: int) -> float:
    """Component of the 700 hPa wind perpendicular to the barrier, km/h.

    Absolute value: easterly flow makes a wave just as westerly does — it puts
    the lens on the other side of the peak, which is a viewing question rather
    than a formation one.
    """
    offset = val(h, "wind_direction_700hPa", i) - h.get("barrier_bearing", 270.0)
    return abs(val(h, "wind_speed_700hPa", i) * math.cos(math.radians(offset)))


def directional_shear(h: dict, i: int) -> float:
    """Absolute 700->500 hPa turning of the wind, degrees (0-180). A standing
    wave needs the flow to hold its bearing through the layer; a lot of turning
    means the wave never organises."""
    d = abs(val(h, "wind_direction_500hPa", i) - val(h, "wind_direction_700hPa", i)) % 360
    return d if d <= 180 else 360 - d


# Breakpoints from the measured 2021+ climatology across the four volcanoes
# (94,412 daylight hours). Percentiles quoted are of that distribution.
CROSS_MIN, CROSS_FULL = 25.0, 85.0  # km/h; median 22, p90 61 — separates well
SHEAR_FREE, SHEAR_DEAD = 15.0, 60.0  # deg; median 15, and 74% of hours are <30
STAB_LOW, STAB_HIGH = 8.0, 16.0  # K over 700->500; p25 8.9, median 10.7, p95 16.0
STAB_FLOOR = 0.7  # stability measured as a *weak* discriminator — see module docs


def _factors(h: dict, i: int) -> dict[str, float] | None:
    if h["solar_elevation"][i] <= 0:
        return None
    rh700 = val(h, "relative_humidity_700hPa", i)
    low = val(h, "cloud_cover_low", i)
    mid = val(h, "cloud_cover_mid", i)
    precip = val(h, "precipitation", i)
    return {
        # The barrier-crossing component, not raw speed: v1 scored 80 km/h of
        # along-crest southerly identically to 80 km/h of westerly.
        "cross": clamp((cross_barrier(h, i) - CROSS_MIN) / (CROSS_FULL - CROSS_MIN)),
        # A wind that turns with height never organises into a standing wave.
        "coherence": clamp(
            1 - (directional_shear(h, i) - SHEAR_FREE) / (SHEAR_DEAD - SHEAR_FREE)
        ),
        # Deliberately shallow-range: the air here is *always* stably stratified
        # in this layer, so this ranks rather than gates. See module docstring.
        "stability": STAB_FLOOR
        + (1 - STAB_FLOOR) * clamp((stability_k(h, i) - STAB_LOW) / (STAB_HIGH - STAB_LOW)),
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
        f"cross-barrier {cross_barrier(h, i):.0f} km/h "
        f"(700hPa {val(h, 'wind_speed_700hPa', i):.0f} from "
        f"{val(h, 'wind_direction_700hPa', i):.0f}°), "
        f"shear {directional_shear(h, i):.0f}°, "
        f"stability {stability_k(h, i):.1f}K, "
        f"RH {val(h, 'relative_humidity_700hPa', i):.0f}%, "
        f"low/mid cloud {val(h, 'cloud_cover_low', i):.0f}/{val(h, 'cloud_cover_mid', i):.0f}%"
    )
