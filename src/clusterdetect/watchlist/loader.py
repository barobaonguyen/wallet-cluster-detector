"""CSV watchlist helpers."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def from_csv(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            address = (row.get("address") or "").strip()
            if not address:
                continue
            item: dict[str, Any] = {
                "address": address,
                "score": int(row.get("score") or 1),
                "label": (row.get("label") or "").strip() or None,
                "chain": (row.get("chain") or "solana").strip().lower(),
            }
            rows.append(item)
    return rows


def to_csv(wallets: list[dict[str, Any]], path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["address", "score", "label", "chain"])
        writer.writeheader()
        for wallet in wallets:
            writer.writerow(
                {
                    "address": wallet.get("address", ""),
                    "score": wallet.get("score", 1),
                    "label": wallet.get("label") or "",
                    "chain": wallet.get("chain") or "solana",
                }
            )
