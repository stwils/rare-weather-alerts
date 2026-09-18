"""Aviation mountain-wave confidence signals (ROADMAP item 18).
Run: python tests/test_aviation.py   (or pytest)

Fixtures in tests/fixtures/awc/ are shaped like live AWC responses. The window
used throughout is 2026-09-20 17:00–20:00Z; the wave G-AIRMET covers Mt. Hood
(not St. Helens) with a snapshot valid at 18:00Z.
"""

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import requests

from rare_weather import aviation
from rare_weather.config import Spot
from rare_weather.opportunities import Opportunity

FIX = Path(__file__).parent / "fixtures" / "awc"

HOOD = (45.3735, -121.6959)
ST_HELENS = (46.1912, -122.1944)

T_1500 = 1789916400  # 2026-09-20T15:00Z
T_1700 = 1789923600
T_2000 = 1789934400
DAY = 86400


def _reports() -> aviation.Reports:
    return aviation.Reports(
        airmets=aviation.parse_gairmets(json.loads((FIX / "gairmet.json").read_text())),
        pireps=aviation.parse_pireps(json.loads((FIX / "pirep.json").read_text())),
    )


def _texts(signals: list[dict]) -> list[str]:
    return [s["text"] for s in signals]


def _airmet_only(r: aviation.Reports) -> aviation.Reports:
    return aviation.Reports(airmets=r.airmets, pireps=[])


def test_wave_airmet_covering_the_spot_during_the_window():
    r = _airmet_only(_reports())
    assert _texts(aviation.signals_for(*HOOD, T_1700, T_2000, r)) == ["wave AIRMET active"]


def test_wave_airmet_elsewhere_does_not_count():
    r = _airmet_only(_reports())
    assert aviation.signals_for(*ST_HELENS, T_1700, T_2000, r) == []


def test_wave_airmet_outside_the_window_does_not_count():
    r = _airmet_only(_reports())
    # snapshot 18:00Z stands for 16:30–19:30Z
    assert aviation.signals_for(*HOOD, T_1700 + DAY, T_2000 + DAY, r) == []
    assert aviation.signals_for(*HOOD, T_1500 - 3600, T_1500, r) == []  # ends before 16:30
    assert _texts(aviation.signals_for(*HOOD, T_1500, T_1700, r)) == ["wave AIRMET active"]


def test_turbulence_airmet_without_a_wave_cause_does_not_count():
    box = [(47.0, -123.0), (47.0, -120.0), (44.0, -120.0), (44.0, -123.0)]
    plain = aviation.Airmet("TURB-HI", "", T_1500, T_2000, box)
    r = aviation.Reports(airmets=[plain], pireps=[])
    assert aviation.signals_for(*HOOD, T_1700, T_2000, r) == []
    wave = aviation.Airmet("TURB-LO", "MTN WAVE", T_1500, T_2000, box)
    r = aviation.Reports(airmets=[wave], pireps=[])
    assert _texts(aviation.signals_for(*HOOD, T_1700, T_2000, r)) == ["wave AIRMET active"]


def test_polygon_containment_is_not_just_a_bounding_box():
    # a triangle whose bounding box holds both points; only one is inside
    tri = aviation.Airmet("TURB-LO", "MTN WAVE", T_1500, T_2000, [(46.0, -122.0), (46.0, -121.0), (45.0, -121.0)])
    r = aviation.Reports(airmets=[tri], pireps=[])
    assert _texts(aviation.signals_for(45.8, -121.2, T_1700, T_2000, r)) == ["wave AIRMET active"]
    assert aviation.signals_for(45.2, -121.8, T_1700, T_2000, r) == []


def _pireps_only(r: aviation.Reports) -> aviation.Reports:
    return aviation.Reports(airmets=[], pireps=r.pireps)


