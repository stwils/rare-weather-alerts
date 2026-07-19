"""Opportunity lifecycle.

An Opportunity is a contiguous span of above-threshold hours for one
(Spot, Phenomenon). It alerts on detection, on tier upgrade, and on
cancellation — never on ordinary forecast-refresh drift. Sub-merge-gap dips
don't split a span. State is a small JSON file of active Opportunities.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

TIER_ORDER = {"notable": 1, "exceptional": 2}


@dataclass
class Span:
    start: float  # epoch of first above-threshold hour
    end: float  # epoch of last above-threshold hour
    peak_score: float
    peak_index: int  # index of peak hour in the forecast series
    tier: str


@dataclass
class Opportunity:
    id: str
    spot: str
    phenomenon: str
    start: float
    end: float
    peak_score: float
    tier: str
    alerted_tier: str


def spans_from_scores(
    times: list[float],
    scores: list[float],
    thr_notable: float,
    thr_exceptional: float,
    merge_gap_hours: float,
) -> list[Span]:
    hits = [i for i, s in enumerate(scores) if s >= thr_notable]
    if not hits:
        return []
    groups: list[list[int]] = [[hits[0]]]
    for i in hits[1:]:
        if times[i] - times[groups[-1][-1]] <= merge_gap_hours * 3600:
            groups[-1].append(i)
        else:
            groups.append([i])
    spans = []
    for g in groups:
        peak_i = max(g, key=lambda i: scores[i])
        peak = scores[peak_i]
        spans.append(
            Span(
                start=times[g[0]],
                end=times[g[-1]] + 3600,
                peak_score=peak,
                peak_index=peak_i,
                tier="exceptional" if peak >= thr_exceptional else "notable",
            )
        )
    return spans


def reconcile(
    active: list[Opportunity],
    candidates: dict[tuple[str, str], list[Span]],
    now: float,
    merge_gap_hours: float,
) -> tuple[list[Opportunity], list[dict]]:
    """Match forecast candidates against active Opportunities.

    Returns (new_active, events); each event is
    {type: detected|upgraded|cancelled, opp: Opportunity, span: Span|None}.
    """
    gap = merge_gap_hours * 3600
    events: list[dict] = []
    new_active: list[Opportunity] = []
    matched_spans: set[int] = set()

    for opp in active:
        spans = candidates.get((opp.spot, opp.phenomenon), [])
        match = next(
            (
                s
                for s in spans
                if id(s) not in matched_spans and s.start - gap <= opp.end and s.end + gap >= opp.start
            ),
            None,
        )
        if match is not None:
            matched_spans.add(id(match))
            upgraded = TIER_ORDER[match.tier] > TIER_ORDER[opp.alerted_tier]
            opp = Opportunity(
                id=opp.id,
                spot=opp.spot,
                phenomenon=opp.phenomenon,
                start=match.start,
                end=match.end,
                peak_score=match.peak_score,
                tier=match.tier,
                alerted_tier=match.tier if upgraded else opp.alerted_tier,
            )
            new_active.append(opp)
            if upgraded:
                events.append({"type": "upgraded", "opp": opp, "span": match})
        elif opp.end < now:
            pass  # ran its course; expire silently
        else:
            events.append({"type": "cancelled", "opp": opp, "span": None})

    for (spot, phen), spans in candidates.items():
        for s in spans:
            if id(s) in matched_spans or s.end < now:
                continue
            opp = Opportunity(
                id=f"{spot}:{phen}:{int(s.start)}",
                spot=spot,
                phenomenon=phen,
                start=s.start,
                end=s.end,
                peak_score=s.peak_score,
                tier=s.tier,
                alerted_tier=s.tier,
            )
            new_active.append(opp)
            events.append({"type": "detected", "opp": opp, "span": s})

    return new_active, events


def load_state(path: Path) -> list[Opportunity]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [Opportunity(**o) for o in data.get("opportunities", [])]


def save_state(path: Path, active: list[Opportunity]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updated": int(time.time()), "opportunities": [asdict(o) for o in active]}
    path.write_text(json.dumps(payload, indent=1))
