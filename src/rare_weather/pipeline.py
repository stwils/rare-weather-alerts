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


def _age(seconds: float) -> str:
    """Rough human duration: '3 hours', '2 days'."""
    hours = seconds / 3600
    if hours < 1:
        return f"{int(seconds // 60)} minutes"
    if hours < 48:
        n = round(hours)
        return f"{n} hour{'s' if n != 1 else ''}"
    return f"{round(hours / 24)} days"


def _dashboard_url(cfg: Settings, anchor: str | None = None) -> str | None:
    base = os.environ.get("DASHBOARD_URL") or cfg.raw["notify"].get("dashboard_url")
    if not base:
        return None
    base = base.rstrip("/")
    return f"{base}/#{anchor}" if anchor else base


def _collect(cfg: Settings, spots: list[Spot]) -> tuple[dict[str, dict], list[str]]:
    """Fetch + score every spot, tolerating individual failures.

    Returns ({spot_id: {"hours": h, "scores": {phen: [..]}}}, failed_spot_ids).
    One unreachable Spot out of two dozen must not cost the whole pass — the
    caller decides whether too many failed to trust the result.
    """
    out: dict[str, dict] = {}
    failed: list[str] = []
    for spot in spots:
        variables = sorted({v for p in spot.phenomena for v in MODELS[p].VARIABLES})
        try:
            raw = openmeteo.fetch_forecast(
                spot.latitude, spot.longitude, variables, cfg.forecast_days, cfg.timezone
            )
            h = hours.prepare(raw, spot.latitude, spot.longitude, cfg.timezone)
        except Exception as exc:  # noqa: BLE001 — any failure is one spot's failure
            print(f"  ! {spot.id}: forecast unavailable ({type(exc).__name__}: {exc})")
            failed.append(spot.id)
            continue
        out[spot.id] = {
            "hours": h,
            "scores": {p: MODELS[p].score_hours(h) for p in spot.phenomena},
        }
    return out, failed


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

    collected, failed = _collect(cfg, spots)
    # Too many failures and the remaining picture isn't worth acting on: every
    # missing Spot looks like a vanished forecast, so publishing would hollow
    # out the board. Fail loudly and leave state untouched for the next pass.
    max_fraction = cfg.raw.get("max_spot_failure_fraction", 0.34)
    if failed and len(failed) > max_fraction * len(spots):
        raise RuntimeError(
            f"{len(failed)}/{len(spots)} spot forecasts unavailable "
            f"({', '.join(failed)}) — aborting without touching state"
        )
    if failed:
        print(f"continuing without {len(failed)} spot(s): {', '.join(failed)}")

    candidates: dict[tuple[str, str], list[opportunities.Span]] = {}
    for spot in spots:
        c = collected.get(spot.id)
        if c is None:
            continue  # fetch failed; held below rather than treated as "gone"
        h = c["hours"]
        for phen, scores in c["scores"].items():
            rt = thresholds.regional_for(thr, phen)
            if rt is None:
                continue  # no baseline yet — backfill hasn't covered this phenomenon
            spans = opportunities.spans_from_scores(
                h["time"], scores, rt["notable"], rt["exceptional"], cfg.merge_gap_hours
            )
            if spans:
                candidates[(spot.id, phen)] = spans

    # Opportunities at a Spot we couldn't reach are held, not cancelled.
    reconcilable, held = opportunities.partition_unknown(active, set(failed), now)
    active, events = opportunities.reconcile(reconcilable, candidates, now, cfg.merge_gap_hours)
    active.extend(held)

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

    data = dashboard.build_data(cfg, spots, thr, active, collected, now, archive, failed)
    if not dry_run:
        dashboard.write_site(cfg, data)
        opportunities.save_state(state_path, active, archive)  # dry run must not consume state

    n_exc = sum(1 for o in active if o.tier == "exceptional")
    print(
        f"{len(active)} active opportunities ({n_exc} exceptional); "
        f"{len(pushable)} pushed this run"
        + (f"; {len(held)} held behind failed fetches" if held else "")
    )


def digest(dry_run: bool = False, force: bool = False) -> None:
    """One morning push summarizing the day's board. Sent every morning, even
    when nothing qualifies (an explicit "nothing rare today").

    Gated on the *local* hour rather than a UTC cron, so the briefing doesn't
    slide an hour when daylight saving ends. Callers that do their own
    scheduling (the Docker daemon, a manual run) pass force=True.
    """
    cfg = load_settings()
    tz = cfg.timezone
    now = time.time()

    digest_hour = int(os.environ.get("RWA_DIGEST_HOUR", cfg.raw.get("digest_hour", 6)))
    local_hour = datetime.fromtimestamp(now, ZoneInfo(tz)).hour
    if not force and local_hour != digest_hour:
        print(f"not the digest hour (local {local_hour:02d}:00, want {digest_hour:02d}:00) — skipping")
        return

    state_path = cfg.path("state")
    spot_by_id = {s.id: s for s in load_spots()}
    active = opportunities.load_state(state_path)
    horizon = now + 24 * 3600

    # A quiet board is the normal case, so it can't be trusted without knowing
    # the pipeline actually ran. Report the outage instead of "nothing rare".
    stale_after = cfg.raw.get("stale_after_hours", 6) * 3600
    updated = opportunities.load_updated(state_path)
    if updated is None or now - updated > stale_after:
        age = "never" if updated is None else _age(now - updated)
        when = (
            ""
            if updated is None
            else f" (last good pass {datetime.fromtimestamp(updated, ZoneInfo(tz)):%a %b %-d, %H:%M})"
        )
        notify.send(
            "⚠️ Rare Weather Alerts — not updating",
            f"The hourly pass hasn't succeeded in {age}{when}.\n"
            "Today's board is stale; treat a quiet dashboard as unknown, not calm.",
            "notable",
            cfg.raw["notify"]["ntfy_url"],
            dry_run,
            click_url=_dashboard_url(cfg),
        )
        return

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
    collected, failed = _collect(cfg, spots)
    tz = cfg.timezone

    rows = []
    for spot in spots:
        c = collected.get(spot.id)
        if c is None:
            continue
        h = c["hours"]
        for phen, scores in c["scores"].items():
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
    if failed:
        print(f"\nforecast unavailable for {len(failed)} spot(s): {', '.join(failed)}")
