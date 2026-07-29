"""Offline paper-trade performance analytics.

Pure transform over rows already stored in the user's own SQLite table:
no network calls, no database access, no wallet/address tracking, and no
collection of new data.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True)
class ExitReasonStat:
    reason: str
    trades: int
    wins: int
    win_rate: float  # 0.0..1.0, 0.0 when trades == 0
    pnl_usd: float


@dataclass(frozen=True)
class PerformanceSummary:
    trades: int
    wins: int
    losses: int
    win_rate: float
    total_pnl_usd: float
    avg_pnl_usd: float
    avg_pnl_pct: float
    median_pnl_pct: float
    expectancy_usd: float
    gross_win_usd: float
    gross_loss_usd: float
    profit_factor: float | None
    max_drawdown_usd: float
    best_trade_usd: float
    worst_trade_usd: float
    longest_win_streak: int
    longest_loss_streak: int
    median_hold_minutes: float | None
    by_exit_reason: tuple[ExitReasonStat, ...]


def _rounded(value: Any) -> Any:
    """Round floats to four decimals; leave everything else unchanged."""
    return round(value, 4) if isinstance(value, float) else value


def summarize_trades(rows: Sequence[Mapping[str, Any]]) -> PerformanceSummary:
    """Return a performance summary for closed rows with a realised PnL."""
    qualified: list[tuple[int, int, float, float, str, int | None, int | None]] = []
    for row in rows:
        if str(row.get("status")) != "closed" or row.get("pnl_usd") is None:
            continue

        exit_ts = row.get("exit_ts")
        trade_id = row.get("id")
        pnl_pct = row.get("pnl_pct")
        raw_reason = row.get("exit_reason")
        reason = raw_reason if raw_reason else "unknown"
        entry_ts = row.get("entry_ts")

        qualified.append(
            (
                int(exit_ts) if exit_ts is not None else 0,
                int(trade_id) if trade_id is not None else 0,
                float(row["pnl_usd"]),
                0.0 if pnl_pct is None else float(pnl_pct),
                str(reason),
                int(entry_ts) if entry_ts is not None else None,
                int(exit_ts) if exit_ts is not None else None,
            )
        )

    qualified.sort(key=lambda item: (item[0], item[1]))

    pnls = [item[2] for item in qualified]
    pct_changes = [item[3] for item in qualified]

    trades = len(pnls)
    wins = sum(1 for pnl in pnls if pnl > 0.0)
    losses = sum(1 for pnl in pnls if pnl < 0.0)
    win_rate = wins / trades if trades else 0.0
    loss_rate = losses / trades if trades else 0.0

    total_pnl = sum(pnls)
    avg_pnl = total_pnl / trades if trades else 0.0
    avg_pct = sum(pct_changes) / trades if trades else 0.0
    median_pct = statistics.median(pct_changes) if trades else 0.0

    gross_win = sum(pnl for pnl in pnls if pnl > 0.0)
    gross_loss = sum(-pnl for pnl in pnls if pnl < 0.0)
    profit_factor = gross_win / gross_loss if gross_loss != 0.0 else None

    avg_win = gross_win / wins if wins else 0.0
    avg_loss = gross_loss / losses if losses else 0.0
    expectancy = win_rate * avg_win - loss_rate * avg_loss

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        if equity > peak:
            peak = equity
        drawdown = peak - equity
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    best = max(pnls) if trades else 0.0
    worst = min(pnls) if trades else 0.0

    longest_win = 0
    longest_loss = 0
    current_win = 0
    current_loss = 0
    for pnl in pnls:
        if pnl > 0.0:
            current_win += 1
            current_loss = 0
            if current_win > longest_win:
                longest_win = current_win
        elif pnl < 0.0:
            current_loss += 1
            current_win = 0
            if current_loss > longest_loss:
                longest_loss = current_loss
        else:
            current_win = 0
            current_loss = 0

    holds: list[float] = []
    for item in qualified:
        entry = item[5]
        exit_ = item[6]
        if entry is not None and exit_ is not None:
            holds.append((exit_ - entry) / 60.0)
    median_hold = statistics.median(holds) if holds else None

    groups: dict[str, list[float]] = {}
    for item in qualified:
        groups.setdefault(item[4], []).append(item[2])

    reason_stats = [
        ExitReasonStat(
            reason=reason,
            trades=len(group_pnls),
            wins=sum(1 for pnl in group_pnls if pnl > 0.0),
            win_rate=sum(1 for pnl in group_pnls if pnl > 0.0) / len(group_pnls)
            if group_pnls
            else 0.0,
            pnl_usd=sum(group_pnls),
        )
        for reason, group_pnls in groups.items()
    ]
    reason_stats.sort(key=lambda stat: (-stat.trades, stat.reason))

    return PerformanceSummary(
        trades=trades,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        total_pnl_usd=total_pnl,
        avg_pnl_usd=avg_pnl,
        avg_pnl_pct=avg_pct,
        median_pnl_pct=median_pct,
        expectancy_usd=expectancy,
        gross_win_usd=gross_win,
        gross_loss_usd=gross_loss,
        profit_factor=profit_factor,
        max_drawdown_usd=max_drawdown,
        best_trade_usd=best,
        worst_trade_usd=worst,
        longest_win_streak=longest_win,
        longest_loss_streak=longest_loss,
        median_hold_minutes=median_hold,
        by_exit_reason=tuple(reason_stats),
    )


def summary_to_dict(summary: PerformanceSummary) -> dict[str, Any]:
    """Convert a summary to a plain JSON-serialisable dict."""
    result: dict[str, Any] = {}
    for field in fields(summary):
        name = field.name
        value = getattr(summary, name)
        if name == "by_exit_reason":
            result[name] = [
                {sub.name: _rounded(getattr(stat, sub.name)) for sub in fields(stat)}
                for stat in value
            ]
        else:
            result[name] = _rounded(value)
    return result


def render_summary_text(
    summary: PerformanceSummary, *, title: str = "Paper-trade performance"
) -> str:
    """Return a plain-text rendering of a performance summary."""
    lines: list[str] = [title]

    rows: list[tuple[str, str]] = [
        ("Trades", str(summary.trades)),
        ("Wins", str(summary.wins)),
        ("Losses", str(summary.losses)),
        ("Win rate", f"{summary.win_rate * 100.0:.1f}%"),
        ("Total PnL (USD)", f"{summary.total_pnl_usd:+.2f}"),
        ("Avg PnL (USD)", f"{summary.avg_pnl_usd:+.2f}"),
        ("Avg PnL (%)", f"{summary.avg_pnl_pct:.2f}%"),
        ("Median PnL (%)", f"{summary.median_pnl_pct:.2f}%"),
        ("Expectancy (USD)", f"{summary.expectancy_usd:+.2f}"),
        ("Gross win (USD)", f"{summary.gross_win_usd:.2f}"),
        ("Gross loss (USD)", f"{summary.gross_loss_usd:.2f}"),
        (
            "Profit factor",
            "n/a" if summary.profit_factor is None else f"{summary.profit_factor:.2f}",
        ),
        ("Max drawdown (USD)", f"{summary.max_drawdown_usd:.2f}"),
        ("Best trade (USD)", f"{summary.best_trade_usd:+.2f}"),
        ("Worst trade (USD)", f"{summary.worst_trade_usd:+.2f}"),
        ("Longest win streak", str(summary.longest_win_streak)),
        ("Longest loss streak", str(summary.longest_loss_streak)),
        (
            "Median hold (minutes)",
            "n/a" if summary.median_hold_minutes is None else f"{summary.median_hold_minutes:.2f}",
        ),
    ]

    label_width = max(len(label) for label, _ in rows)
    for label, value in rows:
        lines.append(f"{label:<{label_width}}: {value}")

    if summary.by_exit_reason:
        lines.append("By exit reason:")
        for stat in summary.by_exit_reason:
            lines.append(
                f"  {stat.reason}: {stat.trades} trades, {stat.wins} wins, "
                f"win rate {stat.win_rate * 100.0:.1f}%, "
                f"PnL {stat.pnl_usd:+.2f} USD"
            )

    return "\n".join(lines)


def render_summary_markdown(
    summary: PerformanceSummary, *, title: str = "Paper-trade performance"
) -> str:
    """Return a GitHub-flavoured Markdown rendering of a performance summary."""
    lines: list[str] = [f"## {title}", ""]

    rows: list[tuple[str, str]] = [
        ("Trades", str(summary.trades)),
        ("Wins", str(summary.wins)),
        ("Losses", str(summary.losses)),
        ("Win rate", f"{summary.win_rate * 100.0:.1f}%"),
        ("Total PnL (USD)", f"{summary.total_pnl_usd:+.2f}"),
        ("Avg PnL (USD)", f"{summary.avg_pnl_usd:+.2f}"),
        ("Avg PnL (%)", f"{summary.avg_pnl_pct:.2f}%"),
        ("Median PnL (%)", f"{summary.median_pnl_pct:.2f}%"),
        ("Expectancy (USD)", f"{summary.expectancy_usd:+.2f}"),
        ("Gross win (USD)", f"{summary.gross_win_usd:.2f}"),
        ("Gross loss (USD)", f"{summary.gross_loss_usd:.2f}"),
        (
            "Profit factor",
            "n/a" if summary.profit_factor is None else f"{summary.profit_factor:.2f}",
        ),
        ("Max drawdown (USD)", f"{summary.max_drawdown_usd:.2f}"),
        ("Best trade (USD)", f"{summary.best_trade_usd:+.2f}"),
        ("Worst trade (USD)", f"{summary.worst_trade_usd:+.2f}"),
        ("Longest win streak", str(summary.longest_win_streak)),
        ("Longest loss streak", str(summary.longest_loss_streak)),
        (
            "Median hold (minutes)",
            "n/a" if summary.median_hold_minutes is None else f"{summary.median_hold_minutes:.2f}",
        ),
    ]

    lines.extend(["| Metric | Value |", "| --- | --- |"])
    for label, value in rows:
        lines.append(f"| {label} | {value} |")

    if summary.by_exit_reason:
        lines.extend(
            [
                "",
                "### By exit reason",
                "",
                "| Reason | Trades | Wins | Win rate | PnL (USD) |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for stat in summary.by_exit_reason:
            lines.append(
                f"| {stat.reason} | {stat.trades} | {stat.wins} | "
                f"{stat.win_rate * 100.0:.1f}% | {stat.pnl_usd:+.2f} |"
            )

    return "\n".join(lines)
