"""Imports-as-projection faithfulness sweep over the real arc libs (corpus harness).

For every `.py` module in the born-non-nbdev arc libs, derive the canonical import block
from the extracted per-symbol + module-level import bindings and check the FALSE-PRUNE
rate: an import the code actually uses (its local name appears in the body) that the
bindings failed to attribute. Faithfulness bar = ZERO false prunes (every used import is
captured). Imports the derivation drops whose local name never appears in the body are
GENUINE dead imports (auto-pruned — a free cleanup), reported separately.

Run: python tests_manual/imports_projection.py  (from a checkout whose siblings are the
other arc libs at ../). This is the parallel-run+diff gate before flipping the default
emit to derive imports ([[true-b-projected-structure-discussion]] N+2).
"""

import glob
import os
import re

from cjm_python_decompose_core.emit import module_used_bindings, render_import_block
from cjm_python_decompose_core.parse import parse_module

ARC_LIBS = ["cjm-dev-graph-schema", "cjm-python-decompose-core", "cjm-markdown-decompose-core",
            "cjm-context-graph-projection", "cjm-notebook-decompose-core"]


def _flatten(symbols):
    """Yield every symbol including nested children (methods carry their own bindings)."""
    for s in symbols:
        yield s
        yield from _flatten(s.children)


def sweep(repos_dir: str = "..") -> dict:  # repos_dir holds the sibling arc-lib checkouts
    """Decompose every arc-lib module and tally false prunes + genuine dead-import prunes."""
    false_prunes, genuine_unused, modules = [], [], 0
    for lib in ARC_LIBS:
        pkg = lib.replace("-", "_")
        for path in sorted(glob.glob(os.path.join(repos_dir, lib, pkg, "*.py"))):
            base = os.path.basename(path)
            if base in ("__init__.py", "_modidx.py"):     # re-export hubs / nbdev index
                continue
            with open(path) as fh:
                src = fh.read()
            m = parse_module(src)
            modules += 1
            sym_dicts = [{"properties": {"import_bindings": s.import_bindings}}
                         for s in _flatten(m.symbols)]
            module_dict = {"properties": {"import_bindings": m.module_used_bindings}}
            derived = {b["name"] for b in module_used_bindings(sym_dicts, module_dict)}
            body = "\n".join(ln for ln in src.splitlines()
                             if not re.match(r"\s*(from|import)\s", ln))
            for name in set(m.import_bindings) - derived:
                if re.search(r"\b" + re.escape(name) + r"\b", body):
                    false_prunes.append((lib, base, name))
                else:
                    genuine_unused.append((lib, base, name))
    return {"modules": modules, "false_prunes": false_prunes, "genuine_unused": genuine_unused}


if __name__ == "__main__":
    r = sweep()
    print(f"modules checked: {r['modules']}")
    print(f"genuine dead imports (correctly auto-pruned): {len(r['genuine_unused'])}")
    for g in r["genuine_unused"]:
        print(f"   - {g[0]}/{g[1]}: {g[2]}")
    print(f"FALSE PRUNES (used import missed by bindings): {len(r['false_prunes'])}")
    for f in r["false_prunes"]:
        print(f"   ! {f[0]}/{f[1]}: {f[2]}")
    assert not r["false_prunes"], "imports-as-projection dropped a USED import"
    print("\nPASS: 0 false prunes — the derived import block is faithful.")
