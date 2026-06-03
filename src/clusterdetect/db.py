"""SQLite schema and connection helpers."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from clusterdetect.config import DEFAULT_DB_PATH

DB_PATH = DEFAULT_DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS wallets (
    address TEXT PRIMARY KEY,
    source TEXT,
    pnl_30d_usd REAL,
    winrate REAL,
    label TEXT,
    score INTEGER DEFAULT 1,
    added_at INTEGER,
    last_active_at INTEGER,
    enabled INTEGER DEFAULT 1,
    chain TEXT DEFAULT 'solana'
);

CREATE TABLE IF NOT EXISTS swaps (
    signature TEXT PRIMARY KEY,
    wallet TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    side TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    token_amount REAL,
    sol_amount REAL,
    usd_value REAL,
    source TEXT,
    raw JSON,
    chain TEXT DEFAULT 'solana'
);
CREATE INDEX IF NOT EXISTS idx_swaps_wallet ON swaps(wallet);
CREATE INDEX IF NOT EXISTS idx_swaps_token ON swaps(token_mint);
CREATE INDEX IF NOT EXISTS idx_swaps_ts ON swaps(timestamp);

CREATE TABLE IF NOT EXISTS tokens (
    mint TEXT PRIMARY KEY,
    symbol TEXT,
    name TEXT,
    pool_address TEXT,
    pair_chain TEXT,
    pair_dex TEXT,
    created_at INTEGER,
    rugcheck_score INTEGER,
    rugcheck_normalised INTEGER,
    lp_locked_pct REAL,
    top10_pct REAL,
    last_enriched_at INTEGER,
    raw JSON,
    chain TEXT DEFAULT 'solana'
);

CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_mint TEXT NOT NULL,
    first_buy_ts INTEGER NOT NULL,
    last_buy_ts INTEGER NOT NULL,
    wallet_count INTEGER NOT NULL,
    wallets_json TEXT,
    total_usd REAL,
    detected_at INTEGER NOT NULL,
    notified INTEGER DEFAULT 0,
    chain TEXT DEFAULT 'solana'
);
CREATE INDEX IF NOT EXISTS idx_clusters_token ON clusters(token_mint);
CREATE INDEX IF NOT EXISTS idx_clusters_ts ON clusters(first_buy_ts);

CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_id INTEGER,
    token_mint TEXT NOT NULL,
    entry_ts INTEGER NOT NULL,
    entry_price_usd REAL NOT NULL,
    position_usd REAL NOT NULL,
    status TEXT DEFAULT 'open',
    exit_ts INTEGER,
    exit_price_usd REAL,
    exit_reason TEXT,
    pnl_pct REAL,
    pnl_usd REAL,
    peak_price_usd REAL,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_paper_status ON paper_trades(status);
CREATE INDEX IF NOT EXISTS idx_paper_token ON paper_trades(token_mint);
CREATE INDEX IF NOT EXISTS idx_paper_entry_ts ON paper_trades(entry_ts);

CREATE TABLE IF NOT EXISTS alert_cooldowns (
    token_mint TEXT PRIMARY KEY,
    last_alert_ts INTEGER NOT NULL,
    last_decision TEXT,
    last_score INTEGER,
    alert_count INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_mint TEXT NOT NULL,
    ts INTEGER NOT NULL,
    price_usd REAL,
    volume_h1 REAL,
    liquidity_usd REAL,
    mcap_usd REAL,
    source TEXT
);
CREATE INDEX IF NOT EXISTS idx_price_token_ts ON price_snapshots(token_mint, ts);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def _db_path(path: str | Path | None = None) -> str:
    p = Path(path or DB_PATH)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


@contextmanager
def conn(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(_db_path(path))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _migrate_chain_column(c: sqlite3.Connection) -> None:
    for table in ("swaps", "wallets", "tokens", "clusters"):
        try:
            cols = [r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
        except sqlite3.OperationalError:
            continue
        if cols and "chain" not in cols:
            c.execute(f"ALTER TABLE {table} ADD COLUMN chain TEXT DEFAULT 'solana'")
            c.execute(f"UPDATE {table} SET chain='solana' WHERE chain IS NULL")
    c.execute("CREATE INDEX IF NOT EXISTS idx_swaps_chain ON swaps(chain)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_clusters_chain ON clusters(chain)")


def init_db(path: str | Path | None = None) -> None:
    with conn(path) as c:
        c.executescript(SCHEMA)
        _migrate_chain_column(c)


def upsert_wallet(
    c: sqlite3.Connection,
    address: str,
    source: str,
    pnl_30d_usd: float | None = None,
    winrate: float | None = None,
    label: str | None = None,
    score: int | None = None,
    added_at: int | None = None,
    enabled: int = 1,
    chain: str = "solana",
) -> None:
    c.execute(
        """INSERT INTO wallets(address, source, pnl_30d_usd, winrate, label, score, added_at, enabled, chain)
           VALUES(?,?,?,?,?,?,?,?,?)
           ON CONFLICT(address) DO UPDATE SET
             source=COALESCE(excluded.source, source),
             pnl_30d_usd=COALESCE(excluded.pnl_30d_usd, pnl_30d_usd),
             winrate=COALESCE(excluded.winrate, winrate),
             label=COALESCE(excluded.label, label),
             score=COALESCE(excluded.score, score),
             enabled=excluded.enabled,
             chain=COALESCE(excluded.chain, chain)""",
        (address, source, pnl_30d_usd, winrate, label, score, added_at, enabled, chain),
    )


def get_meta(c: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(c: sqlite3.Connection, key: str, value: object) -> None:
    c.execute(
        "INSERT INTO meta(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
