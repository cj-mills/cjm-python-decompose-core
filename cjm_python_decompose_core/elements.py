"""The element source unit for Python modules (design abfc2829 (1); d26e00f9; 3e155cd6).

A module decomposes into ELEMENTS: its top-level regions (`parse.parse_regions`), and inside a
class -- recursively -- its members. A def or a nested class is one element; a run of class-level
statements and the free comment blocks among them is one text element; a comment indented deeper
than the member level that trails a body belongs to that member. A class element holds only its
OWN text (decorators, leading comments, header, docstring); its members are its children.

Each element's text is held at depth 0: indentation is derived from depth (one level = 4 spaces,
the corpus's only unit) as a heading's level is, so a member's lines are dedented on decompose and
re-indented on compose. A line that continues a multi-line string literal is never touched -- its
whitespace is the string's value. Seams are derived too: at the top level `parse.emit_regions`'
(two blank lines around a def or class, one between text regions); inside a class none under a
bare header, one after a docstring, none between two consecutive one-line defs, one otherwise.

`compose_elements(decompose_elements(text)) == text` for every canonical module: the round trip is
the oracle the element capture is accepted by. Pure and schema-free, like `parse`.

THE IMPORT BLOCK (abfc2829 (2)-(3), ruling 21b8fcca, design detail 6d35c07d (3)): a captured module's
leading run of imports leaves the text -- `lift_imports` gives each binding to every element whose own
text names it (a reference or a parameter: a pytest fixture is requested by parameter name) and puts
the bindings no element claims on ONE `imports` element; `compose_module` renders the union of every
element's bindings as that element's text at its derived slot (after a leading docstring or comment
preamble, else first). The statements from the first non-import onward stay verbatim, imports among
them included: an import after a statement may depend on it (a sys.path change, an environment
setting), so it is never hoisted. `lift_imports(compose_module(m)) == m` is the element regime's
invariant, as the round trip is the snapshot regime's.
"""

import ast
import builtins
import io
import symtable
import tokenize
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from cjm_python_decompose_core.emit import _looks_like_docstring, render_import_block
from cjm_python_decompose_core.parse import (_import_bindings, emit_regions, parse_regions,
                                             SourceRegion)

INDENT = 4  # One depth level: the corpus's only member indentation (492 of 492 classes)
IMPORTS = "imports"  # The kind of a module's one import-block element (its text derived from bindings)


@dataclass
class CodeElement:
    """One element of a module, its text at depth 0."""

    kind: str                     # "symbol" (a def / class) | "text" (statements and comments) | "imports" (the derived import block)
    text: str                     # The element's OWN text, dedented to depth 0 (no trailing newline); an imports element's is derived
    depth: int = 0                # 0 = top level; a class member sits one deeper than its class
    parent: Optional[int] = None  # Index of the enclosing class element in the list (None at top level)
    qualname: str = ""            # Symbols: dotted through enclosing classes ("Cls.method")
    symbol_kind: str = ""         # Symbols: "function" | "class"
    bindings: list = field(default_factory=list)  # The import-binding descriptors the element owns (`lift_imports`)


