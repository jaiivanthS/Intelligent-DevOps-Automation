"""Steady, realistic background traffic for demo-app (standard library only).

Mix: 70% list items, 20% get one item, 5% create, 5% delete what we created.
Env: TARGET (default http://demo-app:8000), RPS (default 2).
Prints a one-line summary every 60 s; never exits on errors.
"""

import json
import os
import random
import time
import urllib.error
import urllib.request
from collections import Counter

TARGET = os.getenv("TARGET", "http://demo-app:8000").rstrip("/")
RPS = max(0.1, float(os.getenv("RPS", "2")))
REPORT_EVERY = float(os.getenv("REPORT_EVERY", "60"))
DURATION = float(os.getenv("DURATION", "0"))  # 0 = run forever (used by tests)


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(TARGET + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (urllib.error.URLError, OSError):
        return 0, b""  # connection error / app down


def main():
    stats, created = Counter(), []
    started = last_report = time.monotonic()
    print(f"loadgen -> {TARGET} at {RPS} req/s", flush=True)
    while True:
        roll = random.random()  # noqa: S311
        if roll < 0.70:
            status, _ = call("GET", "/api/items")
        elif roll < 0.90:
            status, _ = call("GET", f"/api/items/{random.randint(1, 3)}")  # noqa: S311
        elif roll < 0.95 or not created:
            status, body = call("POST", "/api/items",
                                {"name": "loadgen", "quantity": 1, "price": 1.0})
            if status == 201:
                created.append(json.loads(body)["id"])
        else:
            status, _ = call("DELETE", f"/api/items/{created.pop()}")
        stats["conn_error" if status == 0 else f"{status // 100}xx"] += 1

        now = time.monotonic()
        if now - last_report >= REPORT_EVERY:
            print("loadgen", dict(stats), flush=True)
            stats.clear()
            last_report = now
        if DURATION and now - started >= DURATION:
            print("loadgen", dict(stats), flush=True)
            return
        time.sleep(1 / RPS)


if __name__ == "__main__":
    main()
