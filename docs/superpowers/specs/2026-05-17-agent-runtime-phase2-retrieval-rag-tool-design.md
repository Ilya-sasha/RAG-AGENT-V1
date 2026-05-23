# Agent Runtime Phase 2 Retrieval Gateway And RAG Tool Design

**Date:** 2026-05-17

**Status:** Draft for review

## 1. Goal

Add a first-generation enterprise-oriented retrieval capability on top of the runtime core so agents can query local document knowledge bases through a controlled tool boundary.

This phase focuses on:

- local document knowledge bases only
- runtime-integrated retrieval through a governed tool
- local persistent vector indexing
- local default embedding execution through an abstract provider interface
- multi-agent-safe retrieval contracts with auditable source attribution

This phase does not attempt to build a full memory platform, external retrieval service, or answer-generation pipeline inside the retrieval layer.

## 2. Scope

### In Scope for v1

- named knowledge base registration
- local root-path-backed knowledge bases
- supported document types: `Markdown`, `TXT`, `PDF`
- structure-first chunking with length fallback
- local persistent vector index
- abstract `EmbeddingProvider` with local default implementation
- abstract `VectorIndexProvider` with local persistent default implementation
- manual-trigger internal management API for `ingest`, `reindex`, `status`, and listing
- incremental update behavior for added, changed, and deleted files
- runtime tool integration for retrieval through explicit `kb_ids`
- structured retrieval response with chunk-level citations and optional compiled context
- interface reservation for future semantic chunking and external vector databases

### Out of Scope for v1

- external SaaS or web knowledge sources
- `DOCX`, spreadsheets, images, and additional file formats
- reranking
- tool-internal answer generation
- automatic directory watching and live reindex
- standalone retrieval microservice over HTTP
- user memory or long-term conversational memory
- tracing implementation

## 3. Key Decisions

### Delivery Shape

- first upper-layer phase after runtime core: retrieval gateway and RAG tool
- integration mode: controlled runtime tool, not standalone retrieval service
- deployment direction: enterprise-local and private-environment friendly

### Retrieval and Indexing

- retrieval mode: vector retrieval only
- reranking: excluded from v1
- index persistence: local persistent index
- index update mode: manual trigger with incremental update
- query scope: explicit `kb_ids`
- result shape: structured hits plus optional compiled context
- citation granularity: chunk-level

### Content Processing

- source scope: local documents only
- file types in v1: `Markdown`, `TXT`, `PDF`
- chunking mode: structure-first chunking
- extension point reserved for semantic chunking and other chunking strategies

### Provider Strategy

- embedding strategy: abstract provider with local default implementation
- local embedding model location: `C:\models\embedding_models`
- vector store strategy: abstract provider with local persistent default implementation
- external vector database support: deferred, but adapter interface reserved now

## 4. Design Principles

- retrieval must remain a governed runtime capability, not an unbounded side channel
- indexing and querying must be separated from agent orchestration internals
- v1 must be locally deployable without introducing external infrastructure dependencies
- interfaces should stabilize now so future provider swaps do not break runtime or tool contracts
- ingestion and retrieval failures must be observable and recoverable at the file and knowledge-base level
- source attribution must be preserved in machine-readable form for audit and downstream agent use

## 5. Architecture Overview

The recommended implementation is a same-repository layered architecture with clear module boundaries:

1. `knowledge`
   Owns knowledge base registration, document discovery, file parsing, chunking, embedding, and index write orchestration.

2. `retrieval`
   Owns query-time embedding, vector search, result shaping, filtering, and compiled-context assembly.

3. `runtime tool adapter`
   Bridges retrieval into the existing runtime tool gateway through a controlled `rag_search` tool contract.

4. `internal management API`
   Exposes administrator-facing endpoints for knowledge-base registration and indexing operations.

This keeps retrieval logic reusable and testable while preserving the runtime core's existing policy, audit, and tenant boundaries.

## 6. Module Boundaries

### 6.1 `knowledge`

Responsibilities:

- register and load named knowledge bases
- scan local root paths
- parse supported files into normalized document content
- apply chunking strategy
- embed chunks through `EmbeddingProvider`
- write, update, and delete vectors through `VectorIndexProvider`
- track ingest status and document fingerprints

The `knowledge` layer does not know about agent reasoning, tool approvals, or final answer generation.

### 6.2 `retrieval`

Responsibilities:

- embed queries through `EmbeddingProvider`
- perform tenant- and knowledge-base-scoped search through `VectorIndexProvider`
- assemble `RetrievalHit` records
- optionally build `compiled_context`
- expose a stable retrieval interface independent of runtime API concerns

The `retrieval` layer does not mutate knowledge-base state except through read-only search/stat operations.

### 6.3 `runtime tool adapter`

Responsibilities:

- register `rag_search` with the existing tool registry
- validate tool input schema
- invoke the retrieval service
- return structured retrieval payloads through the tool gateway

The tool adapter does not perform indexing or knowledge-base management.

### 6.4 `internal management API`

Responsibilities:

