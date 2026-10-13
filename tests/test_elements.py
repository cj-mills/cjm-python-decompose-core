"""The element source unit: decompose a module into elements, compose it back (abfc2829 (1); d26e00f9; 3e155cd6)."""

import pytest
from cjm_python_decompose_core.elements import (compose_elements, compose_module,
                                                decompose_elements, lift_imports, unresolved_names)
from cjm_python_decompose_core.emit import render_import_block, sibling_modules

SRC = '''"""Module docstring."""
import os


class Store:
    """A store.

    Long enough to span lines.
    """

    name: str = "s"
    size: int = 0

    # --- Lifecycle ---

    def open(self):
        return os.getpid()
        # trails the body: belongs to open

    def close(self): pass
    def flush(self): pass

    class Inner:
        x = 1

        def get(self):
            return """
literal at column 0
"""


def free():
    return 1
'''


def test_round_trip_is_byte_equal():
    assert compose_elements(decompose_elements(SRC)) == SRC


def test_members_are_elements_with_depth_parent_and_qualname():
    els = decompose_elements(SRC)
    shape = [(e.kind, e.depth, e.qualname, els[e.parent].qualname if e.parent is not None else None)
             for e in els]
    assert shape == [
        ("text", 0, "", None),
        ("symbol", 0, "Store", None),
        ("text", 1, "", "Store"),             # the fields and the free banner: one text run
        ("symbol", 1, "Store.open", "Store"),
        ("symbol", 1, "Store.close", "Store"),
        ("symbol", 1, "Store.flush", "Store"),
        ("symbol", 1, "Store.Inner", "Store"),
        ("text", 2, "", "Store.Inner"),
        ("symbol", 2, "Store.Inner.get", "Store.Inner"),
        ("symbol", 0, "free", None),
    ]


def test_a_class_holds_only_its_own_text():
    store = decompose_elements(SRC)[1]
    assert store.text.startswith("class Store:") and store.text.rstrip().endswith('"""')
    assert "def open" not in store.text


def test_member_text_sits_at_depth_zero_and_keeps_its_trailing_comment():
    opened = next(e for e in decompose_elements(SRC) if e.qualname == "Store.open")
    assert opened.text == ("def open(self):\n    return os.getpid()\n"
                           "    # trails the body: belongs to open")


def test_a_string_literal_line_is_never_reindented():
    get = next(e for e in decompose_elements(SRC) if e.qualname == "Store.Inner.get")
    assert "\nliteral at column 0\n" in get.text
    assert get.text.startswith("def get(self):\n    return")


def test_seams_are_derived():
    loose = SRC.replace('    """\n\n    name', '    """\n    name').replace(
        "        x = 1\n\n        def get", "        x = 1\n\n\n        def get")
    assert loose != SRC
    assert compose_elements(decompose_elements(loose)) == SRC


def test_no_blank_line_under_a_bare_header():
    src = "class A(Base):\n\n    x = 1\n\n    def f(self):\n        return 1\n"
    assert compose_elements(decompose_elements(src)) == src.replace("Base):\n\n", "Base):\n")


def test_a_body_on_the_header_line_is_a_leaf():
    els = decompose_elements("class E(Exception): pass\n")
    assert [(e.kind, e.qualname) for e in els] == [("symbol", "E")]


def test_a_code_line_shallower_than_its_member_is_refused():
    with pytest.raises(ValueError, match="shallower"):
        decompose_elements("class A:\n    def f(self):\n        x = [\n1]\n        return x\n")


MOD = '''"""Tests of a store."""

import os
import sys

import pytest

from _helpers import make_store
from conftest import tmp_store

pytestmark = pytest.mark.slow


class FakeDeps:
    name = "fake"

    def path(self):
        return os.getcwd()


def test_open(tmp_store):
    assert make_store(tmp_store)
'''


def test_lift_gives_each_binding_to_the_elements_naming_it():
    lifted = lift_imports(MOD)
    by = {(e.kind, e.qualname or e.text.split("\\n")[0]): sorted(b["name"] for b in e.bindings)
          for e in lifted.elements}
    assert by[("text", "pytestmark = pytest.mark.slow")] == ["pytest"]
    assert by[("symbol", "FakeDeps.path")] == ["os"]
    assert by[("symbol", "test_open")] == ["make_store", "tmp_store"]  # a fixture claimed by parameter
    assert by[("imports", "")] == ["sys"]  # no element names it: unclaimed, kept on the imports element
    assert [e.kind for e in lifted.elements][:2] == ["text", "imports"]  # the derived slot: after the docstring


