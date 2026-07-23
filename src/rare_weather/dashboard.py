"""Render the static dashboard published to GitHub Pages.

One self-contained HTML file (no external assets), regenerated every run:
  - Active Opportunities (Notable+), each anchored for deep-linking from alerts
  - The full board: every (Spot, Phenomenon)'s best upcoming hour vs the
    regional thresholds, so near-misses are visible too

A sibling data.json carries the same content for any future programmatic use.
"""

from __future__ import annotations

import html
import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Settings, Spot
from .scores import MODELS

TIER_BADGE = {"exceptional": ("EXCEPTIONAL", "#b45309"), "notable": ("Notable", "#2563eb")}


def anchor(spot_id: str, phenomenon: str) -> str:
    return f"{spot_id}--{phenomenon}"


def _fmt_window(start: float, end: float, tz: str) -> str:
    zi = ZoneInfo(tz)
    s, e = datetime.fromtimestamp(start, zi), datetime.fromtimestamp(end, zi)
    day = s.strftime("%a %b %-d")
    if s.date() != e.date():
        return f"{day} {s:%H:%M} – {e.strftime('%a')} {e:%H:%M}"
    return f"{day} {s:%H:%M}–{e:%H:%M}"


def build_data(
    cfg: Settings,
    spots: list[Spot],
    thr: dict,
    active: list,
    collected: dict,
    now: float,
) -> dict:
    spot_by_id = {s.id: s for s in spots}
    tz = cfg.timezone

    opps = []
    for o in sorted(active, key=lambda o: (o.tier != "exceptional", o.start)):
        spot = spot_by_id[o.spot]
        model = MODELS[o.phenomenon]
        # driver text at the opportunity's peak hour, if we scored this run
        drivers = ""
        c = collected.get(o.spot)
        if c:
            scores = c["scores"].get(o.phenomenon, [])
            if scores:
                i = max(range(len(scores)), key=scores.__getitem__)
                drivers = model.explain(c["hours"], i)
        opps.append(
            {
                "anchor": anchor(o.spot, o.phenomenon),
                "phenomenon": o.phenomenon,
                "label": model.LABEL,
                "emoji": model.EMOJI,
                "tier": o.tier,
                "spot": spot.name,
                "spot_id": o.spot,
                "lat": spot.latitude,
                "lon": spot.longitude,
                "window": _fmt_window(o.start, o.end, tz),
                "start": o.start,
                "end": o.end,
                "peak_score": round(o.peak_score, 3),
                "drivers": drivers,
            }
        )

    board = []
    for spot in spots:
        c = collected.get(spot.id)
        if not c:
            continue
        for phen, scores in c["scores"].items():
            i = max(range(len(scores)), key=scores.__getitem__)
            rt = thr.get("_regional", {}).get(phen, {})
            board.append(
                {
                    "spot": spot.name,
                    "phenomenon": phen,
                    "label": MODELS[phen].LABEL,
                    "score": round(scores[i], 3),
                    "when": datetime.fromtimestamp(c["hours"]["time"][i], ZoneInfo(tz)).strftime(
                        "%a %H:%M"
                    ),
                    "notable": round(rt.get("notable", 0), 3),
                    "exceptional": round(rt.get("exceptional", 0), 3),
                }
            )
    board.sort(key=lambda r: r["score"], reverse=True)

    return {
        "generated": int(now),
        "generated_str": datetime.fromtimestamp(now, ZoneInfo(tz)).strftime("%a %b %-d, %H:%M %Z"),
        "home": cfg.raw["home_base"]["name"],
        "opportunities": opps,
        "board": board,
    }


def _esc(s: str) -> str:
    return html.escape(str(s))