def string_lines(
    text: str,  # Python source
) -> set:  # 0-based indexes of the lines that continue a multi-line string literal
    """The lines a string literal continues onto -- their whitespace is the string's value."""
    inside, starts = set(), []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.FSTRING_START:
            starts.append(tok.start[0])
        elif tok.type == tokenize.FSTRING_END:
            inside.update(range(starts.pop(), tok.end[0]))
        elif tok.type == tokenize.STRING:
            inside.update(range(tok.start[0], tok.end[0]))
    return inside


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def class_members(
    lines: list,  # The source's lines
    node: ast.ClassDef,  # A class in that source
) -> Optional[Tuple[int, bool, list]]:  # (anchor, doc, [(first, last, one_line_def, member node | None)])
    """A class's members as 0-based inclusive line spans: the class's own text ends at `anchor`,
    `doc` tells whether it holds a docstring, a text member carries None. None when the class has
    no member below its own text (an empty body, or a body on the header line)."""
    body = node.body
    doc = (isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
           and isinstance(body[0].value.value, str))
    members = body[1:] if doc else body
    if not members:
        return None
    first = members[0].decorator_list[0] if getattr(members[0], "decorator_list", None) else members[0]
    if doc:
        anchor = body[0].end_lineno - 1
    else:
        anchor = next((j for j in range(first.lineno - 2, node.lineno - 2, -1)
                       if lines[j].strip() and not _is_comment(lines[j])), None)
    if anchor is None or anchor >= first.lineno - 1:
        return None
    level = members[0].col_offset

    def opens(s, floor):  # the statement's first line, its attached member-level comments included
        ln = (s.decorator_list[0].lineno if getattr(s, "decorator_list", None) else s.lineno) - 1
        while ln - 1 > floor and _is_comment(lines[ln - 1]) and _indent(lines[ln - 1]) == level:
            ln -= 1
        return ln

    defs = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    units, floor = [], anchor
    for s in members:
        start = opens(s, floor)
        is_def = isinstance(s, defs)
        units.append([start, s.end_lineno - 1, is_def, is_def and start == s.end_lineno - 1,
                      s if is_def else None])
        floor = s.end_lineno - 1
    pieces, prev_end = [], anchor
    for i, u in enumerate(units):
        gap = range(prev_end + 1, u[0])
        if i:  # a deeper comment trailing the previous body belongs to it
            last = units[i - 1]
            for j in gap:
                if not lines[j].strip():
                    continue
                if _indent(lines[j]) > level:
                    last[1], last[3] = j, False
                    continue
                break
            gap = range(last[1] + 1, u[0])
        free = [j for j in gap if lines[j].strip()]
        if free:
            pieces.append([free[0], free[-1], False, False, None])
        pieces.append(u)
        prev_end = u[1]
    merged = []
    for p in pieces:  # a run of statements and free comments is one text element
        if not p[2] and merged and not merged[-1][2]:
            merged[-1][1] = p[1]
        else:
            merged.append(list(p))
    return anchor, doc, [(a, b, one, n) for a, b, _, one, n in merged]


def _shift(
    text: str,  # Source at some depth
    by: int,  # Columns to add (> 0) or remove (< 0) on each line outside a string literal
) -> str:
    """Re-indent every non-blank line that does not continue a string literal."""
    keep = string_lines(text)
    out = []
    for i, ln in enumerate(text.split("\n")):
        if i in keep or not ln.strip():
            out.append(ln)
        elif by > 0:
            out.append(" " * by + ln)
        else:
            if ln[:-by].strip():
                raise ValueError(f"line {i + 1} sits shallower than its member level: {ln!r}")
            out.append(ln[-by:])
    return "\n".join(out)


def _split_symbol(
    text: str,  # A def / class region or member at depth 0 (leading comments + decorators included)
    depth: int,  # Its depth
    parent: Optional[int],  # Its enclosing class element
    prefix: str,  # The enclosing classes' dotted qualname ("" at top level)
    out: list,  # The element list being built (pre-order)
) -> None:
    tree = ast.parse(text)
    node = tree.body[-1]
    qualname = f"{prefix}{node.name}"
    kind = "class" if isinstance(node, ast.ClassDef) else "function"
    lines = text.split("\n")
    found = class_members(lines, node) if kind == "class" else None
    if not found:
        out.append(CodeElement("symbol", text, depth, parent, qualname, kind))
        return
    anchor, _doc, members = found
    me = len(out)
    out.append(CodeElement("symbol", "\n".join(lines[:anchor + 1]), depth, parent, qualname, kind))
    for a, b, _one, member in members:
        body = _shift("\n".join(lines[a:b + 1]), -INDENT)
        if member is None:
            out.append(CodeElement("text", body, depth + 1, me))
        else:
            _split_symbol(body, depth + 1, me, f"{qualname}.", out)


def decompose_elements(
    text: str,  # A module's source
) -> List[CodeElement]:  # Its elements in source order (pre-order: a class precedes its members)
    """Decompose a module into elements -- top-level regions, then class members recursively."""
    out: List[CodeElement] = []
    for r in parse_regions(text):
        if r.kind == "symbol":
            _split_symbol(r.text, 0, None, "", out)
        else:
            out.append(CodeElement("text", r.text))
    return out


def _has_docstring(
    own: str,  # A class element's own text (header, possibly a docstring)
) -> bool:
    """Whether a class's own text ends in its docstring (derived, never stored)."""
    body = ast.parse(own + "\n" + " " * INDENT + "pass").body[-1].body
    return (isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str))


