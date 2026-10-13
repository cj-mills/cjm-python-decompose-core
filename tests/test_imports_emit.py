"""The import block: rendering bindings, and the element regime's composition of it (the union of
the elements' bindings at its derived slot) -- where an import is derived since the verbs emit
verbatim (design detail 25c1fadc, ruling D)."""

from cjm_python_decompose_core.elements import compose_module, IMPORTS, lift_imports, string_reads
from cjm_python_decompose_core.emit import (emit_module_from_nodes, render_binding,
                                            render_import_block)
from cjm_python_decompose_core.extract import decompose_text


def _composed(src):
    """The element regime's composition of a module text."""
    return compose_module(lift_imports(src).elements)


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


def test_emit_module_from_nodes_is_verbatim():
    # emit reassembles the regions as they are: an import no code reads is kept (the element
    # regime decides what drops, at the write).
    src = "import os\nfrom typing import Dict\n\n\ndef f():\n    return os.getpid()\n"
    d = decompose_text("pkg", "pkg/m.py", "/tmp/m.py", src)
    nodes = [s.to_graph_node() for s in d.symbols] + [t.to_graph_node() for t in d.texts]
    assert emit_module_from_nodes(nodes) == src


def _owner(src, name):
    """The elements owning the binding of `name` after the lift ('imports' when none claims it)."""
    return [e.qualname or e.kind for e in lift_imports(src).elements
            if any(b.get("name") == name for b in e.bindings)]


def test_a_parameter_default_or_a_parameter_name_claims_its_binding():
    # A name used ONLY as a parameter DEFAULT is a real reference (NameError at def time otherwise);
    # a parameter NAME is pytest's fixture request.
    src = ("from conftest import db\n\nfrom .config import DEFAULT_DIR\n\n\n"
           "def serve(path: str = DEFAULT_DIR):\n    return path\n\n\n"
           "def test_db(db):\n    assert db\n")
    assert _owner(src, "DEFAULT_DIR") == ["serve"] and _owner(src, "db") == ["test_db"]
    assert _composed(src) == src


def test_string_reads_name_the_fixture_reexport_and_annotation_channels():
    src = ('import pytest\n\n__all__ = ["Path", "helper"]\n\n\n'
           '@pytest.mark.usefixtures("db", "tmp")\n'
           'def test_x(request) -> "Optional[Path]":\n'
           '    x: "Dict" = request.getfixturevalue("cache")\n'
           '    return x\n\n\n'
           'def f(p: "Path") -> None:\n    pass\n')
    reads = set()
    for e in lift_imports(src).elements:
        if e.kind != IMPORTS:
            reads |= string_reads(e.text)
    assert reads == {"Path", "helper", "db", "tmp", "Optional", "cache", "Dict"}
    assert string_reads('x = "not a name at all"') == set()  # a plain string reads nothing
    assert string_reads("pytestmark = pytest.mark.usefixtures('db')") == {"db"}


def test_prose_lines_starting_with_from_survive_composition():
    # A module-docstring LINE beginning with `from ` is prose, not an import.
    src = ('"""Build things\n'
           "from each pyproject) into the lists that extend_graph commits.\n"
           'import-shaped prose line too.\n'
           '"""\n\n'
           "import os\n"
           "\n\n"
           "def f():\n"
           "    return os.getpid()\n")
    assert _composed(src) == src


def test_the_import_block_lands_below_a_shebang_and_docstring():
    # A shebang (or any comment header) ABOVE the module docstring is still the preamble: the
    # composed import block lands after it, never at line 1 (the cascade_manifests.py regression).
    src = ("#!/usr/bin/env python3\n"
           '"""A script with a shebang.\n'
           '"""\n'
           "\n"
           "import os\n"
           "\n\n"
           "def f():\n"
           "    return os.getpid()\n")
    lines = _composed(src).splitlines()
    assert lines[0] == "#!/usr/bin/env python3" and lines[1] == '"""A script with a shebang.'
    assert lines.index("import os") > lines.index('"""', 2)
    src2 = "# -*- coding: utf-8 -*-\n# license header\n\nimport os\n\n\ndef g():\n    return os.sep\n"
    out2 = _composed(src2)
    assert out2.splitlines()[0] == "# -*- coding: utf-8 -*-" and "import os" in out2
    compile(out2, "n.py", "exec")


def test_coexisting_submodule_imports_both_survive_composition():
    """import urllib.request + import urllib.error both bind `urllib` and both are live -- the
    composition must carry BOTH (the one-descriptor-per-name table once kept only the last)."""
    text = ("import urllib.error\n"
            "import urllib.request\n"
            "\n"
            "\n"
            "def fetch(url):\n"
            "    try:\n"
            "        return urllib.request.urlopen(url)\n"
            "    except urllib.error.URLError:\n"
            "        return None\n")
    assert _composed(text) == text


def test_rebinding_imports_still_supersede():
    """Aliased / from-imports rebinding a name follow Python last-binding-wins -- only the LIVE
    binding is composed."""
    text = ("from json import dumps\n"
            "from simplejson import dumps\n"
            "import numpy as np\n"
            "import numpy.typing as np\n"
            "\n"
            "\n"
            "def f(x):\n"
            "    return dumps(x), np\n")
    out = _composed(text)
    assert "from simplejson import dumps" in out and "from json import dumps" not in out
    assert "import numpy.typing as np" in out and out.count("import numpy") == 1


def test_same_module_imported_twice_dedupes():
    """A literally duplicated plain import collapses to one statement."""
    out = _composed("import os\nimport os\n\n\ndef f():\n    return os.getcwd()\n")
    assert out.count("import os") == 1
