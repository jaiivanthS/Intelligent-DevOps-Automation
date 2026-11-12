# RCA evaluation: synthetic incidents

> **Scope.** These results use *synthetic* incidents from `rca_engine/synthetic.py`.
> They measure how the methods compare under controlled conditions. They do **not**
> predict production accuracy. Benchmark (RCAEval) and live-demo results are reported
> separately (see `README.md`).
>
> **Why the ML scores are so high.** The generator ties each cause to signals that the
> features measure directly, so the classes separate well. Treat the *relative* order of
> the methods, the per-cause gaps and the ablations as the findings. The absolute
> accuracy is not a finding. The rule-based baseline uses hand-set thresholds that were
> not tuned on this data.

Train: 2800 incidents (70% standard / 30% hard), 800 normal windows. Test: 1050 incidents per set. 26 features, 7 causes, seed 7. Generated 2026-11-12T15:20:45+00:00.

## Cause ranking

| Method | AC@1 standard | AC@3 standard | Macro-F1 standard | AC@1 hard | AC@3 hard | Macro-F1 hard |
|---|---|---|---|---|---|---|
| rule based | 91.6% | 96.3% | 91.8% | 71.5% | 80.3% | 72.1% |
| random forest | 99.4% | 100.0% | 99.4% | 97.9% | 100.0% | 97.9% |
| gradient boosting | 99.7% | 100.0% | 99.7% | 98.5% | 100.0% | 98.5% |
| xgboost | 99.6% | 100.0% | 99.6% | 98.2% | 100.0% | 98.2% |

## Per-cause recall (hard set): rule-based vs gradient boosting

| Cause | Rule-based | gradient boosting |
|---|---|---|
| bad_deployment | 95.3% | 99.3% |
| dependency_failure | 80.0% | 100.0% |
| error_burst | 84.7% | 97.3% |
| latency_degradation | 54.7% | 98.0% |
| cpu_saturation | 50.0% | 97.3% |
| memory_leak | 36.0% | 97.3% |
| service_down | 100.0% | 100.0% |

## Confusion matrix (gradient boosting, hard set)

Rows = true cause, columns = predicted.

| true \ pred | bad_deploy | dependency | error_burs | latency_de | cpu_satura | memory_lea | service_do |
|---|---|---|---|---|---|---|---|
| bad_deployment | 149 | 0 | 1 | 0 | 0 | 0 | 0 |
| dependency_failure | 0 | 150 | 0 | 0 | 0 | 0 | 0 |
| error_burst | 4 | 0 | 146 | 0 | 0 | 0 | 0 |
| latency_degradation | 3 | 0 | 0 | 147 | 0 | 0 | 0 |
| cpu_saturation | 0 | 0 | 0 | 4 | 146 | 0 | 0 |
| memory_leak | 0 | 0 | 4 | 0 | 0 | 146 | 0 |
| service_down | 0 | 0 | 0 | 0 | 0 | 0 | 150 |

## Ablation (Random Forest): which evidence matters

| Features | AC@1 standard | AC@1 hard | Macro-F1 hard |
|---|---|---|---|
| all features | 99.4% | 97.9% | 97.9% |
| without logs | 99.4% | 97.8% | 97.8% |
| without deploy context | 97.3% | 94.8% | 94.7% |
| without alert labels | 99.0% | 95.7% | 95.7% |
| metrics only | 90.6% | 85.5% | 85.8% |

## Anomaly detection (Isolation Forest, trained on normal windows only)

| Test set | ROC AUC | Incidents flagged | False alarms on normal windows |
|---|---|---|---|
| standard | 0.906 | 46.2% | 0.7% |
| hard | 0.922 | 50.4% | 0.7% |

## Most important features (Random Forest)

| Feature | Importance |
|---|---|
| `alert_dependency` | 0.099 |
| `mins_since_deploy` | 0.089 |
| `up_min` | 0.079 |
| `alert_availability` | 0.072 |
| `cpu_now` | 0.069 |
| `mem_log_ratio` | 0.065 |
| `alert_errors` | 0.055 |
| `mem_growth_per_min` | 0.054 |
| `cpu_delta` | 0.053 |
| `recent_deploy` | 0.049 |
| `log_app_error_frac` | 0.042 |
| `alert_saturation` | 0.041 |
