"""Tests for src.metrics.calculate_metrics (pure DataFrame calculations)."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

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


def test_missing_change_does_not_move_exchange_mean():
    date = datetime(2025, 11, 10, tzinfo=timezone.utc)
    rows = []
    for ticker, pct_change in (("AAA", 10.0), ("BBB", 0.0), ("CCC", float("nan"))):
        rows.append(
            {
                "ticker": ticker,
                "date": date,
                "volume": 100.0,
                "pct_change": pct_change,
                "exchange": "NASDAQ",
                "exchange_sector": "NASDAQ|Tech",
                "exchange_industry": "NASDAQ|Software",
                "exchange_country": "NASDAQ|USA",
                "num_of_rising_days": 1,
            }
        )

    df = calculate_metrics(pd.DataFrame(rows), THRESHOLDS)
    latest = df[df["ticker"] != "CCC"]

    assert latest["exchange_return"].eq(5.0).all()
    assert pd.isna(df.loc[df["ticker"] == "CCC", "pct_change"]).all()


def test_confidence_is_full_when_enough_data_points_and_no_bootstrap():
    df = calculate_metrics(_make_df(), THRESHOLDS)
    # Each ticker has 3 data points and min_data_points is 2, no bootstrap fallback
    assert (df["confidence"] == 1.0).all()


def _row(ticker, date, **overrides):
    row = {
        "ticker": ticker,
        "date": date,
        "volume": 100.0,
        "pct_change": 0.0,
        "exchange": "NASDAQ",
        "exchange_sector": "NASDAQ|Tech",
        "exchange_industry": "NASDAQ|Software",
        "exchange_country": "NASDAQ|USA",
        "num_of_rising_days": 1,
    }
    row.update(overrides)
    return row


def test_volume_baseline_excludes_today_and_spike_z_is_positive():
    base = datetime(2025, 11, 8, tzinfo=timezone.utc)
    volumes = [100.0, 300.0, 100.0, 500.0]
    rows = [
        _row("AAA", base + timedelta(days=offset), volume=volume)
        for offset, volume in enumerate(volumes)
    ]

    df = calculate_metrics(pd.DataFrame(rows), THRESHOLDS)
    latest = df[df["date"] == df["date"].max()].iloc[0]

    # Prior volumes are 100, 300, 100. Median 100, so 500 / 100.
    # Including today would pull that median up to 200.
    assert latest["vol_ratio"] == pytest.approx(5.0)
    assert latest["vol_z"] > 0

    one_day = calculate_metrics(
        pd.DataFrame([_row("BBB", base, volume=100.0)]), THRESHOLDS
    )
    assert pd.isna(one_day.iloc[0]["vol_ratio"])
    assert pd.isna(one_day.iloc[0]["vol_z"])
    assert not one_day.iloc[0]["vol_spike_flag"]


def test_consistency_uses_trailing_ten_days_not_the_whole_lookback():
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    changes = [1.0] * 10 + [1.0, 21.0]
    rows = [
        _row("AAA", base + timedelta(days=offset), pct_change=change)
        for offset, change in enumerate(changes)
    ]

    ordered = calculate_metrics(pd.DataFrame(rows), THRESHOLDS).sort_values("date")

    # The 10th observation is still a flat window. The final day includes the jump.
    assert ordered.iloc[9]["consistency_score"] == pytest.approx(1.0)
    assert ordered.iloc[-1]["consistency_score"] < 1.0


def test_small_sector_bootstraps_from_exchange_mean():
    date = datetime(2025, 11, 10, tzinfo=timezone.utc)
    rows = [
        _row("AAA", date, pct_change=5.0, exchange_sector="NASDAQ|Tech"),
        _row("BBB", date, pct_change=-5.0, exchange_sector="NASDAQ|Other"),
    ]

    df = calculate_metrics(pd.DataFrame(rows), THRESHOLDS)

    assert set(df["bootstrap_source"]) == {"exchange_mean"}
    assert df.loc[df["ticker"] == "AAA", "standout_z"].iloc[0] == pytest.approx(1.0)
    assert df.loc[df["ticker"] == "BBB", "standout_z"].iloc[0] == pytest.approx(-1.0)
    assert df["confidence"].tolist() == pytest.approx([0.4, 0.4])


def test_same_ticker_on_two_exchanges_keeps_its_own_zscores():
    date = datetime(2025, 11, 10, tzinfo=timezone.utc)
    rows = [
        _row("AAA", date, pct_change=5.0),
        _row("BBB", date, pct_change=-5.0),
        _row(
            "AAA",
            date,
            pct_change=-5.0,
            exchange="NYSE",
            exchange_sector="NYSE|Tech",
            exchange_industry="NYSE|Software",
            exchange_country="NYSE|USA",
        ),
        _row(
            "CCC",
            date,
            pct_change=5.0,
            exchange="NYSE",
            exchange_sector="NYSE|Tech",
            exchange_industry="NYSE|Software",
            exchange_country="NYSE|USA",
        ),
    ]

    df = calculate_metrics(pd.DataFrame(rows), THRESHOLDS)

    nasdaq = df[(df["ticker"] == "AAA") & (df["exchange"] == "NASDAQ")].iloc[0]
    nyse = df[(df["ticker"] == "AAA") & (df["exchange"] == "NYSE")].iloc[0]

    assert nasdaq["standout_z"] == pytest.approx(1.0)
    assert nyse["standout_z"] == pytest.approx(-1.0)
    assert nasdaq["robust_rel_z"] == pytest.approx(1.0)
    assert nyse["robust_rel_z"] == pytest.approx(-1.0)
    assert pd.isna(nasdaq["bootstrap_source"])
    assert pd.isna(nyse["bootstrap_source"])
