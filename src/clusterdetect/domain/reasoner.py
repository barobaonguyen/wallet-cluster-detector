"""Rule-based cluster signal scorer with an illustrative public rubric."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from clusterdetect.domain.cluster import Cluster


@dataclass
class Evaluation:
    decision: str
    score: int
    pros: list[str]
    warns: list[str]
    one_liner: str
    total_wallet_score: int


DEFAULT_RUBRIC: dict[str, Any] = {
    "base": 50,
    "wallet": {
        "top_score": 3,
        "top_bonus": 11,
        "mid_score": 2,
        "mid_bonus": 7,
        "total_score_high": 9,
        "total_score_bonus": 9,
        "total_score_ok_bonus": 4,
        "total_score_low_penalty": -11,
    },
    "cluster": {"large_wallet_count": 4, "large_bonus": 9, "ok_bonus": 4},
    "age": {
        "new_hours": 24,
        "new_bonus": 7,
        "fresh_hours": 72,
        "fresh_bonus": 4,
        "older_hours": 240,
        "older_penalty": -7,
    },
    "market_cap": {
        "too_small": 75_000,
        "early": 1_000_000,
        "mid": 5_000_000,
        "too_small_penalty": -7,
        "early_bonus": 9,
        "mid_bonus": 4,
        "large_penalty": -9,
    },
    "liquidity": {
        "healthy": 75_000,
        "minimum": 25_000,
        "healthy_bonus": 4,
        "thin_penalty": -11,
    },
    "flow": {
        "volume_h1": 75_000,
        "volume_bonus": 4,
        "buy_ratio": 1.25,
        "sell_ratio": 0.8,
        "buy_bonus": 7,
        "sell_penalty": -7,
    },
    "rugcheck": {
        "clean": 80,
        "acceptable": 45,
        "clean_bonus": 7,
        "risk_penalty": -13,
        "lp_strong": 75,
        "lp_minimum": 40,
        "lp_bonus": 4,
        "lp_penalty": -11,
        "danger_penalty": -9,
        "warn_penalty": -3,
    },
}


class ClusterScorer:
    def __init__(
        self,
        *,
        rubric: dict[str, Any] | None = None,
        strong_at: int = 70,
        ok_at: int = 50,
        risky_at: int = 30,
    ):
        self.rubric = rubric or DEFAULT_RUBRIC
        self.strong_at = strong_at
        self.ok_at = ok_at
        self.risky_at = risky_at

    def evaluate(
        self,
        cluster: Cluster,
        token_info: dict[str, Any] | None,
        rugcheck: dict[str, Any] | None,
        wallet_details: list[dict[str, Any]],
    ) -> Evaluation:
        pros: list[str] = []
        warns: list[str] = []
        score = int(self.rubric.get("base", 50))
        token_info = token_info or {}

        wallet_rule = self.rubric["wallet"]
        total_wallet_score = sum(int(w.get("score", 1) or 1) for w in wallet_details)
        high_score = [
            w for w in wallet_details if int(w.get("score", 1) or 1) >= wallet_rule["top_score"]
        ]
        mid_score = [
            w for w in wallet_details if int(w.get("score", 1) or 1) == wallet_rule["mid_score"]
        ]

        if high_score:
            pros.append(f"{len(high_score)} top-tier wallet(s) in the cluster")
            score += wallet_rule["top_bonus"]
        if mid_score:
            pros.append(f"{len(mid_score)} proven wallet(s) in the cluster")
            score += wallet_rule["mid_bonus"]

        if total_wallet_score >= wallet_rule["total_score_high"]:
            pros.append(f"Combined wallet score is {total_wallet_score}")
            score += wallet_rule["total_score_bonus"]
        elif total_wallet_score >= cluster.total_wallet_score:
            pros.append(f"Wallet score clears the configured cluster floor ({total_wallet_score})")
            score += wallet_rule["total_score_ok_bonus"]
        else:
            warns.append(f"Wallet score is light for this setup ({total_wallet_score})")
            score += wallet_rule["total_score_low_penalty"]

        cluster_rule = self.rubric["cluster"]
        if cluster.wallet_count >= cluster_rule["large_wallet_count"]:
            pros.append(
                f"{cluster.wallet_count} distinct wallets bought within {cluster.duration_min:.0f} min"
            )
            score += cluster_rule["large_bonus"]
        elif cluster.wallet_count >= 2:
            pros.append(
                f"{cluster.wallet_count} wallets bought within {cluster.duration_min:.0f} min"
            )
            score += cluster_rule["ok_bonus"]

        created_ms = token_info.get("created_at") or 0
        if created_ms:
            age_h = (time.time() - created_ms / 1000) / 3600
            age_rule = self.rubric["age"]
            if age_h < age_rule["new_hours"]:
                pros.append(f"Token is new ({age_h:.1f}h)")
                score += age_rule["new_bonus"]
            elif age_h < age_rule["fresh_hours"]:
                pros.append(f"Token is still fresh ({age_h:.0f}h)")
                score += age_rule["fresh_bonus"]
            elif age_h > age_rule["older_hours"]:
                warns.append(f"Token has already traded for {age_h / 24:.0f}d")
                score += age_rule["older_penalty"]

        market_cap = token_info.get("mcap") or token_info.get("fdv")
        if market_cap:
            score += self._score_market_cap(float(market_cap), pros, warns)

        liquidity = float(token_info.get("liquidity_usd") or 0)
        liq_rule = self.rubric["liquidity"]
        if liquidity >= liq_rule["healthy"]:
            pros.append(f"Liquidity is healthy at {self._fmt_money(liquidity)}")
            score += liq_rule["healthy_bonus"]
        elif liquidity and liquidity < liq_rule["minimum"]:
            warns.append(f"Liquidity is thin at {self._fmt_money(liquidity)}")
            score += liq_rule["thin_penalty"]

        flow_rule = self.rubric["flow"]
        volume_h1 = float(token_info.get("volume_h1") or 0)
        if volume_h1 >= flow_rule["volume_h1"]:
            pros.append(f"1h volume shows activity ({self._fmt_money(volume_h1)})")
            score += flow_rule["volume_bonus"]

        buys_h1 = token_info.get("txn_h1_buys") or 0
        sells_h1 = token_info.get("txn_h1_sells") or 0
        if buys_h1 and sells_h1:
            ratio = buys_h1 / max(sells_h1, 1)
            if ratio >= flow_rule["buy_ratio"]:
                pros.append(f"1h flow leans buy-side ({buys_h1} buys / {sells_h1} sells)")
                score += flow_rule["buy_bonus"]
            elif ratio < flow_rule["sell_ratio"]:
                warns.append(f"1h flow leans sell-side ({sells_h1} sells / {buys_h1} buys)")
                score += flow_rule["sell_penalty"]

        if rugcheck:
            score += self._score_rugcheck(rugcheck, pros, warns)

        score = max(0, min(100, int(score)))
        if score >= self.strong_at and not self._has_hard_warn(warns):
            decision = "STRONG"
        elif score >= self.ok_at:
            decision = "OK"
        elif score >= self.risky_at:
            decision = "RISKY"
        else:
            decision = "SKIP"

        one_liner = self._make_one_liner(
            decision, cluster.wallet_count, total_wallet_score, market_cap, score
        )
        return Evaluation(
            decision=decision,
            score=score,
            pros=pros,
            warns=warns,
            one_liner=one_liner,
            total_wallet_score=total_wallet_score,
        )

    def _score_market_cap(self, market_cap: float, pros: list[str], warns: list[str]) -> int:
        rule = self.rubric["market_cap"]
        if market_cap < rule["too_small"]:
            warns.append(f"Market cap is very small ({self._fmt_money(market_cap)})")
            return rule["too_small_penalty"]
        if market_cap < rule["early"]:
            pros.append(f"Market cap leaves room for discovery ({self._fmt_money(market_cap)})")
            return rule["early_bonus"]
        if market_cap < rule["mid"]:
            pros.append(f"Market cap is in a moderate public range ({self._fmt_money(market_cap)})")
            return rule["mid_bonus"]
        warns.append(
            f"Market cap is already large for a fresh cluster ({self._fmt_money(market_cap)})"
        )
        return rule["large_penalty"]

    def _score_rugcheck(self, rugcheck: dict[str, Any], pros: list[str], warns: list[str]) -> int:
        rule = self.rubric["rugcheck"]
        delta = 0
        rc_score = rugcheck.get("score_normalised")
        if rc_score is not None:
            if rc_score >= rule["clean"]:
                pros.append(f"Rugcheck score is clean enough for research ({rc_score}/100)")
                delta += rule["clean_bonus"]
            elif rc_score < rule["acceptable"]:
                warns.append(f"Rugcheck score is weak ({rc_score}/100)")
                delta += rule["risk_penalty"]

        lp_locked = rugcheck.get("lp_locked_pct")
        if lp_locked is not None:
            if lp_locked >= rule["lp_strong"]:
                pros.append(f"LP lock is visible ({lp_locked:.0f}%)")
                delta += rule["lp_bonus"]
            elif lp_locked < rule["lp_minimum"]:
                warns.append(f"LP lock is weak ({lp_locked:.0f}%)")
                delta += rule["lp_penalty"]

        for risk in (rugcheck.get("risks") or [])[:3]:
            level = risk.get("level", "")
            name = risk.get("name", "unnamed risk")
            if level == "danger":
                warns.append(f"Rugcheck danger: {name}")
                delta += rule["danger_penalty"]
            elif level == "warn":
                warns.append(f"Rugcheck warning: {name}")
                delta += rule["warn_penalty"]
        return delta

    @staticmethod
    def _has_hard_warn(warns: list[str]) -> bool:
        text = " ".join(warns).lower()
        return any(term in text for term in ("danger", "weak", "scam"))

    @staticmethod
    def _fmt_money(v: float) -> str:
        if v >= 1_000_000:
            return f"${v / 1_000_000:.2f}M"
        if v >= 1_000:
            return f"${v / 1_000:.1f}K"
        return f"${v:.0f}"

    def _make_one_liner(
        self, decision: str, wallet_count: int, total_score: int, market_cap: Any, score: int
    ) -> str:
        mcap_str = f" | mcap {self._fmt_money(float(market_cap))}" if market_cap else ""
        return f"{decision} ({score}/100): {wallet_count} wallets / wallet-score {total_score}{mcap_str}"


def format_reason_block(ev: Evaluation) -> str:
    """Telegram-friendly HTML block explaining the signal without trade advice."""

    lines = [f"<b>Signal review</b>: {ev.one_liner}"]
    if ev.pros:
        lines.append("<b>Supporting evidence:</b>")
        for pro in ev.pros[:6]:
            lines.append(f"  - {pro}")
    if ev.warns:
        lines.append("<b>Risk checks:</b>")
        for warn in ev.warns[:6]:
            lines.append(f"  - {warn}")
    if ev.decision == "STRONG":
        lines.append("<b>Next step:</b> verify manually and paper trade first.")
    elif ev.decision == "OK":
        lines.append("<b>Next step:</b> keep on watchlist and validate liquidity/risk.")
    elif ev.decision == "RISKY":
        lines.append("<b>Next step:</b> research only; risk flags remain.")
    else:
        lines.append("<b>Next step:</b> skip this alert path.")
    return "\n".join(lines)
