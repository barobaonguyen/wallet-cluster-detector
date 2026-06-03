"""Token enrichment from free public sources."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from clusterdetect.config import DEXSCREENER_BASE, GECKO_BASE, PUMPFUN_API, RUGCHECK_BASE

log = logging.getLogger(__name__)


class Enricher:
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=20.0,
            headers={"User-Agent": "wallet-cluster-detector/0.1"},
        )
        self._gecko_lock = asyncio.Lock()
        self._gecko_last = 0.0

    async def close(self) -> None:
        await self.client.aclose()

    async def _gecko_throttle(self) -> None:
        async with self._gecko_lock:
            wait = 2.1 - (time.monotonic() - self._gecko_last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._gecko_last = time.monotonic()

    @staticmethod
    def _pair_to_info(mint: str, best: dict[str, Any]) -> dict[str, Any]:
        return {
            "mint": mint,
            "symbol": (best.get("baseToken") or {}).get("symbol"),
            "name": (best.get("baseToken") or {}).get("name"),
            "pool_address": best.get("pairAddress"),
            "dex": best.get("dexId"),
            "price_usd": float(best.get("priceUsd") or 0) or None,
            "liquidity_usd": float((best.get("liquidity") or {}).get("usd") or 0) or None,
            "fdv": best.get("fdv"),
            "mcap": best.get("marketCap"),
            "volume_h24": float((best.get("volume") or {}).get("h24") or 0) or None,
            "volume_h1": float((best.get("volume") or {}).get("h1") or 0) or None,
            "txn_h1_buys": ((best.get("txns") or {}).get("h1") or {}).get("buys"),
            "txn_h1_sells": ((best.get("txns") or {}).get("h1") or {}).get("sells"),
            "created_at": best.get("pairCreatedAt"),
            "url": best.get("url"),
            "raw": best,
        }

    async def dexscreener_token(self, mint: str, *, chain: str = "solana") -> dict[str, Any] | None:
        chain = chain.lower()
        try:
            r = await self.client.get(f"{DEXSCREENER_BASE}/tokens/v1/{chain}/{mint}")
            if r.status_code != 200:
                return None
            data = r.json()
            pairs = data if isinstance(data, list) else data.get("pairs", [])
            chain_pairs = [p for p in pairs if p.get("chainId") == chain]
            if not chain_pairs:
                return None
            chain_pairs.sort(
                key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0),
                reverse=True,
            )
            return self._pair_to_info(mint, chain_pairs[0])
        except Exception as exc:
            log.warning("dexscreener %s (%s): %s", mint[:8], chain, exc)
            return None

    async def dexscreener_tokens_batch(
        self, mints: list[str], *, chain: str = "solana"
    ) -> dict[str, dict[str, Any]]:
        if not mints:
            return {}
        chain = chain.lower()
        result: dict[str, dict[str, Any]] = {}
        for i in range(0, len(mints), 30):
            batch = mints[i : i + 30]
            try:
                r = await self.client.get(f"{DEXSCREENER_BASE}/tokens/v1/{chain}/{','.join(batch)}")
                if r.status_code != 200:
                    continue
                by_mint: dict[str, list[dict[str, Any]]] = {}
                for pair in r.json() or []:
                    if pair.get("chainId") != chain:
                        continue
                    base_mint = (pair.get("baseToken") or {}).get("address")
                    if base_mint:
                        by_mint.setdefault(base_mint, []).append(pair)
                for mint, pairs in by_mint.items():
                    pairs.sort(
                        key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0),
                        reverse=True,
                    )
                    result[mint] = self._pair_to_info(mint, pairs[0])
            except Exception as exc:
                log.warning("dexscreener batch (%s): %s", chain, exc)
        return result

    async def gecko_ohlc(
        self,
        pool_address: str,
        *,
        timeframe: str = "minute",
        aggregate: int = 5,
        limit: int = 100,
        before_ts: int | None = None,
        chain: str = "solana",
    ) -> list:
        chain = chain.lower()
        await self._gecko_throttle()
        params: dict[str, Any] = {"aggregate": aggregate, "limit": limit}
        if before_ts:
            params["before_timestamp"] = before_ts
        try:
            url = f"{GECKO_BASE}/networks/{chain}/pools/{pool_address}/ohlcv/{timeframe}"
            r = await self.client.get(url, params=params)
            if r.status_code != 200:
                return []
            return (r.json().get("data") or {}).get("attributes", {}).get("ohlcv_list", []) or []
        except Exception as exc:
            log.warning("gecko ohlc %s (%s): %s", pool_address[:8], chain, exc)
            return []

    async def gecko_pool_info(
        self, pool_address: str, *, chain: str = "solana"
    ) -> dict[str, Any] | None:
        chain = chain.lower()
        await self._gecko_throttle()
        try:
            r = await self.client.get(f"{GECKO_BASE}/networks/{chain}/pools/{pool_address}")
            if r.status_code != 200:
                return None
            return (r.json().get("data") or {}).get("attributes")
        except Exception:
            return None

    async def rugcheck(self, mint: str) -> dict[str, Any] | None:
        try:
            r = await self.client.get(f"{RUGCHECK_BASE}/tokens/{mint}/report/summary")
            if r.status_code != 200:
                return None
            data = r.json()
            return {
                "score": data.get("score"),
                "score_normalised": data.get("score_normalised"),
                "lp_locked_pct": data.get("lpLockedPct"),
                "risks": data.get("risks") or [],
            }
        except Exception as exc:
            log.warning("rugcheck %s: %s", mint[:8], exc)
            return None

    async def pumpfun_token(self, mint: str) -> dict[str, Any] | None:
        try:
            r = await self.client.get(f"{PUMPFUN_API}/coins/{mint}")
            if r.status_code != 200:
                return None
            data = r.json()
            return {
                "mint": data.get("mint"),
                "name": data.get("name"),
                "symbol": data.get("symbol"),
                "complete": data.get("complete"),
                "market_cap": data.get("usd_market_cap"),
                "bonding_curve": data.get("bonding_curve"),
                "created_timestamp": data.get("created_timestamp"),
                "twitter": data.get("twitter"),
                "telegram": data.get("telegram"),
                "website": data.get("website"),
            }
        except Exception:
            return None
