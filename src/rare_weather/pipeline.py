"""Live pipeline: fetch forecasts for every Spot, score every tagged
Phenomenon, reconcile Opportunities against state, coalesce lifecycle events
into pushes. Also `status`, a read-only view of the same scores for tuning."""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import hours, notify, openmeteo, opportunities, thresholds
from .config import Settings, Spot, load_settings, load_spots
from .scores import MODELS

TIER_LABEL = {"notable": "Notable", "exceptional": "EXCEPTIONAL"}


def _fmt_window(start: float, end: float, tz: str) -> str:
    zi = ZoneInfo(tz)
    s, e = datetime.fromtimestamp(start, zi), datetime.fromtimestamp(end, zi)
    day = s.strftime("%a %b %-d")
    if s.date() != e.date():
        return f"{day} {s:%H:%M} – {e.strftime('%a')} {e:%H:%M}"
    return f"{day} {s:%H:%M}–{e:%H:%M}"


def _maps_url(spot: Spot) -> str:
    return f"https://maps.google.com/?q={spot.latitude},{spot.longitude}"


def _collect(cfg: Settings, spots: list[Spot]) -> dict[str, dict]:
    """Fetch + score every spot. Returns {spot_id: {"hours": h, "scores": {phen: [..]}}}."""
    out: dict[str, dict] = {}
    for spot in spots:
        variables = sorted({v for p in spot.phenomena for v in MODELS[p].VARIABLES})
        raw = openmeteo.fetch_forecast(
            spot.latitude, spot.longitude, variables, cfg.forecast_days, cfg.timezone
        )
        h = hours.prepare(raw, spot.latitude, spot.longitude, cfg.timezone)
        out[spot.id] = {
            "hours": h,
            "scores": {p: MODELS[p].score_hours(h) for p in spot.phenomena},
        }
    return out


def _coalesce(events: list[dict], gap_hours: float) -> list[list[dict]]:
    """Group same-phenomenon, same-type events whose windows are near each other."""
    groups: list[list[dict]] = []
    for ev in sorted(events, key=lambda e: (e["opp"].phenomenon, e["type"], e["opp"].start)):
        g = next(
            (
                g
                for g in groups
                if g[0]["opp"].phenomenon == ev["opp"].phenomenon
                and g[0]["type"] == ev["type"]
                and any(
                    ev["opp"].start - gap_hours * 3600 <= o["opp"].end
                    and ev["opp"].end + gap_hours * 3600 >= o["opp"].start
                    for o in g
                )
            ),
            None,
        )
        (g.append(ev) if g else groups.append([ev]))
    return groups


def run_once(dry_run: bool = False) -> None:
    cfg = load_settings()
    spots = load_spots()
    spot_by_id = {s.id: s for s in spots}
    thr = thresholds.load(cfg.path("thresholds"))
    state_path = cfg.path("state")
    active = opportunities.load_state(state_path)
    now = time.time()
    tz = cfg.timezone

    collected = _collect(cfg, spots)
    candidates: dict[tuple[str, str], list[opportunities.Span]] = {}
    for spot in spots:
        h = collected[spot.id]["hours"]
        for phen, scores in collected[spot.id]["scores"].items():
            t = thr.get(spot.id, {}).get(phen)
            if t is None:
                continue  # no baseline yet — backfill hasn't covered this pair
            spans = opportunities.spans_from_scores(
                h["time"], scores, t["notable"], t["exceptional"], cfg.merge_gap_hours
            )
            if spans:
                candidates[(spot.id, phen)] = spans

    active, events = opportunities.reconcile(active, candidates, now, cfg.merge_gap_hours)

    for group in _coalesce(events, cfg.coalesce_gap_hours):
        group.sort(key=lambda e: e["opp"].peak_score, reverse=True)
        best = group[0]
        opp, span, etype = best["opp"], best["span"], best["type"]
        model = MODELS[opp.phenomenon]
        spot = spot_by_id[opp.spot]
        others = ", ".join(spot_by_id[e["opp"].spot].name for e in group[1:])

        if etype == "cancelled":
            title = f"{model.EMOJI} {model.LABEL} cancelled — {spot.name}"
            body = f"The {TIER_LABEL[opp.alerted_tier]} window {_fmt_window(opp.start, opp.end, tz)} no longer holds."
        else:
            verb = "upgraded to" if etype == "upgraded" else ""
            title = f"{model.EMOJI} {model.LABEL} {verb} {TIER_LABEL[opp.tier]} — {spot.name}".replace("  ", " ")
            body = (
                f"{_fmt_window(opp.start, opp.end, tz)} · peak score {opp.peak_score:.2f}\n"
                f"{model.explain(collected[opp.spot]['hours'], span.peak_index)}"
            )
        if others:
            body += f"\nAlso: {others}"
        notify.send(
            title, body, opp.alerted_tier, cfg.raw["notify"]["ntfy_url"], dry_run,
            click_url=_maps_url(spot),
        )

    if not events:
        print(f"no lifecycle changes; {len(active)} active opportunities")
    if not dry_run:  # a dry run must not consume the detections it previews
        opportunities.save_state(state_path, active)


def status() -> None:
    """Print every (Spot, Phenomenon)'s best upcoming hour vs its thresholds."""
    cfg = load_settings()
    spots = load_spots()
    try:
        thr = thresholds.load(cfg.path("thresholds"))
    except FileNotFoundError:
        thr = {}
    collected = _collect(cfg, spots)
    tz = cfg.timezone

    rows = []
    for spot in spots:
        h = collected[spot.id]["hours"]
        for phen, scores in collected[spot.id]["scores"].items():
            i = max(range(len(scores)), key=scores.__getitem__)
            t = thr.get(spot.id, {}).get(phen, {})
            tier = (
                "EXCEPTIONAL"
                if scores[i] >= t.get("exceptional", 9)
                else "Notable"
                if scores[i] >= t.get("notable", 9)
                else ""
            )
            rows.append((scores[i], spot.name, phen, h["time"][i], tier, t))
    rows.sort(reverse=True)

    print(f"{'score':>5}  {'tier':<12} {'spot':<26} {'phenomenon':<15} {'best hour':<18} {'thresholds n/e'}")
    for score, name, phen, epoch, tier, t in rows:
        when = datetime.fromtimestamp(epoch, ZoneInfo(tz)).strftime("%a %H:%M")
        thr_s = f"{t.get('notable', 0):.2f}/{t.get('exceptional', 0):.2f}" if t else "—"
        print(f"{score:5.2f}  {tier:<12} {name:<26} {phen:<15} {when:<18} {thr_s}")
