# cjm-python-decompose-core

<!-- generated from the context graph by `cjm-context-graph readme` — do not edit by hand; edit the graph (the urge to hand-edit = move it on-graph) -->

A Python source-code decomposition core for context graphs: parses .py modules (docstrings, imports, and the symbol tree of functions/classes/methods with their calls) into provenance-carrying graph nodes and edges that co-reside with the markdown source-type. First source = the ecosystem's own code; generalizes to any Python corpus.

## Modules

- **`cjm_python_decompose_core.__init__`**
- **`cjm_python_decompose_core.elements`** — The element source unit for Python modules (design abfc2829 (1); d26e00f9; 3e155cd6).
- **`cjm_python_decompose_core.emit`** — Project a module BACK out of the graph (graph -> .py) — the canonical emit leg.
- **`cjm_python_decompose_core.extract`** — Bind parsed Python onto dev-graph-schema code nodes (the dev-domain binding).
- **`cjm_python_decompose_core.ingest`** — Flatten a decomposed Python corpus into graph elements (the queue-free half).
- **`cjm_python_decompose_core.parse`** — Schema-free Python parsing (stdlib `ast`).

## API

### `cjm_python_decompose_core.elements`

- `CodeElement` _class_ — One element of a module, its text at depth 0.
- `LiftedModule` _class_ — A module decomposed in the element regime: its elements (one `imports` element among them,
- `binding_union` _function_ — The union of a module's bindings -- the input the import block renders from.
- `class_members` _function_ — A class's members as 0-based inclusive line spans: the class's own text ends at `anchor`,
- `compose_elements` _function_ — Compose elements back into a module: members re-indented by depth, every seam derived.
- `compose_module` _function_ — Compose a captured module: the imports element's text is rendered from the union of every
- `decompose_elements` _function_ — Decompose a module into elements -- top-level regions, then class members recursively. A
- `element_names` _function_ — The names an element's own text uses -- what claims an import binding (abfc2829 (3): a binding
- `import_slot` _function_ — The import block's derived slot: after a leading docstring or comment preamble, else first --
- `lift_imports` _function_ — Decompose a module in the element regime: lift its leading run of imports (after the module
- `string_lines` _function_ — The lines a string literal continues onto -- their whitespace is the string's value.
- `string_reads` _function_ — The names an element reads through a STRING -- a fixture string (`usefixtures("db")`,
- `unresolved_names` _function_ — The names a module reads that no module-level binding (an import, an assignment, a def or class,

### `cjm_python_decompose_core.emit`

- `emit_module_from_nodes` _function_ — Reassemble a module's `.py` source from its graph nodes (the round-trip): its ordered
- `nodes_for_module` _function_ — Filter queried region nodes down to one module (by `module_id` property).
- `regions_from_nodes` _function_ — Collect a module's top-level regions from its nodes, ordered by `order_index`.
- `render_binding` _function_ — Render one import-binding descriptor back to its canonical import statement.
- `render_import_block` _function_ — Render a module's canonical import block from its import bindings (the element regime's
- `sibling_modules` _function_ — The modules a bare import in `module_path` reaches as siblings: `<dir>/<name>.py` and

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
- `accessor_of` _function_ — Whether a def continues the accessor chain of the def directly before it: `@<name>.setter`,
- `emit_regions` _function_ — Reassemble ordered regions into canonical `.py` source — the graph owns formatting.
- `iter_symbols` _function_ — Flatten the symbol tree depth-first (parent before its children).
- `monkeypatch_assignments` _function_ — Top-level monkey-patch assignments: `Class.method = func` (the incremental-class idiom).
- `parse_module` _function_ — Parse Python source into module docstring + imports + the symbol tree.
- `parse_regions` _function_ — Decompose a module into ordered verbatim top-level regions (the round-trip substrate).
- `source_lines` _function_ — Split source where the tokenizer counts lines -- at \n, \r\n and \r only. `str.splitlines` also

## Dependencies

**Depends on:** `cjm-context-graph-layer`, `cjm-context-graph-primitives`, `cjm-dev-graph-schema`
**Used by:** `cjm-context-graph-projection`, `cjm-notebook-decompose-core`, `cjm-substrate`
