"""Offline analytics over data the detector already stored.

Every module here is a pure transform: it reads rows the pipeline has already
written locally, collects nothing new, and touches neither the network nor any
external service.
"""

from __future__ import annotations

from clusterdetect.analytics.calibrate import (
    CalibrationRow,
    best_rows,
    render_rows_markdown,
    render_rows_text,
    rows_to_dicts,
    sweep,
)
from clusterdetect.analytics.performance import (
    ExitReasonStat,
    PerformanceSummary,
    render_summary_markdown,
    render_summary_text,
    summarize_trades,
    summary_to_dict,
)

__all__ = [
    "CalibrationRow",
    "ExitReasonStat",
    "PerformanceSummary",
    "best_rows",
    "render_rows_markdown",
    "render_rows_text",
    "render_summary_markdown",
    "render_summary_text",
    "rows_to_dicts",
    "summarize_trades",
    "summary_to_dict",
    "sweep",
]
