"""Imports-as-projection: deriving a module's canonical import block from bindings."""

from cjm_python_decompose_core.emit import (emit_module_from_nodes, module_used_bindings,
                                            render_binding, render_import_block)
from cjm_python_decompose_core.extract import decompose_text
from cjm_python_decompose_core.parse import parse_module


def _b(name, kind, module, imported="", alias="", level=0):
    return {"name": name, "kind": kind, "module": module,
            "imported": imported, "alias": alias, "level": level}


def test_render_binding_forms():
    assert render_binding(_b("os", "import", "os")) == "import os"
    assert render_binding(_b("c", "import", "a.b", alias="c")) == "import a.b as c"
    assert render_binding(_b("Path", "from", "pathlib", "Path")) == "from pathlib import Path"
    assert render_binding(_b("h", "from", "util", "helper", "h", 1)) == "from .util import helper as h"
    assert render_binding(_b("sib", "from", "", "sib", level=1)) == "from . import sib"


def test_render_import_block_orders_dedups_and_groups():
    bindings = [_b("Path", "from", "pathlib", "Path"),
                _b("h", "from", "util", "helper", "h", 1),
                _b("np", "import", "numpy", alias="np"),
                _b("os", "import", "os"),
                _b("os", "import", "os")]                 # duplicate -> collapsed
    assert render_import_block(bindings) == (
        "import os\n"                                     # stdlib section: `import` first
        "from pathlib import Path\n"                      # then its `from` imports
        "\n"
        "import numpy as np\n"                            # third-party section
        "\n"
        "from .util import helper as h")                  # relative section


def test_render_import_block_wraps_long_from_lines_in_aligned_parens():
    names = [f"very_long_symbol_name_{i:02d}" for i in range(8)]
    bindings = [_b(n, "from", "identity", n, level=1) for n in names]
    block = render_import_block(bindings)
    lines = block.splitlines()
    assert lines[0].startswith("from .identity import (") and lines[-1].endswith(")")
    assert all(len(ln) <= 100 for ln in lines)
    indent = " " * len("from .identity import (")
    assert all(ln.startswith(indent) for ln in lines[1:])
    # The wrapped block round-trips: parsing it back yields the same import set.
    compile(block, "m.py", "exec")


def test_derived_block_is_faithful_and_prunes_dead_imports():
    src = ("import os\n"
           "from pathlib import Path\n"
           "from typing import List\n"                    # never used -> pruned
           "\n\n"
           "def f(p: Path):\n"
           "    return os.fspath(p)\n")
    m = parse_module(src)
    syms = [{"properties": {"import_bindings": s.import_bindings}} for s in m.symbols]
    derived = render_import_block(
        module_used_bindings(syms, {"properties": {"import_bindings": m.module_used_bindings}}))
    assert "import os" in derived and "from pathlib import Path" in derived
    assert "typing" not in derived                        # unused import auto-pruned


def test_emit_module_derive_imports_prunes_dead_and_keeps_bodies():
    src = ("import os\n"
           "from typing import List, Dict\n"              # Dict unused -> pruned; List used
           "from .util import helper\n"                   # unused -> pruned
           "\n\n"
           "def f(xs: List) -> str:\n"
           "    return os.linesep.join(xs)\n")
    d = decompose_text("pkg", "pkg/m.py", "/tmp/m.py", src)
    nodes = [s.to_graph_node() for s in d.symbols] + [t.to_graph_node() for t in d.texts]
    emitted = emit_module_from_nodes(nodes, module_node=d.module.to_graph_node(), derive_imports=True)
    assert "import os" in emitted and "from typing import List" in emitted   # used imports kept
    assert "Dict" not in emitted and "helper" not in emitted                 # dead imports pruned
    assert "def f(xs: List) -> str:" in emitted and "os.linesep.join(xs)" in emitted  # body verbatim
    compile(emitted, "m.py", "exec")                                          # valid Python


def test_emit_module_default_is_verbatim_not_derived():
    # the default path stays byte-exact (the flip is opt-in via derive_imports).
    src = "import os\nfrom typing import Dict\n\n\ndef f():\n    return os.getpid()\n"
    d = decompose_text("pkg", "pkg/m.py", "/tmp/m.py", src)
    nodes = [s.to_graph_node() for s in d.symbols] + [t.to_graph_node() for t in d.texts]
    assert emit_module_from_nodes(nodes) == src           # unused Dict kept (verbatim, no pruning)


