"""Schema-free Python parsing (stdlib `ast`).

Decomposes a `.py` module into its module docstring, imports, and the tree of
top-level + nested symbols (functions, classes, methods) — each with its
qualified name, kind, line number, docstring, decorators, and the names it
references/calls. Carries NO graph-schema dependency on purpose: this is the
genuinely-general layer, reusable for any Python corpus. The dev-domain binding
(-> `CodeModule`/`CodeSymbol` nodes) lives in `extract`.

Mirrors `cjm_markdown_decompose_core.parse`'s split: pure structural
decomposition here, the schema meeting in `extract`.
"""

import ast
from dataclasses import dataclass, field
from typing import Iterator, List

# Definition node types that become symbols (and that own their own call scope).
_DEF_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


@dataclass
class ParsedSymbol:
    """One definition within a module (function/class/method), with its nesting."""
    qualname: str                      # Dotted name within the module (e.g. "EntityNode.to_graph_node")
    name: str                          # Bare name (the last qualname segment)
    kind: str                          # "function" | "class" | "method"
    lineno: int                        # 1-based start line
    docstring: str = ""                # First non-empty line of the symbol's docstring ("" if none)
    decorators: List[str] = field(default_factory=list)  # Decorator names (e.g. "dataclass", "property")
    calls: List[str] = field(default_factory=list)       # Names this symbol directly references/calls (dedup, order-preserved)
    children: List["ParsedSymbol"] = field(default_factory=list)  # Nested symbols (a class's methods, a nested function)


@dataclass
class ParsedModule:
    """The structural decomposition of one Python module."""
    docstring: str = ""                # First non-empty line of the module docstring
    imports: List[str] = field(default_factory=list)  # Imported module names (dotted; relative kept as ".pkg"), dedup/order-preserved
    symbols: List[ParsedSymbol] = field(default_factory=list)  # Top-level symbols (each may carry children)


def _docstring_first_line(
    node: ast.AST,  # A module / function / class node
) -> str:  # First non-empty docstring line ("" when no docstring)
    """The first non-empty line of a node's docstring (the relevance/description hook)."""
    doc = ast.get_docstring(node)
    if not doc:
        return ""
    for line in doc.splitlines():
        s = line.strip()
        if s:
            return s
    return ""


def _callee_name(
    func: ast.AST,  # The `.func` of an ast.Call
) -> str:  # The bare callee name ("" when not a plain Name/Attribute)
    """Bare callee name: `f()` -> "f", `obj.m()` / `mod.f()` -> "m"/"f"."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _decorator_name(
    dec: ast.AST,  # A decorator expression
) -> str:  # The decorator's bare name ("" when not a Name/Attribute/Call of those)
    """Bare decorator name: `@foo` -> "foo", `@a.b` -> "b", `@foo(...)` -> "foo"."""
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Attribute):
        return dec.attr
    if isinstance(dec, ast.Call):
        return _decorator_name(dec.func)
    return ""


def _collect_calls(
    node: ast.AST,         # A statement/expression node to scan
    names: "dict[str, None]",  # Accumulator (ordered set via dict keys)
) -> None:
    """Collect direct call names under `node`, NOT descending into nested defs.

    A nested function/class owns its own calls (attributed to that child symbol),
    so its subtree is skipped here — this keeps each symbol's `calls` to the code
    it itself runs."""
    if isinstance(node, _DEF_TYPES):
        return
    if isinstance(node, ast.Call):
        nm = _callee_name(node.func)
        if nm:
            names.setdefault(nm, None)
    for child in ast.iter_child_nodes(node):
        _collect_calls(child, names)


def _direct_calls(
    node: ast.AST,  # A FunctionDef / ClassDef node
) -> List[str]:  # Direct call names in its body (dedup, order-preserved)
    """Call names made directly in a symbol's body (excluding nested def bodies)."""
    names: "dict[str, None]" = {}
    for stmt in getattr(node, "body", []):
        _collect_calls(stmt, names)
    return list(names)


