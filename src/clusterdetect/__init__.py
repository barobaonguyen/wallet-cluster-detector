"""Public API for wallet-cluster-detector."""

__version__ = "0.5.0"

from clusterdetect.alert.discord import DiscordAlerter
from clusterdetect.alert.telegram import TelegramAlerter
from clusterdetect.analytics.calibrate import CalibrationRow, best_rows, sweep
from clusterdetect.analytics.performance import PerformanceSummary, summarize_trades
from clusterdetect.clients.enrichers import Enricher
from clusterdetect.clients.evm import EvmClient, parse_evm_logs
from clusterdetect.clients.helius import HeliusClient
from clusterdetect.clients.rate_limiter import QuotaTracker, RateLimiter
from clusterdetect.domain.cluster import Cluster, ClusterDetector
from clusterdetect.domain.paper_trade import PaperTrade, PaperTrader
from clusterdetect.domain.reasoner import ClusterScorer, Evaluation
from clusterdetect.domain.swap_parser import get_sol_price_usd, parse_swap
from clusterdetect.graph import ClusterGraph, build_cluster_graph, render_graph
from clusterdetect.report import render_clusters_html
from clusterdetect.schedule.webhook import ingest_payload, sign_payload, verify_signature
from clusterdetect.watchlist.loader import from_csv, to_csv

__all__ = [
    "__version__",
    "CalibrationRow",
    "Cluster",
    "ClusterDetector",
    "ClusterGraph",
    "ClusterScorer",
    "DiscordAlerter",
    "Enricher",
    "Evaluation",
    "EvmClient",
    "HeliusClient",
    "PaperTrade",
    "PaperTrader",
    "PerformanceSummary",
    "QuotaTracker",
    "RateLimiter",
    "TelegramAlerter",
    "best_rows",
    "build_cluster_graph",
    "from_csv",
    "get_sol_price_usd",
    "ingest_payload",
    "parse_evm_logs",
    "parse_swap",
    "render_clusters_html",
    "render_graph",
    "sign_payload",
    "summarize_trades",
    "sweep",
    "to_csv",
    "verify_signature",
]
