"""Aviation mountain-wave reports as confidence signals.

Pilots are warned about the same waves a lenticular photograph needs. The
Aviation Weather Center serves G-AIRMETs and PIREPs as keyless JSON; this
module turns them into named **confidence signals** on an Opportunity.

Signals are never Quality Score inputs — there is no backfill archive of these
products, and ADR 0001 rests every score on a percentile of backfilled history —
and they never change tiering. They are
shown next to the score, not folded into it.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime

import requests

GAIRMET_URL = "https://aviationweather.gov/api/data/gairmet"
PIREP_URL = "https://aviationweather.gov/api/data/pirep"

# A G-AIRMET is issued as 3-hourly snapshots; each stands for the 3h around it.
SNAPSHOT_HALF_WIDTH = 90 * 60

WAVE_RE = re.compile(r"\bMTN[\s_]*(WAVE|WV)\b|\bMWAVE\b|\bMOUNTAIN[\s_]*WAVE\b")
# Low-level wind shear, as pilots remark it: "LLWS", or "WS +15KT".
SHEAR_RE = re.compile(r"\bLLWS\b|\bWS\s*[+-]?\d+\s*KTS?\b")

PIREP_RADIUS_KM = 80
# A PIREP describes the air when it was flown. It vouches for a window it falls
# inside, or one starting soon after — not one a day or two out.
PIREP_LEAD = 6 * 3600
PIREP_AGE_HOURS = 12  # how far back to ask for; covers PIREP_LEAD plus an ongoing window
# Wave-induced turbulence at lens altitude: moderate or worse at 10-20k ft.
WAVE_BAND = (100, 200)  # flight level, hundreds of ft
MOD_OR_WORSE = {"MOD", "MOD-SEV", "SEV", "SEV-EXTM", "EXTM"}
WAVE_TURB_TYPES = {"MWAVE", "LLWS"}


@dataclass
class Airmet:
    hazard: str
    due_to: str
    valid_start: float
    valid_end: float
    polygon: list[tuple[float, float]]  # (lat, lon) vertices


@dataclass
class Turbulence:
    intensity: str
    type: str
    base: int | None  # flight level, hundreds of ft
    top: int | None


@dataclass
class Pirep:
    lat: float
    lon: float
    time: float
    flight_level: int | None
    remarks: str = ""
    turbulence: list[Turbulence] = field(default_factory=list)


@dataclass
class Reports:
    airmets: list[Airmet]
    pireps: list[Pirep]


def _epoch(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def _text(value) -> str:
    return str(value or "").strip().upper()


def _level(value) -> int | None:
    """Flight level (hundreds of ft) from a number or numeric string; 0/blank = unknown.

    Anything else raises ValueError, so a changed format fails the fetch
    rather than slipping a string into the altitude comparison later.
    """
    if value in (None, ""):
        return None
    return int(float(value)) or None


def parse_gairmets(raw: list[dict]) -> list[Airmet]:
    """Area G-AIRMETs from the AWC `gairmet` JSON; lines (freezing levels) are dropped."""
    out = []
    for g in raw:
        if g["geometryType"] != "AREA":
            continue
        t = _epoch(g["validTime"])
        out.append(
            Airmet(
                hazard=_text(g["hazard"]),
                due_to=_text(g.get("due_to")),
                valid_start=t - SNAPSHOT_HALF_WIDTH,
                valid_end=t + SNAPSHOT_HALF_WIDTH,
                polygon=[(float(c["lat"]), float(c["lon"])) for c in g["coords"]],
            )
        )
    return out


def parse_pireps(raw: list[dict]) -> list[Pirep]:
    """PIREPs from the AWC `pirep` JSON (up to two turbulence layers each)."""
    out = []
    for p in raw:
        _, _, remarks = _text(p.get("rawOb")).partition("/RM")
        layers = [
            Turbulence(
                intensity=_text(p.get(f"tbInt{n}")),
                type=_text(p.get(f"tbType{n}")),
                base=_level(p.get(f"tbBas{n}")),
                top=_level(p.get(f"tbTop{n}")),
            )
            for n in (1, 2)
            if p.get(f"tbInt{n}") or p.get(f"tbType{n}")
        ]
        out.append(
            Pirep(
                lat=float(p["lat"]),
                lon=float(p["lon"]),
                time=float(p["obsTime"]),
                flight_level=_level(p.get("fltLvl")),  # 0 = unknown (FLUNKN)
                remarks=remarks.strip(),
                turbulence=layers,
            )
        )
    return out


def _get_json(url: str, params: dict) -> list:
    r = requests.get(url, params={**params, "format": "json"}, timeout=30)
    r.raise_for_status()
    if r.status_code == 204 or not r.content:
        return []  # AWC's answer to a query that matched nothing
    body = r.json()
    if not isinstance(body, list):
        raise ValueError(f"expected a JSON list, got: {str(body)[:200]}")
    return body


def fetch_reports(points: list[tuple[float, float]]) -> Reports | None:
    """Current G-AIRMETs and recent PIREPs around `points` — one request each.

    Returns None (and logs) if the AWC is unreachable or its format has
    changed: an aviation-feed outage must never cost the alert pass.
    """
    pad_lat = PIREP_RADIUS_KM / 111.0 * 1.2
    pad_lon = pad_lat / min(math.cos(math.radians(abs(lat))) for lat, _ in points)
    lats, lons = [p[0] for p in points], [p[1] for p in points]
    bbox = ",".join(
        f"{v:.2f}"
        for v in (min(lats) - pad_lat, min(lons) - pad_lon, max(lats) + pad_lat, max(lons) + pad_lon)
    )
    try:
        # Tango carries the turbulence G-AIRMETs; fore=all gets every 3h snapshot.
        airmets = parse_gairmets(_get_json(GAIRMET_URL, {"product": "tango", "fore": "all"}))
        pireps = parse_pireps(_get_json(PIREP_URL, {"bbox": bbox, "age": PIREP_AGE_HOURS}))
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f"  ! aviation reports unavailable ({type(exc).__name__}: {exc})")
        return None
    return Reports(airmets=airmets, pireps=pireps)


def _contains(polygon: list[tuple[float, float]], lat: float, lon: float) -> bool:
    """Ray casting in lat/lon — fine at the scale of an AIRMET area."""
    inside = False
    n = len(polygon)
    for i in range(n):
        (y1, x1), (y2, x2) = polygon[i], polygon[(i + 1) % n]
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _is_wave(a: Airmet) -> bool:
    """A mountain-wave hazard, or turbulence whose cause is a mountain wave.

    G-AIRMET has no dedicated mountain-wave hazard today (TURB-HI/TURB-LO/LLWS
    ...), so in practice this is turbulence with a wave `due_to`.
    """
    if WAVE_RE.search(a.hazard):
        return True
    return a.hazard.startswith("TURB") and bool(WAVE_RE.search(a.due_to))


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(a))


def _reports_wave(p: Pirep) -> bool:
    """A mountain-wave or wind-shear remark, or moderate+ turbulence at 10-20k ft."""
    if WAVE_RE.search(p.remarks) or SHEAR_RE.search(p.remarks):
        return True
    for t in p.turbulence:
        if t.type in WAVE_TURB_TYPES:
            return True
        if t.intensity not in MOD_OR_WORSE:
            continue
        base = t.base or p.flight_level
        top = t.top or base
        if base is not None and top is not None and base <= WAVE_BAND[1] and top >= WAVE_BAND[0]:
            return True
    return False


def signals_for(
    lat: float, lon: float, start: float, end: float, reports: Reports
) -> list[dict]:
    """Confidence signals for a lenticular Opportunity at (lat, lon) over [start, end]."""
    signals = []
    if any(
        _is_wave(a)
        and a.valid_start < end
        and a.valid_end > start
        and _contains(a.polygon, lat, lon)
        for a in reports.airmets
    ):
        signals.append({"name": "wave_airmet", "text": "wave AIRMET active"})
    n = sum(
        1
        for p in reports.pireps
        if start - PIREP_LEAD <= p.time <= end
        and _distance_km(lat, lon, p.lat, p.lon) <= PIREP_RADIUS_KM
        and _reports_wave(p)
    )
    if n:
        signals.append(
            {"name": "wave_pireps", "text": f"{n} PIREP{'s' if n != 1 else ''} reporting wave"}
        )
    return signals


# Phenomena whose Opportunities aviation wave reports speak to.
PHENOMENA = {"lenticular"}


def attach_signals(active: list, spots: dict, reports: Reports | None) -> None:
    """Refresh each lenticular Opportunity's signals from this pass's reports.

    `reports` is None when the AWC fetch failed: signals are left as they were
    (unknown is not the same as "no wave reported"), just as a failed forecast
    fetch holds an Opportunity rather than cancelling it.
    """
    if reports is None:
        return
    for o in active:
        if o.phenomenon not in PHENOMENA:
            o.signals = []
            continue
        spot = spots[o.spot]
        o.signals = signals_for(spot.latitude, spot.longitude, o.start, o.end, reports)
