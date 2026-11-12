"""Explainable root-cause analysis for platform incidents.

    from rca_engine import RCAEngine
    result = RCAEngine.load("model.joblib").analyze(evidence, alerts)
"""

from .causes import CAUSES
from .engine import RCAEngine

__all__ = ["CAUSES", "RCAEngine"]
