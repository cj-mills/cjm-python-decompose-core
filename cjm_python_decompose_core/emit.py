"""Project a module BACK out of the graph (graph -> .py) — the canonical emit leg.

The inverse of `extract`: reassemble a module's `.py` source from its ordered top-level
regions (top-level `CodeSymbol` verbatim bodies + `CodeText` verbatim regions), with
the SEAMS regenerated canonically. This is the graph→`.py` half of authoring-on-graph
([[graph-as-source-of-truth-inversion]]): the graph OWNS formatting, so a human never
hand-edits the export. Mirrors the notebook compositor's `project.py` (graph -> .ipynb).

Operates on `CodeSymbolNode`/`CodeTextNode` objects OR queried graph wire dicts (so emit
reads the GRAPH as source — the real "graph is a sufficient source" proof). The fidelity
bar: symbol/region BODIES are byte-exact, only the inter-region seams are canonical
(2 blank lines around a def/class, 1 between text regions) — semantically equal, not
necessarily byte-identical to a non-PEP-8 original.
"""

from typing import Any, List, Optional, Tuple

from .parse import SourceRegion, emit_regions

_SYMBOL_LABELS = {"CodeSymbol"}
_TEXT_LABELS = {"CodeText"}


def _region_from_node(
    node: Any,  # A CodeSymbolNode / CodeTextNode object, or a queried wire dict
) -> Optional[Tuple[int, SourceRegion]]:  # (order_index, region) or None when the node is not a top-level region
    """Pull (order_index, verbatim region) from a node — None for non-region nodes.

    A region is a node carrying an `order_index` (top-level symbols + code-text regions);
    nested symbols (no body, no order_index) and any other node kind return None."""
    if isinstance(node, dict):
        label = node.get("label", "")
        p = node.get("properties", {})
        order = p.get("order_index")
        if order is None:
            return None
        if label in _SYMBOL_LABELS:
            return order, SourceRegion(kind="symbol", text=p.get("body", ""),
                                       start_line=0, end_line=0,
                                       qualname=p.get("qualname", ""),
                                       symbol_kind=p.get("symbol_kind", ""))
        if label in _TEXT_LABELS:
            return order, SourceRegion(kind="text", text=p.get("text", ""),
                                       start_line=0, end_line=0,
                                       region_key=p.get("region_key", ""))
        return None
    # Node object: distinguish by the presence of a `body` (symbol) vs `text` (region) attr.
    order = getattr(node, "order_index", None)
    if order is None:
        return None
    if hasattr(node, "body"):
        return order, SourceRegion(kind="symbol", text=node.body, start_line=0, end_line=0,
                                   qualname=getattr(node, "qualname", ""),
                                   symbol_kind=getattr(node, "symbol_kind", ""))
    if hasattr(node, "text"):
        return order, SourceRegion(kind="text", text=node.text, start_line=0, end_line=0,
                                   region_key=getattr(node, "region_key", ""))
    return None


def regions_from_nodes(
    nodes: Any,  # CodeSymbol/CodeText nodes (objects or wire dicts) belonging to ONE module
) -> List[SourceRegion]:  # The module's ordered top-level regions
    """Collect a module's top-level regions from its nodes, ordered by `order_index`.

    Non-region nodes (nested symbols, the module node itself, anything else) are
    skipped — only the ordered verbatim regions reassemble the source."""
    found = [r for r in (_region_from_node(n) for n in nodes) if r is not None]
    found.sort(key=lambda t: t[0])
    return [region for _order, region in found]


def emit_module_from_nodes(
    nodes: Any,  # The module's CodeSymbol/CodeText nodes (objects or queried wire dicts)
) -> str:  # The reconstructed canonical `.py` source
    """Reassemble a module's canonical `.py` source from its graph nodes (the round-trip)."""
    return emit_regions(regions_from_nodes(nodes))


def nodes_for_module(
    nodes: Any,         # Queried CodeSymbol/CodeText wire dicts (e.g. find_nodes_by_label)
    module_id: str,     # The CodeModule id to filter to
) -> List[Any]:  # The region nodes belonging to that module
    """Filter queried region nodes down to one module (by `module_id` property)."""
    out = []
    for n in nodes:
        p = n.get("properties", {}) if isinstance(n, dict) else {}
        if p.get("module_id") == module_id:
            out.append(n)
    return out
