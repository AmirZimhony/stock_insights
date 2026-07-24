"""Tests for src.metrics.calculate_metrics (pure DataFrame calculations)."""

from datetime import datetime, timedelta, timezone

import pandas as pd

from src.metrics import calculate_metrics

THRESHOLDS = {
    "volume_spike_threshold": 2.0,
    "standout_z_threshold": 0.9,
    "min_data_points": 2,
    "trend_up_days": 3,
    "trend_down_days": -2,
}


def _make_df():
    """Two tickers, same exchange/sector, 3 days each.

    AAA spikes in volume and rises on the latest day; BBB stays flat/falls.
    """
    base_date = datetime(2025, 11, 8, tzinfo=timezone.utc)
    rows = []
    for i, day_offset in enumerate([-2, -1, 0]):
        date = base_date + timedelta(days=day_offset)
        rows.append(
            {
                "ticker": "AAA",
                "date": date,
                "volume": 300.0 if day_offset == 0 else 100.0,
                "pct_change": 5.0 if day_offset == 0 else 0.5,
                "exchange": "NASDAQ",
                "exchange_sector": "NASDAQ|Tech",
                "exchange_industry": "NASDAQ|Software",
                "exchange_country": "NASDAQ|USA",
                "num_of_rising_days": 4,
            }
        )
        rows.append(
            {
                "ticker": "BBB",
                "date": date,
                "volume": 100.0,
                "pct_change": -5.0 if day_offset == 0 else 0.1,
                "exchange": "NASDAQ",
                "exchange_sector": "NASDAQ|Tech",
                "exchange_industry": "NASDAQ|Software",
                "exchange_country": "NASDAQ|USA",
                "num_of_rising_days": -3,
            }
        )
    return pd.DataFrame(rows)


def test_calculate_metrics_empty_df_is_noop():
    df = pd.DataFrame()
    result = calculate_metrics(df, THRESHOLDS)
    assert result.empty


def test_volume_spike_flagged_on_latest_day():
    df = calculate_metrics(_make_df(), THRESHOLDS)
    latest = df[df["date"] == df["date"].max()]

    aaa = latest[latest["ticker"] == "AAA"].iloc[0]
    bbb = latest[latest["ticker"] == "BBB"].iloc[0]

    assert aaa["vol_spike_flag"]
    assert not bbb["vol_spike_flag"]


def test_trend_label_reflects_rising_days_thresholds():
    df = calculate_metrics(_make_df(), THRESHOLDS)

    assert (df[df["ticker"] == "AAA"]["trend_label"] == "up").all()
    assert (df[df["ticker"] == "BBB"]["trend_label"] == "down").all()


def test_standout_flag_and_direction_on_latest_day():
    df = calculate_metrics(_make_df(), THRESHOLDS)
    latest = df[df["date"] == df["date"].max()]

    aaa = latest[latest["ticker"] == "AAA"].iloc[0]
    bbb = latest[latest["ticker"] == "BBB"].iloc[0]

    # AAA outperformed, BBB underperformed -> opposite-signed standout z-scores
    assert aaa["standout_z"] > 0
    assert bbb["standout_z"] < 0
    assert aaa["standout_flag"]
    assert bbb["standout_flag"]


def test_confidence_is_full_when_enough_data_points_and_no_bootstrap():
    df = calculate_metrics(_make_df(), THRESHOLDS)
    # Each ticker has 3 data points and min_data_points is 2, no bootstrap fallback
    assert (df["confidence"] == 1.0).all()
