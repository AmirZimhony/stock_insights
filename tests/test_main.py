"""Tests that main.py emits the expected stocker_metrics calls (no real network I/O)."""

from datetime import datetime, timezone

import pytest

import main as main_module


def _stub_parse_args_result(date):
    return (
        date,
        None,
        "dev",
        "db",
        "src_col",
        "tgt_col",
        {},
        None,
        None,
        None,
        None,
    )


@pytest.fixture
def metrics_calls(monkeypatch):
    calls = {"gauge": [], "timing": [], "incr": []}
    monkeypatch.setattr(
        main_module.stocker_metrics,
        "gauge",
        lambda name, value, **kw: calls["gauge"].append((name, value)),
    )
    monkeypatch.setattr(
        main_module.stocker_metrics,
        "timing",
        lambda name, value, **kw: calls["timing"].append((name, value)),
    )
    monkeypatch.setattr(
        main_module.stocker_metrics,
        "incr",
        lambda name, *a, **kw: calls["incr"].append(name),
    )
    monkeypatch.setattr(main_module, "setup_logging", lambda **kw: None)
    return calls


def test_main_success_emits_metrics_and_exits_zero(monkeypatch, metrics_calls):
    date = datetime(2025, 11, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(
        main_module, "parse_args", lambda: _stub_parse_args_result(date)
    )
    monkeypatch.setattr(
        main_module,
        "run_pipeline",
        lambda **kw: {"success": True, "count": 42, "total": 42, "errors": 0},
    )

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 0
    assert ("stock_insights.records_processed", 42) in metrics_calls["gauge"]
    assert ("stock_insights.records_errors", 0) in metrics_calls["gauge"]
    assert len(metrics_calls["timing"]) == 1
    assert metrics_calls["timing"][0][0] == "stock_insights.pipeline_duration_ms"
    assert metrics_calls["incr"] == []


def test_main_failure_emits_failure_counter_and_exits_one(monkeypatch, metrics_calls):
    date = datetime(2025, 11, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(
        main_module, "parse_args", lambda: _stub_parse_args_result(date)
    )
    monkeypatch.setattr(
        main_module,
        "run_pipeline",
        lambda **kw: {"success": False, "count": 0, "errors": 0, "error": "boom"},
    )

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 1
    assert metrics_calls["incr"] == ["stock_insights.pipeline_failures"]
