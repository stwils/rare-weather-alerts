"""Open-Meteo clients.

Three endpoints, one contract: hourly dict with epoch `time` plus requested
variables. Score models may only use variables their backfill source also
provides (forecast/backfill symmetry — see ADR 0001):

- ERA5 archive (10y): surface vars only; no CAPE, no pressure levels.
- Historical Forecast API (2021-04+): same model family as the live forecast,
  including CAPE and 700 hPa — backfill source for storm_light and lenticular.
"""

from __future__ import annotations

import time

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ERA5_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_ARCHIVE_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"


def _fetch(url: str, params: dict, retries: int = 5) -> dict:
    params = {**params, "timeformat": "unixtime"}
    delay = 2.0
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=180)
            if r.status_code == 429:
                raise requests.HTTPError("rate limited", response=r)
            r.raise_for_status()
            body = r.json()
            if "hourly" not in body:
                raise ValueError(f"no hourly block in response: {str(body)[:200]}")
            return body["hourly"]
        except (requests.RequestException, ValueError):
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise AssertionError("unreachable")


def fetch_forecast(lat: float, lon: float, variables: list[str], days: int, tz: str) -> dict:
    return _fetch(
        FORECAST_URL,
        {
            "latitude": lat,
            "longitude": lon,
            "hourly": ",".join(variables),
            "forecast_days": days,
            "timezone": tz,
        },
    )


def fetch_archive(
    source: str, lat: float, lon: float, variables: list[str], start: str, end: str, tz: str
) -> dict:
    url = {"era5": ERA5_URL, "forecast_archive": FORECAST_ARCHIVE_URL}[source]
    return _fetch(
        url,
        {
            "latitude": lat,
            "longitude": lon,
            "hourly": ",".join(variables),
            "start_date": start,
            "end_date": end,
            "timezone": tz,
        },
    )