def test_parameter_default_reference_is_not_pruned():
    # A name used ONLY as a parameter DEFAULT is a real reference — pruning its
    # import would raise NameError at def-evaluation time (the serve.py near-miss).
    src = ("from .config import DEFAULT_DIR\n"
           "\n\n"
           "def serve(path: str = DEFAULT_DIR):\n"
           "    return path\n")
    d = decompose_text("pkg", "pkg/m.py", "/tmp/m.py", src)
    nodes = [s.to_graph_node() for s in d.symbols] + [t.to_graph_node() for t in d.texts]
    emitted = emit_module_from_nodes(nodes, module_node=d.module.to_graph_node(), derive_imports=True)
    assert "from .config import DEFAULT_DIR" in emitted


def test_docstring_lines_starting_with_from_survive_derive():
    # A module-docstring LINE beginning with `from ` is prose, not an import — the
    # AST-located strip must keep it (the devgraph.py/runtime.py near-miss).
    src = ('"""Build things\n'
           "from each pyproject) into the lists that extend_graph commits.\n"
           'import-shaped prose line too.\n'
           '"""\n'
           "import os\n"
           "\n\n"
           "def f():\n"
           "    return os.getpid()\n")
    d = decompose_text("pkg", "pkg/m.py", "/tmp/m.py", src)
    nodes = [s.to_graph_node() for s in d.symbols] + [t.to_graph_node() for t in d.texts]
    emitted = emit_module_from_nodes(nodes, module_node=d.module.to_graph_node(), derive_imports=True)
    assert "from each pyproject) into the lists" in emitted
    assert "import-shaped prose line too." in emitted
    assert "import os" in emitted
    compile(emitted, "m.py", "exec")


def test_coexisting_submodule_imports_both_survive_round_trip():
    """import urllib.request + import urllib.error both bind `urllib` and both are
    live — the emit must carry BOTH (regression: the one-descriptor-per-name table
    kept only the last, silently dropping a used import at flip time)."""
    text = (
        "import urllib.error\n"
        "import urllib.request\n"
        "\n"
        "\n"
        "def fetch(url):\n"
        "    try:\n"
        "        return urllib.request.urlopen(url)\n"
        "    except urllib.error.URLError:\n"
        "        return None\n"
    )
    d = decompose_text("pkg", "pkg/m.py", "/tmp/m.py", text)
    nodes = [s.to_graph_node() for s in d.symbols] + [x.to_graph_node() for x in d.texts]
    emitted = emit_module_from_nodes(nodes, module_node=d.module.to_graph_node(),
                                     derive_imports=True)
    assert "import urllib.error" in emitted
    assert "import urllib.request" in emitted
    compile(emitted, "m.py", "exec")


def test_rebinding_imports_still_supersede():
    """Aliased / from-imports rebinding a name follow Python last-binding-wins —
    only the LIVE binding is emitted."""
    text = (
        "from json import dumps\n"
        "from simplejson import dumps\n"
        "import numpy as np\n"
        "import numpy.typing as np\n"
        "\n"
        "\n"
        "def f(x):\n"
        "    return dumps(x), np\n"
    )
    d = decompose_text("pkg", "pkg/m.py", "/tmp/m.py", text)
    nodes = [s.to_graph_node() for s in d.symbols] + [x.to_graph_node() for x in d.texts]
    emitted = emit_module_from_nodes(nodes, module_node=d.module.to_graph_node(),
                                     derive_imports=True)
    assert "from simplejson import dumps" in emitted
    assert "from json import dumps" not in emitted
    assert "import numpy.typing as np" in emitted
    assert emitted.count("import numpy") == 1


def test_same_module_imported_twice_dedupes():
    """A literally duplicated plain import collapses to one statement."""
    text = (
        "import os\n"
        "import os\n"
        "\n"
        "\n"
        "def f():\n"
        "    return os.getcwd()\n"
    )
    d = decompose_text("pkg", "pkg/m.py", "/tmp/m.py", text)
    nodes = [s.to_graph_node() for s in d.symbols] + [x.to_graph_node() for x in d.texts]
    emitted = emit_module_from_nodes(nodes, module_node=d.module.to_graph_node(),
                                     derive_imports=True)
    assert emitted.count("import os") == 1
