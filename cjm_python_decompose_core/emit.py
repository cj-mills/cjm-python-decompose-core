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

import re
from typing import Any, Dict, List, Optional, Tuple

from .parse import SourceRegion, emit_regions

_SYMBOL_LABELS = {"CodeSymbol"}
_TEXT_LABELS = {"CodeText"}


def _binding_key(b: Dict[str, Any]) -> Tuple:
    """A binding's dedup/identity key (one import across symbols that share it)."""
    return (b.get("kind"), b.get("level", 0), b.get("module", ""),
            b.get("imported", ""), b.get("alias", ""))


def render_binding(b: Dict[str, Any]) -> str:  # One `import ...` / `from ... import ...` line
    """Render one import-binding descriptor back to its canonical import statement.

    `{kind:import, module:os}` -> `import os`; `{kind:import, module:a.b, alias:c}` ->
    `import a.b as c`; `{kind:from, level:1, module:util, imported:helper, alias:h}` ->
    `from .util import helper as h`; `{kind:from, level:1, module:'', imported:sib}` ->
    `from . import sib`."""
    if b.get("kind") == "import":
        line = f"import {b['module']}"
        if b.get("alias"):
            line += f" as {b['alias']}"
        return line
    src = "." * b.get("level", 0) + (b.get("module") or "")
    name = b.get("imported", "")
    line = f"from {src} import {name}"
    if b.get("alias") and b["alias"] != name:
        line += f" as {b['alias']}"
    return line


def _from_name(b: Dict[str, Any]) -> str:
    """The `name` / `name as alias` clause of one `from ... import` binding."""
    name = b.get("imported", "")
    return f"{name} as {b['alias']}" if b.get("alias") and b["alias"] != name else name


def render_import_block(
    bindings: List[Dict[str, Any]],  # Import-binding descriptors (per-symbol + module-level, unioned)
) -> str:  # The canonical import block text ("" when none)
    """Derive a module's canonical import block from its used import bindings.

    The imports-as-projection emit: the block is GENERATED from the bindings the module's
    symbols actually use (so an unused import is auto-pruned), deterministically ordered —
    `from __future__` first, then `import` statements, then `from` imports (absolute before
    relative), all sorted by module; same-source `from` imports MERGE onto one line. Faithful
    at the SET level (the round-trip bar is semantic equality of the import set, not
    byte-identity to a hand-ordered original)."""
    seen: set = set()
    uniq: List[Dict[str, Any]] = []
    for b in bindings:
        k = _binding_key(b)
        if k not in seen:
            seen.add(k)
            uniq.append(b)

    future: List[str] = []
    plain_imports: List[Dict[str, Any]] = []
    from_groups: Dict[Tuple[int, str], List[str]] = {}
    for b in uniq:
        if b.get("kind") == "import":
            plain_imports.append(b)
        elif b.get("module") == "__future__" and not b.get("level", 0):
            future.append(_from_name(b))
        else:
            from_groups.setdefault((b.get("level", 0), b.get("module") or ""), []).append(_from_name(b))

    lines: List[str] = []
    if future:
        lines.append(f"from __future__ import {', '.join(sorted(set(future)))}")
    for b in sorted(plain_imports, key=lambda x: (x.get("module") or "").lower()):
        lines.append(render_binding(b))
    for (level, module) in sorted(from_groups, key=lambda k: (k[0], k[1].lower())):
        names = ", ".join(sorted(set(from_groups[(level, module)]), key=str.lower))
        lines.append(f"from {'.' * level}{module} import {names}")
    return "\n".join(lines)


