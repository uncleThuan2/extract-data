#!/usr/bin/env python3
"""Entry point – run the Telegram bot.

Also starts a lightweight HTTP health server on PORT (default 8080) so that:
- Render.com can detect the process as a "Web Service" (free tier, no sleep)
- UptimeRobot / cron-job.org can ping GET /health every 5 min to keep it awake
"""

from __future__ import annotations

import argparse
import logging

from health_server import start_health_server

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    parser = argparse.ArgumentParser(description="Document Q&A Telegram Bot")
    parser.add_argument(
        "--no-health",
        action="store_true",
        help="Disable the health HTTP server (for local dev)",
    )
    args = parser.parse_args()

    if not args.no_health:
        start_health_server()

    from bot.telegram_bot import main as run_telegram
    run_telegram()


if __name__ == "__main__":
    main()
