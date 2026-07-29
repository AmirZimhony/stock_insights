"""Tests for src.utils.parse_args (date parsing/validation and config overrides)."""

from datetime import timezone

import pytest

from src.utils import parse_args


def test_parse_args_parses_valid_date_and_env(monkeypatch):
    monkeypatch.setattr("sys.argv", ["main.py", "--date", "10-11-2025", "--env", "dev"])

    (
        date,
        prev_date,
        env,
        db_name,
        source_collection,
        target_collection,
        thresholds,
        output_bucket,
        output_prefix,
        bq_dataset,
        bq_table,
    ) = parse_args()

    assert date.year == 2025 and date.month == 11 and date.day == 10
    assert date.tzinfo == timezone.utc
    assert prev_date is None
    assert env == "dev"
    # dev config.json values, unless overridden by CLI flags
    assert db_name == "stock_staging"
    assert source_collection == "stocks_merged_staging"
    assert target_collection == "daily_stock_summaries_dev"
    assert thresholds["volume_spike_threshold"] == 2.0


def test_parse_args_parses_prev_date(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--date", "10-11-2025", "--prev-date", "09-11-2025"],
    )

    _, prev_date, *_ = parse_args()

    assert prev_date.year == 2025 and prev_date.month == 11 and prev_date.day == 9


def test_parse_args_rejects_invalid_date_format(monkeypatch):
    monkeypatch.setattr("sys.argv", ["main.py", "--date", "2025-11-10"])

    with pytest.raises(ValueError, match="DD-MM-YYYY"):
        parse_args()


def test_parse_args_cli_overrides_take_precedence_over_config(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "main.py",
            "--date",
            "10-11-2025",
            "--env",
            "dev",
            "--db-name",
            "custom_db",
            "--source-collection",
            "custom_source",
            "--target-collection",
            "custom_target",
        ],
    )

    (
        _date,
        _prev_date,
        _env,
        db_name,
        source_collection,
        target_collection,
        *_rest,
    ) = parse_args()

    assert db_name == "custom_db"
    assert source_collection == "custom_source"
    assert target_collection == "custom_target"