def test_pireps_reporting_wave_near_the_spot_are_counted():
    # Of the 8 fixture PIREPs, 4 qualify for Mt. Hood: MOD turb at 120-160,
    # an MTN WAVE remark, an LLWS remark, MOD-SEV at FL170 (no layer given).
    # Rejected: LGT turb, MOD turb at FL330, MWAVE near Pasco (~190 km),
    # and an MTN WAVE remark from 30h before the window.
    r = _pireps_only(_reports())
    assert _texts(aviation.signals_for(*HOOD, T_1700, T_2000, r)) == ["4 PIREPs reporting wave"]


def test_pirep_count_is_singular_for_one():
    one = aviation.parse_pireps([json.loads((FIX / "pirep.json").read_text())[1]])
    r = aviation.Reports(airmets=[], pireps=one)
    assert _texts(aviation.signals_for(*HOOD, T_1700, T_2000, r)) == ["1 PIREP reporting wave"]


def test_pireps_far_from_the_spot_do_not_count():
    r = _pireps_only(_reports())
    assert aviation.signals_for(*ST_HELENS, T_1700, T_2000, r) == []


def test_pireps_only_vouch_for_a_window_that_is_near():
    # observed 18:30Z on the 20th: says nothing about the next day's window
    r = _pireps_only(_reports())
    assert aviation.signals_for(*HOOD, T_1700 + DAY, T_2000 + DAY, r) == []


def test_both_signals_together():
    r = _reports()
    assert _texts(aviation.signals_for(*HOOD, T_1700, T_2000, r)) == [
        "wave AIRMET active",
        "4 PIREPs reporting wave",
    ]


# --- fetching -------------------------------------------------------------


def _response(status: int, body: bytes) -> requests.Response:
    r = requests.Response()
    r.status_code, r._content = status, body
    return r


class FakeAWC:
    """Stands in for requests.get; records every call."""

    def __init__(self, gairmet=None, pirep=None, error: Exception | None = None):
        self.calls: list[tuple[str, dict]] = []
        # `is None`, not `or`: a Response with an error status is falsy
        fixture = lambda name: _response(200, (FIX / f"{name}.json").read_bytes())  # noqa: E731
        self.gairmet = fixture("gairmet") if gairmet is None else gairmet
        self.pirep = fixture("pirep") if pirep is None else pirep
        self.error = error

    def __call__(self, url, params=None, timeout=None):
        self.calls.append((url, params or {}))
        if self.error:
            raise self.error
        return self.gairmet if "gairmet" in url else self.pirep

    def fetch(self, points):
        out = io.StringIO()
        with mock.patch.object(aviation.requests, "get", self), redirect_stdout(out):
            reports = aviation.fetch_reports(points)
        return reports, out.getvalue()


VOLCANOES = [HOOD, ST_HELENS, (46.2024, -121.4906), (44.6743, -121.7997)]


def test_fetches_each_product_once_for_all_spots():
    awc = FakeAWC()
    reports, _ = awc.fetch(VOLCANOES)
    assert sorted(url.rsplit("/", 1)[-1] for url, _ in awc.calls) == ["gairmet", "pirep"]
    assert reports is not None
    assert _texts(aviation.signals_for(*HOOD, T_1700, T_2000, reports)) == [
        "wave AIRMET active",
        "4 PIREPs reporting wave",
    ]
    # one PIREP box that reaches 80 km beyond every Spot
    (params,) = [p for url, p in awc.calls if url.endswith("pirep")]
    lat0, lon0, lat1, lon1 = map(float, params["bbox"].split(","))
    assert lat0 < 44.6743 - 0.72 and lat1 > 46.2024 + 0.72
    assert lon0 < -122.1944 - 1.0 and lon1 > -121.4906 + 1.0


def test_no_pireps_is_an_empty_list_not_a_failure():
    # AWC answers an empty query with 204 and no body
    reports, _ = FakeAWC(pirep=_response(204, b"")).fetch(VOLCANOES)
    assert reports is not None and reports.pireps == [] and reports.airmets


def _pirep_bytes(**fields) -> bytes:
    """One fixture PIREP near Mt. Hood during the window, with fields replaced."""
    p = json.loads((FIX / "pirep.json").read_text())[0]
    return json.dumps([{**p, **fields}]).encode()


