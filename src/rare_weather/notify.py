"""Push delivery: ntfy.sh and Pushover, priority mapped to tier.

Channels are configured by environment variables; a missing variable simply
disables that channel (logged, not fatal):
  NTFY_TOPIC       ntfy.sh topic name
  PUSHOVER_TOKEN   Pushover application token
  PUSHOVER_USER    Pushover user key
"""

from __future__ import annotations

import os

import requests

# tier -> (ntfy priority 1-5, pushover priority -2..2)
PRIORITIES = {
    "exceptional": (4, 0),  # high/prominent, but no Do-Not-Disturb bypass or urgent alarm
    "notable": (3, 0),      # default priority (used by the daily digest)
}


def send(
    title: str,
    body: str,
    tier: str,
    ntfy_url: str,
    dry_run: bool = False,
    click_url: str | None = None,
) -> None:
    ntfy_prio, po_prio = PRIORITIES[tier]
    if dry_run:
        print(f"[dry-run] ({tier}) {title}\n{body}\n{click_url or ''}\n")
        return

    sent = []
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        # JSON publish endpoint, not headers: titles contain emoji/em-dashes,
        # and HTTP headers are latin-1 only.
        payload = {
            "topic": topic,
            "title": title,
            "message": body,
            "priority": ntfy_prio,
            "tags": ["camera"],
        }
        if click_url:
            payload["click"] = click_url
        requests.post(ntfy_url, json=payload, timeout=30).raise_for_status()
        sent.append("ntfy")

    po_token = os.environ.get("PUSHOVER_TOKEN")
    po_user = os.environ.get("PUSHOVER_USER")
    if po_token and po_user:
        data = {
            "token": po_token,
            "user": po_user,
            "title": title,
            "message": body,
            "priority": po_prio,
        }
        if click_url:
            data["url"] = click_url
            data["url_title"] = "Open map"
        requests.post(
            "https://api.pushover.net/1/messages.json", data=data, timeout=30
        ).raise_for_status()
        sent.append("pushover")

    print(f"sent via {sent or 'no channels configured'}: {title}")