def _extract_symbols(
    body: List[ast.stmt],   # A module/class/function body
    parent_qual: str = "",  # Enclosing qualname prefix ("" at module level)
    in_class: bool = False,  # Whether `body` is a class body (so defs are methods)
) -> List[ParsedSymbol]:  # Symbols declared directly in this body (with children)
    """Recursively decompose the def/class nodes in a body into `ParsedSymbol`s."""
    out: List[ParsedSymbol] = []
    for node in body:
        if not isinstance(node, _DEF_TYPES):
            continue
        qual = f"{parent_qual}.{node.name}" if parent_qual else node.name
        if isinstance(node, ast.ClassDef):
            kind = "class"
        else:
            kind = "method" if in_class else "function"
        out.append(ParsedSymbol(
            qualname=qual,
            name=node.name,
            kind=kind,
            lineno=node.lineno,
            docstring=_docstring_first_line(node),
            decorators=[d for d in (_decorator_name(x) for x in node.decorator_list) if d],
            calls=_direct_calls(node),
            children=_extract_symbols(node.body, parent_qual=qual,
                                      in_class=isinstance(node, ast.ClassDef)),
        ))
    return out


def _module_imports(
    tree: ast.Module,  # The parsed module
) -> List[str]:  # Imported module names (dotted; relative as leading-dot), dedup/order-preserved
    """Imported module names, in a form a corpus resolver can match.

    `import a.b` / `import a.b as c` -> "a.b"; `from a.b import c` -> "a.b" AND
    "a.b.c" (so `from pkg import submodule` resolves to the submodule when it is a
    module); relative imports keep their leading dots ("." / ".identity" / "..pkg")
    for the extract layer to resolve against the module's own package."""
    names: "dict[str, None]" = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.setdefault(alias.name, None)
        elif isinstance(node, ast.ImportFrom):
            base = "." * (node.level or 0) + (node.module or "")
            if base:
                names.setdefault(base, None)
            for alias in node.names:
                if alias.name == "*":
                    continue
                joiner = "" if base.endswith(".") else "."
                names.setdefault(f"{base}{joiner}{alias.name}" if base else alias.name, None)
    return list(names)


def parse_module(
    text: str,  # Full module source text
) -> ParsedModule:  # The structural decomposition
    """Parse Python source into module docstring + imports + the symbol tree.

    Raises `SyntaxError` on unparseable source (the caller decides how to handle a
    malformed file — there is no silent partial parse)."""
    tree = ast.parse(text)
    return ParsedModule(
        docstring=_docstring_first_line(tree),
        imports=_module_imports(tree),
        symbols=_extract_symbols(tree.body),
    )


def iter_symbols(
    parsed: ParsedModule,  # A decomposed module
) -> Iterator[ParsedSymbol]:  # Every symbol, parents before children (depth-first)
    """Flatten the symbol tree depth-first (parent before its children).

    Convenience for building corpus-wide symbol maps and for emitting one node per
    symbol regardless of nesting."""
    def walk(syms: List[ParsedSymbol]) -> Iterator[ParsedSymbol]:
        for s in syms:
            yield s
            yield from walk(s.children)
    yield from walk(parsed.symbols)


# ----------------------------------------------------------------------------- #
# Verbatim region decomposition (the authoring / round-trip substrate)
#
# A module is an ORDERED sequence of top-level regions: each def/class is a
# "symbol" region carrying its VERBATIM body (decorators + leading comments through
# the end of the def); each run of contiguous non-def top-level statements (imports,
# the module docstring, constants, `__all__`, `if __name__`) is a "text" region held
# verbatim. Blank lines BETWEEN regions are SEAMS — dropped here and regenerated
# canonically on emit ("the graph owns formatting"). This is the plain-`.py`
# analogue of a notebook's ordered verbatim cells; bodies are stored verbatim (NOT
# AST-as-graph — the round-trip trap).
# ----------------------------------------------------------------------------- #

@dataclass
class SourceRegion:
    """One ordered top-level region of a module, held verbatim (symbol or text)."""
    kind: str               # "symbol" (a def/class) | "text" (a non-def run)
    text: str               # The region's VERBATIM source (trailing blank lines trimmed; emit re-adds seams)
    start_line: int         # 1-based first source line of the region
    end_line: int           # 1-based last source line of the region
    qualname: str = ""      # Symbol regions: the top-level def/class name (matches the ParsedSymbol)
    symbol_kind: str = ""   # Symbol regions: "function" | "class"
    region_key: str = ""    # Text regions: a best-effort stable anchor (the region's leading line)


def _toplevel_start(
    node: ast.stmt,  # A top-level statement node
) -> int:  # Its first source line, decorator-aware
    """The first source line of a top-level node, counting decorators above a def."""
    start = node.lineno
    for d in getattr(node, "decorator_list", []):
        start = min(start, d.lineno)
    return start


