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
    calls: List[str] = field(default_factory=list)       # Names this symbol directly CALLS (call-callees only; dedup, order-preserved)
    refs: List[str] = field(default_factory=list)        # Names this symbol REFERENCES (superset of calls: + bases/annotations/decorators/name loads)
    import_bindings: List[dict] = field(default_factory=list)  # Top-level imports this symbol's refs use (travel with it on a move; imports-as-projection)
    children: List["ParsedSymbol"] = field(default_factory=list)  # Nested symbols (a class's methods, a nested function)
    first_param: str = ""              # The function's first parameter name ("" for a class / no-arg fn); "self"/"cls" marks method-shaped
    first_param_annotation: str = ""   # The first param's type annotation name (e.g. "JobQueue" for `@patch def f(self:JobQueue)`)


@dataclass
class ParsedModule:
    """The structural decomposition of one Python module."""
    docstring: str = ""                # First non-empty line of the module docstring
    imports: List[str] = field(default_factory=list)  # Imported module names (dotted; relative kept as ".pkg"), dedup/order-preserved
    symbols: List[ParsedSymbol] = field(default_factory=list)  # Top-level symbols (each may carry children)
    import_bindings: dict = field(default_factory=dict)        # {local-name: [binding, ...]} for every TOP-LEVEL import (the imports-as-projection table; a list because plain submodule imports sharing a root coexist)
    module_used_bindings: List[dict] = field(default_factory=list)  # Bindings used by module-level (non-def) code — constants/__all__/__main__


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


def _annotation_name(
    ann: ast.AST,  # A type-annotation expression (or None)
) -> str:  # The annotation's bare name ("" when absent/unsupported)
    """Bare annotation name: `JobQueue` -> "JobQueue", `mod.T` -> "T", `"JobQueue"` (forward ref) -> "JobQueue"."""
    if ann is None:
        return ""
    if isinstance(ann, ast.Name):
        return ann.id
    if isinstance(ann, ast.Attribute):
        return ann.attr
    if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
        return ann.value
    return ""


def _first_param(
    node: ast.AST,  # A FunctionDef / AsyncFunctionDef node
) -> "tuple[str, str]":  # (first param name, its annotation name) — ("","") when none
    """The function's first positional parameter name + annotation (the method-shape signal).

    A first param named `self`/`cls` marks a method-shaped function; its annotation
    (e.g. `self: JobQueue` under `@patch`) names the class the method belongs to."""
    args = getattr(node, "args", None)
    posonly = list(getattr(args, "posonlyargs", []) or []) if args else []
    pos = list(getattr(args, "args", []) or []) if args else []
    ordered = posonly + pos
    if not ordered:
        return "", ""
    a = ordered[0]
    return a.arg, _annotation_name(a.annotation)


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


def _collect_refs(
    node: ast.AST,             # A statement/expression node to scan
    names: "dict[str, None]",  # Accumulator (ordered set via dict keys)
) -> None:
    """Collect ALL referenced bare names under `node`, NOT descending into nested defs.

    The superset of `_collect_calls`: every `Name` load and `Attribute` access (so a
    base class, a type annotation used bare, a decorator, a referenced constant — not
    just call-callees). A nested def owns its own refs, so its subtree is skipped."""
    if isinstance(node, _DEF_TYPES):
        return
    if isinstance(node, ast.Name):
        names.setdefault(node.id, None)
    elif isinstance(node, ast.Attribute):
        names.setdefault(node.attr, None)
    for child in ast.iter_child_nodes(node):
        _collect_refs(child, names)


def _direct_refs(
    node: ast.AST,  # A FunctionDef / AsyncFunctionDef / ClassDef node
) -> List[str]:  # Referenced names in the symbol's own code (dedup, order-preserved)
    """All names a symbol references in its OWN code (excluding nested def bodies).

    Spans the signature surface a body-only call walk misses — decorators, class bases
    + keywords, parameter/return annotations — plus the body's Name/Attribute loads.
    Resolution against the corpus filters locals/builtins, so over-collection is safe."""
    names: "dict[str, None]" = {}
    for dec in getattr(node, "decorator_list", []):
        _collect_refs(dec, names)
    if isinstance(node, ast.ClassDef):
        for base in node.bases:
            _collect_refs(base, names)
        for kw in node.keywords:                       # metaclass= and other class kwargs
            _collect_refs(kw.value, names)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = node.args
        all_args = (list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
                    + ([args.vararg] if args.vararg else [])
                    + ([args.kwarg] if args.kwarg else []))
        for a in all_args:
            if a is not None and a.annotation is not None:
                _collect_refs(a.annotation, names)
        for d in list(args.defaults) + list(args.kw_defaults):  # parameter DEFAULTS reference names too
            if d is not None:
                _collect_refs(d, names)
        if node.returns is not None:
            _collect_refs(node.returns, names)
    for stmt in getattr(node, "body", []):
        _collect_refs(stmt, names)
    return list(names)


