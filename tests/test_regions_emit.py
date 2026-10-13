"""Verbatim region decomposition + canonical emit (the authoring / round-trip substrate)."""

import ast

from cjm_python_decompose_core.emit import emit_module_from_nodes
from cjm_python_decompose_core.extract import decompose_text
from cjm_python_decompose_core.parse import emit_regions, parse_regions, source_lines

SRC = '''"""Module docstring."""
import os
import sys

CONST = 1


@deco
def alpha():
    """Alpha."""
    return os.getpid()


# leads the class
class Thing:
    def method(self):
        return sys.argv


if __name__ == "__main__":
    alpha()
'''


def test_parse_regions_orders_symbols_and_text():
    regions = parse_regions(SRC)
    kinds = [(r.kind, r.qualname or r.region_key) for r in regions]
    # text(docstring+imports) | text(CONST, split by the blank line) | alpha | Thing | text(__main__)
    assert [k for k, _ in kinds] == ["text", "text", "symbol", "symbol", "text"]
    assert kinds[2][1] == "alpha" and kinds[3][1] == "Thing"


def test_symbol_body_is_verbatim_with_decorators_and_leading_comments():
    regions = {r.qualname: r for r in parse_regions(SRC) if r.kind == "symbol"}
    assert regions["alpha"].text.startswith("@deco\ndef alpha():")
    # The contiguous comment immediately above a def attaches to its region.
    assert regions["Thing"].text.startswith("# leads the class\nclass Thing:")


def test_emit_regions_round_trips_pep8_byte_exact():
    assert emit_regions(parse_regions(SRC)) == SRC


def test_emit_is_ast_equal_and_seam_canonical_on_messy_input():
    messy = "import os\nx=1\ndef a():\n    return os\ndef b():\n    return 2\n"
    emitted = emit_regions(parse_regions(messy))
    assert ast.dump(ast.parse(messy)) == ast.dump(ast.parse(emitted))
    # graph owns the SEAMS: two blank lines now separate the top-level defs.
    assert "\n\n\ndef a():" in emitted and "\n\n\ndef b():" in emitted


def test_decompose_attaches_body_and_order_to_top_level_symbols():
    d = decompose_text("k", "m.py", "m.py", SRC)
    tops = {s.qualname: s for s in d.symbols if s.order_index is not None}
    assert set(tops) == {"alpha", "Thing"}
    assert tops["alpha"].body.startswith("@deco\ndef alpha():")
    assert tops["alpha"].body_hash and tops["Thing"].order_index > tops["alpha"].order_index
    # a NESTED method carries no independent body in v1 (coarse: class = one block)
    method = next(s for s in d.symbols if s.qualname == "Thing.method")
    assert method.body == "" and method.order_index is None


def test_decompose_emit_round_trip_from_nodes():
    d = decompose_text("k", "m.py", "m.py", SRC)
    assert emit_module_from_nodes(list(d.symbols) + list(d.texts)) == SRC


def test_codetext_regions_cover_the_non_def_source():
    d = decompose_text("k", "m.py", "m.py", SRC)
    kinds = {t.kind for t in d.texts}
    # first region leads with the docstring; CONST + __main__ regions are plain code.
    assert "docstring" in kinds and "code" in kinds
    joined = "\n".join(t.text for t in d.texts)
    assert "import os" in joined and "CONST = 1" in joined and '__name__ == "__main__"' in joined


def test_a_raw_line_separator_in_a_literal_never_moves_a_region_boundary():
    # str.splitlines breaks at U+2029 / U+2028 / \x0c ..., the tokenizer does not: a raw one in a
    # literal must not shift the AST's line numbers off the text (design detail ed20aa51).
    text = ('class Bar:\n    def find(self, s):\n        if "\u2029" in s:\n            s = s.strip()\n\n\n'
            "        return s\n\n\nX = 1\n")
    assert [(r.kind, r.text.split("\n")[-1]) for r in parse_regions(text)] == [
        ("symbol", "        return s"), ("text", "X = 1")]
    assert source_lines("a\u2029b\x0cc\r\nd\n") == ["a\u2029b\x0cc", "d"]
    assert emit_regions(parse_regions(text)) == text
