"""Opportunity lifecycle + coalescing tests. Run: python tests/test_lifecycle.py"""

from rare_weather.opportunities import Opportunity, reconcile, spans_from_scores
from rare_weather.pipeline import _coalesce

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

    # window already past -> silent expiry, no cancellation push
    a4, ev4 = reconcile(active, {}, now=30 * H, merge_gap_hours=6)
    assert ev4 == [] and a4 == []


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


if __name__ == "__main__":
    test_span_merging()
    test_lifecycle()
    test_upgrade()
    test_coalesce()
    print("all tests pass")