def test_loosely_typed_fields_are_read_not_crashed_on():
    # numbers as strings, an intensity as a number: parse, then match safely
    body = _pirep_bytes(tbBas1="120", tbTop1="160", tbInt1="MOD", fltLvl="140", tbType1=0)
    reports, log = FakeAWC(pirep=_response(200, body)).fetch(VOLCANOES)
    assert reports is not None, log
    assert _texts(aviation.signals_for(*HOOD, T_1700, T_2000, _pireps_only(reports))) == [
        "1 PIREP reporting wave"
    ]


def test_a_structured_mountain_wave_report_counts_at_any_level():
    body = _pirep_bytes(tbInt1="LGT", tbType1="MWAVE", tbBas1=250, tbTop1=None)
    reports, _ = FakeAWC(pirep=_response(200, body)).fetch(VOLCANOES)
    assert _texts(aviation.signals_for(*HOOD, T_1700, T_2000, _pireps_only(reports))) == [
        "1 PIREP reporting wave"
    ]


def test_awc_failures_are_logged_and_yield_nothing():
    cases = {
        "network": FakeAWC(error=requests.ConnectionError("no route")),
        "http": FakeAWC(gairmet=_response(503, b"down")),
        "not json": FakeAWC(pirep=_response(200, b"<html>maintenance</html>")),
        "wrong shape": FakeAWC(gairmet=_response(200, b'{"error": "moved"}')),
        "missing field": FakeAWC(pirep=_response(200, b'[{"lat": 45.3}]')),
        "not a record": FakeAWC(pirep=_response(200, b'["PDX UA /OV PDX"]')),
        "garbage layer": FakeAWC(pirep=_response(200, _pirep_bytes(tbBas1="low"))),
    }
    for case, awc in cases.items():
        reports, log = awc.fetch(VOLCANOES)
        assert reports is None, case
        assert "aviation reports unavailable" in log, case


# --- attaching to Opportunities ------------------------------------------


def _opp(spot: str, phen: str, signals=None) -> Opportunity:
    return Opportunity(
        id=f"{spot}:{phen}", spot=spot, phenomenon=phen, start=T_1700, end=T_2000,
        peak_score=0.9, tier="exceptional", alerted_tier="exceptional", signals=signals or [],
    )


SPOTS = {
    "mt-hood": Spot("mt-hood", "Mt. Hood", *HOOD, phenomena=["lenticular"]),
    "mt-st-helens": Spot("mt-st-helens", "Mt. St. Helens", *ST_HELENS, phenomena=["lenticular"]),
    "trillium-lake": Spot("trillium-lake", "Trillium Lake", 45.2670, -121.7398, phenomena=["fog"]),
}


def test_lenticular_opportunities_get_signals():
    hood, helens = _opp("mt-hood", "lenticular"), _opp("mt-st-helens", "lenticular")
    aviation.attach_signals([hood, helens], SPOTS, _reports())
    assert _texts(hood.signals) == ["wave AIRMET active", "4 PIREPs reporting wave"]
    assert helens.signals == []


def test_non_lenticular_opportunities_carry_no_signals():
    # 10 km from Mt. Hood, inside the wave AIRMET, near the same PIREPs
    fog = _opp("trillium-lake", "fog")
    aviation.attach_signals([fog], SPOTS, _reports())
    assert fog.signals == []


def test_a_failed_fetch_keeps_the_last_known_signals():
    before = [{"name": "wave_airmet", "text": "wave AIRMET active"}]
    hood = _opp("mt-hood", "lenticular", signals=before)
    aviation.attach_signals([hood], SPOTS, None)
    assert hood.signals == before


def test_a_successful_fetch_clears_signals_that_no_longer_hold():
    hood = _opp("mt-hood", "lenticular", signals=[{"name": "wave_airmet", "text": "wave AIRMET active"}])
    aviation.attach_signals([hood], SPOTS, aviation.Reports(airmets=[], pireps=[]))
    assert hood.signals == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all tests pass")
