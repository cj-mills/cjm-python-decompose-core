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
"""

import ast
import io
import tokenize
from dataclasses import dataclass
from typing import List, Optional, Tuple

from cjm_python_decompose_core.parse import emit_regions, parse_regions, SourceRegion

INDENT = 4  # One depth level: the corpus's only member indentation (492 of 492 classes)


@dataclass
class CodeElement:
    """One element of a module, its text at depth 0."""

    kind: str                     # "symbol" (a def / class) | "text" (statements and comments)
    text: str                     # The element's OWN text, dedented to depth 0 (no trailing newline)
    depth: int = 0                # 0 = top level; a class member sits one deeper than its class
    parent: Optional[int] = None  # Index of the enclosing class element in the list (None at top level)
    qualname: str = ""            # Symbols: dotted through enclosing classes ("Cls.method")
    symbol_kind: str = ""         # Symbols: "function" | "class"


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
    regions = [SourceRegion(kind=e.kind, text=_compose(elements, i, children), start_line=0, end_line=0)
               for i, e in enumerate(elements) if e.parent is None]
    return emit_regions(regions)
