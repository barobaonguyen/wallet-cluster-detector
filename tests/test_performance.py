from __future__ import annotations

import json
from typing import Any

import pytest

from clusterdetect.analytics.performance import (
    ExitReasonStat,
    PerformanceSummary,
    render_summary_markdown,
    render_summary_text,
    summarize_trades,
    summary_to_dict,
)


def _row(
    id_: int,
    status: str,
    pnl_usd: float | None,
    *,
    pnl_pct: float | None = None,
    entry_ts: int | None = None,
    exit_ts: int | None = None,
    exit_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "id": id_,
        "status": status,
        "pnl_usd": pnl_usd,
        "pnl_pct": pnl_pct,
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "exit_reason": exit_reason,
    }


def test_empty_input_returns_zero_summary() -> None:
    summary = summarize_trades([])
    assert summary == PerformanceSummary(
        trades=0,
        wins=0,
        losses=0,
        win_rate=0.0,
        total_pnl_usd=0.0,
        avg_pnl_usd=0.0,
        avg_pnl_pct=0.0,
        median_pnl_pct=0.0,
        expectancy_usd=0.0,
        gross_win_usd=0.0,
        gross_loss_usd=0.0,
        profit_factor=None,
        max_drawdown_usd=0.0,
        best_trade_usd=0.0,
        worst_trade_usd=0.0,
        longest_win_streak=0,
        longest_loss_streak=0,
        median_hold_minutes=None,
        by_exit_reason=(),
    )


def test_mixed_win_loss_set() -> None:
    rows = [
        _row(1, "closed", 100.0, pnl_pct=10.0, entry_ts=0, exit_ts=100, exit_reason="hard_stop"),
        _row(2, "closed", -50.0, pnl_pct=-5.0, entry_ts=20, exit_ts=200, exit_reason="trail_stop"),
        _row(3, "closed", 30.0, pnl_pct=3.0, entry_ts=40, exit_ts=300, exit_reason="time_stop"),
        _row(
            4, "closed", -20.0, pnl_pct=-2.0, entry_ts=60, exit_ts=400, exit_reason="time_stop_dead"
        ),
        _row(5, "closed", 10.0, pnl_pct=1.0, entry_ts=80, exit_ts=500, exit_reason="hard_stop"),
        # The rows below must be skipped.
        _row(6, "open", 999.0, pnl_pct=999.0, entry_ts=0, exit_ts=600, exit_reason="hard_stop"),
        _row(7, "closed", None, pnl_pct=None, entry_ts=0, exit_ts=700, exit_reason="hard_stop"),
    ]
    summary = summarize_trades(rows)

    assert summary.trades == 5
    assert summary.wins == 3
    assert summary.losses == 2
    assert summary.win_rate == 0.6
    assert summary.total_pnl_usd == 70.0
    assert summary.avg_pnl_usd == 14.0
    assert summary.avg_pnl_pct == 1.4
    assert summary.median_pnl_pct == 1.0
    assert summary.expectancy_usd == pytest.approx(14.0)
    assert summary.gross_win_usd == 140.0
    assert summary.gross_loss_usd == 70.0
    assert summary.profit_factor == 2.0
    assert summary.max_drawdown_usd == 50.0
    assert summary.best_trade_usd == 100.0
    assert summary.worst_trade_usd == -50.0
    assert summary.longest_win_streak == 1
    assert summary.longest_loss_streak == 1
    assert summary.median_hold_minutes == 4.333333333333333
    assert summary.by_exit_reason == (
        ExitReasonStat(reason="hard_stop", trades=2, wins=2, win_rate=1.0, pnl_usd=110.0),
        ExitReasonStat(reason="time_stop", trades=1, wins=1, win_rate=1.0, pnl_usd=30.0),
        ExitReasonStat(reason="time_stop_dead", trades=1, wins=0, win_rate=0.0, pnl_usd=-20.0),
        ExitReasonStat(reason="trail_stop", trades=1, wins=0, win_rate=0.0, pnl_usd=-50.0),
    )


def test_drawdown_is_not_simply_worst_trade() -> None:
    rows = [
        _row(1, "closed", 100.0, pnl_pct=10.0, entry_ts=0, exit_ts=100, exit_reason="hard_stop"),
        _row(2, "closed", -30.0, pnl_pct=-3.0, entry_ts=0, exit_ts=200, exit_reason="trail_stop"),
        _row(3, "closed", -80.0, pnl_pct=-8.0, entry_ts=0, exit_ts=300, exit_reason="time_stop"),
        _row(4, "closed", 50.0, pnl_pct=5.0, entry_ts=0, exit_ts=400, exit_reason="hard_stop"),
    ]
    summary = summarize_trades(rows)
    assert summary.worst_trade_usd == -80.0
    assert summary.max_drawdown_usd == 110.0
    assert summary.longest_loss_streak == 2