- create and list knowledge bases
- trigger `ingest`
- trigger `reindex`
- report indexing and document-processing status

These endpoints are internal operational surfaces, separate from agent-facing tool execution.

## 7. Core Data Model

### 7.1 `KnowledgeBaseRecord`

Represents a named, tenant-scoped knowledge base.

Minimum fields:

- `kb_id`
- `tenant_id`
- `name`
- `root_path`
- `status`
- `embedding_provider_id`
- `index_provider_id`
- `chunking_strategy`
- `metadata`
- `created_at`
- `updated_at`

### 7.2 `DocumentRecord`

Represents a single governed source file within a knowledge base.

Minimum fields:

- `document_id`
- `kb_id`
- `tenant_id`
- `relative_path`
- `content_hash`
- `file_type`
- `parse_status`
- `last_indexed_at`
- `error_message`
- `metadata`

### 7.3 `ChunkRecord`

Represents a retrieval unit produced by chunking.

Minimum fields:

- `chunk_id`
- `document_id`
- `kb_id`
- `tenant_id`
- `chunk_index`
- `text`
- `text_length`
- `token_count` or approximate token length
- `source_locator`
- `metadata`

`source_locator` is the normalized citation payload. Examples:

- Markdown heading path
- TXT paragraph index
- PDF page number and page-local order

### 7.4 Index Metadata

The local persistent index must preserve enough metadata to support:

- incremental upsert and delete
- tenant and `kb_id` filtering
- document-level rebuilds
- chunk-level result attribution
- future provider replacement behind the same retrieval contract

## 8. Provider Interfaces

### 8.1 `EmbeddingProvider`

Required operations:

- `embed_documents(chunks) -> vectors`
- `embed_query(query) -> vector`
- `provider_id() -> str`

v1 default implementation:

- `LocalEmbeddingProvider`
- loads embedding models from `C:\models\embedding_models`

This interface is intentionally provider-agnostic so future remote or private-service-backed embeddings can be added without changing retrieval consumers.

### 8.2 `VectorIndexProvider`

Required operations:

- `upsert_chunks(...)`
- `delete_document(...)`
- `search(...)`
- `get_index_stats(...)`
- `provider_id() -> str`

v1 default implementation:

- `LocalPersistentVectorIndexProvider`

The provider contract must be sufficient for later external vector database adapters without changing management API or tool payload shape.

### 8.3 `ChunkingStrategy`

Required operation:

- `split(document) -> chunks`

v1 default strategy:

- `StructureFirstChunkingStrategy`

Behavior:

- honor heading, paragraph, list, and page boundaries when possible
- apply length fallback when structure alone produces overly large chunks

Future strategy hooks are explicitly reserved for:

- semantic chunking
- file-type-specific chunking policies
- hybrid structural plus semantic chunking

## 9. Retrieval Contract

### 9.1 Query Model

`RetrievalQuery` minimum fields:

- `tenant_id`
- `kb_ids`
- `query`
- `top_k`
- `filters`
- `include_compiled_context`

The request must explicitly provide `kb_ids` as a one-or-many list. v1 does not permit implicit global retrieval.

### 9.2 Result Model

`RetrievalHit` minimum fields:

- `kb_id`
- `document_id`
- `chunk_id`
- `score`
- `text`
- `source_locator`
- `metadata`

`RetrievalResponse` minimum fields:

- `hits`
- `compiled_context`
- `query_metadata`

### 9.3 Citation Requirements

Every hit must support chunk-level attribution, including enough information to locate the source within the original file. The minimum acceptable citation payload includes:

- source file path
- `chunk_id`
- chunk index or equivalent local ordering
- type-specific location metadata such as heading path or page number

## 10. Runtime Tool Contract

### 10.1 Tool Name

Recommended tool name:

- `rag_search`

### 10.2 Tool Input

Minimum input fields:

- `kb_ids`
- `query`
- `top_k`
- `include_compiled_context`

Optional future-safe fields may include:

- metadata filters
- retrieval options

### 10.3 Tool Output

The tool returns a `RetrievalResponse`.

Important boundary rule:

- the tool retrieves evidence
- the agent decides how to use the evidence
- the tool does not generate the final answer

This keeps retrieval composable for multi-agent workflows and prevents conflating search with reasoning.

## 11. Internal Management API

### 11.1 Required Endpoints

- `POST /internal/knowledge-bases`
- `GET /internal/knowledge-bases`
- `GET /internal/knowledge-bases/{kb_id}/status`
- `POST /internal/knowledge-bases/{kb_id}/ingest`
- `POST /internal/knowledge-bases/{kb_id}/reindex`

### 11.2 API Boundary Rules

- management endpoints are operator-facing internal surfaces
- runtime agents do not call management endpoints through the tool layer
- indexing operations remain explicit and manually triggered in v1

## 12. Ingestion And Indexing Flow

### 12.1 Knowledge Base Registration

When a knowledge base is registered:

- metadata and configuration are stored
- the root path is associated with a tenant-scoped `kb_id`
- the knowledge base moves to a state such as `registered` or `pending_ingest`

