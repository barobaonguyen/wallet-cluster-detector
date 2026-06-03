"""Command line interface for wallet-cluster-detector."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from clusterdetect.alert.telegram import (
    TelegramAlerter,
    format_cluster_alert,
)
from clusterdetect.clients.enrichers import Enricher
from clusterdetect.clients.helius import HeliusClient
from clusterdetect.commentary.gemini import generate_commentary
from clusterdetect.config import Config, load_config, validate_runtime_config
from clusterdetect.db import conn, init_db
from clusterdetect.domain.cluster import Cluster, ClusterDetector, save_clusters
from clusterdetect.domain.paper_trade import PaperTrader
from clusterdetect.domain.reasoner import ClusterScorer
from clusterdetect.domain.swap_parser import get_sol_price_usd, parse_swap
from clusterdetect.schedule.cron import emit_cron, emit_launchd, emit_windows_task
from clusterdetect.watchlist.discovery import discover_winners

log = logging.getLogger(__name__)


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _cluster_from_row(row: dict[str, Any], scores: dict[str, int]) -> Cluster:
    wallets = json.loads(row.get("wallets_json") or "[]")
    return Cluster(
        token_mint=row["token_mint"],
        first_buy_ts=row["first_buy_ts"],
        last_buy_ts=row["last_buy_ts"],
        wallets=wallets,
        wallet_count=row["wallet_count"],
        total_usd=row.get("total_usd") or 0,
        wallet_scores=scores,
        total_wallet_score=sum(scores.values()),
    )


async def _fetch_wallet_history(
    helius: HeliusClient,
    wallet: str,
    since_ts: int,
    sol_price: float,
    *,
    max_pages: int = 20,
) -> int:
    inserted = 0
    before: str | None = None
    with conn() as c:
        last = c.execute(
            "SELECT MAX(timestamp) AS t FROM swaps WHERE wallet=?", (wallet,)
        ).fetchone()
        last_ts = last["t"] if last and last["t"] else 0
    effective_since = max(since_ts, last_ts)

    for _ in range(max_pages):
        txs = await helius.get_address_transactions(
            wallet, before=before, limit=100, tx_type="SWAP"
        )
        if not txs:
            break
        oldest_ts = None
        rows = []
        for tx in txs:
            ts = tx.get("timestamp")
            if ts is None:
                continue
            oldest_ts = min(oldest_ts, ts) if oldest_ts else ts
            if ts < effective_since:
                continue
            parsed = parse_swap(tx, wallet, sol_price)
            if parsed:
                rows.append(parsed)
        if rows:
            with conn() as c:
                for swap in rows:
                    cur = c.execute(
                        """INSERT OR IGNORE INTO swaps
                           (signature, wallet, timestamp, side, token_mint,
                            token_amount, sol_amount, usd_value, source, raw, chain)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            swap["signature"],
                            swap["wallet"],
                            swap["timestamp"],
                            swap["side"],
                            swap["token_mint"],
                            swap["token_amount"],
                            swap["sol_amount"],
                            swap["usd_value"],
                            swap["source"],
                            None,
                            "solana",
                        ),
                    )
                    inserted += cur.rowcount if cur.rowcount > 0 else 0
        if oldest_ts is None or oldest_ts < effective_since:
            break
        before = txs[-1].get("signature")
        if not before:
            break
    return inserted


async def _cmd_fetch(args: argparse.Namespace, cfg: Config) -> int:
    if not cfg.helius_api_keys:
        print("HELIUS_API_KEY is required for fetch")
        return 2
    init_db()
    cutoff = int(time.time()) - args.days * 86400
    with conn() as c:
        rows = c.execute(
            "SELECT address FROM wallets WHERE enabled=1 ORDER BY score DESC, added_at LIMIT ?",
            (args.limit or 1000,),
        ).fetchall()
    helius = HeliusClient(
        cfg.helius_api_keys,
        rps=cfg.helius_rps,
        retries=cfg.helius_retries,
        daily_budget=cfg.helius_daily_budget,
    )
    await helius.load_persisted_credits()
    try:
        sol_price = await get_sol_price_usd(helius.client)
        total = 0
        for idx, row in enumerate(rows, start=1):
            if helius.is_circuit_open() or helius.is_budget_exhausted():
                break
            n = await _fetch_wallet_history(helius, row["address"], cutoff, sol_price)
            total += n
            print(f"[{idx}/{len(rows)}] {row['address'][:8]}... +{n} swaps")
        print(f"Stored {total} swaps; Helius credits used today: {helius.credits_used}")
        return 0
    finally:
        await helius.close()


