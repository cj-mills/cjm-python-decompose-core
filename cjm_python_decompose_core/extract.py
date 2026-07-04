"""Bind parsed Python onto dev-graph-schema code nodes (the dev-domain binding).

Turns a `ParsedModule` into a `CodeModuleNode` + its `CodeSymbolNode`s, carrying
file-hash provenance and the LOCAL edges (ABOUT -> the repo Entity; DEFINES
module->top-level symbol and class->method). The CORPUS-level edges (IMPORTS/CALLS,
which need the whole decomposed corpus to resolve) are added in `ingest`. This is
the analogue of `cjm_markdown_decompose_core.extract` for the code source type.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from cjm_context_graph_primitives.provenance import SourceRef
from cjm_dev_graph_schema.nodes import CodeModuleNode, CodeSymbolNode, CodeTextNode

from .parse import parse_module, parse_regions, ParsedModule, SourceRegion

# Directories never decomposed as source (generated / virtualenv / packaging cruft).
_SKIP_DIRS = {"__pycache__", ".git", ".ipynb_checkpoints", "build", "dist", ".eggs"}


@dataclass
class DecomposedModule:
    """One module bound to schema nodes: the module + its symbols + local edges.

    `parsed` is retained so the ingest layer can resolve corpus-level IMPORTS/CALLS
    (which need every module's import-name / every symbol's name to be known).
    `texts` are the non-def verbatim regions (the round-trip substrate between symbols);
    the module's CONTAINS edges (in `local_edges`) order all top-level regions for emit."""
    module: CodeModuleNode               # The CodeModule node
    symbols: List[CodeSymbolNode]        # All symbols, flattened (every nesting level)
    local_edges: List[Dict[str, Any]] = field(default_factory=list)  # ABOUT + structural DEFINES + CONTAINS edges
    parsed: Optional[ParsedModule] = None  # The raw parse (for corpus IMPORTS/CALLS resolution)
    texts: List[CodeTextNode] = field(default_factory=list)  # Non-def verbatim regions (imports/docstring/constants/__main__)


def _text_region_kind(
    region: SourceRegion,  # A "text" region
) -> str:  # Coarse flavor for relevance/render ("imports" | "docstring" | "code")
    """Classify a non-def text region for display (imports / module docstring / code)."""
    stripped = region.text.lstrip()
    if stripped.startswith(("import ", "from ")):
        return "imports"
    if stripped.startswith(('"""', "'''", '"', "'")):
        return "docstring"
    return "code"


def module_path_for(
    path: str,       # The file path
    repo_root: str,  # The repo root the module path is relative to
) -> str:  # Repo-relative POSIX module path (e.g. "cjm_dev_graph_schema/nodes.py")
    """The repo-relative POSIX path used as the module's identity input.

    Falls back to the bare filename when the path is not under `repo_root`."""
    p = Path(path)
    try:
        rel = p.relative_to(repo_root)
    except ValueError:
        rel = Path(p.name)
    return rel.as_posix()


