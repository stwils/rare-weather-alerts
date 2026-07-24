"""Live pipeline.

`run_once` fetches forecasts for every Spot, scores every tagged Phenomenon,
reconciles Opportunities against state, regenerates the dashboard, and pushes —
but only for Exceptional-tier lifecycle changes (regional top 0.5%). Notable
Opportunities are tracked and shown on the dashboard, and summarized once a day
by `digest`. `status` is a read-only console view for tuning.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import dashboard, hours, notify, openmeteo, opportunities, thresholds
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


def _dashboard_url(cfg: Settings, anchor: str | None = None) -> str | None:
    base = os.environ.get("DASHBOARD_URL") or cfg.raw["notify"].get("dashboard_url")
    if not base:
        return None
    base = base.rstrip("/")
    return f"{base}/#{anchor}" if anchor else base


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
    archive = opportunities.load_archive(state_path)
    now = time.time()
    tz = cfg.timezone

    collected = _collect(cfg, spots)
    candidates: dict[tuple[str, str], list[opportunities.Span]] = {}
    for spot in spots:
        h = collected[spot.id]["hours"]
        for phen, scores in collected[spot.id]["scores"].items():
            rt = thresholds.regional_for(thr, phen)
            if rt is None:
                continue  # no baseline yet — backfill hasn't covered this phenomenon
            spans = opportunities.spans_from_scores(
                h["time"], scores, rt["notable"], rt["exceptional"], cfg.merge_gap_hours
            )
            if spans:
                candidates[(spot.id, phen)] = spans

    active, events = opportunities.reconcile(active, candidates, now, cfg.merge_gap_hours)

    # Archive opportunities that just left the active set (cancelled or elapsed),
    # and prune the history to the retention window.
    retention = cfg.raw.get("archive_retention_hours", 72) * 3600
    for e in events:
        if e["type"] in ("cancelled", "expired"):
            o = e["opp"]
            archive.append(
                {
                    "spot": o.spot,
                    "phenomenon": o.phenomenon,
                    "start": o.start,
                    "end": o.end,
                    "peak_score": o.peak_score,
                    "tier": o.tier,
                    "outcome": "cancelled" if e["type"] == "cancelled" else "ended",
                    "archived_at": now,
                }
            )
    archive = [a for a in archive if now - a["archived_at"] <= retention]
    archive.sort(key=lambda a: a["archived_at"], reverse=True)

    # Push only Exceptional cancellations/detections/upgrades; never plain expiry.
    pushable = [
        e
        for e in events
        if e["type"] in ("detected", "upgraded", "cancelled")
        and e["opp"].alerted_tier == "exceptional"
    ]
    for group in _coalesce(pushable, cfg.coalesce_gap_hours):
        group.sort(key=lambda e: e["opp"].peak_score, reverse=True)
        best = group[0]
        opp, span, etype = best["opp"], best["span"], best["type"]
        model = MODELS[opp.phenomenon]
        spot = spot_by_id[opp.spot]
        others = ", ".join(spot_by_id[e["opp"].spot].name for e in group[1:])

        if etype == "cancelled":
            title = f"{model.EMOJI} {model.LABEL} cancelled — {spot.name}"
            body = f"The Exceptional window {_fmt_window(opp.start, opp.end, tz)} no longer holds."
        else:
            verb = "upgraded to " if etype == "upgraded" else ""
            title = f"{model.EMOJI} {model.LABEL} {verb}EXCEPTIONAL — {spot.name}"
            body = (
                f"{_fmt_window(opp.start, opp.end, tz)} · peak score {opp.peak_score:.2f}\n"
                f"{model.explain(collected[opp.spot]['hours'], span.peak_index)}"
            )
        if others:
            body += f"\nAlso: {others}"
        notify.send(
            title, body, "exceptional", cfg.raw["notify"]["ntfy_url"], dry_run,
            click_url=_dashboard_url(cfg, dashboard.anchor(opp.spot, opp.phenomenon)),
        )

    data = dashboard.build_data(cfg, spots, thr, active, collected, now, archive)
    if not dry_run:
        dashboard.write_site(cfg, data)
        opportunities.save_state(state_path, active, archive)  # dry run must not consume state

    n_exc = sum(1 for o in active if o.tier == "exceptional")
    print(
        f"{len(active)} active opportunities ({n_exc} exceptional); "
        f"{len(pushable)} pushed this run"
    )


def digest(dry_run: bool = False) -> None:
    """One morning push summarizing the day's board. Sent every morning, even
    when nothing qualifies (an explicit "nothing rare today")."""
    cfg = load_settings()
    spot_by_id = {s.id: s for s in load_spots()}
    active = opportunities.load_state(cfg.path("state"))
    now = time.time()
    tz = cfg.timezone
    horizon = now + 24 * 3600

    todays = [o for o in active if o.start <= horizon and o.end >= now]
    if not todays:
        title = "🌦 Today's board — nothing rare"
        body = "No notable opportunities in the next 24 hours."
    else:
        todays.sort(key=lambda o: (o.tier != "exceptional", o.start))
        lines = [
            f"{MODELS[o.phenomenon].EMOJI} {MODELS[o.phenomenon].LABEL} {TIER_LABEL[o.tier]} — "
            f"{spot_by_id[o.spot].name}, {_fmt_window(o.start, o.end, tz)}"
            for o in todays
        ]
        n = len(todays)
        title = f"🌦 Today's board — {n} opportunit{'y' if n == 1 else 'ies'}"
        body = "\n".join(lines)

    notify.send(
        title, body, "notable", cfg.raw["notify"]["ntfy_url"], dry_run,
        click_url=_dashboard_url(cfg),
    )


def status() -> None:
    """Print every (Spot, Phenomenon)'s best upcoming hour vs regional thresholds."""
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
            rt = thresholds.regional_for(thr, phen) or {}
            tier = (
                "EXCEPTIONAL"
                if scores[i] >= rt.get("exceptional", 9)
                else "Notable"
                if scores[i] >= rt.get("notable", 9)
                else ""
            )
            rows.append((scores[i], spot.name, phen, h["time"][i], tier, rt))
    rows.sort(reverse=True)

    print(f"{'score':>5}  {'tier':<12} {'spot':<26} {'phenomenon':<15} {'best hour':<18} {'reg n/e'}")
    for score, name, phen, epoch, tier, rt in rows:
        when = datetime.fromtimestamp(epoch, ZoneInfo(tz)).strftime("%a %H:%M")
        thr_s = f"{rt.get('notable', 0):.2f}/{rt.get('exceptional', 0):.2f}" if rt else "—"
        print(f"{score:5.2f}  {tier:<12} {name:<26} {phen:<15} {when:<18} {thr_s}")
