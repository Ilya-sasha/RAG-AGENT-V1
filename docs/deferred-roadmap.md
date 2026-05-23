# Deferred Roadmap

**Last Updated:** 2026-05-19

This document tracks agreed deferred work items so the first-generation project can keep a clear delivery boundary without losing follow-up commitments made during design and implementation.

## V1 Closure Boundary

The v1 release is considered closed around the current runtime service, operator handoff, and workflow template delivery shape. The following items are inside the accepted v1 boundary and should not be re-opened as part of release closure:

- `agent_runtime.main:app` remains the single supported v1 service entrypoint
- local and container startup/operations guidance is documented and handed off
- workflow support includes the shipped template-oriented v1 surface plus the shipped `/v1/workflows` management/list/detail compatibility routes
- release evidence includes the recorded workflow-focused result `41 passed in 25.87s` and the recorded full regression result `142 passed, 3 warnings in 76.04s`
- the known `PytestUnhandledThreadExceptionWarning` tied to the `aiosqlite` worker thread remains visible as a documented deferred item rather than a v1 blocker; for this closure run it appeared `3` times with `RuntimeError: Event loop is closed`

Anything not listed above should be treated as post-v1 work unless an explicit v1 defect reclassifies it.

## Selected Post-v1 Next Phase

| Item | Status | Target Phase | Notes |
| --- | --- | --- | --- |
| Workflow v2 platform expansion | selected for immediate implementation | next phase | build on the shipped workflow-template and `/v1/workflows` surfaces with richer browser/history/governance capabilities and broader management ergonomics |

## Deferred Items

| Category | Item | Decision | Target Phase | Notes |
| --- | --- | --- | --- | --- |
| Workflow platform | Pure API-first workflow definition and execution surface | deferred | workflow v2 | keep template asset as the first delivery shape |
| Workflow platform | Visual workflow designer / graph editor | deferred | workflow v2+ | build only after the workflow model is stable |
| Observability | Tracing / span export / OpenTelemetry wiring | deferred | later platform phase | observability v1 intentionally stopped at logs and metrics |
| RAG evolution | External vector database implementation | deferred | RAG v2 | adapter boundary already reserved |
| RAG evolution | Additional file types such as `DOCX`, spreadsheets, and images | deferred | RAG v2 | current v1 supports `Markdown`, `TXT`, and `PDF` only |
| RAG evolution | Semantic chunking implementation | deferred | RAG v2 | structure-first chunking is the current production path |
| RAG evolution | Hybrid structural plus semantic chunking | deferred | RAG v2+ | depends on semantic chunking work |
| RAG evolution | Reranking | deferred | RAG v2+ | current retrieval remains vector-only |
| RAG evolution | Automatic directory watching and live reindex | deferred | RAG v2+ | current indexing remains manual-trigger and incremental |
| Performance | Multi-agent performance baseline | deferred | performance follow-up | current baseline covers core API/runtime paths only |
| Test and runtime cleanup | `PytestUnhandledThreadExceptionWarning` from `aiosqlite` worker thread | deferred | post-v1 cleanup | known full-regression warning accepted for v1 closure; keep visible until root cause is cleaned up |
| Documentation | Additional startup-instruction enhancement beyond operator handoff | deferred | post-v1 docs cleanup | v1 handoff docs are complete; only follow-on refinement stays deferred |

## Items Already Reserved In Current Design

These items are not missing by accident. The current codebase and specs already reserve extension points for them:

- workflow templates as the next product-layer surface
- external vector database adapters
- semantic chunking strategies
- later tracing integration

## Review Rule

Whenever a major phase closes, update this table before starting the next phase so deferred scope stays explicit and does not leak into the current implementation.
