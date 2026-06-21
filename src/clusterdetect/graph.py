"""Turn already-detected clusters into a graph for offline visualisation.

This module is pure presentation: it reshapes clusters that the detector has
*already* produced (token + the wallets that bought it inside the window) into a
node/edge graph you can open in Gephi, Cytoscape or networkx. It collects no new
data, makes no network calls, and watches nothing live — it just exports what is
already in the database into standard graph formats (JSON, Graphviz DOT, GraphML).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from xml.sax.saxutils import escape, quoteattr


@dataclass(frozen=True)
class GraphNode:
    id: str
    label: str
    kind: str  # "token" or "wallet"


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str


@dataclass(frozen=True)
class ClusterGraph:
    nodes: list[GraphNode]
    edges: list[GraphEdge]


def _short(addr: str, head: int = 4, tail: int = 4) -> str:
    return addr if len(addr) <= head + tail + 1 else f"{addr[:head]}…{addr[-tail:]}"


def build_cluster_graph(clusters: list[dict[str, Any]]) -> ClusterGraph:
    """Build a bipartite wallet↔token graph from detected clusters.

    Each cluster is a mapping with a ``token`` (or ``token_mint``) and a list of
    ``wallets``. A wallet that appears in several clusters becomes a single shared
    node — which is the whole point of looking at clusters as a graph.
    """
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    seen_edges: set[tuple[str, str]] = set()

    for cluster in clusters:
        token = str(cluster.get("token") or cluster.get("token_mint") or "").strip()
        if not token:
            continue
        token_id = f"t:{token}"
        if token_id not in nodes:
            nodes[token_id] = GraphNode(id=token_id, label=_short(token), kind="token")
        for wallet in cluster.get("wallets") or []:
            wallet = str(wallet).strip()
            if not wallet:
                continue
            wallet_id = f"w:{wallet}"
            if wallet_id not in nodes:
                nodes[wallet_id] = GraphNode(id=wallet_id, label=_short(wallet), kind="wallet")
            key = (wallet_id, token_id)
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append(GraphEdge(source=wallet_id, target=token_id))

    return ClusterGraph(nodes=list(nodes.values()), edges=edges)


def to_json(graph: ClusterGraph) -> str:
    """Serialise the graph as JSON (``{"nodes": [...], "edges": [...]}``)."""
    payload = {
        "nodes": [{"id": n.id, "label": n.label, "kind": n.kind} for n in graph.nodes],
        "edges": [{"source": e.source, "target": e.target} for e in graph.edges],
    }
    return json.dumps(payload, indent=2)


def to_dot(graph: ClusterGraph) -> str:
    """Serialise the graph as Graphviz DOT. Wallets are circles, tokens are boxes."""
    lines = ["digraph clusters {", "  rankdir=LR;", "  node [style=filled];"]
    for node in graph.nodes:
        shape = "box" if node.kind == "token" else "ellipse"
        color = "#fde68a" if node.kind == "token" else "#bfdbfe"
        lines.append(
            f"  {json.dumps(node.id)} [label={json.dumps(node.label)}, "
            f'shape={shape}, fillcolor="{color}"];'
        )
    for edge in graph.edges:
        lines.append(f"  {json.dumps(edge.source)} -> {json.dumps(edge.target)};")
    lines.append("}")
    return "\n".join(lines) + "\n"


def to_graphml(graph: ClusterGraph) -> str:
    """Serialise the graph as GraphML (opens in Gephi/Cytoscape/yEd)."""
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
        '  <key id="label" for="node" attr.name="label" attr.type="string"/>',
        '  <key id="kind" for="node" attr.name="kind" attr.type="string"/>',
        '  <graph edgedefault="directed">',
    ]
    for node in graph.nodes:
        out.append(f"    <node id={quoteattr(node.id)}>")
        out.append(f'      <data key="label">{escape(node.label)}</data>')
        out.append(f'      <data key="kind">{escape(node.kind)}</data>')
        out.append("    </node>")
    for index, edge in enumerate(graph.edges):
        out.append(
            f'    <edge id="e{index}" source={quoteattr(edge.source)} '
            f"target={quoteattr(edge.target)}/>"
        )
    out.append("  </graph>")
    out.append("</graphml>")
    return "\n".join(out) + "\n"


def render_graph(graph: ClusterGraph, fmt: str = "json") -> str:
    """Render the graph in ``json``, ``dot`` or ``graphml`` format."""
    if fmt == "json":
        return to_json(graph)
    if fmt == "dot":
        return to_dot(graph)
    if fmt == "graphml":
        return to_graphml(graph)
    raise ValueError(f"unknown graph format {fmt!r}; choose json, dot or graphml")
