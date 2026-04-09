#!/usr/bin/env python3
"""Entry point – run Discord bot, Telegram bot, or both concurrently.

Also starts a lightweight HTTP health server on PORT (default 8080) so that:
- Render.com can detect the process as a "Web Service" (free tier, no sleep)
- UptimeRobot / cron-job.org can ping GET /health every 5 min to keep it awake
"""

from __future__ import annotations

import argparse
import logging
import os
import threading

from health_server import start_health_server

logger = logging.getLogger(__name__)


def _run_discord() -> None:
    from bot.discord_bot import main as run_discord
    run_discord()


def _run_telegram() -> None:
    from bot.telegram_bot import main as run_telegram
    run_telegram()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    parser = argparse.ArgumentParser(description="Document Q&A Bot")
    parser.add_argument(
        "platform",
        choices=["discord", "telegram", "both"],
        help="Which bot platform(s) to run",
    )
    parser.add_argument(
        "--no-health",
        action="store_true",
        help="Disable the health HTTP server (for local dev)",
    )
    args = parser.parse_args()

    # Start health server unless explicitly disabled
    if not args.no_health:
        start_health_server()

    if args.platform == "discord":
        _run_discord()

    elif args.platform == "telegram":
        _run_telegram()

    elif args.platform == "both":
        # Run Discord in a background thread, Telegram in main thread
        discord_thread = threading.Thread(target=_run_discord, daemon=True, name="discord")
        discord_thread.start()
        logger.info("Discord bot started in background thread")
        _run_telegram()  # blocks main thread


if __name__ == "__main__":
    main()
