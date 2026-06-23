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
