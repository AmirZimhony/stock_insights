"""Tests for src.comparison delta calculations (pure function, no MongoDB)."""

from datetime import datetime, timezone

import pandas as pd

from src.comparison import _calculate_deltas

TARGET_DATE = datetime(2025, 11, 10, tzinfo=timezone.utc)
PREV_DATE = datetime(2025, 11, 9, tzinfo=timezone.utc)


def test_calculate_deltas_with_matching_previous_record():
    df = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "exchange": "NASDAQ",
                "pct_change": 5.0,
                "vol_ratio": 2.0,
                "consistency_score": 0.8,
            }
        ]
    )
    prev_data = {
        ("AAA", "NASDAQ"): {
            "prev_date": PREV_DATE,
            "pct_change": 1.0,
            "vol_ratio": 1.5,
            "consistency_score": 0.6,
            "prev_exists": True,
        }
    }

    result = _calculate_deltas(df, prev_data, PREV_DATE, TARGET_DATE)
    row = result.iloc[0]

    assert row["comparison_prev_exists"]
    assert row["comparison_prev_date"] == PREV_DATE
    assert row["comparison_delta_pct_change"] == 4.0
    assert row["comparison_delta_vol_ratio"] == 0.5
    assert abs(row["comparison_delta_consistency"] - 0.2) < 1e-9


def test_calculate_deltas_with_no_previous_record():
    df = pd.DataFrame(
        [
            {
                "ticker": "ZZZ",
                "exchange": "NYSE",
                "pct_change": 3.0,
                "vol_ratio": 1.0,
                "consistency_score": 0.5,
            }
        ]
    )

    result = _calculate_deltas(df, {}, PREV_DATE, TARGET_DATE)
    row = result.iloc[0]

    assert not row["comparison_prev_exists"]
    assert row["comparison_prev_date"] is None
    assert row["comparison_delta_pct_change"] is None
    assert row["comparison_delta_vol_ratio"] is None
    assert row["comparison_delta_consistency"] is None


def test_calculate_deltas_partial_previous_data_leaves_missing_deltas_none():
    """Previous record exists but is missing vol_ratio/consistency (e.g. raw-data fallback)."""
    df = pd.DataFrame(
        [
            {
                "ticker": "BBB",
                "exchange": "NASDAQ",
                "pct_change": -2.0,
                "vol_ratio": 1.2,
                "consistency_score": 0.9,
            }
        ]
    )
    prev_data = {
        ("BBB", "NASDAQ"): {
            "prev_date": None,
            "pct_change": -1.0,
            "vol_ratio": None,
            "consistency_score": None,
            "prev_exists": True,
        }
    }

    result = _calculate_deltas(df, prev_data, PREV_DATE, TARGET_DATE)
    row = result.iloc[0]

    assert row["comparison_delta_pct_change"] == -1.0
    assert row["comparison_delta_vol_ratio"] is None
    assert row["comparison_delta_consistency"] is None
    # prev_date falls back to the passed-in prev_date when the record has none
    assert row["comparison_prev_date"] == PREV_DATE
