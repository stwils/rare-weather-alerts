"""Solar elevation (NOAA approximation, refraction ignored — accurate to ~0.1°,
plenty for gating scores to dawn/dusk/daylight windows)."""

from __future__ import annotations

import math
from datetime import datetime, timezone


def solar_elevation_deg(lat: float, lon: float, epoch: float) -> float:
    t = datetime.fromtimestamp(epoch, tz=timezone.utc)
    y, m = t.year, t.month
    day = t.day + (t.hour + t.minute / 60 + t.second / 3600) / 24
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    jd = int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + day + b - 1524.5
    jc = (jd - 2451545) / 36525

    gml = (280.46646 + jc * (36000.76983 + 0.0003032 * jc)) % 360
    gma = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    ecc = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    ceq = (
        math.sin(math.radians(gma)) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
        + math.sin(math.radians(2 * gma)) * (0.019993 - 0.000101 * jc)
        + math.sin(math.radians(3 * gma)) * 0.000289
    )
    app_long = gml + ceq - 0.00569 - 0.00478 * math.sin(math.radians(125.04 - 1934.136 * jc))
    mean_obliq = 23 + (26 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60) / 60
    obliq = mean_obliq + 0.00256 * math.cos(math.radians(125.04 - 1934.136 * jc))
    decl = math.asin(math.sin(math.radians(obliq)) * math.sin(math.radians(app_long)))

    var_y = math.tan(math.radians(obliq / 2)) ** 2
    eq_time = 4 * math.degrees(
        var_y * math.sin(2 * math.radians(gml))
        - 2 * ecc * math.sin(math.radians(gma))
        + 4 * ecc * var_y * math.sin(math.radians(gma)) * math.cos(2 * math.radians(gml))
        - 0.5 * var_y**2 * math.sin(4 * math.radians(gml))
        - 1.25 * ecc**2 * math.sin(2 * math.radians(gma))
    )
    minutes = t.hour * 60 + t.minute + t.second / 60
    true_solar_min = (minutes + eq_time + 4 * lon) % 1440
    hour_angle = true_solar_min / 4 - 180

    lat_r = math.radians(lat)
    zenith = math.acos(
        math.sin(lat_r) * math.sin(decl)
        + math.cos(lat_r) * math.cos(decl) * math.cos(math.radians(hour_angle))
    )
    return 90 - math.degrees(zenith)