def _compose(
    elements: List[CodeElement],  # The module's elements
    i: int,  # The element to compose
    children: dict,  # parent index -> child indexes, in order
) -> str:  # The element with its members, at depth 0
    e = elements[i]
    kids = children.get(i)
    if not kids:
        return e.text
    parts = [e.text]
    if _has_docstring(e.text):
        parts.append("")
    composed = [_compose(elements, k, children) for k in kids]
    one_line = [elements[k].kind == "symbol" and "\n" not in c for k, c in zip(kids, composed)]
    for n, c in enumerate(composed):
        if n and not (one_line[n] and one_line[n - 1]):  # a class with members is never one line
            parts.append("")
        parts.append(_shift(c, INDENT))
    return "\n".join(parts)


def compose_elements(
    elements: List[CodeElement],  # A module's elements (pre-order, parents by index)
) -> str:  # The module's canonical source
    """Compose elements back into a module: members re-indented by depth, every seam derived."""
    children: dict = {}
    for i, e in enumerate(elements):
        if e.parent is not None:
            children.setdefault(e.parent, []).append(i)
    regions = [SourceRegion(kind="symbol" if e.kind == "symbol" else "text",
                            text=_compose(elements, i, children), start_line=0, end_line=0)
               for i, e in enumerate(elements)
               if e.parent is None and not (e.kind == IMPORTS and not e.text)]
    return emit_regions(regions)


def import_slot(
    elements: List[CodeElement],  # A module's elements WITHOUT its imports element (pre-order)
) -> int:  # The list index the imports element takes
    """The import block's derived slot: after a leading docstring or comment preamble, else first --
    `emit_module_from_nodes`' rule, so a captured module keeps the block where the snapshot regime put it."""
    first = next((i for i, e in enumerate(elements) if e.parent is None), None)
    if first is not None and elements[first].kind == "text" and _looks_like_docstring(elements[first].text):
        return first + 1
    return 0


def _parse_own(
    text: str,  # An element's own text at depth 0
) -> ast.Module:
    """Parse an element's own text; a class's own text (header and docstring, its members apart)
    is given a body first."""
    try:
        return ast.parse(text)
    except SyntaxError:
        return ast.parse(text + "\n" + " " * INDENT + "pass")


def element_names(
    text: str,  # An element's own text at depth 0
) -> set:  # Every name it loads, stores or declares as a parameter
    """The names an element's own text uses -- what claims an import binding (abfc2829 (3): a binding
    goes to the elements whose refs or parameters name it). A parameter counts: pytest requests a
    fixture by parameter name. A string (`usefixtures("db")`) names nothing; its import stays unclaimed."""
    out = set()
    for n in ast.walk(_parse_own(text)):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            out.update(n.names)
    return out


def binding_union(
    elements: List[CodeElement],  # A module's elements
) -> list:  # Every binding they own, deduplicated, in element order
    """The union of a module's bindings -- the input the import block renders from."""
    out, seen = [], set()
    for e in elements:
        for b in e.bindings:
            k = (b.get("kind"), b.get("level", 0), b.get("module", ""), b.get("imported", ""),
                 b.get("alias", ""))
            if k not in seen:
                seen.add(k)
                out.append(b)
    return out


def compose_module(
    elements: List[CodeElement],  # A captured module's elements, its imports element among them
    local: frozenset = frozenset(),  # The module's sibling module names (`emit.sibling_modules`)
) -> str:  # The module's source
    """Compose a captured module: the imports element's text is rendered from the union of every
    element's bindings, then the elements compose as `compose_elements`."""
    block = render_import_block(binding_union(elements), local)
    return compose_elements([CodeElement(e.kind, block, e.depth, e.parent, e.qualname, e.symbol_kind,
                                         e.bindings) if e.kind == IMPORTS else e for e in elements])


# Names every module holds without binding them: the interpreter sets them on the module object.
MODULE_NAMES = frozenset({"__annotations__", "__builtins__", "__cached__", "__dict__", "__doc__", "__file__",
                          "__loader__", "__name__", "__package__", "__path__", "__spec__"})


