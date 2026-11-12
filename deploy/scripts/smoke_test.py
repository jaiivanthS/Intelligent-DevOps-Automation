#!/usr/bin/env python3
"""Post-deployment smoke test for demo-app (standard library only).

Usage: smoke_test.py BASE_URL [EXPECTED_VERSION] [--timeout 60] [--max-latency-ms 1000]

Exits 0 when every check passes, 1 otherwise. Prints one line per check, plus a
JSON summary on the last line so Jenkins and the platform can parse it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def fetch(url: str, timeout: float = 5.0) -> tuple[int, bytes, float]:
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - http(s) URL from CI
            body = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        body, status = exc.read(), exc.code
    return status, body, (time.perf_counter() - start) * 1000


def wait_until_up(base: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if fetch(f"{base}/health", timeout=3)[0] == 200:
                return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(2)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument("expected_version", nargs="?")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--max-latency-ms", type=float, default=1000)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    results: list[dict[str, object]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append({"check": name, "ok": ok, "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}".rstrip())

    if not wait_until_up(base, args.timeout):
        check("reachable", False, f"{base}/health not 200 within {args.timeout:.0f}s")
    else:
        check("reachable", True, base)

        status, body, _ = fetch(f"{base}/ready")
        check("ready", status == 200, f"HTTP {status}")

        status, body, ms = fetch(f"{base}/api/items")
        is_list = False
        if status == 200:
            try:
                is_list = isinstance(json.loads(body), list)
            except ValueError:
                is_list = False
        check("api_items", status == 200 and is_list, f"HTTP {status}")
        limit = args.max_latency_ms
        check("latency", ms <= limit, f"{ms:.0f} ms (limit {limit:.0f})")

        status, body, _ = fetch(f"{base}/metrics")
        check("metrics", status == 200 and b"http_requests_total" in body, f"HTTP {status}")

        if args.expected_version:
            status, body, _ = fetch(f"{base}/")
            version = json.loads(body).get("version") if status == 200 else None
            check("version", version == args.expected_version,
                  f"running={version} expected={args.expected_version}")

    passed = all(r["ok"] for r in results)
    print(json.dumps({"smoke_test": "passed" if passed else "failed", "base_url": base,
                      "checks": results}))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
