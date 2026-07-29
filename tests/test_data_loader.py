"""Tests for src.data_loader parsing/derivation/validation helpers (no MongoDB)."""

import pandas as pd
import pytest

from src.data_loader import _derive_fields, _parse_fields, _validate_data


def test_parse_fields_parses_percentages_volume_and_market_cap():
    df = pd.DataFrame(
        [
            {
                "date": "2025-11-10T00:00:00Z",
                "change": "-0.22%",
                "volume": "98,935",
                "num_of_rising_days": "2",
                "accumulated_change": "4.0",
                "pe_ratio": "30.0",
                "market_cap": "83.48M",
            }
        ]
    )

    result = _parse_fields(df)

    assert result.loc[0, "pct_change"] == pytest.approx(-0.22)
    assert result.loc[0, "volume"] == 98935
    assert result.loc[0, "num_of_rising_days"] == 2
    assert result.loc[0, "accumulated_change"] == pytest.approx(4.0)
    assert result.loc[0, "pe_ratio"] == pytest.approx(30.0)
    assert result.loc[0, "market_cap"] == pytest.approx(83.48e6)
    assert result.loc[0, "date"].tzinfo is not None


def test_parse_fields_handles_unparseable_change_as_zero():
    df = pd.DataFrame([{"change": "-"}])
    result = _parse_fields(df)
    assert result.loc[0, "pct_change"] == 0.0


def test_derive_fields_computes_prev_close_and_composite_keys():
    df = pd.DataFrame(
        [
            {
                "last_price": 110.0,
                "pct_change": 10.0,
                "sector": None,
                "industry": None,
                "country": None,
                "exchange": "NASDAQ",
            }
        ]
    )

    result = _derive_fields(df)

    assert result.loc[0, "prev_close"] == pytest.approx(100.0)
    assert result.loc[0, "sector"] == "Unknown"
    assert result.loc[0, "exchange_sector"] == "NASDAQ|Unknown"
    assert result.loc[0, "exchange_industry"] == "NASDAQ|Unknown"
    assert result.loc[0, "exchange_country"] == "NASDAQ|Unknown"


def test_validate_data_raises_on_missing_required_columns():
    df = pd.DataFrame([{"ticker": "AAA"}])
    with pytest.raises(ValueError, match="Missing required columns"):
        _validate_data(df)


def test_validate_data_drops_nulls_and_non_positive_volume():
    df = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "date": pd.Timestamp("2025-11-10", tz="UTC"),
                "last_price": 100.0,
                "volume": 1000.0,
                "exchange": "NASDAQ",
                "change": "1%",
            },
            {
                "ticker": "BBB",
                "date": pd.Timestamp("2025-11-10", tz="UTC"),
                "last_price": None,
                "volume": 500.0,
                "exchange": "NASDAQ",
                "change": "1%",
            },
            {
                "ticker": "CCC",
                "date": pd.Timestamp("2025-11-10", tz="UTC"),
                "last_price": 50.0,
                "volume": 0.0,
                "exchange": "NASDAQ",
                "change": "1%",
            },
        ]
    )

    result = _validate_data(df)

    assert list(result["ticker"]) == ["AAA"]
