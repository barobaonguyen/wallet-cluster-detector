"""Base/EVM read adapter demo — normalizes on-chain swaps to the Solana shape.

This runs entirely offline against a fixture of decoded ERC-20 ``Transfer`` logs,
so it needs no RPC and no keys. It shows that Base swaps come out in the *same*
normalized shape the Solana ``parse_swap`` yields, which is what lets the existing
``ClusterDetector`` run unchanged on Base via ``clusterdetect scan --chain base``.

Run:

    python examples/base_adapter/run_base.py
"""

from __future__ import annotations

from clusterdetect import ClusterDetector, parse_evm_logs
from clusterdetect.config import USDC_BASE, WETH_BASE

TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
WALLET_A = "0x000000000000000000000000000000000000aaaa"
WALLET_B = "0x000000000000000000000000000000000000bbbb"
WALLET_C = "0x000000000000000000000000000000000000cccc"
MEME = "0x00000000000000000000000000000000000d1234"


def _topic(addr: str) -> str:
    return "0x" + "0" * 24 + addr.removeprefix("0x")


def _amt18(value: float) -> str:
    return hex(int(value * 10**18))


def _buy_logs(wallet: str, tx: str, weth_in: float, meme_out: float) -> list[dict]:
    return [
        {
            "address": WETH_BASE,
            "topics": [TRANSFER, _topic(wallet), _topic(MEME)],
            "data": _amt18(weth_in),
            "transactionHash": tx,
            "blockNumber": "0x1",
        },
        {
            "address": MEME,
            "topics": [TRANSFER, _topic(MEME), _topic(wallet)],
            "data": _amt18(meme_out),
            "transactionHash": tx,
            "blockNumber": "0x1",
        },
    ]


def main() -> None:
    decimals = {MEME.lower(): 18, WETH_BASE.lower(): 18, USDC_BASE.lower(): 6}
    swaps = []
    plan = [
        (WALLET_A, "0xa1", 0.4, 1000, 1000),
        (WALLET_B, "0xb1", 0.5, 1200, 1120),
        (WALLET_C, "0xc1", 0.3, 800, 1240),
    ]
    for wallet, tx, weth_in, meme_out, ts in plan:
        for swap in parse_evm_logs(
            _buy_logs(wallet, tx, weth_in, meme_out),
            wallet,
            chain="base",
            decimals=decimals,
            timestamps={tx: ts},
        ):
            swaps.append(swap)

    print("Normalized Base swaps (same shape as Solana parse_swap):")
    for swap in swaps:
        print(
            f"  {swap['side']:<4} {swap['wallet'][:10]}... "
            f"token={swap['token_mint'][:10]}... amount={swap['token_amount']:.0f} chain={swap['chain']}"
        )

    detector = ClusterDetector(min_wallets=3, window_minutes=15, min_total_score=3)
    scores = {WALLET_A: 1, WALLET_B: 1, WALLET_C: 1}
    clusters = detector.detect(swaps, scores)
    print(f"\nClusters detected on Base: {len(clusters)}")
    for cluster in clusters:
        print(
            f"  token={cluster.token_mint[:10]}... wallets={cluster.wallet_count} "
            f"window={cluster.duration_min:.0f}min"
        )


if __name__ == "__main__":
    main()
