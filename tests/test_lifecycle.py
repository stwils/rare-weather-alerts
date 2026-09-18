"""Opportunity lifecycle, coalescing and digest-scheduling tests.
Run: python tests/test_lifecycle.py"""

from datetime import datetime
from zoneinfo import ZoneInfo

import json
import tempfile
from pathlib import Path

from rare_weather.opportunities import (
    Opportunity,
    load_state,
    partition_unknown,
    reconcile,
    save_state,
    spans_from_scores,
)
from rare_weather.pipeline import _coalesce, digest_due

H = 3600
TIMES = [i * H for i in range(48)]


def scores_at(pairs: dict[int, float]) -> list[float]:
    s = [0.0] * 48
    for i, v in pairs.items():
        s[i] = v
    return s


def test_span_merging():
    # hours 10-13 and 16-18 with a 3h gap -> one span (merge gap 6h)
    spans = spans_from_scores(
        TIMES, scores_at({10: 0.5, 11: 0.5, 12: 0.5, 13: 0.5, 16: 0.9, 17: 0.9, 18: 0.9}),
        0.4, 0.8, 6,
    )
    assert len(spans) == 1
    s = spans[0]
    assert (s.tier, s.start, s.end, s.peak_index) == ("exceptional", 10 * H, 19 * H, 16)
    # gap > 6h splits
    assert len(spans_from_scores(TIMES, scores_at({5: 0.5, 20: 0.5}), 0.4, 0.8, 6)) == 2


def test_lifecycle():
    spans = spans_from_scores(TIMES, scores_at({10: 0.9}), 0.4, 0.8, 6)
    active, ev = reconcile([], {("a", "fog"): spans}, now=0, merge_gap_hours=6)
    assert [e["type"] for e in ev] == ["detected"]
    assert active[0].alerted_tier == "exceptional"

    # same span on the next refresh -> no events (the anti-spam rule)
    active, ev = reconcile(active, {("a", "fog"): spans}, now=0, merge_gap_hours=6)
    assert ev == [] and len(active) == 1

    # forecast falls apart before the window ends -> cancelled
    a3, ev3 = reconcile(active, {}, now=5 * H, merge_gap_hours=6)
    assert [e["type"] for e in ev3] == ["cancelled"] and a3 == []

    # window already past -> expired (archived, not pushed as a cancellation)
    a4, ev4 = reconcile(active, {}, now=30 * H, merge_gap_hours=6)
    assert [e["type"] for e in ev4] == ["expired"] and a4 == []


def test_upgrade():
    weak = spans_from_scores(TIMES, scores_at({10: 0.5}), 0.4, 0.8, 6)
    active, _ = reconcile([], {("a", "fog"): weak}, now=0, merge_gap_hours=6)
    strong = spans_from_scores(TIMES, scores_at({10: 0.9}), 0.4, 0.8, 6)
    active, ev = reconcile(active, {("a", "fog"): strong}, now=0, merge_gap_hours=6)
    assert [e["type"] for e in ev] == ["upgraded"]
    assert active[0].alerted_tier == "exceptional"


def _opp(spot, phen, start_h, end_h, score=0.5):
    return Opportunity(
        id=f"{spot}:{phen}:{start_h}", spot=spot, phenomenon=phen,
        start=start_h * H, end=end_h * H, peak_score=score, tier="notable",
        alerted_tier="notable",
    )


def test_unreachable_spot_is_not_a_cancellation():
    """A failed fetch must not read as 'the forecast fell apart'."""
    live, dead = _opp("a", "fog", 10, 14), _opp("b", "fog", 10, 14)
    reconcilable, held = partition_unknown([live, dead], {"b"}, now=5 * H)
    assert reconcilable == [live] and held == [dead]

    # ...and the held one is carried through untouched, raising no event
    active, ev = reconcile(reconcilable, {}, now=5 * H, merge_gap_hours=6)
    active.extend(held)
    assert [e["type"] for e in ev] == ["cancelled"]  # only the reachable spot
    assert active == [dead]


