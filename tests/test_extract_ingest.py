"""Extract (parse -> schema nodes) + ingest (corpus -> graph elements) binding."""

from cjm_dev_graph_schema.identity import entity_node_id
from cjm_dev_graph_schema.vocab import DevNodeKinds, DevRelations

from cjm_python_decompose_core.extract import (decompose_text, import_name_for,
                                               module_path_for)
from cjm_python_decompose_core.ingest import (build_call_map, build_import_map,
                                              corpus_graph_elements, resolve_import)

MOD_A = '''"""Module A docstring."""

from .b import shared_helper


def alpha():
    """Alpha does a thing."""
    return shared_helper()


class Thing:
    def method_one(self):
        return alpha()
'''

MOD_B = '''"""Module B docstring."""


def shared_helper():
    return 1
'''


def _corpus():
    a = decompose_text("demo-repo", "demo/a.py", "/abs/demo/a.py", MOD_A,
                       import_name="demo.a")
    b = decompose_text("demo-repo", "demo/b.py", "/abs/demo/b.py", MOD_B,
                       import_name="demo.b")
    return a, b


# --- path/import-name helpers ---

def test_module_path_and_import_name():
    assert module_path_for("/repo/pkg/sub/mod.py", "/repo") == "pkg/sub/mod.py"
    assert import_name_for("pkg/sub/mod.py") == "pkg.sub.mod"
    assert import_name_for("pkg/__init__.py") == "pkg"


# --- extract: nodes + local edges ---

def test_decompose_text_builds_module_and_symbols():
    a, _ = _corpus()
    assert a.module.to_graph_node()["label"] == DevNodeKinds.CODE_MODULE
    assert a.module.docstring == "Module A docstring."
    quals = {s.qualname for s in a.symbols}
    assert quals == {"alpha", "Thing", "Thing.method_one"}


def test_local_edges_about_repo_and_defines_nesting():
    a, _ = _corpus()
    about = [e for e in a.local_edges if e["relation_type"] == DevRelations.ABOUT]
    assert len(about) == 1
    assert about[0]["target_id"] == entity_node_id("repo", "demo-repo")

    defines = [e for e in a.local_edges if e["relation_type"] == DevRelations.DEFINES]
    sym = {s.qualname: s.id for s in a.symbols}
    pairs = {(e["source_id"], e["target_id"]) for e in defines}
    # module -> top-level alpha + Thing; Thing -> method_one.
    assert (a.module.id, sym["alpha"]) in pairs
    assert (a.module.id, sym["Thing"]) in pairs
    assert (sym["Thing"], sym["Thing.method_one"]) in pairs


# --- ingest: corpus maps + resolved edges ---

def test_import_map_and_call_map():
    a, b = _corpus()
    imap = build_import_map([a, b])
    assert imap["demo.a"] == a.module.id and imap["demo.b"] == b.module.id
    cmap = build_call_map([a, b])
    # shared_helper + alpha + method_one are unambiguous; resolvable as call targets.
    assert "shared_helper" in cmap and "alpha" in cmap


def test_resolve_import_relative_and_absolute():
    # absolute passes through
    assert resolve_import("os.path", "demo.a", False) == "os.path"
    # `.b` from module demo.a (not a package) -> demo.b
    assert resolve_import(".b", "demo.a", False) == "demo.b"
    # `.b` from package demo (__init__) -> demo.b
    assert resolve_import(".b", "demo", True) == "demo.b"
    # `from . import x` -> the importer's package
    assert resolve_import(".", "demo.a", False) == "demo"
    # `..sib` from demo.a climbs to root level -> a top-level sibling "sib"
    assert resolve_import("..sib", "demo.a", False) == "sib"
    # climbing ABOVE the top package is unresolvable (more dots than package depth)
    assert resolve_import("...x", "demo.a", False) is None


def test_corpus_imports_and_calls_resolve_intra_corpus():
    a, b = _corpus()
    nodes, edges = corpus_graph_elements([a, b])
    by_label: dict = {}
    for n in nodes:
        by_label[n["label"]] = by_label.get(n["label"], 0) + 1
    # 2 modules + 4 symbols (alpha, shared_helper, Thing, Thing.method_one) + the non-def
    # CodeText regions (imports/constants) now emitted as the verbatim round-trip substrate.
    assert by_label["CodeModule"] == 2
    assert by_label["CodeSymbol"] == 4
    assert by_label.get("CodeText", 0) >= 1

    imports = [e for e in edges if e["relation_type"] == DevRelations.IMPORTS]
    # a imports .b -> resolves to module b.
    assert any(e["source_id"] == a.module.id and e["target_id"] == b.module.id for e in imports)

    calls = [e for e in edges if e["relation_type"] == DevRelations.CALLS]
    sym = {s.qualname: s.id for s in (*a.symbols, *b.symbols)}
    # alpha() calls shared_helper (cross-module); method_one calls alpha.
    assert (sym["alpha"], sym["shared_helper"]) in {(e["source_id"], e["target_id"]) for e in calls}
    assert (sym["Thing.method_one"], sym["alpha"]) in {(e["source_id"], e["target_id"]) for e in calls}


def test_ingest_is_idempotent_in_ids():
    a, b = _corpus()
    n1, e1 = corpus_graph_elements([a, b])
    n2, e2 = corpus_graph_elements([a, b])
    assert {n["id"] for n in n1} == {n["id"] for n in n2}
    assert {e["id"] for e in e1} == {e["id"] for e in e2}


def test_external_imports_not_minted():
    src = "import os\nfrom collections import OrderedDict\n\ndef f():\n    return os.getpid()\n"
    d = decompose_text("demo-repo", "demo/c.py", "/abs/c.py", src, import_name="demo.c")
    _, edges = corpus_graph_elements([d])
    assert [e for e in edges if e["relation_type"] == DevRelations.IMPORTS] == []
