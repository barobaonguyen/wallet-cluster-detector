"""Score-weighted sliding-window cluster detection."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from clusterdetect.config import STABLES_BY_CHAIN


@dataclass
class Cluster:
    token_mint: str
    first_buy_ts: int
    last_buy_ts: int
    wallets: list[str]
    wallet_count: int
    total_usd: float
    wallet_scores: dict[str, int]
    total_wallet_score: int

    @property
    def duration_min(self) -> float:
        return max(0.0, (self.last_buy_ts - self.first_buy_ts) / 60.0)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ClusterDetector:
    def __init__(
        self,
        *,
        min_wallets: int = 3,
        window_minutes: int = 15,
        min_total_score: int = 6,
        min_usd: float = 0.0,
    ):
        self.min_wallets = min_wallets
        self.window_minutes = window_minutes
        self.min_total_score = min_total_score
        self.min_usd = min_usd

    def detect(self, swaps: list[dict[str, Any]], wallet_scores: dict[str, int]) -> list[Cluster]:
        window = self.window_minutes * 60
        by_token: dict[str, list[dict[str, Any]]] = {}
        stables = STABLES_BY_CHAIN["solana"]

        for swap in swaps:
            if swap.get("side") != "buy":
                continue
            token = swap.get("token_mint")
            if not token or token in stables:
                continue
            usd_value = swap.get("usd_value")
            if usd_value is not None and float(usd_value) < self.min_usd:
                continue
            wallet = swap.get("wallet")
            timestamp = swap.get("timestamp")
            if not wallet or timestamp is None:
                continue
            by_token.setdefault(token, []).append(
                {
                    "wallet": wallet,
                    "ts": int(timestamp),
                    "usd": float(usd_value or 0),
                    "sol": float(swap.get("sol_amount") or 0),
                    "sig": swap.get("signature"),
                    "score": int(wallet_scores.get(wallet, 1) or 1),
                }
            )

        clusters: list[Cluster] = []
        for token, buys in by_token.items():
            buys.sort(key=lambda x: x["ts"])
            start_idx = 0
            seen_clusters: list[tuple[int, int, set[str], float, set[str], dict[str, int]]] = []
            for end_idx in range(len(buys)):
                while buys[end_idx]["ts"] - buys[start_idx]["ts"] > window:
                    start_idx += 1
                window_buys = buys[start_idx : end_idx + 1]
                distinct_wallets = {b["wallet"] for b in window_buys}
                scores_in_window = {b["wallet"]: b["score"] for b in window_buys}
                total_score = sum(scores_in_window.values())
                if len(distinct_wallets) < self.min_wallets or total_score < self.min_total_score:
                    continue

                first_ts = window_buys[0]["ts"]
                last_ts = window_buys[-1]["ts"]
                sigs = {b["sig"] for b in window_buys if b.get("sig")}
                total_usd = sum(b["usd"] for b in window_buys)
                if seen_clusters and (first_ts - seen_clusters[-1][1] < window):
                    prev = seen_clusters[-1]
                    new_sigs = sigs - prev[4]
                    seen_clusters[-1] = (
                        prev[0],
                        last_ts,
                        prev[2] | distinct_wallets,
                        prev[3] + sum(b["usd"] for b in window_buys if b.get("sig") in new_sigs),
                        prev[4] | sigs,
                        {**prev[5], **scores_in_window},
                    )
                else:
                    seen_clusters.append(
                        (
                            first_ts,
                            last_ts,
                            set(distinct_wallets),
                            total_usd,
                            sigs,
                            scores_in_window,
                        )
                    )

            for first_ts, last_ts, wallets, total_usd, _sigs, scores in seen_clusters:
                clusters.append(
                    Cluster(
                        token_mint=token,
                        first_buy_ts=first_ts,
                        last_buy_ts=last_ts,
                        wallets=sorted(wallets),
                        wallet_count=len(wallets),
                        total_usd=total_usd,
                        wallet_scores=scores,
                        total_wallet_score=sum(scores.values()),
                    )
                )
        return clusters


def _cluster_value(cluster: Cluster | dict[str, Any], key: str) -> Any:
    return getattr(cluster, key) if isinstance(cluster, Cluster) else cluster[key]


def save_clusters(clusters: Sequence[Cluster | dict[str, Any]], *, chain: str = "solana") -> int:
    """Insert new clusters. Skip same-token overlapping clusters for the same chain."""

    from clusterdetect.db import conn

    now = int(time.time())
    inserted = 0
    with conn() as c:
        for cluster in clusters:
            token = _cluster_value(cluster, "token_mint")
            first_ts = _cluster_value(cluster, "first_buy_ts")
            last_ts = _cluster_value(cluster, "last_buy_ts")
            existing = c.execute(
                """SELECT id FROM clusters WHERE token_mint=? AND chain=?
                   AND first_buy_ts <= ? AND last_buy_ts >= ?""",
                (token, chain, last_ts, first_ts),
            ).fetchone()
            if existing:
                continue
            wallets = _cluster_value(cluster, "wallets")
            c.execute(
                """INSERT INTO clusters(token_mint, first_buy_ts, last_buy_ts, wallet_count,
                                        wallets_json, total_usd, detected_at, notified, chain)
                   VALUES(?,?,?,?,?,?,?,0,?)""",
                (
                    token,
                    first_ts,
                    last_ts,
                    _cluster_value(cluster, "wallet_count"),
                    json.dumps(wallets),
                    _cluster_value(cluster, "total_usd"),
                    now,
                    chain,
                ),
            )
            inserted += 1
    return inserted


def get_unnotified_clusters() -> list[dict[str, Any]]:
    from clusterdetect.db import conn

    with conn() as c:
        rows = c.execute(
            "SELECT * FROM clusters WHERE notified=0 ORDER BY first_buy_ts DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def mark_cluster_notified(cluster_id: int) -> None:
    from clusterdetect.db import conn

    with conn() as c:
        c.execute("UPDATE clusters SET notified=1 WHERE id=?", (cluster_id,))
