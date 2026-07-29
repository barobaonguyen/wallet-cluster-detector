"""Run an offline what-if grid of detector thresholds over locally stored swap rows and wallet
scores, without network access, database access, new data collection, or individual identity
analysis.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from itertools import product
from statistics import median
from typing import Any

from clusterdetect.domain.cluster import ClusterDetector


@dataclass(frozen=True)
class CalibrationRow:
    min_wallets: int
    window_minutes: int
    min_total_score: int
    clusters: int
    tokens: int
    total_usd: float
    median_wallet_count: float
    max_wallet_count: int


def sweep(
    swaps: Sequence[Mapping[str, Any]],
    wallet_scores: Mapping[str, int],
    *,
    min_wallets: Sequence[int] = (2, 3, 4),
    window_minutes: Sequence[int] = (5, 15, 30),
    min_total_score: Sequence[int] = (4, 6, 9),
    min_usd: float = 0.0,
) -> list[CalibrationRow]:
    wallets_sorted = sorted(set(min_wallets))
    windows_sorted = sorted(set(window_minutes))
    scores_sorted = sorted(set(min_total_score))

    if not wallets_sorted or not windows_sorted or not scores_sorted:
        return []

    swap_list = [dict(swap) for swap in swaps]
    scores_map = dict(wallet_scores)
    rows: list[CalibrationRow] = []

    for min_w, window, min_score in product(wallets_sorted, windows_sorted, scores_sorted):
        detector = ClusterDetector(
            min_wallets=min_w,
            window_minutes=window,
            min_total_score=min_score,
            min_usd=min_usd,
        )
        clusters = detector.detect(swap_list, scores_map)
        cluster_count = len(clusters)

        token_count = 0
        total_usd = 0.0
        median_wallets = 0.0
        max_wallets = 0
        if cluster_count:
            token_count = len({cluster.token_mint for cluster in clusters})
            total_usd = round(sum(cluster.total_usd for cluster in clusters), 2)
            wallet_counts = sorted(cluster.wallet_count for cluster in clusters)
            max_wallets = wallet_counts[-1]
            median_wallets = round(float(median(wallet_counts)), 2)

        rows.append(
            CalibrationRow(
                min_wallets=min_w,
                window_minutes=window,
                min_total_score=min_score,
                clusters=cluster_count,
                tokens=token_count,
                total_usd=total_usd,
                median_wallet_count=median_wallets,
                max_wallet_count=max_wallets,
            )
        )

    return sorted(rows, key=lambda row: (row.min_wallets, row.window_minutes, row.min_total_score))


def rows_to_dicts(rows: Sequence[CalibrationRow]) -> list[dict[str, Any]]:
    return [asdict(row) for row in rows]


def render_rows_text(
    rows: Sequence[CalibrationRow], *, title: str = "Threshold sensitivity"
) -> str:
    if not rows:
        return f"{title}\nNo combinations."

    headers = ["wallets", "window", "score", "clusters", "tokens", "median_wallets", "total_usd"]
    values: list[list[str]] = []
    for row in rows:
        values.append(
            [
                str(row.min_wallets),
                str(row.window_minutes),
                str(row.min_total_score),
                str(row.clusters),
                str(row.tokens),
                f"{row.median_wallet_count:.2f}",
                f"{row.total_usd:.2f}",
            ]
        )

    widths = [len(header) for header in headers]
    for line in values:
        widths = [max(widths[i], len(cell)) for i, cell in enumerate(line)]

    lines: list[str] = [title]
    lines.append("  ".join(header.rjust(widths[i]) for i, header in enumerate(headers)))
    for line in values:
        lines.append("  ".join(cell.rjust(widths[i]) for i, cell in enumerate(line)))

    return "\n".join(lines)


def render_rows_markdown(
    rows: Sequence[CalibrationRow], *, title: str = "Threshold sensitivity"
) -> str:
    if not rows:
        return f"## {title}\n_No combinations._"

    headers = [
        "Min wallets",
        "Window (min)",
        "Min score",
        "Clusters",
        "Tokens",
        "Median wallets",
        "Total USD",
    ]
    lines: list[str] = [f"## {title}"]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        cells = [
            str(row.min_wallets),
            str(row.window_minutes),
            str(row.min_total_score),
            str(row.clusters),
            str(row.tokens),
            f"{row.median_wallet_count:.2f}",
            f"{row.total_usd:.2f}",
        ]
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines)


def best_rows(rows: Sequence[CalibrationRow], *, limit: int = 3) -> list[CalibrationRow]:
    if limit <= 0:
        return []
    nonempty = [row for row in rows if row.clusters]
    ranked = sorted(
        nonempty,
        key=lambda row: (row.clusters, -row.min_wallets, -row.min_total_score, row.window_minutes),
    )
    return ranked[:limit]
