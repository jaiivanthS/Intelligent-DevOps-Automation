#!/usr/bin/env python3
"""Generate the provisioned Grafana dashboards (JSON) from compact Python definitions.

    python monitoring/grafana/build_dashboards.py

Edit this file rather than the generated JSON, then re-run it and commit both.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).parent / "dashboards"
PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}
APP = 'job="demo-app"'
API = 'job="demo-app", route!~"/health|/ready|/metrics"'


class Layout:
    """Places panels left-to-right on Grafana's 24-column grid."""

    def __init__(self) -> None:
        self.x = self.y = self.row_h = 0
        self.next_id = 1

    def place(self, panel: dict, w: int, h: int) -> dict:
        if self.x + w > 24:
            self.x, self.y, self.row_h = 0, self.y + self.row_h, 0
        panel["gridPos"] = {"x": self.x, "y": self.y, "w": w, "h": h}
        panel["id"] = self.next_id
        self.next_id += 1
        self.x += w
        self.row_h = max(self.row_h, h)
        return panel

    def row(self, title: str) -> dict:
        if self.x:
            self.x, self.y, self.row_h = 0, self.y + self.row_h, 0
        panel = {"type": "row", "title": title, "collapsed": False, "panels": []}
        return self.place(panel, 24, 1)


def targets(*exprs: tuple[str, str]) -> list[dict]:
    return [
        {"refId": chr(65 + i), "datasource": PROM, "expr": expr, "legendFormat": legend}
        for i, (expr, legend) in enumerate(exprs)
    ]


def stat(title, expr, unit="short", thresholds=None, decimals=None, mappings=None):
    steps = [{"color": "green", "value": None}] + [
        {"color": c, "value": v} for v, c in (thresholds or [])
    ]
    defaults = {"unit": unit, "thresholds": {"mode": "absolute", "steps": steps}}
    if decimals is not None:
        defaults["decimals"] = decimals
    if mappings:
        defaults["mappings"] = mappings
    return {
        "type": "stat", "title": title, "datasource": PROM,
        "targets": targets((expr, "")),
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "colorMode": "background", "graphMode": "area", "textMode": "auto"},
    }


def timeseries(title, *exprs, unit="short", stack=False, description=""):
    return {
        "type": "timeseries", "title": title, "description": description, "datasource": PROM,
        "targets": targets(*exprs),
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "custom": {"lineWidth": 2, "fillOpacity": 15 if stack else 5,
                           "stacking": {"mode": "normal" if stack else "none"},
                           "showPoints": "never"},
            },
            "overrides": [],
        },
        "options": {"legend": {"displayMode": "list", "placement": "bottom"},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
    }


def logs(title, expr):
    return {
        "type": "logs", "title": title, "datasource": LOKI,
        "targets": [{"refId": "A", "datasource": LOKI, "expr": expr}],
        "options": {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending",
                    "enableLogDetails": True, "prettifyLogMessage": False},
    }


def dashboard(uid, title, panels, tags, refresh="10s"):
    return {
        "uid": uid, "title": title, "tags": tags, "timezone": "browser",
        "schemaVersion": 39, "version": 1, "editable": False, "refresh": refresh,
        "time": {"from": "now-30m", "to": "now"},
        "templating": {"list": []}, "annotations": {"list": [{
            "builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
            "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
            "name": "Annotations & Alerts", "type": "dashboard"}]},
        "panels": panels,
    }