def _text_region_key(
    text: str,  # The region's verbatim text
) -> str:  # A best-effort stable anchor key
    """A best-effort identity anchor for a text region: its first non-blank line.

    Stable across edits that don't change what the region LEADS with (v1 limitation —
    symbol identity is the rename-stable one that carries born-on-graph annotations;
    text-region identity is best-effort, since text regions hold no annotations)."""
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s[:80]
    return "region"


def parse_regions(
    text: str,  # Full module source text
) -> List[SourceRegion]:  # The ordered top-level regions (verbatim), seams excluded
    """Decompose a module into ordered verbatim top-level regions (the round-trip substrate).

    Def/class nodes become "symbol" regions (verbatim body incl. decorators + the
    contiguous comment block immediately above); runs of adjacent non-def top-level
    statements merge into "text" regions. Leading blank lines of each gap are dropped
    as seams (canonical emit regenerates them); a comment touching the following node
    attaches to it. Raises `SyntaxError` on unparseable source (caller decides)."""
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)  # 0-based; line L is lines[L-1]
    n = len(lines)

    def slice_text(start: int, end: int) -> str:  # 1-based inclusive -> verbatim, trailing blanks trimmed
        return "".join(lines[start - 1:end]).rstrip("\n")

    regions: List[SourceRegion] = []
    prev_end = 0  # last assigned source line (1-based)
    for node in tree.body:
        nstart, nend = _toplevel_start(node), (node.end_lineno or node.lineno)
        seg_start = prev_end + 1
        # Drop leading blank lines of the gap (seams); a comment then attaches to this node.
        while seg_start < nstart and not lines[seg_start - 1].strip():
            seg_start += 1
        is_def = isinstance(node, _DEF_TYPES)
        body = slice_text(seg_start, nend)
        if is_def:
            regions.append(SourceRegion(
                kind="symbol", text=body, start_line=seg_start, end_line=nend,
                qualname=node.name,
                symbol_kind="class" if isinstance(node, ast.ClassDef) else "function"))
        else:
            # Merge with a directly-adjacent preceding text region (no blank line between),
            # so an import block / consecutive statements stay ONE region (one seam, not N).
            if (regions and regions[-1].kind == "text"
                    and seg_start <= regions[-1].end_line + 1):
                merged = regions[-1]
                merged.text = slice_text(merged.start_line, nend)
                merged.end_line = nend
            else:
                regions.append(SourceRegion(
                    kind="text", text=body, start_line=seg_start, end_line=nend,
                    region_key=_text_region_key(body)))
        prev_end = nend

    # Trailing non-blank content after the last node (e.g. a trailing comment) -> a final text region.
    tail_start = prev_end + 1
    while tail_start <= n and not lines[tail_start - 1].strip():
        tail_start += 1
    if tail_start <= n:
        tail = slice_text(tail_start, n)
        regions.append(SourceRegion(kind="text", text=tail, start_line=tail_start,
                                    end_line=n, region_key=_text_region_key(tail)))

    # An empty / comments-only module has no ast nodes -> one text region holding it all.
    if not regions and text.strip():
        whole = text.rstrip("\n")
        regions.append(SourceRegion(kind="text", text=whole, start_line=1, end_line=n,
                                    region_key=_text_region_key(whole)))
    return regions


def emit_regions(
    regions: List[SourceRegion],  # Ordered top-level regions (symbol/text) to reassemble
) -> str:  # Canonical module source (verbatim bodies + canonical seams)
    """Reassemble ordered regions into canonical `.py` source — the graph owns formatting.

    Bodies are emitted VERBATIM; only the SEAMS between top-level regions are canonical:
    two blank lines around any def/class region (PEP-8), one blank line between text
    regions, and exactly one trailing newline. So decompose→emit is identity on PEP-8
    source and seam-normalizing otherwise (the deliberate v1 fidelity bar: bodies
    byte-exact, seams canonical, semantically equal)."""
    parts: List[str] = []
    for i, r in enumerate(regions):
        if i > 0:
            either_symbol = r.kind == "symbol" or regions[i - 1].kind == "symbol"
            parts.append("\n\n\n" if either_symbol else "\n\n")
        parts.append(r.text.rstrip("\n"))
    return ("".join(parts) + "\n") if parts else ""
