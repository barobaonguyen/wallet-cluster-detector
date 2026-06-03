"""Paper-trade simulator with parameterized exit rules."""

from __future__ import annotations

from dataclasses import dataclass

from clusterdetect.domain.cluster import Cluster


@dataclass
class PaperTrade:
    token_mint: str
    entry_ts: int
    entry_price_usd: float
    position_usd: float
    status: str = "open"
    peak_price_usd: float | None = None
    exit_ts: int | None = None
    exit_price_usd: float | None = None
    exit_reason: str | None = None
    pnl_pct: float | None = None
    pnl_usd: float | None = None


class PaperTrader:
    """Illustrative paper-trade rules. Tune these on your own paper data."""

    def __init__(
        self,
        *,
        position_usd: float = 50.0,
        hard_stop_pct: float = -0.40,
        hard_stop_window_min: int = 20,
        tp1_x: float = 3.0,
        tp1_take: float = 0.5,
        tp2_x: float = 10.0,
        tp2_take: float = 0.25,
        trail_pct_from_peak: float = -0.50,
        time_stop_hours: int = 48,
    ):
        self.position_usd = position_usd
        self.hard_stop_pct = hard_stop_pct
        self.hard_stop_window_min = hard_stop_window_min
        self.tp1_x = tp1_x
        self.tp1_take = tp1_take
        self.tp2_x = tp2_x
        self.tp2_take = tp2_take
        self.trail_pct_from_peak = trail_pct_from_peak
        self.time_stop_hours = time_stop_hours

    def open(
        self, cluster: Cluster, entry_price_usd: float, *, ts: int, size_mult: float = 1.0
    ) -> PaperTrade:
        if entry_price_usd <= 0:
            raise ValueError("entry_price_usd must be > 0")
        return PaperTrade(
            token_mint=cluster.token_mint,
            entry_ts=ts,
            entry_price_usd=entry_price_usd,
            position_usd=self.position_usd * size_mult,
            peak_price_usd=entry_price_usd,
        )

    def update(self, trade: PaperTrade, current_price_usd: float | None, *, now: int) -> PaperTrade:
        if trade.status != "open":
            return trade

        elapsed = now - trade.entry_ts
        entry = trade.entry_price_usd
        peak = trade.peak_price_usd or entry

        if current_price_usd is None:
            if elapsed >= self.time_stop_hours * 3600:
                return self._close(trade, peak, now=now, reason="time_stop_dead")
            return trade

        peak = max(peak, current_price_usd)
        trade.peak_price_usd = peak
        pnl_ratio = current_price_usd / entry - 1

        if elapsed <= self.hard_stop_window_min * 60 and pnl_ratio <= self.hard_stop_pct:
            return self._close(trade, current_price_usd, now=now, reason="hard_stop")

        tp1_reached = peak / entry >= self.tp1_x
        if tp1_reached and (current_price_usd - peak) / peak <= self.trail_pct_from_peak:
            return self._close(trade, current_price_usd, now=now, reason="trail_stop")

        if elapsed >= self.time_stop_hours * 3600:
            return self._close(trade, current_price_usd, now=now, reason="time_stop")

        return trade

    @staticmethod
    def _close(trade: PaperTrade, exit_price: float, *, now: int, reason: str) -> PaperTrade:
        ratio = exit_price / trade.entry_price_usd - 1
        trade.status = "closed"
        trade.exit_ts = now
        trade.exit_price_usd = exit_price
        trade.exit_reason = reason
        trade.pnl_pct = ratio * 100
        trade.pnl_usd = trade.position_usd * ratio
        trade.peak_price_usd = max(trade.peak_price_usd or trade.entry_price_usd, exit_price)
        return trade