def import_name_for(
    module_path: str,  # Repo-relative module path
) -> str:  # Dotted import name ("pkg/sub/mod.py" -> "pkg.sub.mod"; "pkg/__init__.py" -> "pkg")
    """The dotted import name a module is reachable by (drops a trailing `__init__`)."""
    parts = list(Path(module_path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _build_symbols(
    module: CodeModuleNode,   # The enclosing module node
    parsed: ParsedModule,     # Its parse
    content_hash: str,        # The module file's content hash (symbols share their file's source)
    path: str,                # The file path (provenance locator)
) -> Tuple[List[CodeSymbolNode], List[Dict[str, Any]]]:  # (flat symbol nodes, DEFINES edges)
    """Flatten the parse tree into symbol nodes + structural DEFINES edges.

    DEFINES runs module->top-level symbol and parent-symbol->nested-symbol, so the
    nesting (class -> its methods) is preserved as edges, not just qualname text."""
    symbols: List[CodeSymbolNode] = []
    edges: List[Dict[str, Any]] = []

    def make(ps) -> CodeSymbolNode:
        node = CodeSymbolNode(
            module_id=module.id, qualname=ps.qualname, symbol_kind=ps.kind,
            path=path, content_hash=content_hash, lineno=ps.lineno,
            docstring=ps.docstring, calls=list(ps.calls), refs=list(ps.refs),
            import_bindings=list(ps.import_bindings),
            properties={"decorators": list(ps.decorators)} if ps.decorators else {},
        )
        symbols.append(node)
        children = [make(c) for c in ps.children]
        if children:
            edges.extend(node.defines_edges([c.id for c in children]))
        return node

    top = [make(ps) for ps in parsed.symbols]
    edges[:0] = module.defines_edges([t.id for t in top])  # module->top DEFINES first
    return symbols, edges


def decompose_text(
    repo_key: str,                    # The repo's durable conceptual slug (caller-supplied; the federation anchor)
    module_path: str,                 # Repo-relative module path (identity input)
    path: str,                        # File path (provenance locator)
    text: str,                        # The module source text
    content_hash: Optional[str] = None,  # Precomputed file hash (else hashed over the UTF-8 text)
    import_name: Optional[str] = None,   # Override the derived dotted import name
) -> DecomposedModule:  # The decomposed module
    """Parse + bind in one step from in-memory source text."""
    ch = content_hash if content_hash is not None else SourceRef.compute_hash(text.encode("utf-8"))
    parsed = parse_module(text)
    module = CodeModuleNode(
        repo_key=repo_key, module_path=module_path, path=path, content_hash=ch,
        import_name=import_name if import_name is not None else import_name_for(module_path),
        docstring=parsed.docstring, imports=list(parsed.imports),
        import_bindings=list(parsed.module_used_bindings),
    )
    symbols, defines = _build_symbols(module, parsed, ch, path)

    # Verbatim-region overlay (the authoring / round-trip substrate): attach each
    # top-level symbol's VERBATIM body + order, mint CodeText nodes for the non-def
    # regions, and order ALL top-level regions under the module via CONTAINS.
    top_by_qual = {s.qualname: s for s in symbols if "." not in s.qualname}
    texts: List[CodeTextNode] = []
    region_ids: List[str] = []
    for i, region in enumerate(parse_regions(text)):
        if region.kind == "symbol":
            sym = top_by_qual.get(region.qualname)
            if sym is None:  # defensive: a top-level def with no matching ParsedSymbol (shouldn't happen)
                continue
            sym.body = region.text
            sym.body_hash = SourceRef.compute_hash(region.text.encode("utf-8"))
            sym.order_index = i
            region_ids.append(sym.id)
        else:
            ct = CodeTextNode(
                module_id=module.id, region_key=region.region_key, text=region.text,
                content_hash=SourceRef.compute_hash(region.text.encode("utf-8")),
                order_index=i, path=path, kind=_text_region_kind(region))
            texts.append(ct)
            region_ids.append(ct.id)

    local_edges = [module.about_edge(), *defines, *module.contains_edges(region_ids)]
    return DecomposedModule(module=module, symbols=symbols, local_edges=local_edges,
                            parsed=parsed, texts=texts)


def decompose_file(
    repo_key: str,    # The repo's durable conceptual slug
    path: str,        # Path to the .py file
    repo_root: str,   # Repo root (for the repo-relative module path)
) -> DecomposedModule:  # The decomposed module
    """Read a `.py` file and decompose it (hash over the raw file bytes)."""
    raw = Path(path).read_bytes()
    mp = module_path_for(path, repo_root)
    return decompose_text(repo_key, mp, str(path), raw.decode("utf-8"),
                          content_hash=SourceRef.compute_hash(raw))


def iter_py_files(
    root: str,  # Directory to walk
) -> Iterator[str]:  # Paths to .py files (skipping generated/packaging dirs)
    """Yield `.py` file paths under `root`, skipping `__pycache__`/build/etc."""
    base = Path(root)
    for p in sorted(base.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in p.relative_to(base).parts):
            continue
        yield str(p)


def decompose_paths(
    repo_key: str,           # The repo's durable conceptual slug
    paths: Iterable[str],    # The .py files to decompose
    repo_root: str,          # Repo root (for repo-relative module paths)
) -> List[DecomposedModule]:  # One DecomposedModule per parseable file
    """Decompose an explicit set of files; unparseable files are skipped (recorded by the caller)."""
    out: List[DecomposedModule] = []
    for path in paths:
        try:
            out.append(decompose_file(repo_key, path, repo_root))
        except SyntaxError:
            continue
    return out


def decompose_package(
    repo_key: str,                    # The repo's durable conceptual slug
    package_dir: str,                 # The importable package directory (e.g. ".../cjm_dev_graph_schema")
    repo_root: Optional[str] = None,  # Repo root for relative module paths (default = package_dir's parent)
) -> List[DecomposedModule]:  # The decomposed package modules
    """Decompose every `.py` under a package dir (the lib's own importable source).

    `repo_root` defaults to the package dir's parent, so module paths read like
    `cjm_dev_graph_schema/nodes.py` (the importable form)."""
    root = repo_root if repo_root is not None else str(Path(package_dir).parent)
    return decompose_paths(repo_key, iter_py_files(package_dir), root)
