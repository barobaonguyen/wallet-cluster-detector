"""Telegram bot client and HTML alert formatting."""

from __future__ import annotations

import html
import logging
from typing import Any

import httpx

from clusterdetect.domain.cluster import Cluster
from clusterdetect.domain.reasoner import Evaluation, format_reason_block

log = logging.getLogger(__name__)


class TelegramAlerter:
    def __init__(self, bot_token: str | None, chat_id: str | None):
        self.bot_token = (bot_token or "").strip()
        self.chat_id = (chat_id or "").strip()
        self.api = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else ""

    async def send(
        self,
        text: str,
        *,
        parse_mode: str = "HTML",
        disable_preview: bool = True,
    ) -> bool:
        if not self.bot_token or not self.chat_id:
            log.warning("Telegram credentials missing; skipping send")
            return False
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                r = await client.post(
                    f"{self.api}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": parse_mode,
                        "disable_web_page_preview": disable_preview,
                    },
                )
                data = r.json()
                if not data.get("ok"):
                    log.error("Telegram error: %s", data)
                    return False
                return True
            except Exception as exc:
                log.error("telegram send failed: %s", exc)
                return False

    async def get_updates(self, offset: int | None = None) -> list:
        if not self.bot_token:
            return []
        params: dict[str, Any] = {"timeout": 0}
        if offset:
            params["offset"] = offset
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{self.api}/getUpdates", params=params)
            return r.json().get("result", [])


def _value(obj: Cluster | dict[str, Any], key: str, default: Any = None) -> Any:
    if isinstance(obj, Cluster):
        return getattr(obj, key, default)
    return obj.get(key, default)


def _fmt_money(v: Any) -> str:
    if v is None:
        return "?"
    v = float(v)
    if v >= 1_000_000:
        return f"${v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v / 1_000:.1f}K"
    return f"${v:.0f}"


def _fmt_price(v: Any) -> str:
    if v is None:
        return "?"
    return f"${float(v):.8f}".rstrip("0").rstrip(".")


def format_cluster_alert(
    cluster: Cluster | dict[str, Any],
    token_info: dict[str, Any],
    rugcheck: dict[str, Any] | None = None,
    evaluation: Evaluation | None = None,
) -> str:
    sym = html.escape(str(token_info.get("symbol") or "?"))
    name = html.escape(str(token_info.get("name") or ""))
    mint = html.escape(str(_value(cluster, "token_mint")))
    wallet_count = _value(cluster, "wallet_count", 0)
    total = _value(cluster, "total_usd", 0)
    total_score = _value(cluster, "total_wallet_score", 0)
    first_ts = _value(cluster, "first_buy_ts", 0)
    last_ts = _value(cluster, "last_buy_ts", first_ts)
    duration_min = max(0.0, (last_ts - first_ts) / 60)

    decision = f" {evaluation.decision}" if evaluation else ""
    header = f"<b>CLUSTER BUY{decision}: {sym}</b>"
    msg = [
        header,
        f"<i>{name}</i>" if name else "",
        "",
        f"Smart wallets: <b>{wallet_count}</b> (score {total_score}) in {duration_min:.0f} min",
        f"Total buy: {_fmt_money(total)}",
        f"Price: {_fmt_price(token_info.get('price_usd'))}"
        + (f" | MCap: {_fmt_money(token_info.get('mcap'))}" if token_info.get("mcap") else ""),
        f"Liquidity: {_fmt_money(token_info.get('liquidity_usd'))}"
        + (
            f" | Vol 1h: {_fmt_money(token_info.get('volume_h1'))}"
            if token_info.get("volume_h1")
            else ""
        ),
    ]

    buys_h1 = token_info.get("txn_h1_buys")
    sells_h1 = token_info.get("txn_h1_sells")
    if buys_h1 is not None and sells_h1 is not None:
        msg[-1] += f" ({buys_h1} buys / {sells_h1} sells)"

    if rugcheck:
        rc_score = rugcheck.get("score_normalised")
        lp = rugcheck.get("lp_locked_pct")
        line = f"Rugcheck: <b>{rc_score}/100</b>"
        if lp is not None:
            line += f" | LP locked: {lp:.0f}%"
        msg.append(line)

    if evaluation:
        msg.extend(["", format_reason_block(evaluation)])

    msg.extend(
        [
            "",
            f"<code>{mint}</code>",
            "",
            f"<a href='https://gmgn.ai/sol/token/{mint}'>GMGN</a>"
            f" | <a href='https://dexscreener.com/solana/{mint}'>DexScreener</a>"
            f" | <a href='https://birdeye.so/token/{mint}?chain=solana'>Birdeye</a>"
            f" | <a href='https://rugcheck.xyz/tokens/{mint}'>Rugcheck</a>"
            f" | <a href='https://photon-sol.tinyastro.io/en/lp/{mint}'>Photon</a>",
        ]
    )
    return "\n".join(line for line in msg if line != "")


def format_paper_trade_close(trade: dict[str, Any], token_info: dict[str, Any]) -> str:
    sym = html.escape(str(token_info.get("symbol") or "?"))
    pnl = float(trade.get("pnl_pct") or 0)
    label = "GAIN" if pnl > 0 else "LOSS"
    return (
        f"<b>Paper trade closed ({label}): {sym}</b>\n"
        f"Entry: {_fmt_price(trade['entry_price_usd'])}\n"
        f"Exit: {_fmt_price(trade['exit_price_usd'])}\n"
        f"Reason: {html.escape(str(trade['exit_reason']))}\n"
        f"PnL: <b>{pnl:+.1f}%</b> ({float(trade.get('pnl_usd', 0)):+.1f} USD)"
    )