def _import_bindings(
    tree: ast.Module,  # The parsed module
) -> "dict[str, list[dict]]":  # {local-name bound in the namespace: its binding descriptor(s)}
    """Map each name a TOP-LEVEL import binds to descriptor(s) emit can regenerate.

    Only module-level imports (a local import inside a function stays in that function's
    verbatim body, so it must NOT be hoisted to the regenerated module import block).
    `import a.b` binds `a`; `import a.b as c` binds `c`; `from m import x [as y]` binds
    `y or x`. The descriptor carries kind/module/imported/alias/level so a faithful
    `import ...` / `from ... import ...` line can be re-emitted and a symbol's used subset
    can travel with it on a move.

    A name maps to a LIST because plain un-aliased submodule imports COEXIST: `import
    urllib.request` + `import urllib.error` both bind `urllib` and both statements are
    live (each initializes a different submodule) — keying one descriptor per name
    silently dropped all but the last (the flip-time import-dedupe bug). Aliased and
    `from` imports rebinding a name genuinely supersede it (Python's last-binding-wins),
    so those still REPLACE the entry."""
    out: "dict[str, list[dict]]" = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                desc = {"name": local, "kind": "import", "module": alias.name,
                        "imported": "", "alias": alias.asname or "", "level": 0}
                existing = out.get(local)
                if (not alias.asname and existing
                        and all(d["kind"] == "import" and not d["alias"] for d in existing)):
                    if not any(d["module"] == alias.name for d in existing):
                        existing.append(desc)
                else:
                    out[local] = [desc]
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                out[local] = [{"name": local, "kind": "from", "module": node.module or "",
                               "imported": alias.name, "alias": alias.asname or "",
                               "level": node.level or 0}]
    return out


def _used_bindings(
    ref_names: List[str],       # Names a symbol (or region) references
    bindings: "dict[str, list[dict]]",  # The module's top-level import-binding table
) -> List[dict]:  # The binding descriptors those refs use (order-preserved, dedup)
    """The subset of `bindings` a set of referenced names actually uses.

    A referenced name pulls in EVERY descriptor bound to it (all coexisting
    `import root.sub` statements — the ref walk sees only `root`, so which submodule
    the symbol touches is unknowable; carrying all of them is the faithful answer)."""
    out: List[dict] = []
    seen: set = set()
    for r in ref_names:
        for b in bindings.get(r, ()):
            k = (b.get("kind"), b.get("level", 0), b.get("module", ""),
                 b.get("imported", ""), b.get("alias", ""))
            if k not in seen:
                seen.add(k)
                out.append(b)
    return out


def _extract_symbols(
    body: List[ast.stmt],   # A module/class/function body
    bindings: "dict[str, dict]",  # The module's top-level import-binding table (for per-symbol used imports)
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
            fp, fpa = "", ""
        else:
            kind = "method" if in_class else "function"
            fp, fpa = _first_param(node)
        refs = _direct_refs(node)
        out.append(ParsedSymbol(
            qualname=qual,
            name=node.name,
            kind=kind,
            lineno=node.lineno,
            docstring=_docstring_first_line(node),
            decorators=[d for d in (_decorator_name(x) for x in node.decorator_list) if d],
            calls=_direct_calls(node),
            refs=refs,
            import_bindings=_used_bindings(refs, bindings),
            children=_extract_symbols(node.body, bindings, parent_qual=qual,
                                      in_class=isinstance(node, ast.ClassDef)),
            first_param=fp,
            first_param_annotation=fpa,
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
    bindings = _import_bindings(tree)
    # Imports used by module-level (non-def) code — constants, __all__, an `if __main__`.
    mod_names: "dict[str, None]" = {}
    for stmt in tree.body:
        if not isinstance(stmt, _DEF_TYPES):
            _collect_refs(stmt, mod_names)
    return ParsedModule(
        docstring=_docstring_first_line(tree),
        imports=_module_imports(tree),
        symbols=_extract_symbols(tree.body, bindings),
        import_bindings=bindings,
        module_used_bindings=_used_bindings(list(mod_names), bindings),
    )


def monkeypatch_assignments(
    text: str,  # Module / cell source text
) -> List["tuple[str, str, str]"]:  # (class_name, attr_name, value_func_name) per top-level `Class.attr = func`
    """Top-level monkey-patch assignments: `Class.method = func` (the incremental-class idiom).

    The nbdev/notebook pattern (e.g. `JobQueue.submit = submit`) that reattaches a
    free function as a class method in a later cell — opaque to the AST symbol walk, so
    surfaced here for the compositor to rebuild the true class->method structure. Only
    `Attribute(Name) = Name` top-level assigns are matched (precision over recall)."""
    out: List["tuple[str, str, str]"] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Name):
            continue
        func = node.value.id
        for tgt in node.targets:
            if (isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name)):
                out.append((tgt.value.id, tgt.attr, func))
    return out


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
