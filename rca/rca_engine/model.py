"""ML models: Isolation Forest (is this window anomalous, and which signals deviate)
plus a cause classifier (Random Forest or gradient boosting) that ranks causes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    IsolationForest,
    RandomForestClassifier,
)

from .causes import CAUSE_KEYS
from .features import FEATURE_NAMES, to_vector


def make_classifier(kind: str, seed: int = 0):
    if kind == "random_forest":
        return RandomForestClassifier(n_estimators=300, min_samples_leaf=2,
                                      class_weight="balanced", random_state=seed, n_jobs=-1)
    if kind == "gradient_boosting":
        return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08,
                                              max_leaf_nodes=31, random_state=seed)
    if kind == "xgboost":
        from xgboost import XGBClassifier  # optional dependency

        return XGBClassifier(n_estimators=300, max_depth=5, learning_rate=0.08,
                             subsample=0.9, colsample_bytree=0.9, random_state=seed,
                             eval_metric="mlogloss")
    raise ValueError(f"unknown classifier kind {kind!r}")


@dataclass
class RCAModel:
    kind: str
    classifier: Any
    detector: IsolationForest
    normal_mean: np.ndarray
    normal_std: np.ndarray
    # Raw anomaly score (-score_samples) above which a window counts as anomalous;
    # calibrated to a target false-alarm rate on normal training windows.
    threshold: float = 0.0
    classes: tuple[str, ...] = CAUSE_KEYS
    meta: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ train
    @classmethod
    def train(cls, X: np.ndarray, y: list[str], X_normal: np.ndarray, kind: str = "random_forest",
              seed: int = 0, meta: dict[str, Any] | None = None,
              false_alarm_rate: float = 0.02) -> RCAModel:
        index = {c: i for i, c in enumerate(CAUSE_KEYS)}
        clf = make_classifier(kind, seed)
        clf.fit(X, np.array([index[c] for c in y]))
        iso = IsolationForest(n_estimators=200, contamination="auto", random_state=seed)
        iso.fit(X_normal)
        threshold = float(np.quantile(-iso.score_samples(X_normal), 1 - false_alarm_rate))
        std = X_normal.std(axis=0)
        std[std < 1e-6] = 1e-6
        return cls(kind, clf, iso, X_normal.mean(axis=0), std, threshold, CAUSE_KEYS, meta or {})

    # ---------------------------------------------------------------- predict
    def rank(self, features: dict[str, float]) -> list[tuple[str, float]]:
        proba = self.classifier.predict_proba(np.array([to_vector(features)]))[0]
        labels = [self.classes[int(i)] for i in self.classifier.classes_]
        return sorted(zip(labels, (float(p) for p in proba), strict=True),
                      key=lambda kv: kv[1], reverse=True)

    def rank_many(self, X: np.ndarray) -> list[list[str]]:
        proba = self.classifier.predict_proba(X)
        labels = [self.classes[int(i)] for i in self.classifier.classes_]
        order = np.argsort(-proba, axis=1)
        return [[labels[j] for j in row] for row in order]

    def anomaly(self, features: dict[str, float], top: int = 5) -> dict[str, Any]:
        x = np.array([to_vector(features)])
        raw = float(-self.detector.score_samples(x)[0])
        z = (x[0] - self.normal_mean) / self.normal_std
        order = np.argsort(-np.abs(z))[:top]
        return {
            "score": round(raw / self.threshold, 3) if self.threshold else raw,  # >= 1 = anomalous
            "is_anomalous": raw >= self.threshold,
            "top_deviations": [{"feature": FEATURE_NAMES[i], "z": round(float(z[i]), 2),
                                "value": round(float(x[0][i]), 4)} for i in order],
        }

    def is_anomalous_many(self, X: np.ndarray) -> np.ndarray:
        return -self.detector.score_samples(X) >= self.threshold

    def importances(self) -> dict[str, float]:
        imp = getattr(self.classifier, "feature_importances_", None)
        if imp is None:
            return {}
        return {FEATURE_NAMES[i]: float(v) for i, v in enumerate(imp)}

    # -------------------------------------------------------------- persist
    def save(self, path: str) -> None:
        joblib.dump(self, path, compress=3)

    @staticmethod
    def load(path: str) -> RCAModel:
        model = joblib.load(path)
        if not isinstance(model, RCAModel):
            raise TypeError(f"{path} does not contain an RCAModel")
        return model
