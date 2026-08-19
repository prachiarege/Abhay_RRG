"""Quadrant classification, direction, rotation signals, returns and scores."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.engine.quadrants import (
    IMPROVING,
    LAGGING,
    LEADING,
    WEAKENING,
    classify,
    direction,
    heading_label,
    rotation_signal,
)
from app.engine.rotation import detect_crossings, detect_rotations
from app.engine.stats import (
    RETURN_WINDOWS,
    ScoreWeights,
    relative_return,
    relative_returns,
    rotation_scores,
)


# ------------------------------------------------------------------------------ quadrants


@pytest.mark.parametrize(
    ("x", "y", "expected"),
    [
        (104.0, 102.0, LEADING),     # right, up
        (104.0, 98.0, WEAKENING),    # right, down
        (96.0, 98.0, LAGGING),       # left, down
        (96.0, 102.0, IMPROVING),    # left, up
    ],
)
def test_canonical_orientation(x, y, expected):
    """SRS 12 orientation: Improving is TOP-LEFT and Weakening is BOTTOM-RIGHT.

    Pinned down explicitly because SRS section 11 contradicts sections 4 and 12 -- it
    labels both top quadrants "Leading" and places Weakening top-right. Sections 4 and 12
    agree with each other, and this is what the whole codebase implements.
    """
    assert classify(x, y) == expected


def test_boundary_points_resolve_to_the_stronger_quadrant():
    """Classification must be total: every finite point gets exactly one quadrant."""
    assert classify(100.0, 100.0) == LEADING
    assert classify(100.0, 99.0) == WEAKENING
    assert classify(99.0, 100.0) == IMPROVING
    assert classify(99.9, 99.9) == LAGGING


def test_configurable_centre():
    assert classify(50.5, 50.5, center=50.0) == LEADING
    assert classify(49.5, 49.5, center=50.0) == LAGGING


def test_non_finite_points_are_unclassified():
    assert classify(float("nan"), 100.0) is None
    assert classify(float("inf"), 100.0) is None
    assert classify(None, None) is None


@pytest.mark.parametrize(
    ("dx", "dy", "expected"),
    [
        (1.0, 0.0, "right"),
        (1.0, 1.0, "up_right"),
        (0.0, 1.0, "up"),
        (-1.0, 1.0, "up_left"),
        (-1.0, 0.0, "left"),
        (-1.0, -1.0, "down_left"),
        (0.0, -1.0, "down"),
        (1.0, -1.0, "down_right"),
        (0.0, 0.0, "flat"),
    ],
)
def test_direction_buckets(dx, dy, expected):
    assert direction(dx, dy) == expected


def test_direction_labels_are_human_readable():
    assert "right" in heading_label("up_right").lower()
    assert heading_label("flat")


# ------------------------------------------------------------------------------- rotation


def test_rotation_signal_polarity():
    assert rotation_signal(IMPROVING, LEADING) == "POSITIVE_ROTATION"
    assert rotation_signal(LAGGING, IMPROVING) == "POSITIVE_ROTATION"
    assert rotation_signal(LEADING, WEAKENING) == "NEGATIVE_ROTATION"
    assert rotation_signal(WEAKENING, LAGGING) == "NEGATIVE_ROTATION"
    assert rotation_signal(LEADING, LEADING) is None
    assert rotation_signal(None, LEADING) is None


def test_diagonal_transition_is_neutral_rotation():
    """Leading straight to Lagging skips a quadrant; real but not signed either way."""
    assert rotation_signal(LEADING, LAGGING) == "ROTATION"


def test_detect_rotations_finds_transitions():
    index = pd.bdate_range("2025-01-01", periods=5)
    frame = pd.DataFrame(
        {
            "rs_ratio": [99.0, 99.5, 101.0, 101.5, 100.5],
            "rs_momentum": [101.0, 101.5, 101.2, 99.0, 99.5],
            "quadrant": [IMPROVING, IMPROVING, LEADING, WEAKENING, WEAKENING],
        },
        index=index,
    )
    events = detect_rotations(frame, "NIFTY_TEST")
    assert [(e.previous_quadrant, e.current_quadrant) for e in events] == [
        (IMPROVING, LEADING),
        (LEADING, WEAKENING),
    ]
    assert events[0].signal == "POSITIVE_ROTATION"
    assert events[1].signal == "NEGATIVE_ROTATION"


def test_gaps_do_not_manufacture_rotations():
    """A hole in the data must not read as a transition when values resume."""
    index = pd.bdate_range("2025-01-01", periods=4)
    frame = pd.DataFrame(
        {
            "rs_ratio": [101.0, np.nan, 101.2, 101.4],
            "rs_momentum": [101.0, np.nan, 101.1, 101.3],
            "quadrant": [LEADING, None, LEADING, LEADING],
        },
        index=index,
    )
    assert detect_rotations(frame, "X") == []


def test_detect_crossings_of_the_centre_line():
    index = pd.bdate_range("2025-01-01", periods=5)
    frame = pd.DataFrame(
        {
            "rs_ratio": [99.0, 99.5, 100.5, 101.0, 99.5],
            "rs_momentum": [100.5, 100.2, 100.1, 100.4, 100.3],
        },
        index=index,
    )
    events = detect_crossings(frame, "X")
    ratio_events = [e for e in events if e.metric == "rs_ratio"]
    assert [e.kind for e in ratio_events] == ["crossed_above", "crossed_below"]
    # RS-Momentum never leaves the upper half, so it must produce no crossing at all.
    assert [e for e in events if e.metric == "rs_momentum"] == []


# -------------------------------------------------------------------------------- returns


def _series(values: list[float], start: str = "2025-01-01") -> pd.Series:
    index = pd.bdate_range(start=start, periods=len(values))
    return pd.Series(values, index=index, dtype="float64")


def test_relative_return_is_geometric():
    """Sector +10%, benchmark +5% over the window -> 1.10/1.05 - 1 = 4.7619%.

    The series runs well past one month so that the lookback lands inside the data; with
    a shorter series the correct answer is None, which is a different test (below).
    """
    sector = _series([100.0] * 59 + [110.0])
    benchmark = _series([100.0] * 59 + [105.0])
    as_of = sector.index[-1]
    result = relative_return(sector, benchmark, as_of, RETURN_WINDOWS["1m"])
    assert result == pytest.approx((1.10 / 1.05 - 1) * 100, abs=1e-9)


def test_relative_return_zero_when_matching_benchmark():
    sector = _series([100.0, 105.0, 110.0] * 10)
    benchmark = sector.copy()
    as_of = sector.index[-1]
    for label in ("1w", "1m"):
        assert relative_return(sector, benchmark, as_of, RETURN_WINDOWS[label]) == pytest.approx(0.0)


def test_relative_return_uses_last_value_at_or_before_the_window_start():
    """Strictly backward-looking: never interpolates and never reads ahead."""
    sector = _series([100.0] * 30)
    benchmark = _series([100.0] * 30)
    as_of = sector.index[10]
    # A one-year window predates the data entirely, so there is no honest answer.
    assert relative_return(sector, benchmark, as_of, RETURN_WINDOWS["1y"]) is None


def test_relative_returns_returns_all_windows():
    sector = _series(list(np.linspace(100, 160, 400)))
    benchmark = _series(list(np.linspace(100, 130, 400)))
    result = relative_returns(sector, benchmark, sector.index[-1])
    assert set(result) == {"1d", "1w", "1m", "3m", "6m", "1y"}
    assert all(v is not None for v in result.values())
    assert result["1y"] > 0  # the sector outgrew the benchmark


# --------------------------------------------------------------------------------- score


def test_rotation_score_weights_must_sum_to_one():
    with pytest.raises(ValueError, match="sum to 1.0"):
        ScoreWeights(rs_ratio=0.5, rs_momentum=0.5, momentum_change=0.2)


def test_rotation_score_ranks_within_the_universe():
    latest = {
        "A": {"rs_ratio": 104.0, "rs_momentum": 103.0, "momentum_change": 0.5},
        "B": {"rs_ratio": 102.0, "rs_momentum": 101.0, "momentum_change": 0.2},
        "C": {"rs_ratio": 98.0, "rs_momentum": 97.0, "momentum_change": -0.4},
    }
    scores = rotation_scores(latest)
    assert scores["A"] > scores["B"] > scores["C"]
    assert all(0 <= s <= 100 for s in scores.values())
    assert scores["A"] == pytest.approx(100.0)


def test_rotation_score_is_universe_relative():
    """Documented caveat, asserted: the same sector scores differently in a different set."""
    strong = {"rs_ratio": 101.0, "rs_momentum": 101.0, "momentum_change": 0.1}
    weaker_peers = {
        "X": strong,
        "Y": {"rs_ratio": 99.0, "rs_momentum": 99.0, "momentum_change": -0.1},
    }
    stronger_peers = {
        "X": strong,
        "Y": {"rs_ratio": 105.0, "rs_momentum": 105.0, "momentum_change": 1.0},
    }
    assert rotation_scores(weaker_peers)["X"] != rotation_scores(stronger_peers)["X"]


def test_single_sector_universe_is_neutral():
    scores = rotation_scores(
        {"ONLY": {"rs_ratio": 104.0, "rs_momentum": 103.0, "momentum_change": 0.5}}
    )
    assert scores["ONLY"] == 50.0


def test_missing_components_yield_no_score():
    scores = rotation_scores(
        {
            "A": {"rs_ratio": 104.0, "rs_momentum": 103.0, "momentum_change": None},
            "B": {"rs_ratio": 102.0, "rs_momentum": 101.0, "momentum_change": 0.2},
        }
    )
    assert scores["A"] is None
