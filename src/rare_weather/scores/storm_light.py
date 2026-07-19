"""Dramatic storm light — convective cells with low-angle sun.

The shot: towering cumulus, shafts of rain, shelf clouds — lit by a sun low
enough to be golden, through a sky broken enough to let light through.

Factors (multiplied):
  convection  CAPE plus active showers — energy for dramatic cloud structure
  broken_sky  total cloud in the middle range; overcast is flat, clear is empty
  light       sun elevation 0–25°, best 3–18° (golden light on the cells)

Backfill source is the Historical Forecast API (2021+): ERA5 has no CAPE.
"""

from __future__ import annotations

from . import clamp, tent, val

ID = "storm_light"
LABEL = "Storm light"
EMOJI = "\N{CLOUD WITH LIGHTNING}️"
SOURCE = "forecast_archive"
VARIABLES = [
    "cape",
    "precipitation",
    "cloud_cover",
    "cloud_cover_low",
]


def _factors(h: dict, i: int) -> dict[str, float] | None:
    elev = h["solar_elevation"][i]
    if not (0 <= elev <= 25):
        return None
    cape = val(h, "cape", i)
    precip = val(h, "precipitation", i)
    cc = val(h, "cloud_cover", i)
    # Soft-saturating CAPE (PNW-calibrated: 350 J/kg is halfway) so bigger
    # convection always ranks higher — a hard cap would tie all strong days
    # at 1.0 and break top-percentile thresholds. Postfrontal shower activity
    # carries real weight here too.
    return {
        "convection": clamp(0.9 * cape / (cape + 350) + 0.25 * clamp(precip / 2)),
        "broken_sky": tent(cc, 15, 35, 80, 100),
        "light": tent(elev, 0, 3, 18, 25),
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
        f"CAPE {val(h, 'cape', i):.0f} J/kg, precip {val(h, 'precipitation', i):.1f} mm/h, "
        f"cloud {val(h, 'cloud_cover', i):.0f}%, sun {h['solar_elevation'][i]:.0f}°"
    )
