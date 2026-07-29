from __future__ import annotations

import json
from typing import Any

from clusterdetect.analytics.calibrate import (
    CalibrationRow,
    best_rows,
    render_rows_markdown,
    render_rows_text,
    rows_to_dicts,
    sweep,
)


def _make_fixture() -> tuple[list[dict[str, Any]], dict[str, int]]:
    swaps: list[dict[str, Any]] = [
        {
            "signature": f"sig{i}",
            "wallet": wallet,
            "timestamp": ts,
            "side": "buy",
            "token_mint": "tok1",
            "token_amount": 1.0,
            "sol_amount": 0.1,
            "usd_value": 10.0,
            "source": "test",
            "chain": "solana",
        }
        for i, (wallet, ts) in enumerate(
            zip(["w1", "w2", "w3", "w4"], [0, 60, 120, 180], strict=True)
        )
    ]
    wallet_scores = {"w1": 2, "w2": 2, "w3": 2, "w4": 1}
    return swaps, wallet_scores


def test_loose_finds_cluster_and_strict_finds_none() -> None:
    swaps, wallet_scores = _make_fixture()
    loose = sweep(
        swaps,
        wallet_scores,
        min_wallets=(2,),
        window_minutes=(5,),
        min_total_score=(4,),
    )
    assert loose == [
        CalibrationRow(
            min_wallets=2,
            window_minutes=5,
            min_total_score=4,
            clusters=1,
            tokens=1,
            total_usd=40.0,
            median_wallet_count=4.0,
            max_wallet_count=4,
        )
    ]

    strict = sweep(
        swaps,
        wallet_scores,
        min_wallets=(4,),
        window_minutes=(5,),
        min_total_score=(8,),
    )
    assert strict == [
        CalibrationRow(
            min_wallets=4,
            window_minutes=5,
            min_total_score=8,
            clusters=0,
            tokens=0,
            total_usd=0.0,
            median_wallet_count=0.0,
            max_wallet_count=0,
        )
    ]


def test_empty_swaps_yields_zero_cluster_rows() -> None:
    rows = sweep(
        [],
        {},
        min_wallets=(2, 3),
        window_minutes=(5,),
        min_total_score=(4,),
    )
    assert len(rows) == 2
    for row in rows:
        assert row.clusters == 0
        assert row.tokens == 0
        assert row.total_usd == 0.0
        assert row.median_wallet_count == 0.0
        assert row.max_wallet_count == 0


def test_empty_knob_sequence_returns_empty_list() -> None:
    swaps, wallet_scores = _make_fixture()
    assert sweep(swaps, wallet_scores, min_wallets=()) == []


def test_sweep_rows_are_sorted_deterministically() -> None:
    swaps, wallet_scores = _make_fixture()
    rows = sweep(swaps, wallet_scores)
    keys = [(r.min_wallets, r.window_minutes, r.min_total_score) for r in rows]
    assert len(rows) == 27
    assert keys == sorted(keys)
    assert rows[0].min_wallets == 2
    assert rows[0].window_minutes == 5
    assert rows[0].min_total_score == 4
    assert rows[-1].min_wallets == 4
    assert rows[-1].window_minutes == 30
    assert rows[-1].min_total_score == 9


def test_knob_sequence_is_deduplicated() -> None:
    swaps, wallet_scores = _make_fixture()
    rows = sweep(
        swaps,
        wallet_scores,
        min_wallets=(3, 3, 2),
        window_minutes=(5,),
        min_total_score=(4,),
    )
    keys = [(r.min_wallets, r.window_minutes, r.min_total_score) for r in rows]
    assert keys == [(2, 5, 4), (3, 5, 4)]


def test_rows_to_dicts_are_json_serialisable() -> None:
    swaps, wallet_scores = _make_fixture()
    rows = sweep(swaps, wallet_scores)
    dicts = rows_to_dicts(rows)
    json.dumps(dicts)
    assert isinstance(dicts, list)
    assert dicts[0]["min_wallets"] == 2


def test_best_rows_ranks_by_selectivity() -> None:
    swaps, wallet_scores = _make_fixture()
    rows = sweep(swaps, wallet_scores)
    best = best_rows(rows, limit=3)
    assert len(best) == 3
    assert best[0] == CalibrationRow(
        min_wallets=4,
        window_minutes=5,
        min_total_score=6,
        clusters=1,
        tokens=1,
        total_usd=40.0,
        median_wallet_count=4.0,
        max_wallet_count=4,
    )
    assert best[1].min_wallets == 4
    assert best[1].min_total_score == 6
    assert best[1].window_minutes == 15
    assert best[2].min_wallets == 4
    assert best[2].min_total_score == 6
    assert best[2].window_minutes == 30


def test_best_rows_non_positive_limit_returns_empty() -> None:
    swaps, wallet_scores = _make_fixture()
    rows = sweep(swaps, wallet_scores)
    assert best_rows(rows, limit=0) == []
    assert best_rows(rows, limit=-3) == []


def test_renderers_handle_empty_and_nonempty() -> None:
    assert render_rows_text([]) == "Threshold sensitivity\nNo combinations."
    assert render_rows_markdown([]) == "## Threshold sensitivity\n_No combinations._"

    swaps, wallet_scores = _make_fixture()
    rows = sweep(swaps, wallet_scores)
    text = render_rows_text(rows, title="Sweep")
    md = render_rows_markdown(rows, title="Sweep")

    assert not text.endswith("\n")
    assert not md.endswith("\n")
    assert "Sweep" in text
    assert "Sweep" in md
    assert "wallets" in text
    assert "| Min wallets |" in md
    assert "40.00" in text
    assert "40.00" in md
