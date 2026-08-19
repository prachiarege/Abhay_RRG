"""RRG engine parameters and version identity.

The engine version is part of the reproducibility contract (SRS 50.3). Any change
to the mathematics in `rrg_engine.py` MUST bump ENGINE_VERSION so that previously
stored `rrg_values` rows remain attributable to the algorithm that produced them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict, field
from typing import Literal

ENGINE_VERSION = "1.0.0"

SmoothingMethod = Literal["none", "sma", "ema"]
Frequency = Literal["daily", "weekly"]


@dataclass(frozen=True)
class RRGParams:
    """Every knob the calculation engine exposes.

    Defaults follow SRS 51. They are deliberately all finite-window operations
    (see `smoothing_method`) so that results are truncation-invariant, which is
    what makes the no-look-ahead guarantee exact rather than approximate.
    """

    rs_period: int = 14
    momentum_period: int = 10
    smoothing_period: int = 5
    # "sma" is the default rather than "ema" on purpose. An EMA with adjust=False
    # carries a seed that depends on where the input series begins, so recomputing
    # a historical date from truncated data yields slightly different numbers.
    # SMA is window-local, so snapshot(D) from full history is bit-identical to
    # snapshot(D) from history truncated at D. "ema" remains selectable but is
    # only asymptotically truncation-invariant; see docs/RRG_CALCULATION_SPEC.md.
    smoothing_method: SmoothingMethod = "sma"
    # Window used to standardise both RS-Ratio and RS-Momentum.
    norm_period: int = 14
    # Multiplier applied to the standardised value before offsetting from centre.
    scale_factor: float = 1.0
    # Standardised values are clipped to +/- this many sigma so that a single
    # outlier cannot fling a sector across the chart (SRS 8).
    clip_sigma: float = 3.0
    center: float = 100.0

    def __post_init__(self) -> None:
        for name in ("rs_period", "momentum_period", "norm_period"):
            if getattr(self, name) < 2:
                raise ValueError(f"{name} must be >= 2")
        if self.smoothing_period < 1:
            raise ValueError("smoothing_period must be >= 1")
        if self.clip_sigma <= 0:
            raise ValueError("clip_sigma must be > 0")
        if self.scale_factor <= 0:
            raise ValueError("scale_factor must be > 0")

    @property
    def min_bars(self) -> int:
        """Bars of history required before the first RS-Momentum value exists.

        rs                          -> 1 bar
        smoothed rs                 -> + (smoothing_period - 1)
        rolling mean/std of that    -> + (rs_period - 1)
        momentum difference         -> + momentum_period
        rolling std of momentum     -> + (norm_period - 1)
        """
        smoothing = self.smoothing_period if self.smoothing_method != "none" else 1
        return (
            smoothing
            + (self.rs_period - 1)
            + self.momentum_period
            + (self.norm_period - 1)
        )

    def fingerprint(self) -> str:
        """Stable short hash identifying this parameter set plus engine version.

        Stored alongside every computed row so that cached/precomputed values for
        different parameter sets can never be confused with one another.
        """
        payload = {"engine": ENGINE_VERSION, **asdict(self)}
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        return asdict(self)
