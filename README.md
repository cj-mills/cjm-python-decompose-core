# cjm-python-decompose-core

<!-- generated from the context graph by `cjm-context-graph readme` — do not edit by hand; edit the graph (the urge to hand-edit = move it on-graph) -->

A Python source-code decomposition core for context graphs: parses .py modules (docstrings, imports, and the symbol tree of functions/classes/methods with their calls) into provenance-carrying graph nodes and edges that co-reside with the markdown source-type. First source = the ecosystem's own code; generalizes to any Python corpus.

## Modules

- **`cjm_python_decompose_core.__init__`**
- **`cjm_python_decompose_core.emit`** — Project a module BACK out of the graph (graph -> .py) — the canonical emit leg.
- **`cjm_python_decompose_core.extract`** — Bind parsed Python onto dev-graph-schema code nodes (the dev-domain binding).
- **`cjm_python_decompose_core.ingest`** — Flatten a decomposed Python corpus into graph elements (the queue-free half).
- **`cjm_python_decompose_core.parse`** — Schema-free Python parsing (stdlib `ast`).

## API

### `cjm_python_decompose_core.emit`

- `emit_module_from_nodes` _function_ — Reassemble a module's canonical `.py` source from its graph nodes (the round-trip).
- `module_used_bindings` _function_ — Union of every contained symbol's import bindings + the module-level ones (+ any
- `nodes_for_module` _function_ — Filter queried region nodes down to one module (by `module_id` property).
- `regions_from_nodes` _function_ — Collect a module's top-level regions from its nodes, ordered by `order_index`.
- `render_binding` _function_ — Render one import-binding descriptor back to its canonical import statement.
- `render_import_block` _function_ — Derive a module's canonical import block from its used import bindings.
- `synth_import` _function_ — A synthetic `from <import_name> import <local_name>` binding (USES-derived).

### `cjm_python_decompose_core.extract`

- `DecomposedModule` _class_ — One module bound to schema nodes: the module + its symbols + local edges.
- `decompose_file` _function_ — Read a `.py` file and decompose it (hash over the raw file bytes).
- `decompose_package` _function_ — Decompose every `.py` under a package dir (the lib's own importable source).
- `decompose_paths` _function_ — Decompose an explicit set of files; unparseable files are skipped (recorded by the caller).
- `decompose_text` _function_ — Parse + bind in one step from in-memory source text.
- `import_name_for` _function_ — The dotted import name a module is reachable by (drops a trailing `__init__`).
- `iter_py_files` _function_ — Yield `.py` file paths under `root`, skipping `__pycache__`/build/etc.
- `module_path_for` _function_ — The repo-relative POSIX path used as the module's identity input.

### `cjm_python_decompose_core.ingest`

- `build_call_map` _function_ — Map UNAMBIGUOUS bare symbol names to their node ids (the CALLS target table).
- `build_import_map` _function_ — Map every module's dotted import name to its node id (the IMPORTS target table).
- `corpus_graph_elements` _function_ — Collect a decomposed corpus into the node + edge wire-dict lists `extend_graph` expects.
- `resolve_import` _function_ — Resolve a (possibly relative) import to an absolute dotted module name.

### `cjm_python_decompose_core.parse`

- `ParsedModule` _class_ — The structural decomposition of one Python module.
- `ParsedSymbol` _class_ — One definition within a module (function/class/method), with its nesting.
- `SourceRegion` _class_ — One ordered top-level region of a module, held verbatim (symbol or text).
- `emit_regions` _function_ — Reassemble ordered regions into canonical `.py` source — the graph owns formatting.
- `iter_symbols` _function_ — Flatten the symbol tree depth-first (parent before its children).
- `monkeypatch_assignments` _function_ — Top-level monkey-patch assignments: `Class.method = func` (the incremental-class idiom).
- `parse_module` _function_ — Parse Python source into module docstring + imports + the symbol tree.
- `parse_regions` _function_ — Decompose a module into ordered verbatim top-level regions (the round-trip substrate).

## Dependencies

**Depends on:** `cjm-context-graph-layer`, `cjm-context-graph-primitives`, `cjm-dev-graph-schema`
**Used by:** `cjm-context-graph-projection`, `cjm-notebook-decompose-core`
