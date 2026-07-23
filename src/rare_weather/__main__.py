"""CLI: rare-weather <command>

  run            one live pass: fetch, update Opportunities, rebuild dashboard, push Exceptional
  digest         one push summarizing today's board (run once each morning); silent if empty
  status         read-only: current best score per (Spot, Phenomenon) vs thresholds
  daemon         run forever on an interval (for Docker); RWA_INTERVAL_MINUTES (default 60)
  backfill       fetch archives, score history, write thresholds + greatest hits
  finish         recompute thresholds + greatest hits from cached daily scores
  test-notify    send a test push through configured channels
"""

from __future__ import annotations

import argparse
import os
import time
import traceback


def main() -> None:
    parser = argparse.ArgumentParser(prog="rare-weather", description=__doc__)
    parser.add_argument(
        "command",
        choices=["run", "digest", "status", "daemon", "backfill", "finish", "test-notify"],
    )
    parser.add_argument("--dry-run", action="store_true", help="print alerts instead of pushing")
    args = parser.parse_args()

    if args.command == "run":
        from .pipeline import run_once

        run_once(dry_run=args.dry_run)
    elif args.command == "digest":
        from .pipeline import digest

        digest(dry_run=args.dry_run)
    elif args.command == "status":
        from .pipeline import status

        status()
    elif args.command == "daemon":
        from datetime import datetime

        from .pipeline import digest, run_once

        interval = int(os.environ.get("RWA_INTERVAL_MINUTES", "60"))
        digest_hour = int(os.environ.get("RWA_DIGEST_HOUR", "6"))  # local hour
        last_digest_day = None
        while True:
            try:
                run_once(dry_run=args.dry_run)
                today = datetime.now().date()
                if datetime.now().hour >= digest_hour and last_digest_day != today:
                    digest(dry_run=args.dry_run)
                    last_digest_day = today
            except Exception:
                traceback.print_exc()
            time.sleep(interval * 60)
    elif args.command == "backfill":
        from . import backfill

        backfill.run()
    elif args.command == "finish":
        from . import backfill

        backfill.finish()
    elif args.command == "test-notify":
        from .config import load_settings
        from .notify import send

        send(
            "Rare Weather Alerts — test",
            "If you can read this, the channel works.",
            "notable",
            load_settings().raw["notify"]["ntfy_url"],
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
