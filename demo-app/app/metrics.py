"""Prometheus metrics exposed on /metrics.

Metrics are module-level because prometheus_client registers them globally;
creating them per app instance would raise duplicate-registration errors.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, Info

APP_INFO = Info("app", "Static information about the running build")

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "route", "status"],
)

HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

HTTP_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "HTTP requests currently being served",
)

INVENTORY_ITEMS = Gauge("inventory_items", "Number of items in the inventory store")

DEPENDENCY_UP = Gauge(
    "dependency_up",
    "1 if a downstream dependency is reachable, 0 otherwise",
    ["dependency"],
)

CHAOS_ACTIVE = Gauge(
    "chaos_injection_active",
    "Currently configured failure injection (0 = off)",
    ["mode"],
)

LEAKED_BYTES = Gauge(
    "chaos_leaked_memory_bytes",
    "Memory deliberately retained by the memory-leak failure mode",
)
