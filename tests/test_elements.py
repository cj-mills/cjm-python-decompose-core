"""The element source unit: decompose a module into elements, compose it back (abfc2829 (1); d26e00f9; 3e155cd6)."""

import pytest

from cjm_python_decompose_core.elements import compose_elements, decompose_elements

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