def test_longest_win_and_loss_streaks() -> None:
    pnls = [10.0, 20.0, -5.0, -15.0, -3.0, 7.0, 8.0, 9.0, 10.0]
    rows = [
        _row(i + 1, "closed", pnl, exit_ts=(i + 1) * 100, exit_reason="hard_stop")
        for i, pnl in enumerate(pnls)
    ]
    summary = summarize_trades(rows)
    assert summary.longest_win_streak == 4
    assert summary.longest_loss_streak == 3


def test_median_hold_minutes_even_count() -> None:
    rows = [
        _row(1, "closed", 1.0, entry_ts=0, exit_ts=60, exit_reason="hard_stop"),
        _row(2, "closed", 2.0, entry_ts=0, exit_ts=120, exit_reason="hard_stop"),
        _row(3, "closed", 3.0, entry_ts=0, exit_ts=180, exit_reason="hard_stop"),
        _row(4, "closed", 4.0, entry_ts=0, exit_ts=600, exit_reason="hard_stop"),
    ]
    summary = summarize_trades(rows)
    assert summary.median_hold_minutes == 2.5


def test_unknown_exit_reason_bucket() -> None:
    rows = [
        _row(1, "closed", 50.0, exit_ts=100, exit_reason=None),
        _row(2, "closed", -10.0, exit_ts=200, exit_reason=""),
        _row(3, "closed", 20.0, exit_ts=300, exit_reason="trail_stop"),
    ]
    summary = summarize_trades(rows)

    unknown = next(stat for stat in summary.by_exit_reason if stat.reason == "unknown")
    assert unknown == ExitReasonStat(reason="unknown", trades=2, wins=1, win_rate=0.5, pnl_usd=40.0)

    trail = next(stat for stat in summary.by_exit_reason if stat.reason == "trail_stop")
    assert trail == ExitReasonStat(
        reason="trail_stop", trades=1, wins=1, win_rate=1.0, pnl_usd=20.0
    )


def test_summary_to_dict_is_json_serializable() -> None:
    rows = [
        _row(1, "closed", 100.0, pnl_pct=10.0, entry_ts=0, exit_ts=100, exit_reason="hard_stop"),
        _row(2, "closed", -50.0, pnl_pct=-5.0, entry_ts=0, exit_ts=200, exit_reason="trail_stop"),
    ]
    summary = summarize_trades(rows)
    as_dict = summary_to_dict(summary)

    json_text = json.dumps(as_dict)
    assert isinstance(json_text, str)
    assert "by_exit_reason" in as_dict
    assert isinstance(as_dict["by_exit_reason"], list)
    assert all(isinstance(item, dict) for item in as_dict["by_exit_reason"])
    assert all(not isinstance(item, tuple) for item in as_dict["by_exit_reason"])


def test_render_summary_text() -> None:
    rows = [
        _row(1, "closed", 100.0, pnl_pct=10.0, entry_ts=0, exit_ts=100, exit_reason="hard_stop"),
        _row(2, "closed", -50.0, pnl_pct=-5.0, entry_ts=0, exit_ts=200, exit_reason="trail_stop"),
    ]
    summary = summarize_trades(rows)
    text = render_summary_text(summary, title="Test Summary")

    assert not text.endswith("\n")
    assert text.splitlines()[0] == "Test Summary"
    assert "Trades" in text
    assert "Win rate" in text
    assert "Profit factor" in text
    assert "By exit reason:" in text
    assert "hard_stop" in text
    assert all(line == line.rstrip() for line in text.splitlines())


def test_render_summary_markdown() -> None:
    rows = [
        _row(1, "closed", 100.0, pnl_pct=10.0, entry_ts=0, exit_ts=100, exit_reason="hard_stop"),
        _row(2, "closed", -50.0, pnl_pct=-5.0, entry_ts=0, exit_ts=200, exit_reason="trail_stop"),
    ]
    summary = summarize_trades(rows)
    md = render_summary_markdown(summary, title="Test Summary")

    assert not md.endswith("\n")
    assert "## Test Summary" in md
    assert "| Metric | Value |" in md
    assert "| hard_stop |" in md


def test_empty_renderers_have_no_trailing_newline() -> None:
    summary = summarize_trades([])
    text = render_summary_text(summary)
    md = render_summary_markdown(summary)

    assert text.splitlines()[0] == "Paper-trade performance"
    assert "Trades" in text
    assert "Profit factor" in text and "n/a" in text
    assert not text.endswith("\n")

    assert md.startswith("## Paper-trade performance\n\n| Metric | Value |\n| --- | --- |")
    assert "### By exit reason" not in md
    assert not md.endswith("\n")
