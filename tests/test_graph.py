"""Tests for the offline cluster-graph export (v0.4)."""

from __future__ import annotations

import json
from xml.dom import minidom

import pytest

from clusterdetect.graph import build_cluster_graph, render_graph, to_dot, to_graphml, to_json

CLUSTERS = [
    {"token": "TokenAAA", "wallets": ["walletONE", "walletTWO", "walletTHREE"]},
    {"token_mint": "TokenBBB", "wallets": ["walletTWO", "walletFOUR"]},  # walletTWO shared
]


def test_build_graph_shares_repeated_wallet_nodes() -> None:
    g = build_cluster_graph(CLUSTERS)
    wallet_nodes = [n for n in g.nodes if n.kind == "wallet"]
    token_nodes = [n for n in g.nodes if n.kind == "token"]
    assert len(token_nodes) == 2
    # walletTWO appears in both clusters but is a single shared node
    assert len(wallet_nodes) == 4
    # 3 + 2 = 5 directed wallet->token edges
    assert len(g.edges) == 5


def test_build_graph_dedupes_edges_and_skips_blanks() -> None:
    g = build_cluster_graph(
        [
            {"token": "T", "wallets": ["w1", "w1", "", "w2"]},
            {"token": "", "wallets": ["w3"]},  # no token -> skipped
        ]
    )
    assert len([n for n in g.nodes if n.kind == "token"]) == 1
    assert len(g.edges) == 2  # w1 deduped, blank skipped, w3 cluster skipped


def test_to_json_round_trips() -> None:
    g = build_cluster_graph(CLUSTERS)
    payload = json.loads(to_json(g))
    assert {n["id"] for n in payload["nodes"]} == {n.id for n in g.nodes}
    assert len(payload["edges"]) == len(g.edges)


def test_to_dot_is_a_digraph() -> None:
    dot = to_dot(build_cluster_graph(CLUSTERS))
    assert dot.startswith("digraph clusters {")
    assert "->" in dot
    assert dot.strip().endswith("}")


def test_to_graphml_is_valid_xml() -> None:
    xml = to_graphml(build_cluster_graph(CLUSTERS))
    # parses without error
    doc = minidom.parseString(xml)
    assert doc.getElementsByTagName("graphml")
    assert doc.getElementsByTagName("node")
    assert doc.getElementsByTagName("edge")


def test_render_graph_dispatch_and_unknown() -> None:
    g = build_cluster_graph(CLUSTERS)
    assert render_graph(g, "json").startswith("{")
    assert render_graph(g, "dot").startswith("digraph")
    assert render_graph(g, "graphml").startswith("<?xml")
    with pytest.raises(ValueError):
        render_graph(g, "svg")


def test_empty_clusters_graph() -> None:
    g = build_cluster_graph([])
    assert g.nodes == []
    assert g.edges == []