Registration does not automatically trigger heavy indexing work.

### 12.2 Initial Ingest

On explicit ingest request:

1. scan the knowledge-base root path
2. identify supported files
3. compute file fingerprints
4. parse content
5. apply structure-first chunking
6. embed chunks
7. upsert chunks and metadata into the persistent index
8. update knowledge-base, document, and ingest status

Unsupported files are skipped and recorded without failing the entire ingest batch.

### 12.3 Incremental Update

On repeated ingest request, the system compares current files against recorded state:

- new file: parse, chunk, embed, and insert
- changed file: remove old chunks, reprocess, and upsert replacement chunks
- deleted file: remove associated document and chunk entries from metadata and index

This is the default operational path for v1.

### 12.4 Reindex

`reindex` is a stronger administrative operation for a single `kb_id`.

Use cases:

- chunking strategy changes
- embedding model changes
- index implementation changes
- metadata consistency repair

Reindex rebuilds the knowledge base from source files rather than relying only on incremental diffs.

## 13. Query Flow

When an agent calls `rag_search`:

1. the runtime tool gateway validates the request
2. tenant and tool policy checks are applied
3. approval logic is applied only if configured by runtime governance
4. the runtime tool adapter builds a `RetrievalQuery`
5. the retrieval layer embeds the query
6. the index provider searches within the explicit `kb_ids`
7. hits are normalized into `RetrievalHit` records
8. `compiled_context` is assembled if requested
9. the structured result returns through the tool gateway to the calling agent

This path preserves the current runtime's tool invocation records, policy boundaries, and auditability.

## 14. Multi-Agent Behavior

The retrieval capability is shared through one governed tool contract across all agents.

For every retrieval call, the runtime should retain:

- `tenant_id`
- `run_id`
- `agent_id`
- `tool_name`

This enables:

- agent-level audit trails
- per-run retrieval inspection
- future differentiated tool access by agent role or tenant policy

The retrieval subsystem itself does not need agent-specific logic. Agent-specific governance stays in the runtime layer.

## 15. Error Handling

### 15.1 Ingestion Errors

Ingestion must follow a partial-failure-tolerant model:

- one broken file must not collapse the entire batch
- failures must be recorded at the document level
- batch status must distinguish `success`, `partial_success`, and `failed`

Failure categories should at minimum cover:

- parse failure
- chunking failure
- embedding failure
- index write failure

### 15.2 Query Errors

Retrieval query failures must be surfaced explicitly. v1 should not silently convert operational failures into empty result sets, because that would mislead agents into treating system failure as evidence absence.

### 15.3 Unsupported Content

Unsupported file types are skipped with recorded reason and visible status rather than hard failure.

## 16. Observability

This phase should extend the current runtime observability model without introducing tracing work.

Minimum metrics and events should cover:

- ingest requests
- ingest success and failure counts
- document counts per knowledge base
- chunk counts per knowledge base
- retrieval query counts
- retrieval latency
- provider-level errors for parsing, embedding, and indexing

Logging should preserve operational debugging value without dumping raw full-document content into standard logs.

## 17. Security And Governance

- retrieval is only available through the governed runtime tool path
- retrieval scope is restricted to explicit `kb_ids`
- tenant identity must be preserved from API/tool boundary through retrieval execution
- management API and agent retrieval tool paths must remain separate
- provider swapping must not bypass governance or audit capture

This phase targets logical governance boundaries, not hard physical tenant isolation.

## 18. Testing Strategy

### 18.1 Unit Tests

- chunking strategy behavior
- provider interface contract behavior
- retrieval response assembly
- citation payload normalization

### 18.2 Integration Tests

- knowledge-base registration
- initial ingest for `Markdown`, `TXT`, and `PDF`
- incremental update for new, changed, and deleted files
- `rag_search` end-to-end retrieval through the runtime tool gateway
- explicit `kb_ids` scope enforcement
- restart-safe querying against the persistent local index

### 18.3 Regression Tests

- provider replacement does not break upper-layer contracts
- structured result shape remains stable
- multi-agent retrieval calls retain runtime audit linkage

## 19. Acceptance Criteria

This phase is complete when:

- a tenant-scoped named knowledge base can be registered through internal API
- local `Markdown`, `TXT`, and `PDF` documents can be ingested into a local persistent vector index
- ingest supports manual trigger and incremental update
- runtime agents can query through `rag_search` using explicit `kb_ids`
- retrieval returns structured hits, chunk-level citations, and optional compiled context
- the architecture preserves provider extension points for semantic chunking and external vector databases

## 20. Deferred Follow-Up

The following items are intentionally deferred beyond this v1 phase:

- external vector database implementation
- additional file types such as `DOCX`
- semantic chunking implementation
- reranking
- standalone retrieval service
- tracing

These must remain visible in future planning, but they are not required for v1 acceptance.

## 21. Recommendation

Implement this phase as a same-repository layered extension of the runtime rather than as a separate service. That preserves local deployability and keeps governance, multi-agent auditability, and future provider swaps aligned from the start.
