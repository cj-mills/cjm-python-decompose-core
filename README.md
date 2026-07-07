# cjm-python-decompose-core

<!-- generated from the context graph by `cjm-context-graph readme` — do not edit by hand; edit the graph (the urge to hand-edit = move it on-graph) -->

A Python source-code decomposition core for context graphs: parses .py modules (docstrings, imports, and the symbol tree of functions/classes/methods with their calls) into provenance-carrying graph nodes and edges that co-reside with the markdown source-type. First source = the ecosystem's own code; generalizes to any Python corpus.

## Modules

- **`cjm_python_decompose_core.__init__`**
- **`cjm_python_decompose_core.emit`** — Project a module BACK out of the graph (graph -> .py) — the canonical emit leg.
- **`cjm_python_decompose_core.extract`** — Bind parsed Python onto dev-graph-schema code nodes (the dev-domain binding).
- **`cjm_python_decompose_core.ingest`** — Flatten a decomposed Python corpus into graph elements (the queue-free half).
- **`cjm_python_decompose_core.parse`** — Schema-free Python parsing (stdlib `ast`).
- **`tests.test_extract_ingest`** — Extract (parse -> schema nodes) + ingest (corpus -> graph elements) binding.
- **`tests.test_imports_emit`** — Imports-as-projection: deriving a module's canonical import block from bindings.
- **`tests.test_method_attribution`** — First-param capture + monkey-patch-assignment detection (the cross-cell method idioms).
- **`tests.test_parse`** — Schema-free Python parsing: docstrings, imports, the symbol tree, and calls.
- **`tests.test_regions_emit`** — Verbatim region decomposition + canonical emit (the authoring / round-trip substrate).
- **`tests_manual.imports_projection`** — Imports-as-projection faithfulness sweep over the real arc libs (corpus harness).

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

### `tests.test_extract_ingest`

- `test_corpus_imports_and_calls_resolve_intra_corpus` _function_
- `test_decompose_text_builds_module_and_symbols` _function_
- `test_external_imports_not_minted` _function_
- `test_import_map_and_call_map` _function_
- `test_ingest_is_idempotent_in_ids` _function_
- `test_local_edges_about_repo_and_defines_nesting` _function_
- `test_module_path_and_import_name` _function_
- `test_resolve_import_relative_and_absolute` _function_

### `tests.test_imports_emit`

- `test_coexisting_submodule_imports_both_survive_round_trip` _function_ — import urllib.request + import urllib.error both bind `urllib` and both are
- `test_derived_block_is_faithful_and_prunes_dead_imports` _function_
- `test_docstring_lines_starting_with_from_survive_derive` _function_
- `test_emit_module_default_is_verbatim_not_derived` _function_
- `test_emit_module_derive_imports_prunes_dead_and_keeps_bodies` _function_
- `test_parameter_default_reference_is_not_pruned` _function_
- `test_rebinding_imports_still_supersede` _function_ — Aliased / from-imports rebinding a name follow Python last-binding-wins —
- `test_render_binding_forms` _function_
- `test_render_import_block_orders_dedups_and_groups` _function_
- `test_render_import_block_wraps_long_from_lines_in_aligned_parens` _function_
- `test_same_module_imported_twice_dedupes` _function_ — A literally duplicated plain import collapses to one statement.

### `tests.test_method_attribution`

- `test_first_param_and_annotation_captured` _function_
- `test_first_param_forward_ref_annotation` _function_
- `test_first_param_unannotated_and_classes_have_none` _function_
- `test_monkeypatch_assignments_detected` _function_
- `test_monkeypatch_is_structural_filtering_is_downstream` _function_
- `test_no_arg_function_has_empty_first_param` _function_

### `tests.test_parse`

- `parsed` _function_
- `test_class_methods_are_children_with_method_kind` _function_
- `test_empty_and_docstringless_module` _function_
- `test_function_calls_are_direct_only` _function_
- `test_import_bindings_per_symbol_and_module_level` _function_
- `test_imports_collected_with_relative_and_submodule_forms` _function_
- `test_iter_symbols_flattens_parents_before_children` _function_
- `test_local_import_not_hoisted_to_bindings` _function_
- `test_method_calls` _function_
- `test_module_docstring_first_line` _function_
- `test_nested_function_is_its_own_symbol_with_own_calls` _function_
- `test_refs_are_superset_of_calls_capturing_bases_and_annotations` _function_
- `test_syntax_error_propagates` _function_
- `test_top_level_symbols` _function_

### `tests.test_regions_emit`

- `test_codetext_regions_cover_the_non_def_source` _function_
- `test_decompose_attaches_body_and_order_to_top_level_symbols` _function_
- `test_decompose_emit_round_trip_from_nodes` _function_
- `test_emit_is_ast_equal_and_seam_canonical_on_messy_input` _function_
- `test_emit_regions_round_trips_pep8_byte_exact` _function_
- `test_parse_regions_orders_symbols_and_text` _function_
- `test_symbol_body_is_verbatim_with_decorators_and_leading_comments` _function_

### `tests_manual.imports_projection`

- `sweep` _function_ — Decompose every arc-lib module and tally false prunes + genuine dead-import prunes.

## Dependencies

**Depends on:** `cjm-dev-graph-schema`
**Used by:** `cjm-context-graph-projection`, `cjm-notebook-decompose-core`
