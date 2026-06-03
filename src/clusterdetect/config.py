"""Configuration helpers for the public wallet-cluster-detector package."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

DEXSCREENER_BASE = "https://api.dexscreener.com"
GECKO_BASE = "https://api.geckoterminal.com/api/v2"
RUGCHECK_BASE = "https://api.rugcheck.xyz/v1"
PUMPFUN_API = "https://frontend-api-v3.pump.fun"

WSOL = "So11111111111111111111111111111111111111112"
USDC_SOL = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_SOL = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
USDC = USDC_SOL
USDT = USDT_SOL
STABLES = {WSOL, USDC_SOL, USDT_SOL}
STABLES_BY_CHAIN = {"solana": STABLES}

DEFAULT_DB_PATH = Path(os.getenv("CLUSTERDETECT_DB_PATH", "data/clusterdetect.db"))


@dataclass
class Config:
    helius_api_keys: list[str] = field(default_factory=list)
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    gemini_api_keys: list[str] | None = None
    db_path: Path = DEFAULT_DB_PATH

    cluster_min_wallets: int = 3
    cluster_window_minutes: int = 15
    cluster_min_total_score: int = 6
    min_buy_usd: float = 0.0
    poll_interval_seconds: int = 60
    poll_sigs_per_wallet: int = 5
    dormant_wallet_days: int = 7
    helius_rps: float = 6.0
    helius_retries: int = 5
    helius_daily_budget: int = 95_000
    alert_cooldown_minutes: int = 60
    gemini_enabled: bool = False
    gemini_max_calls_per_day: int = 0
    gemini_min_cluster_score: int = 8


def _clean(v: Any) -> str:
    return str(v or "").strip()


def _as_bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


def _as_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _as_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _yaml_config(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _env_keys(prefix: str, max_n: int = 10) -> list[str]:
    keys = []
    first = _clean(os.getenv(prefix))
    if first:
        keys.append(first)
    for idx in range(2, max_n + 1):
        key = _clean(os.getenv(f"{prefix}_{idx}"))
        if key:
            keys.append(key)
    return keys


def load_config(path: str = "config.yaml", env_path: str = ".env") -> Config:
    """Load config from YAML plus environment, with environment taking precedence."""

    load_dotenv(env_path, override=False)
    data = _yaml_config(path)

    def pick(name: str, default: Any = None) -> Any:
        return os.getenv(name, data.get(name.lower(), data.get(name, default)))

    yaml_helius = data.get("helius_api_keys") or []
    helius_keys = _env_keys("HELIUS_API_KEY") or [_clean(k) for k in yaml_helius if _clean(k)]
    yaml_gemini = data.get("gemini_api_keys") or []
    gemini_keys = _env_keys("GEMINI_API_KEY") or [_clean(k) for k in yaml_gemini if _clean(k)]

    return Config(
        helius_api_keys=helius_keys,
        telegram_bot_token=_clean(pick("TELEGRAM_BOT_TOKEN")) or None,
        telegram_chat_id=_clean(
            os.getenv("TELEGRAM_CHAT_ID")
            or os.getenv("TELEGRAM_CHANNEL_ID")
            or data.get("telegram_chat_id")
        )
        or None,
        gemini_api_keys=gemini_keys,
        db_path=Path(_clean(pick("DB_PATH", DEFAULT_DB_PATH)) or DEFAULT_DB_PATH),
        cluster_min_wallets=_as_int(pick("CLUSTER_MIN_WALLETS"), 3),
        cluster_window_minutes=_as_int(pick("CLUSTER_WINDOW_MINUTES"), 15),
        cluster_min_total_score=_as_int(pick("CLUSTER_MIN_TOTAL_SCORE"), 6),
        min_buy_usd=_as_float(pick("MIN_BUY_USD"), 0.0),
        poll_interval_seconds=_as_int(pick("POLL_INTERVAL_SECONDS"), 60),
        poll_sigs_per_wallet=_as_int(pick("POLL_SIGS_PER_WALLET"), 5),
        dormant_wallet_days=_as_int(pick("DORMANT_WALLET_DAYS"), 7),
        helius_rps=_as_float(pick("HELIUS_RPS"), 6.0),
        helius_retries=_as_int(pick("HELIUS_RETRIES"), 5),
        helius_daily_budget=_as_int(pick("HELIUS_DAILY_BUDGET"), 95_000),
        alert_cooldown_minutes=_as_int(pick("ALERT_COOLDOWN_MINUTES"), 60),
        gemini_enabled=_as_bool(pick("GEMINI_ENABLED"), False),
        gemini_max_calls_per_day=_as_int(pick("GEMINI_MAX_CALLS_PER_DAY"), 0),
        gemini_min_cluster_score=_as_int(pick("GEMINI_MIN_CLUSTER_SCORE"), 8),
    )


def validate_runtime_config(cfg: Config) -> list[str]:
    """Return missing or nonsensical runtime settings. Secrets are never included."""

    errors = []
    if not cfg.helius_api_keys:
        errors.append("HELIUS_API_KEY is missing; required for Helius polling and history fetches")
    if cfg.cluster_min_wallets < 1:
        errors.append("CLUSTER_MIN_WALLETS must be >= 1")
    if cfg.cluster_window_minutes < 1:
        errors.append("CLUSTER_WINDOW_MINUTES must be >= 1")
    if cfg.cluster_min_total_score < 1:
        errors.append("CLUSTER_MIN_TOTAL_SCORE must be >= 1")
    if cfg.helius_rps <= 0:
        errors.append("HELIUS_RPS must be > 0")
    if cfg.helius_retries < 1:
        errors.append("HELIUS_RETRIES must be >= 1")
    if cfg.helius_daily_budget < 1:
        errors.append("HELIUS_DAILY_BUDGET must be >= 1")
    if cfg.gemini_max_calls_per_day < 0:
        errors.append("GEMINI_MAX_CALLS_PER_DAY must be >= 0")
    if cfg.gemini_enabled and not cfg.gemini_api_keys:
        errors.append("GEMINI_ENABLED=true but no GEMINI_API_KEY is configured")
    return errors
