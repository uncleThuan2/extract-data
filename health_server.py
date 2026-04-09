"""Minimal HTTP health server to keep the process alive on Render/Railway free tier.

Run alongside the bot. An external service (UptimeRobot, cron-job.org) pings
GET /health every 5 minutes → server stays awake, never sleeps.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

logger = logging.getLogger(__name__)

_start_time = datetime.now(timezone.utc)


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/health", "/ping"):
            uptime_sec = int(
                (datetime.now(timezone.utc) - _start_time).total_seconds()
            )
            body = json.dumps(
                {
                    "status": "ok",
                    "uptime_seconds": uptime_sec,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        # Suppress default access logs to reduce noise
        pass


def start_health_server(port: int | None = None) -> threading.Thread:
    """Start the health HTTP server in a daemon thread.

    Port is read from the PORT env var (Render injects this automatically),
    falling back to the provided port argument, then 8080.
    """
    resolved_port = int(os.getenv("PORT", str(port or 8080)))
    server = HTTPServer(("0.0.0.0", resolved_port), _HealthHandler)

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
        name="health-server",
    )
    thread.start()
    logger.info("Health server running on port %d → GET /health", resolved_port)
    return thread
