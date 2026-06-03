"""Discover candidate smart wallets from early buyers of recent winners."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import Counter, defaultdict
from typing import Any

import httpx

from clusterdetect.clients.helius import HeliusClient
from clusterdetect.config import DEXSCREENER_BASE, GECKO_BASE, STABLES
from clusterdetect.db import conn, init_db, upsert_wallet

log = logging.getLogger(__name__)

TARGET_X = 2.0
MAX_AGE_DAYS = 21
MIN_FDV_USD = 100_000
MIN_LIQUIDITY_USD = 5_000
MAX_PAGES_BACK = 60
PARSE_PAGES_FROM_OLDEST = 4
PARSE_PER_PAGE = 60


async def collect_candidate_pools(http: httpx.AsyncClient) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}

    try:
        for page in (1, 2, 3):
            r = await http.get(
                f"{GECKO_BASE}/networks/solana/trending_pools",
                params={"page": page},
                timeout=15,
            )
            if r.status_code != 200:
                break
            for item in r.json().get("data", []):
                attr = item.get("attributes") or {}
                rel = item.get("relationships") or {}
                pool_addr = attr.get("address")
                base = (rel.get("base_token") or {}).get("data") or {}
                base_id = base.get("id", "")
                if not pool_addr or "solana_" not in base_id:
                    continue
                mint = base_id.split("solana_", 1)[1]
                change = attr.get("price_change_percentage") or {}
                candidates[pool_addr] = {
                    "pool": pool_addr,
                    "mint": mint,
                    "name": attr.get("name"),
                    "h1": float(change.get("h1") or 0),
                    "h6": float(change.get("h6") or 0),
                    "h24": float(change.get("h24") or 0),
                    "fdv": float(attr.get("fdv_usd") or 0),
                    "mcap": float(attr.get("market_cap_usd") or 0),
                    "liq": float(attr.get("reserve_in_usd") or 0),
                    "src": f"gecko_trending_p{page}",
                }
            await asyncio.sleep(2.2)
    except Exception as exc:
        log.warning("gecko trending: %s", exc)

    try:
        r = await http.get(
            f"{GECKO_BASE}/networks/solana/new_pools", params={"page": 1}, timeout=15
        )
        if r.status_code == 200:
            for item in r.json().get("data", []):
                attr = item.get("attributes") or {}
                rel = item.get("relationships") or {}
                pool_addr = attr.get("address")
                base = (rel.get("base_token") or {}).get("data") or {}
                base_id = base.get("id", "")
                if not pool_addr or "solana_" not in base_id or pool_addr in candidates:
                    continue
                mint = base_id.split("solana_", 1)[1]
                change = attr.get("price_change_percentage") or {}
                candidates[pool_addr] = {
                    "pool": pool_addr,
                    "mint": mint,
                    "name": attr.get("name"),
                    "h1": float(change.get("h1") or 0),
                    "h6": float(change.get("h6") or 0),
                    "h24": float(change.get("h24") or 0),
                    "fdv": float(attr.get("fdv_usd") or 0),
                    "mcap": float(attr.get("market_cap_usd") or 0),
                    "liq": float(attr.get("reserve_in_usd") or 0),
                    "src": "gecko_new",
                }
        await asyncio.sleep(2.2)
    except Exception as exc:
        log.warning("gecko new_pools: %s", exc)

    try:
        for endpoint in ("/token-boosts/top/v1", "/token-boosts/latest/v1"):
            r = await http.get(f"{DEXSCREENER_BASE}{endpoint}", timeout=15)
            if r.status_code != 200:
                continue
            mints = [
                item["tokenAddress"]
                for item in r.json()
                if item.get("chainId") == "solana" and item.get("tokenAddress")
            ]
            for i in range(0, min(len(mints), 60), 30):
                batch = mints[i : i + 30]
                rr = await http.get(
                    f"{DEXSCREENER_BASE}/tokens/v1/solana/{','.join(batch)}", timeout=15
                )
                if rr.status_code != 200:
                    continue
                for pair in rr.json() or []:
                    if pair.get("chainId") != "solana":
                        continue
                    pool = pair.get("pairAddress")
                    if not pool or pool in candidates:
                        continue
                    change = pair.get("priceChange") or {}
                    candidates[pool] = {
                        "pool": pool,
                        "mint": (pair.get("baseToken") or {}).get("address"),
                        "name": (pair.get("baseToken") or {}).get("symbol"),
                        "h1": float(change.get("h1") or 0),
                        "h6": float(change.get("h6") or 0),
                        "h24": float(change.get("h24") or 0),
                        "fdv": float(pair.get("fdv") or 0),
                        "mcap": float(pair.get("marketCap") or 0),
                        "liq": float((pair.get("liquidity") or {}).get("usd") or 0),
                        "src": "dex_boost",
                    }
    except Exception as exc:
        log.warning("dexscreener boosts: %s", exc)

    return list(candidates.values())


def is_winner(c: dict[str, Any]) -> bool:
    target_pct = (TARGET_X - 1) * 100
    return bool(c["h24"] >= target_pct or c["h6"] >= target_pct * 0.6 or c["h1"] >= 200)


def passes_quality(c: dict[str, Any]) -> bool:
    if c["fdv"] and c["fdv"] < MIN_FDV_USD:
        return False
    return not (c["liq"] and c["liq"] < MIN_LIQUIDITY_USD)


async def find_oldest_buyers(helius: HeliusClient, pool: str) -> list[dict[str, Any]]:
    before: str | None = None
    page_buffer: list[list[dict[str, Any]]] = []
    for _ in range(MAX_PAGES_BACK):
        sigs = await helius.get_signatures_for_address(pool, limit=100, before=before)
        if not sigs:
            break
        page_buffer.append(sigs)
        if len(page_buffer) > PARSE_PAGES_FROM_OLDEST + 1:
            page_buffer.pop(0)
        if len(sigs) < 100:
            break
        before = sigs[-1]["signature"]

    if not page_buffer:
        return []
    pages_to_parse = page_buffer[:-1] if len(page_buffer) > 1 else page_buffer
    sig_strs: list[str] = []
    for page in pages_to_parse:
        sig_strs.extend(s["signature"] for s in page[:PARSE_PER_PAGE] if not s.get("err"))
    sig_strs = sig_strs[: PARSE_PAGES_FROM_OLDEST * PARSE_PER_PAGE]

    parsed: list[dict[str, Any]] = []
    for i in range(0, len(sig_strs), 100):
        parsed.extend(await helius.parse_transactions(sig_strs[i : i + 100]))

    buyers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tx in parsed:
        ts = tx.get("timestamp")
        sig = tx.get("signature")
        swap = (tx.get("events") or {}).get("swap") or {}
        candidates: list[tuple[str | None, str | None]] = []
        for token_output in swap.get("tokenOutputs") or []:
            candidates.append(
                (
                    token_output.get("userAccount") or token_output.get("toUserAccount"),
                    token_output.get("mint"),
                )
            )
        for transfer in tx.get("tokenTransfers") or []:
            candidates.append((transfer.get("toUserAccount"), transfer.get("mint")))
        for user, mint in candidates:
            if not user or not mint or mint in STABLES or user == pool or user in seen:
                continue
            seen.add(user)
            buyers.append({"wallet": user, "ts": ts, "sig": sig, "mint": mint})
    return buyers


async def discover_winners(
    http: httpx.AsyncClient,
    *,
    helius: HeliusClient | None = None,
    max_winners: int = 25,
    max_keep: int = 80,
    dry_run: bool = False,
) -> list:
    init_db()
    candidates = await collect_candidate_pools(http)
    winners = [c for c in candidates if is_winner(c) and passes_quality(c)]
    winners.sort(key=lambda c: max(c["h24"], c["h6"] * 1.5, c["h1"] * 4), reverse=True)
    winners = winners[:max_winners]

    if dry_run:
        return winners
    if helius is None:
        raise ValueError("helius is required when dry_run=False")

    wallet_score: Counter[str] = Counter()
    wallet_winners: dict[str, set[str]] = defaultdict(set)
    for winner in winners:
        buyers = await find_oldest_buyers(helius, winner["pool"])
        for buyer in buyers:
            wallet = buyer["wallet"]
            wallet_score[wallet] += 1
            wallet_winners[wallet].add(winner["pool"])
        if helius.credits_used > 75_000:
            log.warning("Stopping discovery near the configured Helius credit guardrail")
            break

    ranked = sorted(wallet_score.items(), key=lambda x: x[1], reverse=True)
    very_smart = [(w, s) for w, s in ranked if s >= 3]
    smart = [(w, s) for w, s in ranked if s == 2]
    single = [(w, s) for w, s in ranked if s == 1]
    kept = very_smart[:] + smart[: max_keep - len(very_smart)]
    if len(kept) < max_keep:
        kept.extend(single[: max_keep - len(kept)])

    now = int(time.time())
    with conn() as c:
        c.execute("UPDATE wallets SET enabled=0 WHERE source='winner_discovered'")
        for wallet, score in kept:
            upsert_wallet(
                c,
                wallet,
                source="winner_discovered",
                label=f"early_in_{score}_winners",
                score=score,
                added_at=now,
            )
        c.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (
                "last_winner_discover",
                json.dumps(
                    {
                        "ts": now,
                        "winners": len(winners),
                        "wallets_kept": len(kept),
                        "credits_used": helius.credits_used,
                    }
                ),
            ),
        )
    return kept
