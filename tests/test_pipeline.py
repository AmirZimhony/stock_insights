"""Tests for src.pipeline.run_pipeline orchestration, with all I/O mocked."""

from datetime import datetime, timezone

import pandas as pd
import pytest

import src.pipeline as pipeline

TARGET_DATE = datetime(2025, 11, 10, tzinfo=timezone.utc)
PREV_DATE = datetime(2025, 11, 9, tzinfo=timezone.utc)
THRESHOLDS = {"lookback_days": 17}


def _df_for_target_date(n=2):
    return pd.DataFrame(
        [
            {
                "ticker": f"T{i}",
                "exchange": "NASDAQ",
                "date": TARGET_DATE,
                "pct_change": 1.0 * i,
                "volume": 1000.0,
            }
            for i in range(n)
        ]
    )


@pytest.fixture(autouse=True)
def _isolate_calculate_metrics(monkeypatch):
    """Pipeline orchestration tests don't need real metric math (covered elsewhere)."""
    monkeypatch.setattr(pipeline, "calculate_metrics", lambda df, thresholds: df)


def test_run_pipeline_success_without_gcp(monkeypatch):
    monkeypatch.setattr(pipeline, "load_stock_data", lambda **kw: _df_for_target_date())
    monkeypatch.setattr(
        pipeline,
        "upsert_summaries",
        lambda **kw: {"upserted": 2, "errors": 0, "total": 2},
    )

    result = pipeline.run_pipeline(
        date=TARGET_DATE,
        prev_date=None,
        db_name="db",
        source_collection="src_col",
        target_collection="tgt_col",
        thresholds=THRESHOLDS,
    )

    assert result["success"] is True
    assert result["count"] == 2
    assert result["gcp"] is None


def test_run_pipeline_no_data_returns_failure(monkeypatch):
    monkeypatch.setattr(pipeline, "load_stock_data", lambda **kw: pd.DataFrame())

    result = pipeline.run_pipeline(
        date=TARGET_DATE,
        prev_date=None,
        db_name="db",
        source_collection="src_col",
        target_collection="tgt_col",
        thresholds=THRESHOLDS,
    )

    assert result["success"] is False
    assert result["count"] == 0
    assert "No data found" in result["error"]


def test_run_pipeline_no_rows_for_target_date_returns_failure(monkeypatch):
    """Data loaded, but none of it falls on the target date after filtering."""
    other_day = pd.DataFrame(
        [
            {
                "ticker": "T0",
                "exchange": "NASDAQ",
                "date": PREV_DATE,
                "pct_change": 1.0,
                "volume": 1000.0,
            }
        ]
    )
    monkeypatch.setattr(pipeline, "load_stock_data", lambda **kw: other_day)

    result = pipeline.run_pipeline(
        date=TARGET_DATE,
        prev_date=None,
        db_name="db",
        source_collection="src_col",
        target_collection="tgt_col",
        thresholds=THRESHOLDS,
    )

    assert result["success"] is False
    assert "No data found for target date" in result["error"]


def test_run_pipeline_calls_add_comparisons_when_prev_date_given(monkeypatch):
    calls = {}

    def fake_add_comparisons(df, **kwargs):
        calls["called"] = True
        calls["kwargs"] = kwargs
        return df

    monkeypatch.setattr(pipeline, "load_stock_data", lambda **kw: _df_for_target_date())
    monkeypatch.setattr(pipeline, "add_comparisons", fake_add_comparisons)
    monkeypatch.setattr(
        pipeline,
        "upsert_summaries",
        lambda **kw: {"upserted": 2, "errors": 0, "total": 2},
    )

    result = pipeline.run_pipeline(
        date=TARGET_DATE,
        prev_date=PREV_DATE,
        db_name="db",
        source_collection="src_col",
        target_collection="tgt_col",
        thresholds=THRESHOLDS,
    )

    assert calls.get("called") is True
    assert result["success"] is True


def test_run_pipeline_gcp_write_error_marks_failure_but_keeps_mongo_result(
    monkeypatch,
):
    monkeypatch.setattr(pipeline, "load_stock_data", lambda **kw: _df_for_target_date())
    monkeypatch.setattr(
        pipeline,
        "upsert_summaries",
        lambda **kw: {"upserted": 2, "errors": 0, "total": 2},
    )

    def fake_write_to_gcp(**kwargs):
        raise RuntimeError("GCS unavailable")

    monkeypatch.setattr(pipeline, "write_to_gcp", fake_write_to_gcp)

    result = pipeline.run_pipeline(
        date=TARGET_DATE,
        prev_date=None,
        db_name="db",
        source_collection="src_col",
        target_collection="tgt_col",
        thresholds=THRESHOLDS,
        output_bucket="bucket",
        output_prefix="prefix",
        bq_dataset="dataset",
        bq_table="table",
    )

    assert result["success"] is False
    assert "GCS unavailable" in result["gcp_error"]
    # Mongo write itself still succeeded
    assert result["count"] == 2


def test_run_pipeline_mongo_errors_marks_failure(monkeypatch):
    monkeypatch.setattr(pipeline, "load_stock_data", lambda **kw: _df_for_target_date())
    monkeypatch.setattr(
        pipeline,
        "upsert_summaries",
        lambda **kw: {"upserted": 1, "errors": 1, "total": 2},
    )

    result = pipeline.run_pipeline(
        date=TARGET_DATE,
        prev_date=None,
        db_name="db",
        source_collection="src_col",
        target_collection="tgt_col",
        thresholds=THRESHOLDS,
    )

    assert result["success"] is False
    assert result["errors"] == 1