def demo_app_dashboard() -> dict:
    g = Layout()
    up_map = [{"type": "value", "options": {
        "0": {"text": "DOWN", "color": "red"}, "1": {"text": "UP", "color": "green"}}}]
    p = [
        g.row("Service health (RED)"),
        g.place(stat("Status", f"up{{{APP}}}", mappings=up_map,
                     thresholds=[(0, "red"), (1, "green")]), 4, 4),
        g.place(stat("Request rate", f"sum(rate(http_requests_total{{{API}}}[2m]))",
                     unit="reqps", decimals=2), 5, 4),
        g.place(stat("Error ratio (5xx)",
                     "sum(rate(http_requests_total{" + APP + ', status=~"5.."}[2m])) / '
                     "clamp_min(sum(rate(http_requests_total{" + APP + "}[2m])), 1e-9)",
                     unit="percentunit", decimals=1, thresholds=[(0.01, "orange"), (0.05, "red")]),
                5, 4),
        g.place(stat("p95 latency",
                     f"histogram_quantile(0.95, sum by (le) "
                     f"(rate(http_request_duration_seconds_bucket{{{API}}}[2m])))",
                     unit="s", decimals=3, thresholds=[(0.25, "orange"), (0.5, "red")]), 5, 4),
        g.place(stat("inventory-db", f'dependency_up{{{APP}, dependency="inventory-db"}}',
                     mappings=up_map, thresholds=[(0, "red"), (1, "green")]), 5, 4),

        g.place(timeseries("Requests by status",
                           (f"sum by (status) (rate(http_requests_total{{{API}}}[1m]))",
                            "{{status}}"), unit="reqps", stack=True), 12, 8),
        g.place(timeseries("Latency percentiles",
                           *[(f"histogram_quantile({q}, sum by (le) "
                              f"(rate(http_request_duration_seconds_bucket{{{API}}}[1m])))",
                              f"p{int(q * 100)}") for q in (0.5, 0.95, 0.99)],
                           unit="s"), 12, 8),
        g.place(timeseries("Requests by route",
                           (f"sum by (route) (rate(http_requests_total{{{API}}}[1m]))", "{{route}}"),
                           unit="reqps"), 12, 8),
        g.place(timeseries("Error ratio by route",
                           ("sum by (route) (rate(http_requests_total{" + API + ', status=~"5.."}[1m]))'
                            " / clamp_min(sum by (route) (rate(http_requests_total{" + API + "}[1m])), 1e-9)",
                            "{{route}}"), unit="percentunit"), 12, 8),

        g.row("Saturation"),
        g.place(timeseries("Process memory (RSS)",
                           (f"process_resident_memory_bytes{{{APP}}}", "rss"),
                           ("chaos_leaked_memory_bytes{" + APP + "}", "deliberately leaked"),
                           unit="bytes"), 8, 8),
        g.place(timeseries("Process CPU", (f"rate(process_cpu_seconds_total{{{APP}}}[1m])", "cores"),
                           unit="percentunit"), 8, 8),
        g.place(timeseries("In-flight requests", (f"http_requests_in_progress{{{APP}}}", "in flight")),
                8, 8),

        g.row("Failure injection (ground truth for experiments)"),
        g.place(timeseries("Active chaos settings",
                           (f"chaos_injection_active{{{APP}}} > 0", "{{mode}}"),
                           description="Non-zero while a fault is being injected via /chaos."),
                24, 6),

        g.row("Logs"),
        g.place(logs("Errors and warnings",
                     '{service="demo-app", level=~"ERROR|WARNING"}'), 24, 10),
        g.place(logs("All requests", '{service="demo-app", event="http_request"}'), 24, 10),
    ]
    return dashboard("demo-app-overview", "demo-app: Service Overview", p, ["demo-app", "red"])


def infra_dashboard() -> dict:
    g = Layout()
    p = [
        g.row("Hosts (node-exporter)"),
        g.place(timeseries("CPU usage",
                           ('1 - avg by (host) (rate(node_cpu_seconds_total{mode="idle"}[2m]))', "{{host}}"),
                           unit="percentunit"), 12, 8),
        g.place(timeseries("Memory usage",
                           ("1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes", "{{host}}"),
                           unit="percentunit"), 12, 8),
        g.place(timeseries("Root disk used",
                           ('1 - node_filesystem_avail_bytes{mountpoint="/", fstype!~"tmpfs|overlay"}'
                            ' / node_filesystem_size_bytes{mountpoint="/", fstype!~"tmpfs|overlay"}',
                            "{{host}}"), unit="percentunit"), 12, 8),
        g.place(timeseries("Network traffic",
                           ('sum by (host) (rate(node_network_receive_bytes_total{device!~"lo|veth.*|docker.*|br-.*"}[2m]))',
                            "{{host}} in"),
                           ('sum by (host) (rate(node_network_transmit_bytes_total{device!~"lo|veth.*|docker.*|br-.*"}[2m]))',
                            "{{host}} out"), unit="Bps"), 12, 8),

        g.row("Containers (cAdvisor)"),
        g.place(timeseries("Container CPU",
                           ("sum by (name) (rate(container_cpu_usage_seconds_total[2m]))", "{{name}}"),
                           unit="percentunit"), 12, 8),
        g.place(timeseries("Container memory (working set)",
                           ("sum by (name) (container_memory_working_set_bytes)", "{{name}}"),
                           unit="bytes"), 12, 8),

        g.row("Platform"),
        g.place(timeseries("Scrape targets up",
                           ("up", "{{job}} {{instance}}")), 12, 8),
        g.place(timeseries("Firing alerts",
                           ('sum by (alertname, severity) (ALERTS{alertstate="firing"})',
                            "{{alertname}} ({{severity}})")), 12, 8),
    ]
    return dashboard("infrastructure", "Infrastructure: Hosts & Containers", p,
                     ["infrastructure"], refresh="30s")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for d in (demo_app_dashboard(), infra_dashboard()):
        path = OUT / f"{d['uid']}.json"
        path.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path} ({len(d['panels'])} panels)")


if __name__ == "__main__":
    main()
