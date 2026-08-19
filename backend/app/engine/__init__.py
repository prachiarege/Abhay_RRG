"""RRG calculation engine."""

from .params import ENGINE_VERSION, RRGParams
from .quadrants import classify, direction, rotation_signal, QUADRANTS
from .rrg_engine import compute_rrg, relative_strength, rs_ratio_series, rs_momentum_series
from .rotation import detect_rotations, detect_crossings
from .stats import relative_returns, rotation_scores, ScoreWeights, RETURN_WINDOWS

__all__ = [
    "ENGINE_VERSION",
    "RRGParams",
    "QUADRANTS",
    "classify",
    "direction",
    "rotation_signal",
    "compute_rrg",
    "relative_strength",
    "rs_ratio_series",
    "rs_momentum_series",
    "detect_rotations",
    "detect_crossings",
    "relative_returns",
    "rotation_scores",
    "ScoreWeights",
    "RETURN_WINDOWS",
]
