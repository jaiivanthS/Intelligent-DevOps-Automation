# RCA engine: explainable root-cause analysis

When the platform opens an incident and collects evidence, this engine ranks the
probable root causes, explains why, and suggests checks and a recovery action.
**It is advisory only:** an operator approves every recovery (step 8).

```
evidence snapshot ──▶ features.extract() ──┬──▶ rules.rank()              (baseline, always shown)
(metrics, logs,        26 features         ├──▶ Random Forest classifier  (ranked causes + confidence)
 deployments, alerts)                      └──▶ Isolation Forest          (anomalous? which signals deviate?)
                                                       │
                       engine.explain() ◀──────────────┘  human-readable "why", checks, action
```

The same `features.extract()` runs in training and in production, so there is no
train/serve skew.

## Causes

| Key | Meaning | Suggested action |
|---|---|---|
| `bad_deployment` | Errors or latency began shortly after a release | rollback (only if a last-good image exists) |
| `dependency_failure` | Database or network dependency unreachable | none (rolling back the app won't help) |
| `error_burst` | Application errors without a deploy or dependency cause | none (investigate) |
| `latency_degradation` | Slow responses while CPU and errors stay normal | none (investigate) |
| `cpu_saturation` | CPU-bound process | restart |
| `memory_leak` | Steady RSS growth | restart |
| `service_down` | Not responding to scrapes or health checks | restart |

## Features (26)

* **Errors:** current, peak and change from baseline
* **Latency:** p95 and its ratio to baseline
* **Traffic:** ratio to baseline
* **Memory:** ratio to baseline and growth per minute
* **CPU:** current and change from baseline
* **In-flight requests:** peak
* **Availability:** `dependency_up` and `up` minimums
* **Logs:** volume, plus the share of error logs about dependencies, timeouts or application failures (regex over messages)
* **Deployment context:** minutes since the last deploy, recent deploy, recent rollback
* **Alert categories:** errors, latency, saturation, dependency, availability
* **Missing data:** how many signals were unavailable

Ground-truth (`ChaosInjectionActive`) alerts are **never** used as inputs.

## Three evaluations, reported separately

| | Data | Status |
|---|---|---|
| **1. Synthetic** | `synthetic.py`: 7 causes with confounders (unrelated deploys, missing telemetry, Loki outages, misleading "slow" warnings), plus a *hard* set with weaker signals | ✅ [reports/synthetic_evaluation.md](reports/synthetic_evaluation.md) |
| **2. Live demo** | Real incidents created by fault injection on the deployed platform, labelled automatically from `ground_truth` | Scripts ready; run on AWS (below) |
| **3. RCAEval benchmark** | RE1/RE2 fault types mapped to our causes | Adapter ready; data not downloaded (about 5 GB) |

### 1. Synthetic results (seed 7, 2,800 training incidents, 1,050 test incidents per set)

| Method | AC@1 standard | AC@1 hard | AC@3 hard | Macro-F1 hard |
|---|---|---|---|---|
| Rule-based baseline | 91.6% | 71.5% | 80.3% | 72.1% |
| **Random Forest** (deployed) | 99.4% | 97.9% | 100% | 97.9% |
| Gradient boosting (HistGB) | 99.7% | 98.5% | 100% | 98.5% |
| XGBoost | 99.6% | 98.2% | 100% | 98.2% |

What these results show:

* **The ML models beat the hand-written rules.** The gap is largest on the hard set,
  for signals that are gradual or confounded. Hard-set recall:
  * memory leak: 36% (rules) vs 97% (ML)
  * CPU saturation: 50% vs 97%
  * latency degradation: 55% vs 98%
* **Random Forest, gradient boosting and XGBoost perform alike** (differences under
  1 point). Random Forest is deployed because it gives feature importances and is
  robust without tuning.
* **Ablations show which evidence matters.** Removing deployment context, alert
  labels or logs costs 0–3 points each. Using only metrics drops hard-set AC@1 to
  85.5%, so combining telemetry with deploy context is what makes the diagnosis
  reliable.
* **Isolation Forest separates incidents from normal windows** with ROC AUC 0.91–0.92.
  At the calibrated 2% false-alarm threshold it flags about half of the incidents,
  with only 0.7% false alarms on normal windows. It is supporting evidence, not
  the trigger, since alerts already open incidents.

> ⚠️ **The absolute accuracy is optimistic.** The generator ties each cause to signals
> the features measure directly. Only the live-demo and benchmark evaluations can
> show real-world accuracy. Do not quote the synthetic numbers as production accuracy.

### 2. Live-demo evaluation (after deployment)

```bash
# on the app host: inject faults one at a time, e.g.
TOKEN=$(sudo grep CHAOS_TOKEN /opt/app/secrets.env | cut -d= -f2)
curl -X POST localhost/chaos -H "X-Chaos-Token: $TOKEN" -H 'Content-Type: application/json' -d '{"memory_leak_mb": 4}'
#   ...wait for the incident (about 3-5 min), then: curl -X DELETE localhost/chaos -H "X-Chaos-Token: $TOKEN"
# from your PC (rca venv):
python -m rca_engine.live export   --api http://<app_ip>:8000 --out data/live.jsonl
python -m rca_engine.live evaluate --data data/live.jsonl --model models/rca_model.joblib
```

Labels come from the `ChaosInjectionActive` ground truth. Incidents with several
faults at once are skipped. Optionally retrain with live data:
`python -m rca_engine.train --live data/live.jsonl`.

### 3. RCAEval benchmark

> Pham, L. et al. *RCAEval: A Benchmark for Root Cause Analysis of Microservice Systems
> with Telemetry Data.* 2025. https://github.com/phamquiluan/RCAEval

* **License:** the code is MIT. The datasets are stated as MIT in the README but
  **CC BY 4.0 on Zenodo** (record 14590730). That conflicts, so follow the stricter
  one: cite the paper and give attribution.
* **Task mapping:** RCAEval mainly evaluates *which service* is at fault. We evaluate
  *fault-type classification on the true root-cause service's metrics*. These numbers
  must **not** be compared with RCAEval's published Avg@5 localisation scores.
* **Mapping:** cpu → cpu_saturation, mem → memory_leak, delay and loss →
  latency_degradation, socket → dependency_failure. `disk` and the RE3 code-level
  faults have no matching class and are skipped.
* **Schema caveat:** metric column names are not documented. Run `--inspect` first
  and adjust `COLUMN_PATTERNS` if columns aren't found.

```bash
pip install -e ".[benchmark]"
# download (about 5 GB zipped, about 38 GB unpacked); see the RCAEval README
python -m rca_engine.benchmarks.rcaeval --data data/RE2 --inspect
python -m rca_engine.benchmarks.rcaeval --data data/RE2 --model models/rca_model.joblib
```

## Commands

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"            # add ,xgboost for the XGBoost comparison
pytest                             # 14 tests
python -m rca_engine.evaluate --xgboost --out-dir reports
python -m rca_engine.train --out models/rca_model.joblib
```

The platform-api Docker image trains the model at build time (seed 42) and loads it
from `RCA_MODEL_PATH`. If the model is missing or corrupt, the engine falls back to
the rule-based baseline and keeps working.