async def _poll_wallets_once(helius: HeliusClient, cfg: Config, sol_price: float) -> int:
    cutoff = int(time.time()) - cfg.dormant_wallet_days * 86400
    with conn() as c:
        rows = c.execute(
            """SELECT w.address,
                      COALESCE((SELECT MAX(timestamp) FROM swaps s WHERE s.wallet=w.address), 0) AS last_swap_ts,
                      (SELECT signature FROM swaps s WHERE s.wallet=w.address ORDER BY timestamp DESC LIMIT 1) AS last_sig
               FROM wallets w WHERE w.enabled=1 ORDER BY w.score DESC"""
        ).fetchall()
    active = [r for r in rows if r["last_swap_ts"] >= cutoff or r["last_swap_ts"] == 0]
    new_sigs: dict[str, list[str]] = {}
    for row in active:
        sigs = await helius.get_signatures_for_address(
            row["address"], limit=cfg.poll_sigs_per_wallet
        )
        last_seen = row["last_sig"]
        for sig_obj in sigs:
            sig = sig_obj.get("signature")
            if not sig or sig == last_seen:
                break
            if sig_obj.get("err"):
                continue
            new_sigs.setdefault(row["address"], []).append(sig)

    if not new_sigs:
        return 0
    sig_to_wallet = {sig: wallet for wallet, sigs in new_sigs.items() for sig in sigs}
    inserted = 0
    all_sigs = list(sig_to_wallet)
    for i in range(0, len(all_sigs), 100):
        parsed = await helius.parse_transactions(all_sigs[i : i + 100])
        rows_to_insert = []
        for tx in parsed:
            sig = tx.get("signature")
            if not isinstance(sig, str):
                continue
            wallet = sig_to_wallet.get(sig)
            if not wallet:
                continue
            swap = parse_swap(tx, wallet, sol_price)
            if swap:
                rows_to_insert.append(swap)
        if rows_to_insert:
            with conn() as c:
                for swap in rows_to_insert:
                    cur = c.execute(
                        """INSERT OR IGNORE INTO swaps
                           (signature, wallet, timestamp, side, token_mint, token_amount,
                            sol_amount, usd_value, source, raw, chain)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            swap["signature"],
                            swap["wallet"],
                            swap["timestamp"],
                            swap["side"],
                            swap["token_mint"],
                            swap["token_amount"],
                            swap["sol_amount"],
                            swap["usd_value"],
                            swap["source"],
                            None,
                            "solana",
                        ),
                    )
                    inserted += cur.rowcount if cur.rowcount > 0 else 0
    return inserted


async def _scan_once(cfg: Config, *, commentary: bool = False) -> tuple[int, int]:
    if not cfg.helius_api_keys:
        print("HELIUS_API_KEY is required for scan")
        return 0, 0
    init_db()
    helius = HeliusClient(
        cfg.helius_api_keys,
        rps=cfg.helius_rps,
        retries=cfg.helius_retries,
        daily_budget=cfg.helius_daily_budget,
    )
    enricher = Enricher()
    alerter = TelegramAlerter(cfg.telegram_bot_token, cfg.telegram_chat_id)
    scorer = ClusterScorer()
    try:
        await helius.load_persisted_credits()
        sol_price = await get_sol_price_usd(helius.client)
        new_swaps = await _poll_wallets_once(helius, cfg, sol_price)

        end_ts = int(time.time())
        start_ts = end_ts - max(30, cfg.cluster_window_minutes * 2) * 60
        with conn() as c:
            rows = [
                dict(r)
                for r in c.execute(
                    """SELECT * FROM swaps WHERE timestamp BETWEEN ? AND ? AND side='buy' AND chain='solana'
                   ORDER BY timestamp""",
                    (start_ts, end_ts),
                ).fetchall()
            ]
            wallet_scores = {
                r["address"]: r["score"] or 1
                for r in c.execute("SELECT address, score FROM wallets WHERE enabled=1").fetchall()
            }
        detector = ClusterDetector(
            min_wallets=cfg.cluster_min_wallets,
            window_minutes=cfg.cluster_window_minutes,
            min_total_score=cfg.cluster_min_total_score,
            min_usd=cfg.min_buy_usd,
        )
        clusters = detector.detect(rows, wallet_scores)
        save_clusters(list(clusters))

        alerted = 0
        with conn() as c:
            pending = [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM clusters WHERE notified=0 ORDER BY first_buy_ts DESC"
                ).fetchall()
            ]
        for row in pending:
            wallets = json.loads(row.get("wallets_json") or "[]")
            scores = {wallet: wallet_scores.get(wallet, 1) for wallet in wallets}
            cluster = _cluster_from_row(row, scores)
            token_info = await enricher.dexscreener_token(cluster.token_mint)
            if not token_info:
                with conn() as c:
                    c.execute("UPDATE clusters SET notified=1 WHERE id=?", (row["id"],))
                continue
            rug = await enricher.rugcheck(cluster.token_mint)
            wallet_details = [{"address": w, "score": scores.get(w, 1)} for w in wallets]
            evaluation = scorer.evaluate(cluster, token_info, rug, wallet_details)
            if evaluation.decision == "SKIP":
                with conn() as c:
                    c.execute("UPDATE clusters SET notified=1 WHERE id=?", (row["id"],))
                continue
            msg = format_cluster_alert(cluster, token_info, rug, evaluation)
            if commentary and evaluation.score >= cfg.gemini_min_cluster_score:
                text = generate_commentary(
                    {
                        "cluster": cluster.to_dict(),
                        "token": token_info,
                        "rugcheck": rug,
                        "evaluation": evaluation,
                    }
                )
                if text:
                    msg += f"\n\n<b>AI commentary</b>\n{text}"
            sent = (
                await alerter.send(msg)
                if cfg.telegram_bot_token and cfg.telegram_chat_id
                else False
            )
            print(
                msg
                if not sent
                else f"sent alert for {token_info.get('symbol') or cluster.token_mint[:8]}"
            )
            with conn() as c:
                c.execute("UPDATE clusters SET notified=1 WHERE id=?", (row["id"],))
            alerted += 1
            if token_info.get("price_usd") and evaluation.decision in {"STRONG", "OK"}:
                size_mult = 1.0 if evaluation.decision == "STRONG" else 0.5
                trade = PaperTrader().open(
                    cluster, token_info["price_usd"], ts=int(time.time()), size_mult=size_mult
                )
                with conn() as c:
                    c.execute(
                        """INSERT INTO paper_trades(token_mint, entry_ts, entry_price_usd,
                           position_usd, status, peak_price_usd, notes)
                           VALUES(?,?,?,?,?,?,?)""",
                        (
                            trade.token_mint,
                            trade.entry_ts,
                            trade.entry_price_usd,
                            trade.position_usd,
                            trade.status,
                            trade.peak_price_usd,
                            evaluation.one_liner,
                        ),
                    )
        return new_swaps, alerted
    finally:
        await helius.close()
        await enricher.close()


async def _cmd_scan(args: argparse.Namespace, cfg: Config) -> int:
    while True:
        new_swaps, alerted = await _scan_once(cfg, commentary=args.commentary)
        print(f"cycle: +{new_swaps} swaps, {alerted} alerts")
        if not args.watch:
            return 0
        await asyncio.sleep(max(1, cfg.poll_interval_seconds))


async def _cmd_discover(args: argparse.Namespace, cfg: Config) -> int:
    async with httpx.AsyncClient(timeout=20) as http:
        if args.dry:
            winners = await discover_winners(http, max_winners=args.n, dry_run=True)
        else:
            if not cfg.helius_api_keys:
                print("HELIUS_API_KEY is required unless --dry is used")
                return 2
            helius = HeliusClient(
                cfg.helius_api_keys, rps=cfg.helius_rps, daily_budget=cfg.helius_daily_budget
            )
            try:
                winners = await discover_winners(
                    http, helius=helius, max_winners=args.n, dry_run=False
                )
            finally:
                await helius.close()
    for item in winners[: args.n]:
        if isinstance(item, tuple):
            print(f"{item[0]} score={item[1]}")
        else:
            print(
                f"{item.get('name') or '?':16s} h1={item.get('h1', 0):+7.0f}% "
                f"h6={item.get('h6', 0):+7.0f}% h24={item.get('h24', 0):+7.0f}% "
                f"fdv={item.get('fdv', 0):.0f} liq={item.get('liq', 0):.0f} pool={item.get('pool')}"
            )
    return 0


def _cmd_status() -> int:
    init_db()
    now = int(time.time())
    with conn() as c:
        active = c.execute("SELECT COUNT(*) AS n FROM wallets WHERE enabled=1").fetchone()["n"]
        swaps = c.execute("SELECT COUNT(*) AS n FROM swaps").fetchone()["n"]
        clusters = c.execute("SELECT COUNT(*) AS n FROM clusters").fetchone()["n"]
        open_trades = c.execute(
            "SELECT COUNT(*) AS n FROM paper_trades WHERE status='open'"
        ).fetchone()["n"]
        closed = c.execute(
            "SELECT COUNT(*) AS n FROM paper_trades WHERE status='closed'"
        ).fetchone()["n"]
        latest = c.execute("SELECT MAX(timestamp) AS t FROM swaps").fetchone()["t"]
        pnl = c.execute(
            "SELECT SUM(pnl_usd) AS pnl FROM paper_trades WHERE status='closed'"
        ).fetchone()["pnl"]
    print("wallet-cluster-detector status")
    print(f"active wallets: {active}")
    print(f"swaps: {swaps}")
    print(f"clusters: {clusters}")
    print(f"paper trades: {open_trades} open / {closed} closed")
    print(f"closed PnL: {pnl or 0:+.2f} USD")
    if latest:
        age = now - int(latest)
        print(f"latest swap age: {age // 60} min")
    return 0


def _collect_pnl(days: int) -> dict[str, Any]:
    end = int(time.time())
    start = end - days * 86400
    with conn() as c:
        rows = [
            dict(r)
            for r in c.execute(
                """SELECT pt.*, t.symbol FROM paper_trades pt
               LEFT JOIN tokens t ON pt.token_mint=t.mint
               WHERE pt.status='closed' AND pt.exit_ts >= ?
               ORDER BY pt.exit_ts""",
                (start,),
            ).fetchall()
        ]
    by_day: dict[str, list[dict[str, Any]]] = {}
    for trade in rows:
        date = datetime.fromtimestamp(trade["exit_ts"], tz=UTC).strftime("%Y-%m-%d")
        by_day.setdefault(date, []).append(trade)
    daily = []
    for date, trades in sorted(by_day.items()):
        pnl = sum(t.get("pnl_usd") or 0 for t in trades)
        wins = sum(1 for t in trades if (t.get("pnl_usd") or 0) > 0)
        daily.append({"date": date, "trades": len(trades), "wins": wins, "pnl_usd": round(pnl, 2)})
    return {
        "days": days,
        "daily": daily,
        "totals": {
            "trades": len(rows),
            "pnl_usd": round(sum(t.get("pnl_usd") or 0 for t in rows), 2),
        },
    }


def _cmd_pnl(args: argparse.Namespace) -> int:
    init_db()
    report = _collect_pnl(args.days)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"PnL last {args.days}d: {report['totals']['pnl_usd']:+.2f} USD over {report['totals']['trades']} trades"
        )
        for row in report["daily"]:
            print(
                f"{row['date']} trades={row['trades']} wins={row['wins']} pnl={row['pnl_usd']:+.2f}"
            )
    return 0


async def _cmd_backtest(args: argparse.Namespace, cfg: Config) -> int:
    init_db()
    end_ts = int(time.time())
    start_ts = end_ts - args.days * 86400
    with conn() as c:
        swaps = [
            dict(r)
            for r in c.execute(
                "SELECT * FROM swaps WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp",
                (start_ts, end_ts),
            ).fetchall()
        ]
        scores = {
            r["address"]: r["score"] or 1
            for r in c.execute("SELECT address, score FROM wallets").fetchall()
        }
    detector = ClusterDetector(
        min_wallets=cfg.cluster_min_wallets,
        window_minutes=cfg.cluster_window_minutes,
        min_total_score=cfg.cluster_min_total_score,
        min_usd=cfg.min_buy_usd,
    )
    clusters = detector.detect(swaps, scores)
    print(f"Clusters detected: {len(clusters)}")
    print(
        "Backtest caveat: sparse free OHLC can make data_end exits dominate; live paper trade first."
    )
    if args.no_reasoner:
        return 0
    scorer = ClusterScorer()
    for cluster in clusters[:10]:
        ev = scorer.evaluate(
            cluster, {}, None, [{"address": w, "score": scores.get(w, 1)} for w in cluster.wallets]
        )
        print(f"{cluster.token_mint[:8]} {ev.decision} score={ev.score}")
    return 0


async def _cmd_get_chat_id(cfg: Config) -> int:
    alerter = TelegramAlerter(cfg.telegram_bot_token, cfg.telegram_chat_id)
    if not cfg.telegram_bot_token:
        print("Set TELEGRAM_BOT_TOKEN, then send a message to @your_bot and rerun this command.")
        return 2
    updates = await alerter.get_updates()
    for upd in updates:
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id"):
            print(
                f"{chat.get('type', 'chat')}: {chat['id']} {chat.get('title') or chat.get('username') or ''}"
            )
    return 0


async def _cmd_doctor(cfg: Config) -> int:
    errors = validate_runtime_config(cfg)
    print("doctor")
    print(f"Helius keys present: {len(cfg.helius_api_keys)}")
    print(f"Telegram configured: {bool(cfg.telegram_bot_token and cfg.telegram_chat_id)}")
    print(f"Gemini configured: {bool(cfg.gemini_api_keys)} enabled={cfg.gemini_enabled}")
    print(
        "cluster defaults: "
        f"{cfg.cluster_min_wallets} wallets / {cfg.cluster_min_total_score} score / "
        f"{cfg.cluster_window_minutes} min"
    )
    if errors:
        print("config notices:")
        for error in errors:
            print(f"- {error}")
    async with httpx.AsyncClient(timeout=8) as http:
        checks = {
            "DexScreener": "https://api.dexscreener.com/token-boosts/latest/v1",
            "GeckoTerminal": "https://api.geckoterminal.com/api/v2/networks/solana/trending_pools",
            "Rugcheck": "https://api.rugcheck.xyz/v1/tokens/So11111111111111111111111111111111111111112/report/summary",
        }
        for name, url in checks.items():
            try:
                r = await http.get(url)
                print(f"{name}: HTTP {r.status_code}")
            except Exception as exc:
                print(f"{name}: unreachable ({exc.__class__.__name__})")
    return 0


def _cmd_schedule(args: argparse.Namespace) -> int:
    command = "clusterdetect scan --watch"
    if args.os == "win":
        print(emit_windows_task("wallet-cluster-detector", command, at=args.at))
    elif args.os == "mac":
        print(emit_launchd("wallet-cluster-detector", command, at=args.at))
    else:
        print(emit_cron(command, at=args.at))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clusterdetect")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--env", default=".env")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db")
    p = sub.add_parser("discover")
    p.add_argument("n", nargs="?", type=int, default=25)
    p.add_argument("--dry", action="store_true")

    p = sub.add_parser("fetch")
    p.add_argument("days", nargs="?", type=int, default=30)
    p.add_argument("--limit", type=int)

    p = sub.add_parser("scan")
    p.add_argument("--watch", action="store_true")
    p.add_argument("--commentary", action="store_true")

    p = sub.add_parser("backtest")
    p.add_argument("days", nargs="?", type=int, default=30)
    p.add_argument("--no-reasoner", action="store_true")

    sub.add_parser("status")
    p = sub.add_parser("pnl")
    p.add_argument("days", nargs="?", type=int, default=7)
    p.add_argument("--json", action="store_true")

    sub.add_parser("get-chat-id")
    sub.add_parser("doctor")
    p = sub.add_parser("schedule")
    p.add_argument("--at", default="09:00")
    p.add_argument("--os", choices=["win", "linux", "mac"], default="linux")
    return parser


async def _async_main(argv: list[str] | None = None) -> int:
    _setup_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)
    cfg = load_config(args.config, args.env)

    if args.cmd == "init-db":
        init_db()
        print("SQLite schema initialized")
        return 0
    if args.cmd == "discover":
        return await _cmd_discover(args, cfg)
    if args.cmd == "fetch":
        return await _cmd_fetch(args, cfg)
    if args.cmd == "scan":
        return await _cmd_scan(args, cfg)
    if args.cmd == "backtest":
        return await _cmd_backtest(args, cfg)
    if args.cmd == "get-chat-id":
        return await _cmd_get_chat_id(cfg)
    if args.cmd == "doctor":
        return await _cmd_doctor(cfg)
    if args.cmd == "status":
        return _cmd_status()
    if args.cmd == "pnl":
        return _cmd_pnl(args)
    if args.cmd == "schedule":
        return _cmd_schedule(args)
    parser.print_help()
    return 2


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_async_main(argv))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
