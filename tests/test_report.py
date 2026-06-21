"""Tests for the offline HTML cluster report (v0.4)."""

from __future__ import annotations

from clusterdetect.report import render_clusters_html

ROWS = [
    {
        "token": "TokenAAA",
        "wallet_count": 5,
        "score": 18,
        "tier": "S",
        "timestamp": "2026-06-21T00:00:00+00:00",
        "total_usd": 12345.6,
    },
    {"token": "TokenBBB", "wallet_count": 3, "score": 7, "tier": "B", "total_usd": None},
]


def test_render_is_self_contained_html() -> None:
    out = render_clusters_html(ROWS)
    assert out.startswith("<!doctype html>")
    assert "<script" not in out.lower()
    assert "http://" not in out
    assert "TokenAAA" in out and "TokenBBB" in out


def test_render_handles_none_total_usd() -> None:
    out = render_clusters_html(ROWS)
    assert "$0" in out  # None coerced to 0
    assert "$12,346" in out or "$12,345" in out


def test_render_escapes_token() -> None:
    out = render_clusters_html([{"token": "<b>x</b>", "wallet_count": 1, "tier": "C"}])
    assert "<b>x</b>" not in out
    assert "&lt;b&gt;" in out


def test_render_empty_rows() -> None:
    out = render_clusters_html([])
    assert "No clusters." in out