def test_compose_renders_the_block_with_a_local_section_and_lift_reproduces_the_elements():
    lifted = lift_imports(MOD)
    composed = compose_module(lifted.elements, frozenset({"_helpers", "conftest"}))
    assert composed == MOD  # the author's grouping is the derived rule: stdlib, third-party, local
    again = lift_imports(composed)
    assert [(e.kind, e.depth, e.parent, e.text, e.bindings) for e in again.elements] == \
           [(e.kind, e.depth, e.parent, e.text, e.bindings) for e in lifted.elements]


def test_without_siblings_the_local_imports_sort_as_third_party():
    composed = compose_module(lift_imports(MOD).elements)
    assert "import pytest\nfrom _helpers import make_store\nfrom conftest import tmp_store\n" in composed


def test_an_import_after_a_statement_stays_verbatim_in_source_order():
    src = ('import os\n\nos.environ.setdefault("QT_QPA_PLATFORM", "offscreen")\n'
           'from PySide6.QtWidgets import QApplication\n\n\ndef test_app():\n    return QApplication\n')
    lifted = lift_imports(src)
    texts = [e.text for e in lifted.elements if e.kind == "text"]
    assert texts == ['os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")\n'
                     'from PySide6.QtWidgets import QApplication']
    assert compose_module(lifted.elements) == src


def test_the_lift_reports_which_regions_it_empties():
    lifted = lift_imports(MOD)
    # regions: 0 docstring, 1-3 the three import groups, 4 pytestmark, ...
    assert lifted.imports_origin == 1 and lifted.emptied == [1, 2, 3]
    assert lifted.origins[0] == 0 and lifted.origins[2] == 4


def test_sibling_modules_only_outside_a_package():
    paths = {"tests/test_a.py", "tests/conftest.py", "tests/_helpers.py", "tests/util/__init__.py",
             "pkg/__init__.py", "pkg/platform.py", "pkg/config.py"}
    assert sibling_modules("tests/test_a.py", paths) == {"conftest", "_helpers", "util"}
    assert sibling_modules("pkg/config.py", paths) == frozenset()  # inside a package: `import platform` is the stdlib's


def test_a_sibling_outranks_the_stdlib_name_it_shadows():
    b = [{"name": "platform", "kind": "import", "module": "platform", "imported": "", "alias": "", "level": 0}]
    assert render_import_block(b, frozenset({"platform"})) == "import platform"
    two = b + [{"name": "os", "kind": "import", "module": "os", "imported": "", "alias": "", "level": 0}]
    assert render_import_block(two, frozenset({"platform"})) == "import os\n\nimport platform"


def test_unresolved_names_reads_every_scope_against_the_module_bindings():
    text = (
        "import os\n"
        "try:\n    import yaml\nexcept ImportError:\n    yaml = None\n"
        "LIMIT = 1\n\n\n"
        "def run(p, *a):\n    global STATE\n    STATE = 2\n"
        "    def inner():\n        return p + gone\n"
        "    return os.sep, yaml, LIMIT, STATE, inner, [q for q in a if q in missing], print, __file__\n\n\n"
        "class Fake(Base):\n    size = LIMIT\n\n    def m(self):\n        return attr\n\n\n"
        "assert other\n")
    assert unresolved_names(text) == {"gone", "missing", "Base", "attr", "other"}
    assert unresolved_names("import os\n\n\ndef f():\n    return os\n") == set()
    assert unresolved_names("from x import *\n\n\ndef f():\n    return y\n") is None  # unknowable


def test_a_property_accessor_chain_is_one_symbol_element():
    text = ("class Form:\n    @property\n    def row(self) -> int:\n        return self._row\n\n"
            "    @row.setter\n    def row(self, i: int) -> None:\n        self._row = i\n\n"
            "    def reset(self):\n        self.row = 0\n")
    els = decompose_elements(text)
    assert [(e.kind, e.qualname) for e in els] == [("symbol", "Form"), ("symbol", "Form.row"),
                                                   ("symbol", "Form.reset")]
    assert els[1].text.startswith("@property\n") and "\n\n@row.setter\n" in els[1].text
    assert compose_elements(els) == text


def test_two_definitions_of_one_qualname_are_refused_by_name():
    with pytest.raises(ValueError, match="two definitions of Form.row"):
        decompose_elements("class Form:\n    def row(self):\n        return 1\n\n    def row(self):\n        return 2\n")
    with pytest.raises(ValueError, match="two definitions of f "):
        decompose_elements("def f():\n    return 1\n\n\ndef f():\n    return 2\n")
    with pytest.raises(ValueError, match="two definitions of Form.row"):  # a setter not after its getter
        decompose_elements("class Form:\n    @property\n    def row(self):\n        return 1\n\n"
                           "    x = 1\n\n    @row.setter\n    def row(self, i):\n        pass\n")
