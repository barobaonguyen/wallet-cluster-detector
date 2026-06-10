"""Configuration helpers for the public wallet-cluster-detector package."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

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

# Standard public token constants on Base (8453). These are well-known canonical
# addresses, not wallets: wrapped native plus the major stablecoins. They let the
# EVM adapter mark stable-leg swaps the same way WSOL/USDC/USDT do on Solana.
WETH_BASE = "0x4200000000000000000000000000000000000006"
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
USDBC_BASE = "0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA"
USDT_BASE = "0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2"
STABLES_BASE = {
    WETH_BASE.lower(),
    USDC_BASE.lower(),
    USDBC_BASE.lower(),
    USDT_BASE.lower(),
}

STABLES_BY_CHAIN = {"solana": STABLES, "base": STABLES_BASE}

# Free, keyless public RPC endpoints per EVM chain. Override with EVM_RPC_URL
# (BYO endpoint) for higher rate limits.
EVM_RPC_DEFAULTS = {"base": "https://mainnet.base.org"}
EVM_CHAIN_IDS = {"base": 8453}

DEFAULT_DB_PATH = Path(os.getenv("CLUSTERDETECT_DB_PATH", "data/clusterdetect.db"))


@dataclass
class Config:
    helius_api_keys: list[str] = field(default_factory=list)
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    discord_webhook_url: str | None = None
    alert_channel: str = "telegram"
    gemini_api_keys: list[str] | None = None
    db_path: Path = DEFAULT_DB_PATH
    evm_rpc_url: str | None = None
    webhook_secret: str | None = None

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
    pumpfun_graduation: bool = False
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
    filters_obj = data.get("filters")
    alert_obj = data.get("alert")
    filters = cast(dict[str, Any], filters_obj) if isinstance(filters_obj, dict) else {}
    alert = cast(dict[str, Any], alert_obj) if isinstance(alert_obj, dict) else {}

    def pick(name: str, default: Any = None) -> Any:
        return os.getenv(name, data.get(name.lower(), data.get(name, default)))

    def pick_nested(env_name: str, section: dict[str, Any], key: str, default: Any = None) -> Any:
        env_value = os.getenv(env_name)
        if env_value is not None:
            return env_value
        if key in section:
            return section[key]
        return data.get(key, data.get(env_name.lower(), default))

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
        discord_webhook_url=_clean(
            os.getenv("DISCORD_WEBHOOK_URL")
            or data.get("discord_webhook_url")
            or alert.get("discord_webhook_url")
            or alert.get("webhook_url")
        )
        or None,
        alert_channel=_clean(pick_nested("ALERT_CHANNEL", alert, "channel", "telegram")).lower()
        or "telegram",
        gemini_api_keys=gemini_keys,
        db_path=Path(_clean(pick("DB_PATH", DEFAULT_DB_PATH)) or DEFAULT_DB_PATH),
        evm_rpc_url=_clean(pick("EVM_RPC_URL")) or None,
        webhook_secret=_clean(pick("WEBHOOK_SECRET")) or None,
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
        pumpfun_graduation=_as_bool(
            pick_nested("PUMPFUN_GRADUATION", filters, "pumpfun_graduation", False),
            False,
        ),
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
    if cfg.alert_channel not in {"telegram", "discord", "both"}:
        errors.append("ALERT_CHANNEL must be telegram, discord, or both")
    if cfg.alert_channel in {"discord", "both"} and not cfg.discord_webhook_url:
        errors.append("Discord alert channel selected but DISCORD_WEBHOOK_URL is missing")
    if cfg.gemini_max_calls_per_day < 0:
        errors.append("GEMINI_MAX_CALLS_PER_DAY must be >= 0")
    if cfg.gemini_enabled and not cfg.gemini_api_keys:
        errors.append("GEMINI_ENABLED=true but no GEMINI_API_KEY is configured")
    return errors