def render_html(data: dict) -> str:
    op_cards = []
    if not data["opportunities"]:
        op_cards.append(
            '<p class="empty">No active opportunities in the forecast window. '
            "Rare should feel rare — check back tomorrow.</p>"
        )
    for o in data["opportunities"]:
        label, color = TIER_BADGE[o["tier"]]
        maps = f'https://maps.google.com/?q={o["lat"]},{o["lon"]}'
        others = ""
        drivers = f'<div class="drivers">{_esc(o["drivers"])}</div>' if o["drivers"] else ""
        op_cards.append(
            f"""<article class="opp" id="{_esc(o['anchor'])}">
  <div class="opp-head">
    <span class="emoji">{o['emoji']}</span>
    <span class="phen">{_esc(o['label'])}</span>
    <span class="badge" style="background:{color}">{label}</span>
  </div>
  <div class="spot"><a href="{maps}" target="_blank" rel="noopener">{_esc(o['spot'])} ↗</a></div>
  <div class="window">{_esc(o['window'])} · peak {o['peak_score']:.2f}</div>
  {drivers}
</article>"""
        )

    board_rows = []
    for r in data["board"]:
        tier_cls = (
            "exceptional"
            if r["score"] >= r["exceptional"] and r["exceptional"] > 0
            else "notable"
            if r["score"] >= r["notable"] and r["notable"] > 0
            else ""
        )
        board_rows.append(
            f"<tr class='{tier_cls}'><td>{r['score']:.2f}</td><td>{_esc(r['label'])}</td>"
            f"<td>{_esc(r['spot'])}</td><td>{_esc(r['when'])}</td>"
            f"<td class='thr'>{r['notable']:.2f} / {r['exceptional']:.2f}</td></tr>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rare Weather Alerts — {_esc(data['home'])}</title>
<style>
  :root {{ color-scheme: light dark; --bg:#fff; --fg:#111; --muted:#666; --card:#f6f7f9; --line:#e3e5e9; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0f1115; --fg:#e8eaed; --muted:#9aa0a6; --card:#1a1d23; --line:#2a2e37; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         background:var(--bg); color:var(--fg); }}
  header {{ padding:20px 16px 8px; }}
  h1 {{ font-size:1.3rem; margin:0 0 2px; }}
  .sub {{ color:var(--muted); font-size:.85rem; }}
  main {{ max-width:760px; margin:0 auto; padding:8px 16px 48px; }}
  h2 {{ font-size:.8rem; text-transform:uppercase; letter-spacing:.05em; color:var(--muted);
       margin:28px 0 10px; }}
  .opp {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
         padding:14px 16px; margin:10px 0; scroll-margin-top:16px; }}
  .opp:target {{ outline:2px solid #b45309; }}
  .opp-head {{ display:flex; align-items:center; gap:8px; }}
  .emoji {{ font-size:1.3rem; }}
  .phen {{ font-weight:600; }}
  .badge {{ margin-left:auto; color:#fff; font-size:.68rem; font-weight:700; padding:2px 8px;
           border-radius:999px; letter-spacing:.03em; }}
  .spot a {{ color:inherit; text-decoration:none; font-size:1.05rem; }}
  .window {{ color:var(--muted); font-size:.9rem; margin-top:2px; }}
  .drivers {{ color:var(--muted); font-size:.82rem; margin-top:6px; font-variant-numeric:tabular-nums; }}
  .empty {{ color:var(--muted); }}
  table {{ width:100%; border-collapse:collapse; font-size:.85rem; }}
  th,td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line);
          font-variant-numeric:tabular-nums; }}
  th {{ color:var(--muted); font-weight:600; font-size:.72rem; text-transform:uppercase; }}
  tr.notable td:first-child {{ color:#2563eb; font-weight:700; }}
  tr.exceptional td:first-child {{ color:#b45309; font-weight:700; }}
  td.thr {{ color:var(--muted); }}
  footer {{ color:var(--muted); font-size:.75rem; padding:24px 16px; text-align:center; }}
</style>
</head>
<body>
<header>
  <h1>🌦 Rare Weather Alerts</h1>
  <div class="sub">{_esc(data['home'])} · updated {_esc(data['generated_str'])}</div>
</header>
<main>
  <h2>Active opportunities</h2>
  {''.join(op_cards)}
  <h2>Full board · best upcoming hour per spot</h2>
  <table>
    <thead><tr><th>Score</th><th>Phenomenon</th><th>Spot</th><th>Best hour</th><th>Reg. n / e</th></tr></thead>
    <tbody>{''.join(board_rows)}</tbody>
  </table>
</main>
<footer>Rarity is judged against 10 years of regional history. Exceptional = regional top 0.5%.</footer>
</body>
</html>"""


def write_site(cfg: Settings, data: dict) -> Path:
    site = cfg.path("site")
    site.mkdir(parents=True, exist_ok=True)
    (site / "index.html").write_text(render_html(data))
    (site / "data.json").write_text(json.dumps(data, indent=1))
    return site