def test_unreachable_spot_still_expires():
    """Held ≠ immortal: an elapsed window still retires even if its spot is down."""
    past = _opp("b", "fog", 10, 14)
    reconcilable, held = partition_unknown([past], {"b"}, now=30 * H)
    assert reconcilable == [past] and held == []
    _, ev = reconcile(reconcilable, {}, now=30 * H, merge_gap_hours=6)
    assert [e["type"] for e in ev] == ["expired"]


TZ = "America/Los_Angeles"


def _at(stamp: str) -> float:
    return datetime.fromisoformat(stamp).replace(tzinfo=ZoneInfo(TZ)).timestamp()


def test_digest_survives_late_runs():
    """Regression: GitHub ran the 06:xx digest cron at ~10:36 local, and an
    exact-hour gate skipped it every day from Aug 25 to Sep 17."""
    assert digest_due(_at("2026-09-17T10:36"), TZ, 6, "2026-09-16")  # the bug case
    assert digest_due(_at("2026-09-17T06:00"), TZ, 6, None)  # first ever, on time
    assert not digest_due(_at("2026-09-17T05:59"), TZ, 6, "2026-09-16")  # too early


def test_digest_goes_out_once_per_local_day():
    assert not digest_due(_at("2026-09-17T13:00"), TZ, 6, "2026-09-17")
    assert digest_due(_at("2026-09-17T23:30"), TZ, 6, "2026-09-16")  # late, but not missed
    # just after local midnight belongs to the new day, but it's before 06:00
    assert not digest_due(_at("2026-09-18T00:30"), TZ, 6, "2026-09-17")


def test_digest_uses_local_time_across_dst():
    # 06:30 local in winter (PST, UTC-8) and summer (PDT, UTC-7) both count
    assert digest_due(_at("2026-12-15T06:30"), TZ, 6, "2026-12-14")
    assert digest_due(_at("2026-07-15T06:30"), TZ, 6, "2026-07-14")


def test_coalesce():
    events = [
        {"type": "detected", "opp": _opp("a", "fog", 10, 14, 0.5), "span": None},
        {"type": "detected", "opp": _opp("b", "fog", 11, 15, 0.9), "span": None},  # same morning
        {"type": "detected", "opp": _opp("c", "fog", 40, 44, 0.6), "span": None},  # next day
        {"type": "detected", "opp": _opp("d", "lenticular", 11, 15, 0.7), "span": None},
    ]
    groups = _coalesce(events, gap_hours=12)
    keys = sorted(tuple(sorted(e["opp"].spot for e in g)) for g in groups)
    assert keys == [("a", "b"), ("c",), ("d",)]


WAVE = [{"name": "wave_airmet", "text": "wave AIRMET active"}]


def test_signals_ride_along_with_a_tracked_opportunity():
    spans = spans_from_scores(TIMES, scores_at({10: 0.9}), 0.4, 0.8, 6)
    active, _ = reconcile([], {("hood", "lenticular"): spans}, now=0, merge_gap_hours=6)
    assert active[0].signals == []  # a fresh detection has none yet
    active[0].signals = WAVE
    refreshed = spans_from_scores(TIMES, scores_at({10: 0.9, 11: 0.85}), 0.4, 0.8, 6)
    active, _ = reconcile(active, {("hood", "lenticular"): refreshed}, now=0, merge_gap_hours=6)
    assert active[0].signals == WAVE


def test_signals_survive_a_state_round_trip():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "state.json"
        o = _opp("hood", "lenticular", 10, 14)
        o.signals = WAVE
        save_state(path, [o])
        assert load_state(path)[0].signals == WAVE


def test_state_written_before_signals_existed_still_loads():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "state.json"
        legacy = {k: v for k, v in _opp("a", "fog", 10, 14).__dict__.items() if k != "signals"}
        path.write_text(json.dumps({"opportunities": [legacy]}))
        assert load_state(path)[0].signals == []


if __name__ == "__main__":
    test_span_merging()
    test_lifecycle()
    test_upgrade()
    test_unreachable_spot_is_not_a_cancellation()
    test_unreachable_spot_still_expires()
    test_digest_survives_late_runs()
    test_digest_goes_out_once_per_local_day()
    test_digest_uses_local_time_across_dst()
    test_coalesce()
    test_signals_ride_along_with_a_tracked_opportunity()
    test_signals_survive_a_state_round_trip()
    test_state_written_before_signals_existed_still_loads()
    print("all tests pass")
