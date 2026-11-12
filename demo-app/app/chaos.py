"""Controlled failure injection.

Each mode produces a distinct signature in metrics and logs, which later
gives the RCA engine labelled incidents to learn from:

* error_rate          -> 5xx spike, ERROR logs "Injected failure"
* latency_ms          -> p95/p99 latency increase, no errors
* cpu_burn_ms         -> CPU saturation plus latency (blocks the event loop)
* memory_leak_mb      -> steadily growing resident memory
* dependency_failure  -> 503s on /api/*, readiness fails, "connection refused" logs
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import asdict, dataclass, replace

from . import metrics

# Safety cap so the leak mode degrades the service without taking down the host.
MAX_LEAK_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class ChaosState:
    error_rate: float = 0.0
    latency_ms: int = 0
    cpu_burn_ms: int = 0
    memory_leak_mb: int = 0
    dependency_failure: bool = False

    @property
    def active(self) -> bool:
        return self != ChaosState()

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class ChaosController:
    def __init__(self, rng: random.Random | None = None) -> None:
        self._lock = threading.Lock()
        self._state = ChaosState()
        self._leak: list[bytearray] = []
        self._leaked_bytes = 0
        self._rng = rng or random.Random()
        self._publish()

    @property
    def state(self) -> ChaosState:
        return self._state

    @property
    def leaked_bytes(self) -> int:
        return self._leaked_bytes

    def configure(self, **changes: object) -> ChaosState:
        with self._lock:
            self._state = replace(self._state, **changes)
            self._publish()
            return self._state

    def reset(self) -> ChaosState:
        with self._lock:
            self._state = ChaosState()
            self._leak.clear()
            self._leaked_bytes = 0
            self._publish()
            return self._state

    def should_fail(self) -> bool:
        rate = self._state.error_rate
        return rate > 0 and self._rng.random() < rate

    def burn_cpu(self, milliseconds: int) -> None:
        deadline = time.perf_counter() + milliseconds / 1000
        x = 0
        while time.perf_counter() < deadline:
            x = (x * 31 + 7) % 1_000_003

    def leak(self, megabytes: int) -> None:
        size = megabytes * 1024 * 1024
        with self._lock:
            if self._leaked_bytes + size > MAX_LEAK_BYTES:
                return
            chunk = bytearray(size)
            # Touch every page so the OS actually commits the memory.
            for i in range(0, size, 4096):
                chunk[i] = 1
            self._leak.append(chunk)
            self._leaked_bytes += size
            metrics.LEAKED_BYTES.set(self._leaked_bytes)

    def _publish(self) -> None:
        s = self._state
        metrics.CHAOS_ACTIVE.labels("error_rate").set(s.error_rate)
        metrics.CHAOS_ACTIVE.labels("latency_ms").set(s.latency_ms)
        metrics.CHAOS_ACTIVE.labels("cpu_burn_ms").set(s.cpu_burn_ms)
        metrics.CHAOS_ACTIVE.labels("memory_leak_mb").set(s.memory_leak_mb)
        metrics.CHAOS_ACTIVE.labels("dependency_failure").set(int(s.dependency_failure))
        metrics.DEPENDENCY_UP.labels("inventory-db").set(0 if s.dependency_failure else 1)
        metrics.LEAKED_BYTES.set(self._leaked_bytes)