def module_used_bindings(
    symbol_nodes: Any,        # The module's CodeSymbol nodes (objects or wire dicts) — carry per-symbol import_bindings
    module_node: Any = None,  # The CodeModule node (carries module-level import_bindings) — optional
) -> List[Dict[str, Any]]:  # The unioned import bindings this module needs
    """Union of every contained symbol's import bindings + the module-level ones.

    This is the input to `render_import_block`: which imports the module's CURRENT members
    (symbols + module-level code) actually use — so moving a symbol between modules
    recomputes both sides' import blocks correctly (imports-as-projection / pure move)."""
    def get(node: Any, key: str) -> List[Dict[str, Any]]:
        if node is None:
            return []
        if isinstance(node, dict):
            return (node.get("properties") or node).get(key, []) or []
        props = getattr(node, "properties", None)       # graph node object carrying a props dict
        if isinstance(props, dict):
            return props.get(key, []) or []
        return getattr(node, key, []) or []              # plain object with the attr directly

    out: List[Dict[str, Any]] = []
    if module_node is not None:
        out.extend(get(module_node, "import_bindings"))
    for s in symbol_nodes:
        out.extend(get(s, "import_bindings"))
    return out


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


def _label_of(node: Any) -> str:
    """A node's label ('CodeSymbol' / 'CodeText' / …) from a wire dict or object."""
    if isinstance(node, dict):
        return node.get("label", "")
    return getattr(node, "label", node.__class__.__name__)


def _looks_like_docstring(text: str) -> bool:
    """Whether a text region opens with a string literal (a module docstring)."""
    return text.lstrip().startswith(('"""', "'''", '"', "'"))


_IMPORT_LINE = re.compile(r"\s*(from|import)\s")


def _strip_import_lines(text: str) -> str:  # The region text with top-level import statements removed
    """Drop top-level `import`/`from ... import` statements (paren/backslash continuations
    included) from a text region, keeping any non-import lines — so a region that mixes
    imports with a constant keeps the constant while the imports are regenerated."""
    lines = text.splitlines()
    out: List[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if _IMPORT_LINE.match(ln):
            depth = ln.count("(") - ln.count(")")
            cont = ln.rstrip().endswith("\\")
            i += 1
            while (depth > 0 or cont) and i < len(lines):
                depth += lines[i].count("(") - lines[i].count(")")
                cont = lines[i].rstrip().endswith("\\")
                i += 1
            continue
        out.append(ln)
        i += 1
    return "\n".join(out)


def emit_module_from_nodes(
    nodes: Any,  # The module's CodeSymbol (incl. methods, for bindings) + CodeText nodes
    module_node: Any = None,        # The CodeModule node (module-level import bindings) — for derive_imports
    derive_imports: bool = False,   # Regenerate the import block from bindings instead of the verbatim region
) -> str:  # The reconstructed canonical `.py` source
    """Reassemble a module's canonical `.py` source from its graph nodes (the round-trip).

    With `derive_imports`, the verbatim import region is replaced by the block DERIVED from
    the module's used import bindings (imports-as-projection): unused imports drop, ordering
    is canonical, and a moved symbol's imports recompute — at the SEMANTIC fidelity bar
    (bodies byte-exact, the import set equal/canonical), not byte-identity."""
    regions = regions_from_nodes(nodes)
    if not derive_imports:
        return emit_regions(regions)
    symbols = [n for n in nodes if _label_of(n) == "CodeSymbol"]
    block = render_import_block(module_used_bindings(symbols, module_node))
    rebuilt: List[SourceRegion] = []
    for r in regions:
        if r.kind == "text":
            kept = _strip_import_lines(r.text).strip("\n")
            if kept.strip():
                rebuilt.append(SourceRegion(kind="text", text=kept, start_line=0, end_line=0,
                                            region_key=getattr(r, "region_key", "")))
        else:
            rebuilt.append(r)
    if block:
        imp = SourceRegion(kind="text", text=block, start_line=0, end_line=0, region_key="imports")
        pos = 1 if (rebuilt and rebuilt[0].kind == "text"
                    and _looks_like_docstring(rebuilt[0].text)) else 0
        rebuilt.insert(pos, imp)
    return emit_regions(rebuilt)


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
