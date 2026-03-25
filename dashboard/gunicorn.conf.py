"""
Gunicorn configuration for the pxmx-clusters dashboard.

Workers are kept at 2 (stateless per-request + in-process TTL cache is
shared within a single process but intentionally simple); increase if you
need more throughput.  The GitHub API round-trip dominates latency, so
gevent workers are not required.
"""

import multiprocessing
import os

# ── Binding ────────────────────────────────────────────────────────────────────
bind    = f"0.0.0.0:{os.environ.get('PORT', '5001')}"
backlog = 64

# ── Workers ───────────────────────────────────────────────────────────────────
# Flask app uses an in-process TTL cache that is NOT shared across processes.
# Keep workers=1 for cache coherence; bump to 2-4 with an external cache (Redis).
workers     = int(os.environ.get("GUNICORN_WORKERS", 1))
worker_class = "sync"
threads      = int(os.environ.get("GUNICORN_THREADS", 4))

# ── Timeouts ──────────────────────────────────────────────────────────────────
# GitHub API calls have a 10 s request timeout inside the app; 60 s here
# gives plenty of headroom.
timeout       = 60
graceful_timeout = 30
keepalive     = 5

# ── Logging ───────────────────────────────────────────────────────────────────
accesslog  = "-"   # stdout
errorlog   = "-"   # stderr
loglevel   = os.environ.get("LOG_LEVEL", "info")
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(D)sµs'

# ── Security ──────────────────────────────────────────────────────────────────
# Prevents the server header from leaking the Gunicorn version
server_software = "gunicorn"

# ── Lifecycle hooks ───────────────────────────────────────────────────────────
def on_starting(server):  # noqa: D401
    server.log.info("pxmx-dashboard starting on %s", bind)
