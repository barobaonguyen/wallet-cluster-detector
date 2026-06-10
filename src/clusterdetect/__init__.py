"""Public API for wallet-cluster-detector."""

__version__ = "0.3.0"

from clusterdetect.alert.discord import DiscordAlerter
from clusterdetect.alert.telegram import TelegramAlerter
from clusterdetect.clients.enrichers import Enricher
from clusterdetect.clients.evm import EvmClient, parse_evm_logs
from clusterdetect.clients.helius import HeliusClient
from clusterdetect.clients.rate_limiter import QuotaTracker, RateLimiter
from clusterdetect.domain.cluster import Cluster, ClusterDetector
from clusterdetect.domain.paper_trade import PaperTrade, PaperTrader
from clusterdetect.domain.reasoner import ClusterScorer, Evaluation
from clusterdetect.domain.swap_parser import get_sol_price_usd, parse_swap
from clusterdetect.schedule.webhook import ingest_payload, sign_payload, verify_signature
from clusterdetect.watchlist.loader import from_csv, to_csv

__all__ = [
    "__version__",
    "Cluster",
    "ClusterDetector",
    "ClusterScorer",
    "DiscordAlerter",
    "Enricher",
    "Evaluation",
    "EvmClient",
    "HeliusClient",
    "PaperTrade",
    "PaperTrader",
    "QuotaTracker",
    "RateLimiter",
    "TelegramAlerter",
    "from_csv",
    "get_sol_price_usd",
    "ingest_payload",
    "parse_evm_logs",
    "parse_swap",
    "sign_payload",
    "to_csv",
    "verify_signature",
]
