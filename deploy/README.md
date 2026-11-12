# Deployment & release control

| File | Runs on | Purpose |
|---|---|---|
| `app/docker-compose.yml` | app host (`/opt/app`) | Runs `demo-app` from the ECR image on port 80. It has a memory limit, log rotation and the shared `devops-net` network. |
| `app/appctl.sh` | app host | Release controller with `deploy`, `promote`, `rollback`, `restart`, `status` and `history`. |
| `scripts/smoke_test.py` | Jenkins | Post-deploy checks: reachable, `/ready`, `/api/items`, latency, `/metrics`, running version. |

Jenkins copies `app/*` to the app host on every deployment, so the host always
runs the scripts from the commit being deployed.

## Release flow (Jenkinsfile)

```
Publish to ECR
   │
   ▼
Approval ──(production and not AUTO_APPROVE: operator clicks "Deploy", 30-minute timeout)
   │
   ▼
Deploy: appctl deploy <image>
   │      container never healthy ──▶ appctl restores last good image ──▶ build FAILS
   ▼
Post-deploy smoke test: smoke_test.py http://APP_HOST <tag>
   │      any check fails ──▶ appctl rollback (to last good) ──▶ build FAILS
   ▼
Promote: appctl promote (this image becomes "last good")
```

Every step also sends an event to the platform API (`PLATFORM_API_URL`, step 6).
The events are `pipeline`, `approval`, `deploy`, `smoke_test`, `rollback` and `release`.

## Release state on the app host

`/opt/app/state/` contains:

* `current_image`: what is running now
* `last_good_image`: the last image that passed post-deploy smoke tests
* `releases.jsonl`: an audit trail with one JSON line per action, including who did it

```bash
/opt/app/appctl.sh status          # {"current_image": ..., "last_good_image": ..., "health": ...}
/opt/app/appctl.sh history 10
/opt/app/appctl.sh rollback        # back to last good
/opt/app/appctl.sh rollback <ecr-repo>:<tag>   # to a specific release
```

ECR tags are immutable, so a rollback restores exactly the bytes that were tested.

## Failure-injection token

On the first deploy, `appctl.sh` creates `/opt/app/secrets.env` (mode 600) with a
random `CHAOS_TOKEN`. To trigger a demo incident:

```bash
TOKEN=$(sudo grep CHAOS_TOKEN /opt/app/secrets.env | cut -d= -f2)
curl -X POST localhost/chaos -H "X-Chaos-Token: $TOKEN" -H 'Content-Type: application/json' \
     -d '{"error_rate": 0.5}'
```
