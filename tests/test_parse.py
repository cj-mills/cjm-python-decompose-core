"""Schema-free Python parsing: docstrings, imports, the symbol tree, and calls."""

import pytest

from cjm_python_decompose_core.parse import (ParsedModule, iter_symbols, parse_module)

SRC = '''"""Module docstring first line.

More detail on a later line.
"""

import os
import a.b.c as abc
from .identity import note_node_id
from cjm_dev_graph_schema import nodes
from . import sibling


def top_level(x):
    """A top-level function."""
    note_node_id(x)
    return helper(x)


def helper(x):
    return x + 1


@dataclass
class Widget:
    """A widget."""

    name: str

    @property
    def label(self):
        """The display label."""
        return format_label(self.name)

    def render(self):
        return self.label + draw()
'''


@pytest.fixture
def parsed() -> ParsedModule:
    return parse_module(SRC)


def test_module_docstring_first_line(parsed):
    assert parsed.docstring == "Module docstring first line."


def test_imports_collected_with_relative_and_submodule_forms(parsed):
    imp = parsed.imports
    assert "os" in imp
    assert "a.b.c" in imp                       # `import a.b.c as abc` -> the dotted module
    assert ".identity" in imp                   # relative module kept with leading dot
    assert ".identity.note_node_id" in imp      # plus the from-imported name (resolver tries both)
    assert "cjm_dev_graph_schema" in imp
    assert "cjm_dev_graph_schema.nodes" in imp  # `from pkg import submodule` -> the submodule
    assert "." in imp                           # `from . import sibling` -> the current package
    assert ".sibling" in imp


def test_top_level_symbols(parsed):
    names = {s.qualname: s for s in parsed.symbols}
    assert set(names) == {"top_level", "helper", "Widget"}
    assert names["top_level"].kind == "function"
    assert names["Widget"].kind == "class"
    assert names["top_level"].docstring == "A top-level function."


def test_function_calls_are_direct_only(parsed):
    top = next(s for s in parsed.symbols if s.qualname == "top_level")
    assert set(top.calls) == {"note_node_id", "helper"}


def test_class_methods_are_children_with_method_kind(parsed):
    widget = next(s for s in parsed.symbols if s.qualname == "Widget")
    assert widget.decorators == ["dataclass"]
    child_quals = {c.qualname: c for c in widget.children}
    assert set(child_quals) == {"Widget.label", "Widget.render"}
    assert child_quals["Widget.label"].kind == "method"
    assert child_quals["Widget.label"].decorators == ["property"]
    assert child_quals["Widget.label"].docstring == "The display label."


def test_method_calls(parsed):
    widget = next(s for s in parsed.symbols if s.qualname == "Widget")
    label = next(c for c in widget.children if c.qualname == "Widget.label")
    render = next(c for c in widget.children if c.qualname == "Widget.render")
    assert "format_label" in label.calls
    assert "draw" in render.calls  # `self.label` is an attribute access, not a call


REF_SRC = '''
from mod import Base, MyType, Ret, thing


class Sub(Base):
    field: MyType


def f(x: MyType) -> Ret:
    return thing(x)
'''


def test_refs_are_superset_of_calls_capturing_bases_and_annotations():
    m = parse_module(REF_SRC)
    sub = next(s for s in m.symbols if s.qualname == "Sub")
    f = next(s for s in m.symbols if s.qualname == "f")
    # base class + class-level annotation are REFERENCES but not CALLS.
    assert "Base" in sub.refs and "MyType" in sub.refs
    assert "Base" not in sub.calls
    # function param/return annotations are refs; only the actual call is a call.
    assert {"MyType", "Ret"} <= set(f.refs)
    assert "thing" in f.calls and "thing" in f.refs
    assert "MyType" not in f.calls
    assert set(f.calls) <= set(f.refs)              # refs is a strict superset of calls


BIND_SRC = '''
import os
from pathlib import Path
from .util import helper as h

CONST = os.getcwd()


def f(p: Path):
    return h(p)
'''


def test_import_bindings_per_symbol_and_module_level():
    m = parse_module(BIND_SRC)
    # the module's binding table maps each bound LOCAL name.
    assert set(m.import_bindings) == {"os", "Path", "h"}
    assert m.import_bindings["h"] == [{"name": "h", "kind": "from", "module": "util",
                                       "imported": "helper", "alias": "h", "level": 1}]  # dots from `level`
    # f uses Path (annotation) + h (call) -> those two bindings travel with it; not os.
    f = next(s for s in m.symbols if s.qualname == "f")
    used = {b["name"] for b in f.import_bindings}
    assert used == {"Path", "h"}
    # module-level code (`CONST = os.getcwd()`) carries the os binding.
    assert {b["name"] for b in m.module_used_bindings} == {"os"}


def test_local_import_not_hoisted_to_bindings():
    src = "def f():\n    import json\n    return json.dumps({})\n"
    m = parse_module(src)
    assert m.import_bindings == {}                  # a function-local import is NOT a module binding
    assert m.symbols[0].import_bindings == []


def test_iter_symbols_flattens_parents_before_children(parsed):
    quals = [s.qualname for s in iter_symbols(parsed)]
    assert quals.index("Widget") < quals.index("Widget.label")
    assert set(quals) == {"top_level", "helper", "Widget", "Widget.label", "Widget.render"}


def test_nested_function_is_its_own_symbol_with_own_calls():
    src = (
        "def outer():\n"
        "    a()\n"
        "    def inner():\n"
        "        b()\n"
        "    return inner\n"
    )
    parsed = parse_module(src)
    outer = parsed.symbols[0]
    assert outer.calls == ["a"]                 # inner's call is NOT attributed to outer
    inner = outer.children[0]
    assert inner.qualname == "outer.inner" and inner.kind == "function"
    assert inner.calls == ["b"]


def test_empty_and_docstringless_module():
    parsed = parse_module("x = 1\n")
    assert parsed.docstring == ""
    assert parsed.symbols == []


def test_syntax_error_propagates():
    with pytest.raises(SyntaxError):
        parse_module("def (:\n")
