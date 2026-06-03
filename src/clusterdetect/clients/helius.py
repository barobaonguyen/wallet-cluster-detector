"""Helius RPC and Enhanced API wrapper.

Helius free accounts have a monthly credit ceiling. This client is intentionally
defensive: it rate-limits, rotates keys on monthly exhaustion, persists credit
usage, and opens a circuit breaker instead of hammering the API.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from clusterdetect.clients.rate_limiter import QuotaTracker, RateLimiter

log = logging.getLogger(__name__)


class CircuitBreakerOpen(Exception):
    """Raised by callers that choose to make circuit-open state explicit."""


class HeliusClient:
    CIRCUIT_429_THRESHOLD = 8
    CIRCUIT_OPEN_SECONDS = 900
    DEAD_WALLET_404_THRESHOLD = 3
    RPC_URL_DEFAULT = "https://mainnet.helius-rpc.com/?api-key={api_key}"
    PARSE_TX_URL = "https://api.helius.xyz/v0/transactions"
    ADDRESS_TX_URL = "https://api.helius.xyz/v0/addresses/{address}/transactions"

    def __init__(
        self,
        api_keys: list[str],
        *,
        rps: float = 6.0,
        retries: int = 5,
        daily_budget: int = 95_000,
        rpc_url: str | None = None,
    ):
        keys = [k.strip() for k in api_keys if k and k.strip()]
        if not keys:
            raise ValueError("api_keys must contain at least one Helius key")
        self.client = httpx.AsyncClient(timeout=30.0)
        self.limiter = RateLimiter(rps)
        self.quota = QuotaTracker(daily_budget, label_prefix="helius_credits")
        self.retries = max(1, retries)
        self.daily_budget = daily_budget
        self.rpc_url = rpc_url or self.RPC_URL_DEFAULT
        self.max_backoff_seconds = 30.0
        self.retry_jitter_seconds = 0.35

        self.api_keys = keys
        self.current_key_idx = 0
        self._exhausted_keys: set[str] = set()
        self._today_key: str | None = None
        self._month_key: str | None = None

        self._backoff_until = 0.0
        self._backoff_lock = asyncio.Lock()
        self._consecutive_429s = 0
        self._circuit_open_until = 0.0
        self._circuit_lock = asyncio.Lock()
        self._wallet_404_counts: dict[str, int] = {}

    @property
    def credits_used(self) -> int:
        return self.quota.used

    @credits_used.setter
    def credits_used(self, value: int) -> None:
        self.quota.used = value

    def is_circuit_open(self) -> bool:
        return time.monotonic() < self._circuit_open_until

    def is_budget_exhausted(self) -> bool:
        self._maybe_rollover_day()
        return self.quota.is_exhausted()

    def current_key(self) -> str:
        return self.api_keys[self.current_key_idx]

    def _apply_current_key(
        self, url: str | None, params: dict[str, Any] | None
    ) -> tuple[str | None, dict[str, Any] | None]:
        key = self.current_key()
        if url:
            if "{api_key}" in url:
                url = url.format(api_key=key)
            elif "api-key=" in url:
                url = re.sub(r"api-key=[^&]+", f"api-key={key}", url)
        if params and "api-key" in params:
            params = {**params, "api-key": key}
        return url, params

    def _key_label(self, key: str) -> str:
        idx = self.api_keys.index(key) if key in self.api_keys else -1
        return f"key#{idx + 1}" if idx >= 0 else "key#?"

    def rotate_key(self) -> bool:
        cur = self.current_key()
        self._exhausted_keys.add(cur)
        log.warning("Helius %s exhausted; rotating", self._key_label(cur))
        self._persist_exhausted_keys()
        for offset in range(1, len(self.api_keys) + 1):
            idx = (self.current_key_idx + offset) % len(self.api_keys)
            if self.api_keys[idx] not in self._exhausted_keys:
                self.current_key_idx = idx
                self._consecutive_429s = 0
                log.info("Helius now using %s", self._key_label(self.api_keys[idx]))
                return True
        return False

    async def load_persisted_credits(self) -> None:
        try:
            from clusterdetect.db import conn, get_meta

            now = datetime.now(UTC)
            self._today_key = f"helius_credits_{now:%Y-%m-%d}"
            self._month_key = f"helius_exhausted_keys_{now:%Y-%m}"
            with conn() as c:
                credits = get_meta(c, self._today_key, default="0")
                fingerprints = get_meta(c, self._month_key, default="") or ""
            self.credits_used = int(credits or 0)
            exhausted_fps = {fp for fp in fingerprints.split(",") if fp}
            for key in self.api_keys:
                if key[-6:] in exhausted_fps:
                    self._exhausted_keys.add(key)
            if self.current_key() in self._exhausted_keys:
                self.rotate_key()
            log.info(
                "Helius credit budget: %s/%s used today (UTC)",
                self.credits_used,
                self.daily_budget,
            )
        except Exception as exc:  # pragma: no cover - best effort around local DB
            log.warning("could not load persisted Helius credits: %s", exc)

    def _maybe_rollover_day(self) -> None:
        if not self._today_key:
            return
        today_key = f"helius_credits_{datetime.now(UTC):%Y-%m-%d}"
        if today_key != self._today_key:
            previous_key = self._today_key
            previous_used = self.credits_used
            self._today_key = today_key
            try:
                from clusterdetect.db import conn, get_meta

                with conn() as c:
                    self.credits_used = int(get_meta(c, self._today_key, default="0") or 0)
            except Exception:
                self.credits_used = 0
            log.info(
                "Helius UTC day rollover: %s (%s used) -> %s (%s used)",
                previous_key,
                previous_used,
                self._today_key,
                self.credits_used,
            )

        month_key = f"helius_exhausted_keys_{datetime.now(UTC):%Y-%m}"
        if self._month_key and month_key != self._month_key:
            self._month_key = month_key
            self._exhausted_keys.clear()

    def _persist_credits(self) -> None:
        if not self._today_key:
            return
        try:
            from clusterdetect.db import conn, set_meta

            with conn() as c:
                set_meta(c, self._today_key, self.credits_used)
        except Exception:  # pragma: no cover - best effort persistence
            pass

    def _persist_exhausted_keys(self) -> None:
        if not self._month_key:
            self._month_key = f"helius_exhausted_keys_{datetime.now(UTC):%Y-%m}"
        try:
            from clusterdetect.db import conn, set_meta

            fingerprints = ",".join(sorted(k[-6:] for k in self._exhausted_keys))
            with conn() as c:
                set_meta(c, self._month_key, fingerprints)
        except Exception:  # pragma: no cover - best effort persistence
            pass

    async def _open_circuit_if_needed(self) -> None:
        async with self._circuit_lock:
            if self._consecutive_429s >= self.CIRCUIT_429_THRESHOLD:
                self._circuit_open_until = time.monotonic() + self.CIRCUIT_OPEN_SECONDS
                self._consecutive_429s = 0
                log.error(
                    "Helius circuit open after repeated 429s; pausing requests for %s seconds",
                    self.CIRCUIT_OPEN_SECONDS,
                )

    async def close(self) -> None:
        await self.client.aclose()

    @staticmethod
    def _redact_url(url: str) -> str:
        if "api-key=" not in url:
            return url
        start = url.find("api-key=") + len("api-key=")
        end = url.find("&", start)
        if end == -1:
            return url[:start] + "***"
        return url[:start] + "***" + url[end:]

    @staticmethod
    def _parse_retry_after_seconds(r: httpx.Response) -> float | None:
        raw = r.headers.get("Retry-After")
        if not raw:
            return None
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return max(0.0, (dt - datetime.now(UTC)).total_seconds())
        except Exception:
            return None

    def _backoff_seconds(self, attempt: int, retry_after: float | None = None) -> float:
        base = (
            retry_after
            if retry_after is not None
            else min(self.max_backoff_seconds, float(2**attempt))
        )
        return base + random.uniform(0.0, self.retry_jitter_seconds)

    async def _sleep_with_global_backoff(self) -> None:
        while True:
            async with self._backoff_lock:
                wait = self._backoff_until - time.monotonic()
            if wait <= 0:
                return
            await asyncio.sleep(wait)

    async def _extend_global_backoff(self, wait_seconds: float) -> None:
        if wait_seconds <= 0:
            return
        async with self._backoff_lock:
            self._backoff_until = max(self._backoff_until, time.monotonic() + wait_seconds)

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        op_name: str,
        retries: int | None = None,
        on_4xx: Any = None,
    ) -> httpx.Response | None:
        if self.is_circuit_open():
            wait = self._circuit_open_until - time.monotonic()
            log.debug("%s: circuit open for %.0fs, skipping", op_name, wait)
            return None
        if self.is_budget_exhausted():
            log.debug(
                "%s: Helius budget exhausted (%s/%s), skipping",
                op_name,
                self.credits_used,
                self.daily_budget,
            )
            return None

        tries = max(1, retries if retries is not None else self.retries)
        for attempt in range(tries):
            await self._sleep_with_global_backoff()
            await self.limiter.acquire()
            req_url, req_params = self._apply_current_key(url, params)
            if req_url is None:
                return None
            safe_url = self._redact_url(req_url)
            try:
                r = await self.client.request(method, req_url, params=req_params, json=json)
            except Exception as exc:
                if attempt == tries - 1:
                    log.error("%s failed after %s tries: %s", op_name, tries, exc)
                    return None
                wait = self._backoff_seconds(attempt)
                log.warning("%s network error; retrying in %.1fs", op_name, wait)
                await asyncio.sleep(wait)
                continue

            if r.status_code == 429:
                body_snip = (r.text or "")[:200].lower()
                if "max usage reached" in body_snip:
                    if self.rotate_key():
                        await asyncio.sleep(0.2)
                        continue
                    self._circuit_open_until = time.monotonic() + 86_400
                    log.error("All Helius keys exhausted. Circuit open for 24h.")
                    return None
                async with self._circuit_lock:
                    self._consecutive_429s += 1
                await self._open_circuit_if_needed()
                if self.is_circuit_open():
                    return None
                wait = self._backoff_seconds(attempt, self._parse_retry_after_seconds(r))
                await self._extend_global_backoff(wait)
                if attempt == tries - 1:
                    log.error("%s hit 429 after %s tries (%s)", op_name, tries, safe_url)
                    return None
                await asyncio.sleep(wait)
                continue

            if r.status_code >= 500:
                if attempt == tries - 1:
                    log.error(
                        "%s server error %s after %s tries (%s)",
                        op_name,
                        r.status_code,
                        tries,
                        safe_url,
                    )
                    return None
                wait = self._backoff_seconds(attempt)
                await asyncio.sleep(wait)
                continue

            if r.status_code >= 400:
                log.error("%s returned %s (%s)", op_name, r.status_code, safe_url)
                if on_4xx is not None:
                    on_4xx(r.status_code)
                return None

            async with self._circuit_lock:
                self._consecutive_429s = 0
            return r
        return None

    async def _rpc(self, method: str, params: list[Any], retries: int = 3) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        r = await self._request_with_retry(
            "POST", self.rpc_url, json=payload, op_name=f"rpc:{method}", retries=retries
        )
        if not r:
            return None
        self._maybe_rollover_day()
        self.quota.add(1)
        self._persist_credits()
        try:
            data = r.json()
        except Exception as exc:
            log.error("RPC decode failed for %s: %s", method, exc)
            return None
        if "error" in data:
            log.warning("RPC error for %s: %s", method, data["error"])
            return None
        return data.get("result")

    async def get_signatures_for_address(
        self,
        address: str,
        *,
        limit: int = 100,
        before: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        opts: dict[str, Any] = {"limit": limit}
        if before:
            opts["before"] = before
        if until:
            opts["until"] = until
        return await self._rpc("getSignaturesForAddress", [address, opts]) or []

    async def get_transaction(self, signature: str) -> dict[str, Any] | None:
        return await self._rpc(
            "getTransaction",
            [signature, {"maxSupportedTransactionVersion": 0, "encoding": "jsonParsed"}],
        )

    async def parse_transactions(
        self, signatures: list[str], *, retries: int = 3
    ) -> list[dict[str, Any]]:
        if not signatures:
            return []
        batch = signatures[:100]
        r = await self._request_with_retry(
            "POST",
            self.PARSE_TX_URL,
            params={"api-key": "_PLACEHOLDER_"},
            json={"transactions": batch},
            op_name="parse_transactions",
            retries=retries,
        )
        if not r:
            return []
        try:
            data = r.json() or []
        except Exception as exc:
            log.error("parse_transactions decode failed: %s", exc)
            return []
        self._maybe_rollover_day()
        self.quota.add(len(batch))
        self._persist_credits()
        return data if isinstance(data, list) else []

    def _bump_404_and_maybe_disable(self, address: str) -> None:
        n = self._wallet_404_counts.get(address, 0) + 1
        self._wallet_404_counts[address] = n
        if n < self.DEAD_WALLET_404_THRESHOLD:
            return
        try:
            from clusterdetect.db import conn

            with conn() as c:
                c.execute("UPDATE wallets SET enabled=0 WHERE address=? AND enabled=1", (address,))
            self._wallet_404_counts.pop(address, None)
            log.warning("auto-disabled wallet %s after repeated 404s", address[:8])
        except Exception as exc:  # pragma: no cover - best effort DB coupling
            log.debug("could not auto-disable %s: %s", address[:8], exc)

    async def get_address_transactions(
        self,
        address: str,
        *,
        before: str | None = None,
        limit: int = 100,
        tx_type: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"api-key": "_PLACEHOLDER_", "limit": limit}
        if before:
            params["before"] = before
        if tx_type:
            params["type"] = tx_type
        r = await self._request_with_retry(
            "GET",
            self.ADDRESS_TX_URL.format(address=address),
            params=params,
            op_name=f"get_address_transactions:{address[:8]}",
            on_4xx=lambda status: self._bump_404_and_maybe_disable(address)
            if status == 404
            else None,
        )
        if not r:
            return []
        self._wallet_404_counts.pop(address, None)
        try:
            data = r.json() or []
        except Exception as exc:
            log.error("get_address_transactions decode failed for %s: %s", address[:8], exc)
            return []
        if isinstance(data, list):
            self._maybe_rollover_day()
            self.quota.add(max(1, len(data)))
            self._persist_credits()
            return data
        return []
