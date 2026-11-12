# Demo script (about 15 minutes)

A live walkthrough of the complete loop: **commit → pipeline → deploy → incident →
RCA → approved recovery → resolution**. Prepare it once using the [setup guide](setup-guide.md).

**Before the demo:** open these tabs:
* Platform: `http://<app_ip>:8081`
* Jenkins: `http://<jenkins_ip>:8080`
* Grafana: `http://<app_ip>:3000` (dashboard *demo-app: Service Overview*)

On the app host:

```bash
TOKEN=$(sudo grep CHAOS_TOKEN /opt/app/secrets.env | cut -d= -f2)
chaos() { curl -s -X POST localhost/chaos -H "X-Chaos-Token: $TOKEN" -H 'Content-Type: application/json' -d "$1"; echo; }
calm()  { curl -s -X DELETE localhost/chaos -H "X-Chaos-Token: $TOKEN"; echo; }
```

## Act 1: Automated delivery (4 min)

1. Make a small visible change (for example, add a seed item in `demo-app/app/inventory.py`), then commit and push.
2. **Jenkins:** the webhook starts the build. Point out the parallel gates (tests and coverage, ruff, Bandit, pip-audit, IaC scan), the image scan and the container smoke test.
3. **Approval** stage: click *Deploy*. Explain that production needs a human.
4. **Platform → Pipeline:** the build's stages and test report. **Dashboard:** latest build and events.
5. **Platform → Deployments:** the new image is running, the version is consistent, and the audit trail shows *deploy → promote*.

## Act 2: Incident and AI diagnosis (5 min)

6. Inject a fault: `chaos '{"dependency_failure": true}'`. Say: "the database just went away."
7. **Grafana:** the error ratio jumps and `inventory-db` turns DOWN. The logs panel shows *connection refused*.
8. After about 1–2 minutes the alerts fire. **Platform → Incidents:** a single incident correlates *DependencyDown* and *HighErrorRate*.
9. Open it and walk through **Root cause analysis**:
   * Downstream dependency failure, with high confidence
   * the "Why" list (error ratio, `dependency_up = 0`, connection-refused logs)
   * suggested checks
   * the rule-based baseline agrees
   * the anomaly score
   * the suggested action is **none**: rolling back the app wouldn't fix a database
10. `calm`. Within a few minutes the alerts resolve and the incident **auto-resolves**.

## Act 3: Bad release and approved rollback (5 min)

11. Deploy a "bad" build. Push a commit that raises errors, or simulate one right after a deploy with `chaos '{"error_rate": 0.4}'`.
12. A new incident opens. RCA now ranks **faulty deployment** (a deployment finished minutes before) and suggests a **rollback**.
13. Click **Request this recovery**. The Recovery page opens pre-filled. Enter a reason and your name, then request it.
14. A second person (or you, if four-eyes is off) **approves**. Show the approval token prompt if it's enabled.
15. Watch the status: *requested → approved → running* (Jenkins `recovery` job) → **succeeded**. Then expand the row:
    * the smoke-test checks
    * the platform's independent check: ready, and the version matches the target
16. The incident's notes show the full audit trail. `calm` if you used chaos. The incident resolves.

## Act 4: Wrap-up (1 min)

* DevOps automation is the core: IaC, CI/CD with security gates, immutable releases, auto-rollback, observability.
* The AI enhancement is explainable RCA that is advisory only. Recovery always needs human approval.
* Evaluation is honest: synthetic, live-demo and benchmark results are reported separately (see the report).

### Backup plan

If AWS is unavailable, run the platform locally against the demo app. The steps are in
[platform/README.md](../platform/README.md#develop-locally). Show the RCA and recovery
UI with seeded incidents.
