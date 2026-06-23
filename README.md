# cjm-python-decompose-core

A Python source-code decomposition core for context graphs.

It parses `.py` modules into their structure — module docstring, imports, and the
tree of symbols (functions, classes, methods) with their docstrings and the names
they call — and binds that structure onto `cjm-dev-graph-schema` `CodeModule` /
`CodeSymbol` nodes plus `DEFINES` / `IMPORTS` / `CALLS` / `ABOUT` edges. The
resulting nodes **co-reside on the same graph** as the markdown source-type
(`cjm-markdown-decompose-core`), so code symbols, decisions, and memory notes
interlink in one place.

This is the sibling of `cjm-markdown-decompose-core` for the *code* source type —
the second source-type core of the [self-hosting graph arc](https://github.com/cj-mills/cjm-substrate).

## Layering

- `parse` — schema-free `ast` decomposition (no graph dependency; reusable for any
  Python corpus).
- `extract` — bind a parsed module onto `CodeModuleNode` / `CodeSymbolNode`.
- `ingest` — flatten a decomposed corpus into the `(nodes, edges)` wire-dict lists
  that `cjm_context_graph_layer.ops.extend_graph` commits, resolving intra-corpus
  `IMPORTS` / `CALLS` edges.

## Identity

Code-node ids are content-addressed and **rename-/cross-graph-stable**: a module's
id is `(durable repo key, repo-relative path)` and a symbol's id is `(module,
qualified name)`. The same repo decomposed in any graph reproduces the same ids,
so a different project's graph can reference a symbol by its stable id.

## Install

```bash
pip install cjm-python-decompose-core
```

## License

Apache-2.0