def unresolved_names(
    text: str,  # A module's source
) -> Optional[set]:  # The names it reads that nothing binds; None when a star import makes that unknowable
    """The names a module reads that no module-level binding (an import, an assignment, a def or class,
    a `global` declaration that assigns), builtin or module attribute covers -- in any scope: a name a
    function, class body or comprehension reads from the module (`symtable`'s implicit globals) and a
    name the module body itself reads. The binding check of abfc2829 (2): such a name raises NameError
    when the code runs. A `from x import *` binds names no parse can see, so the check cannot run."""
    if any(isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names) for n in ast.walk(ast.parse(text))):
        return None
    top = symtable.symtable(text, "<module>", "exec")
    syms = top.get_symbols()
    bound = {s.get_name() for s in syms if s.is_assigned() or s.is_imported() or s.is_declared_global()}
    reads: List[str] = [s.get_name() for s in syms if s.is_referenced()]
    tables = list(top.get_children())
    while tables:
        t = tables.pop()
        tables.extend(t.get_children())
        for s in t.get_symbols():
            if s.is_declared_global() and s.is_assigned():
                bound.add(s.get_name())
            elif s.is_global() and not s.is_declared_global() and s.is_referenced():
                reads.append(s.get_name())
    known = bound | set(dir(builtins)) | MODULE_NAMES
    return {n for n in reads if n not in known}


@dataclass
class LiftedModule:
    """A module decomposed in the element regime: its elements (one `imports` element among them,
    its text empty -- derived at compose) and, per top-level text element, the region it came from."""

    elements: List[CodeElement]   # Pre-order; the imports element at `import_slot`
    origins: List[Optional[int]]  # Per element: the index (in `parse_regions(text)`) of the top-level text region it holds content of; None for symbols, members and the imports element
    imports_origin: Optional[int]  # The first import-holding region the lift empties (the imports element takes its identity), else None
    emptied: List[int]            # Import-holding regions the lift empties, `imports_origin` included


def lift_imports(
    text: str,  # A module's source (canonical)
) -> LiftedModule:
    """Decompose a module in the element regime: lift its leading run of imports (after the module
    docstring) into bindings, give each binding to every element whose own text names it, and put
    the rest on the imports element. Statements from the first non-import onward stay verbatim."""
    tree = ast.parse(text)
    body = tree.body
    i = 1 if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
              and isinstance(body[0].value.value, str)) else 0
    run = []
    while i < len(body) and isinstance(body[i], (ast.Import, ast.ImportFrom)):
        run.append(body[i])
        i += 1
    lines = text.split("\n")
    lifted = {ln for s in run for ln in range(s.lineno - 1, s.end_lineno)}
    kept = [n for n in range(len(lines)) if n not in lifted]
    stripped = "\n".join(lines[n] for n in kept)
    table = _import_bindings(ast.Module(body=run, type_ignores=[]))
    before = [r for r in parse_regions(text)]
    after = parse_regions(stripped)
    region_of = {}  # original 0-based line -> original region index
    for k, r in enumerate(before):
        for ln in range(r.start_line - 1, r.end_line):
            region_of[ln] = k
    elements = decompose_elements(stripped)
    origins: List[Optional[int]] = []
    top = iter(after)
    for e in elements:
        if e.parent is None:
            r = next(top)
            origins.append(region_of.get(kept[r.start_line - 1]) if e.kind == "text" else None)
        else:
            origins.append(None)
    holding = sorted({region_of[ln] for ln in lifted})
    keeping = {o for o in origins if o is not None}
    emptied = [k for k in holding if k not in keeping]
    claimed = set()
    for e in elements:
        names = element_names(e.text)
        e.bindings = [b for name, bs in table.items() if name in names for b in bs]
        claimed.update(name for name in table if name in names)
    unclaimed = [b for name, bs in table.items() if name not in claimed for b in bs]
    slot = import_slot(elements)
    imports = CodeElement(IMPORTS, "", bindings=unclaimed)
    shifted = [CodeElement(e.kind, e.text, e.depth,
                           None if e.parent is None else e.parent + (e.parent >= slot),
                           e.qualname, e.symbol_kind, e.bindings) for e in elements]
    shifted.insert(slot, imports)
    origins.insert(slot, None)
    return LiftedModule(shifted, origins, emptied[0] if emptied else None, emptied)
