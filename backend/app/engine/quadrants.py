"""Quadrant classification and direction bucketing.

Canonical coordinate system (SRS 12) -- this is the ONE true orientation and the
only one used anywhere in this codebase, API or UI:

                     RS-Momentum
                          ^
                          |
          Improving       |       Leading
                          |
    ----------------------+----------------------> RS-Ratio
                          |
           Lagging        |       Weakening
                          |

Note that SRS section 11 contains a contradictory diagram (it labels the two top
quadrants "Leading"/"Leading-Transition" and places Weakening top-right). That
section is wrong; sections 4 and 12 agree with each other and with this module.
"""

from __future__ import annotations

import math
from typing import Final

LEADING: Final = "Leading"
WEAKENING: Final = "Weakening"
LAGGING: Final = "Lagging"
IMPROVING: Final = "Improving"

QUADRANTS: Final = (LEADING, WEAKENING, LAGGING, IMPROVING)

# A move out of the left half or up into the top half is constructive.
POSITIVE_ROTATIONS: Final = frozenset(
    {(LAGGING, IMPROVING), (IMPROVING, LEADING), (WEAKENING, LEADING)}
)
NEGATIVE_ROTATIONS: Final = frozenset(
    {(LEADING, WEAKENING), (WEAKENING, LAGGING), (IMPROVING, LAGGING)}
)


def classify(rs_ratio: float, rs_momentum: float, center: float = 100.0) -> str | None:
    """Map a point to its quadrant.

    Points exactly on a boundary are assigned to the stronger quadrant (>= center)
    so that classification is total: every finite point gets exactly one quadrant.
    """
    if rs_ratio is None or rs_momentum is None:
        return None
    if not (math.isfinite(rs_ratio) and math.isfinite(rs_momentum)):
        return None
    strong_rs = rs_ratio >= center
    strong_mom = rs_momentum >= center
    if strong_rs and strong_mom:
        return LEADING
    if strong_rs and not strong_mom:
        return WEAKENING
    if not strong_rs and strong_mom:
        return IMPROVING
    return LAGGING


def direction(dx: float, dy: float, deadzone: float = 1e-9) -> str:
    """Bucket the latest tail segment into one of eight compass directions.

    Uses the last two observations only, per SRS 10.
    """
    if not (math.isfinite(dx) and math.isfinite(dy)):
        return "flat"
    if abs(dx) < deadzone and abs(dy) < deadzone:
        return "flat"
    angle = math.degrees(math.atan2(dy, dx)) % 360.0
    buckets = [
        (22.5, "right"),
        (67.5, "up_right"),
        (112.5, "up"),
        (157.5, "up_left"),
        (202.5, "left"),
        (247.5, "down_left"),
        (292.5, "down"),
        (337.5, "down_right"),
    ]
    for limit, name in buckets:
        if angle < limit:
            return name
    return "right"


def rotation_signal(previous: str | None, current: str | None) -> str | None:
    """Classify a quadrant transition (SRS 23). Returns None when unchanged."""
    if previous is None or current is None or previous == current:
        return None
    pair = (previous, current)
    if pair in POSITIVE_ROTATIONS:
        return "POSITIVE_ROTATION"
    if pair in NEGATIVE_ROTATIONS:
        return "NEGATIVE_ROTATION"
    return "ROTATION"


def heading_label(direction_code: str) -> str:
    return {
        "right": "Right (gaining relative strength)",
        "up_right": "Up and right (strengthening, gaining momentum)",
        "up": "Up (gaining momentum)",
        "up_left": "Up and left (losing strength, gaining momentum)",
        "left": "Left (losing relative strength)",
        "down_left": "Down and left (deteriorating)",
        "down": "Down (losing momentum)",
        "down_right": "Down and right (gaining strength, losing momentum)",
        "flat": "Flat (no material change)",
    }.get(direction_code, direction_code)
