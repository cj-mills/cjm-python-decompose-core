"""Flatten a decomposed Python corpus into graph elements (the queue-free half).

Turns `DecomposedModule`s into the `(nodes, edges)` wire-dict lists that
`cjm_context_graph_layer.ops.extend_graph` commits — adding the CORPUS-level edges
that need the whole corpus to resolve:

- `IMPORTS` (module -> module): each module's raw imports are resolved (relative
  imports against the importer's own package) and matched to a module in the corpus.
- `CALLS` (symbol -> symbol): best-effort, by UNAMBIGUOUS bare name — a call name
  that maps to exactly one symbol in the corpus links; ambiguous/external names are
  skipped (precision over recall — never mint a wrong edge).

External/stdlib targets are simply absent from the maps and skipped (never
phantom-minted), mirroring the markdown core's dangling-reference discipline. The
queue/capability wiring is the projection-CLI driver's concern; the flattening here
is reusable and unit-testable without a running graph.
"""

from typing import Any, Dict, Iterable, List, Optional, Tuple

from .extract import DecomposedModule


def resolve_import(
    raw: str,                  # Raw import as captured by parse ("os", "pkg.mod", ".identity", "..pkg")
    importer_import_name: str,  # The importing module's dotted import name (e.g. "pkg.sub.mod")
    is_package: bool,          # Whether the importer is a package (__init__) — its package is itself
) -> Optional[str]:  # Absolute dotted module name, or None when it escapes the corpus root
    """Resolve a (possibly relative) import to an absolute dotted module name.

    Absolute imports pass through unchanged. A relative import's leading dots are a
    level (1 = the importer's own package, each extra dot goes one package up); the
    remainder is appended. Returns None when the dots climb above the top package."""
    if not raw.startswith("."):
        return raw
    n_dots = len(raw) - len(raw.lstrip("."))
    suffix = raw[n_dots:]
    parts = importer_import_name.split(".") if importer_import_name else []
    base = parts if is_package else parts[:-1]  # the importer's package
    up = n_dots - 1
    if up > len(base):
        return None
    pkg = list(base[:len(base) - up]) if up else list(base)
    if suffix:
        pkg += suffix.split(".")
    return ".".join(pkg) if pkg else None


def build_import_map(
    decomposed: Iterable[DecomposedModule],  # The decomposed corpus
) -> Dict[str, str]:  # {dotted import name: CodeModule id}
    """Map every module's dotted import name to its node id (the IMPORTS target table)."""
    return {d.module.import_name: d.module.id for d in decomposed if d.module.import_name}


def build_call_map(
    decomposed: Iterable[DecomposedModule],  # The decomposed corpus
) -> Dict[str, str]:  # {bare symbol name: CodeSymbol id}, UNAMBIGUOUS names only
    """Map UNAMBIGUOUS bare symbol names to their node ids (the CALLS target table).

    A name defined by more than one symbol is omitted — resolving it would guess.
    This favors precision: distinctively-named free functions link, shared method
    names (`id`, `to_graph_node`, ...) do not."""
    name_to_ids: Dict[str, set] = {}
    for d in decomposed:
        for s in d.symbols:
            name_to_ids.setdefault(s.qualname.split(".")[-1], set()).add(s.id)
    return {name: next(iter(ids)) for name, ids in name_to_ids.items() if len(ids) == 1}


def corpus_graph_elements(
    decomposed: Iterable[DecomposedModule],  # The decomposed corpus (one entry per module)
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:  # (node wire dicts, edge wire dicts)
    """Collect a decomposed corpus into the node + edge wire-dict lists `extend_graph` expects.

    Nodes: one `CodeModule` per file + one `CodeSymbol` per definition. Edges: the
    per-module local edges (ABOUT to the repo Entity + structural DEFINES) plus the
    resolved corpus-level IMPORTS/CALLS. Deterministic ids make this idempotent
    under `extend_graph` (re-ingesting collides into verified no-ops)."""
    decs = list(decomposed)
    import_map = build_import_map(decs)
    call_map = build_call_map(decs)

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    for d in decs:
        nodes.append(d.module.to_graph_node())
        nodes.extend(s.to_graph_node() for s in d.symbols)
        edges.extend(d.local_edges)

        is_pkg = d.module.module_path.endswith("__init__.py")
        local_imports: Dict[str, str] = {}
        for raw in d.module.imports:
            target = resolve_import(raw, d.module.import_name, is_pkg)
            if target and target in import_map and import_map[target] != d.module.id:
                local_imports[raw] = import_map[target]
        edges.extend(d.module.import_edges(local_imports))

        for s in d.symbols:
            edges.extend(s.calls_edges(call_map))
    return nodes, edges
