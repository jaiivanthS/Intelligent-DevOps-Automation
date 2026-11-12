"""Root-cause catalogue: the classes the engine predicts, with operator guidance.

`action` is only a *suggestion* shown in the UI; recovery always needs operator
approval (step 8).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Cause:
    key: str
    title: str
    description: str
    checks: tuple[str, ...]
    action: str  # rollback | restart | none


CAUSES: dict[str, Cause] = {c.key: c for c in (
    Cause("bad_deployment", "Faulty deployment",
          "Errors or latency started shortly after a new release was deployed.",
          ("Compare the failing release with the last good image (diff, changelog).",
           "Check the post-deploy smoke test and the first error logs after rollout.",
           "Roll back to the last good image if the regression is confirmed."),
          "rollback"),
    Cause("dependency_failure", "Downstream dependency failure",
          "A dependency (database/network) is unreachable; requests fail with 503s.",
          ("Check readiness (/ready) and the dependency_up metric.",
           "Verify the dependency host, credentials, security groups and DNS.",
           "Do not roll back the app: the fault is outside the service."),
          "none"),
    Cause("error_burst", "Application errors",
          "The service returns 5xx errors without a recent deployment or dependency outage.",
          ("Group error logs by message and route to find the failing code path.",
           "Check recent configuration or traffic changes.",
           "Restart only if errors correlate with a stuck process."),
          "none"),
    Cause("latency_degradation", "Latency degradation",
          "Responses are slow while CPU and errors stay near normal (I/O wait, slow calls).",
          ("Inspect p95/p99 latency by route and slow request logs (duration_ms).",
           "Check downstream call latency and connection pools.",
           "Check for lock contention or blocking calls."),
          "none"),
    Cause("cpu_saturation", "CPU saturation",
          "The process is CPU-bound, which raises latency and in-flight requests.",
          ("Check process CPU and in-flight requests; profile hot endpoints.",
           "Look for runaway loops or expensive requests.",
           "Restart to recover quickly; scale out if load-driven."),
          "restart"),
    Cause("memory_leak", "Memory leak",
          "Resident memory grows steadily; the container will eventually be OOM-killed.",
          ("Confirm steady RSS growth on the memory panel.",
           "Take a heap snapshot / compare allocations between releases.",
           "Restart to reclaim memory; roll back if the leak started with a release."),
          "restart"),
    Cause("service_down", "Service down / crashed",
          "The service stopped responding to health checks and metric scrapes.",
          ("Check container status and exit code (docker ps -a, docker logs).",
           "Check for OOM kills (dmesg) and host resource exhaustion.",
           "Restart the service; roll back if it crashes again after a new release."),
          "restart"),
)}

CAUSE_KEYS: tuple[str, ...] = tuple(CAUSES)

# Fault-injection mode (demo-app /chaos, ChaosInjectionActive alert) -> cause label.
CHAOS_MODE_TO_CAUSE = {
    "error_rate": "error_burst",
    "latency_ms": "latency_degradation",
    "cpu_burn_ms": "cpu_saturation",
    "memory_leak_mb": "memory_leak",
    "dependency_failure": "dependency_failure",
}
