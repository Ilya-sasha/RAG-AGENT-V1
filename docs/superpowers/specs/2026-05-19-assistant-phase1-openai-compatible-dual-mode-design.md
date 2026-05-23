# Assistant Phase 1 OpenAI-Compatible Dual-Mode Design

## Summary

This design defines the first product-layer assistant slice on top of the existing `agent_runtime` execution kernel. The phase adds a real `OpenAI-compatible` model provider, a dedicated `/assistant` user workspace, persisted assistant sessions and messages, and a dual-mode interaction model that supports both chat-style and task-style usage in one unified interface.

The goal is to turn the current project from a runtime-oriented agent platform with an operations console into a usable tool-type assistant product. The first delivery intentionally stays narrow: it focuses on real model-backed execution, tenant-scoped session history, RAG and knowledge-base management tools, and assistant-side visibility into run progress and approvals.

## Context

The current codebase already provides a strong runtime base:

- durable runs, events, checkpoints, and resume behavior
- a tool gateway with tenant policy and approval support
- workflow templates and workflow launches
- RAG retrieval and knowledge-base ingestion/reindex paths
- workflow observability APIs
- an operator-facing `/admin` console

However, the current system is still missing the product layer required for a usable tool-type assistant:

- the default runtime model is still `ScriptedModelClient`
- there is no user-facing assistant workspace
- there is no persisted assistant session and message model
- there is no chat/task product experience above the runtime
- there is no real model-backed assistant flow that can be validated end-to-end against a compatible provider such as DeepSeek

## User Decisions Captured In This Spec

The user explicitly chose the following boundaries for this phase:

- build the first sub-project before memory and auth
- support both chat mode and task mode in phase 1
- use an `OpenAI-compatible` model interface
- validate the finished model integration against `DeepSeek`
- first tool bundle is `RAG + knowledge-base management`
- create a dedicated `/assistant` workspace rather than extending `/admin`
- use a unified assistant workspace with mode switching rather than two separate apps
- persist session history across reloads and later returns
- do not implement login/auth in this phase

These decisions are treated as hard scope constraints for this design.

## Goals

- Add a real `OpenAI-compatible` model provider that satisfies the existing `ModelClient` boundary.
- Introduce a dedicated `/assistant` workspace for end users.
- Support both `chat` and `task` modes inside the same assistant workspace.
- Persist assistant sessions and message history in the application database.
- Reuse the existing runtime, tool gateway, approval flow, and workflow/run surfaces instead of building a second execution core.
- Make the assistant able to use:
  - `rag_search`
  - knowledge-base list and status
  - knowledge-base ingest
  - knowledge-base reindex
- Surface run progress and approval state inside the assistant experience.
- Validate the phase against a real DeepSeek-compatible endpoint after implementation.

## Non-Goals

This phase does not include:

- user login, auth, or RBAC
- long-term memory or user preference memory
- cross-session semantic memory
- external vector database integration
- expanded file-type support beyond the current RAG surface
- visual workflow designer or workflow graph studio
- broad external business tool integrations
- production multi-provider routing logic beyond the required compatible-provider abstraction
- replacing `/admin` as the operator console

## Product Boundary

After this phase, the project should no longer be described only as an agent runtime with admin and workflow APIs. It should be described as:

- a runtime-backed assistant service
- with a user-facing assistant workspace
- with real model inference
- with tool calling
- with session history
- with task execution visibility

This phase still stops short of a complete enterprise assistant platform because auth, long-term memory, and advanced governance remain out of scope.

## High-Level Architecture

The recommended implementation approach is to extend the current runtime in place and add a thin assistant product layer above it.

### Architectural Principle

There must remain only one execution kernel:

- `RunService`
- `RuntimeOrchestrator`
- `ToolGateway`
- workflow launch and workflow observability

The assistant layer must orchestrate and present those capabilities, not reimplement them.

### New Layers

1. `OpenAI-compatible model provider layer`
   A real provider implementation of `ModelClient` that translates runtime turns into compatible chat-completions requests and converts model responses back into `ModelDecision`.

2. `Assistant application layer`
   A service layer above the runtime that manages assistant sessions, messages, mode-specific behavior, and run/message linking.

3. `Assistant persistence layer`
   Repository and table support for assistant sessions and assistant messages.

4. `Assistant UI layer`
   A dedicated `/assistant` workspace for end users.

### Existing Layers Reused

- runtime persistence and event replay
- tool registration and execution
- approvals API
- workflow launches
- knowledge-base APIs and services
- admin console

## Module Boundaries

### 1. OpenAI-Compatible Model Provider

**Responsibility**

- talk to a real model endpoint using an OpenAI-compatible request format
- support normal reply generation
- support tool-call style decisions
- translate provider responses into runtime `ModelDecision`

**Boundary**

- this module does not own sessions, UI, tools, approvals, or history
- it only implements real model completion behind `ModelClient`

**Expected Behaviors**

- configurable base URL
- configurable API key
- configurable model name
- configurable request timeout
- robust error mapping for connection failures, bad responses, and compatibility mismatches

### 2. Assistant Application Layer

**Responsibility**

- create and manage assistant sessions
- store user and assistant messages
- route interaction through `chat` mode or `task` mode
- coordinate runtime execution and assistant history writes
- expose assistant-oriented APIs

**Boundary**

- it does not replace `RunService`
- it does not replace workflow APIs
- it does not own low-level tool policy logic

### 3. Assistant Persistence Layer

**Responsibility**

- persist assistant sessions
- persist assistant messages
- persist explicit assistant-to-run links when needed

**Boundary**

- this is product interaction storage, not execution storage
- runtime events and checkpoints remain the execution system of record

### 4. Assistant UI Layer

**Responsibility**

- provide the end-user workspace at `/assistant`
- expose one unified workspace for chat mode and task mode
- show history, progress, status, and approval context

**Boundary**

- `/assistant` is for end users
- `/admin` remains for operator and observability workflows

## Chat Mode And Task Mode

The system must support both modes in one workspace, but they must not be implemented as two fully independent products.

### Chat Mode

Chat mode is for iterative assistant interactions.

Behavior:

- user sends a message
- the assistant stores the user message in the session history
- the assistant gathers prior session history as context
- the model may:
  - answer directly
  - call a tool
  - route into a run-backed execution path if needed
- the assistant stores the assistant reply and any relevant tool or run linkage

Chat mode is optimized for natural assistant interaction, not explicit run management.

### Task Mode

Task mode is for explicit objective execution.

Behavior:

- user submits a structured objective
- the assistant stores the task request as session history
- the assistant creates or launches a run through the existing runtime/workflow system
- progress, approvals, and outputs are projected back into the assistant workspace

Task mode is optimized for traceable and resumable execution.

### Shared Principles

- both modes share the same session model
- both modes share the same message store
- both modes share the same tool ecosystem
- both modes share the same model provider
- both modes share the same assistant workspace

## Data Model

This phase requires a new assistant-side persistence model that is distinct from runtime event storage.

### AssistantSession

Represents an assistant workspace conversation container.

Suggested fields:

- `session_id`
- `tenant_id`
- `title`
- `mode`
  - `chat`
  - `task`
- `status`
  - `active`
  - `archived`
- `created_at`
- `updated_at`

### AssistantMessage

Represents a user, assistant, tool, or system entry within one assistant session.

Suggested fields:

- `message_id`
- `session_id`
- `tenant_id`
- `role`
  - `user`
  - `assistant`
  - `system`
  - `tool`
- `content`
- `structured_payload`
- `run_id` nullable
- `created_at`

### AssistantRunLink

Optional but recommended explicit bridge between assistant interactions and runtime runs.

Suggested fields:

- `session_id`
- `message_id`
- `run_id`
- `launch_kind`
  - `chat_turn`
  - `task_run`
  - `workflow_launch`
- `created_at`

### Persistence Boundary Rules

- assistant sessions and messages are the source of truth for product interaction history
- runtime runs, events, approvals, and checkpoints are the source of truth for execution state
- assistant-side APIs should read assistant tables first, then enrich with runtime state when necessary

## API Design

This phase adds assistant-oriented APIs without replacing existing runtime routes.

### Session APIs

- `POST /v1/assistant/sessions`
  - create a session
- `GET /v1/assistant/sessions?tenant_id=<tenant>`
  - list sessions
- `GET /v1/assistant/sessions/{session_id}`
  - session detail
- `GET /v1/assistant/sessions/{session_id}/messages`
  - session history

### Chat API

- `POST /v1/assistant/sessions/{session_id}/chat`

Purpose:

- accept one user message in chat mode
- persist the message
- invoke assistant execution
- return the created message, linked run if any, and initial status

### Task API

- `POST /v1/assistant/sessions/{session_id}/tasks`

Purpose:

- accept an explicit task objective
- optionally target a workflow/template launch
- create a runtime run
- return task-to-run linkage

Expected request shape includes:

- `objective`
- optional `workflow_id`
- optional `version`
- optional structured `input`

### Activity Aggregation API

- `GET /v1/assistant/sessions/{session_id}/activity`

Purpose:

- aggregate recent assistant messages
- current linked run states
- pending approval context
- recent tool activity summary

This avoids forcing the assistant UI to assemble multiple runtime surfaces directly for routine rendering.

### Existing APIs Reused

The assistant product layer may continue to reuse:

- `GET /v1/runs/{run_id}`
- `GET /v1/runs/{run_id}/events`
- `GET /v1/runs/{run_id}/events/replay`
- `GET /v1/approvals/{approval_id}`
- `POST /v1/approvals/{approval_id}/approve`
- `POST /v1/approvals/{approval_id}/reject`
- workflow launch and workflow run observability APIs

## Tool Surface For Phase 1

The first assistant tool bundle is intentionally narrow.

### Required Tools

1. `rag_search`
2. knowledge-base list/status capability
3. knowledge-base ingest capability
4. knowledge-base reindex capability

### Product Expectation

The assistant must be able to:

- answer knowledge questions by retrieving from RAG
- inspect knowledge-base status from within the assistant experience
- trigger ingest or reindex actions from within the assistant experience

This is enough to make the first version a tool-type assistant for internal knowledge operations without prematurely broadening the tool catalog.

### Tool Registration Boundary

The current codebase separates tool definitions from executable tool registrations:

- tool metadata is persisted
- executable tool handlers live in the in-process registry

This phase should preserve that design and extend it with assistant-facing tool use, not collapse the distinction.

## Assistant UI

The assistant UI must be a dedicated product workspace at `/assistant`.

### Layout

The workspace should use three primary regions:

1. left session rail
   - create session
   - list sessions
   - show mode and updated timestamp

2. center interaction workspace
   - mode toggle between chat and task
   - chat transcript and composer
   - task objective input and task status/result views

3. right context rail
   - tenant context
   - linked run status
   - recent tool summaries
   - pending approval status and actions
   - knowledge-base context summary

### UI Boundary

- `/assistant` is the end-user workspace
- `/admin` remains the operator workspace
- the two may share visual primitives or utility code later, but must remain product-distinct

## Error Handling

The assistant phase must normalize errors into product-relevant categories.

### Model Errors

Examples:

- base URL unreachable
- bad API key
- timeout
- incompatible response format

Handling:

- write a visible assistant/system message
- fail the linked run if a run exists
- preserve enough structured detail for operator diagnosis
- do not expose raw stack traces to end users

### Tool Errors

Examples:

- invalid tool arguments
- missing knowledge base
- ingest or reindex failure

Handling:

- preserve tool error summaries
- allow assistant responses to reference tool failure when useful
- keep tool error state visually distinct from model error state

### Approval Blocking

Handling:

- show pending approval in assistant activity
- allow user action via the existing approval APIs
- preserve approved or rejected outcomes in assistant-visible history

### Session-Layer Errors

Examples:

- missing session
- message persistence failure
- run link inconsistency

Handling:

- treat these as assistant application errors
- keep them distinct from runtime orchestration errors

## Configuration

This phase adds assistant- and provider-specific configuration needs.

Minimum required environment surface:

- compatible model base URL
- compatible model API key
- compatible model name
- compatible request timeout

These settings should integrate cleanly with the existing local startup story and must not break current startup defaults when the compatible provider is not configured.

## DeepSeek Validation Target

Implementation is not considered complete until it passes a real compatibility check against DeepSeek.

Minimum validation cases:

1. pure chat response
   - user sends a normal question
   - assistant returns a model-backed answer
   - session history persists

2. chat with `rag_search`
   - user asks a KB-backed question
   - model chooses or is routed to `rag_search`
   - tool result is incorporated into the assistant answer

3. task-mode execution with knowledge-base action
   - user submits a task
   - the system creates a run
   - the task uses knowledge-base related operations
   - final status and result are visible in `/assistant`

This phase must validate actual assistant behavior, not only endpoint connectivity.

## Testing Strategy

This phase should follow TDD during implementation and should add coverage at four levels.

### 1. Provider Unit Tests

- compatible request construction
- response parsing
- tool call mapping
- finish decision mapping
- provider error mapping

### 2. Assistant Application Unit Tests

- session creation
- message persistence
- chat-mode dispatch
- task-mode dispatch
- assistant-to-run linking
- activity aggregation

### 3. API Integration Tests

- assistant session routes
- assistant chat route
- assistant task route
- `/assistant` page and static assets
- session history retrieval

### 4. End-to-End Phase Flows

- chat success
- chat plus `rag_search`
- task success
- approval-required path
- provider failure path

The implementation does not need fully automated live DeepSeek CI coverage if environment constraints make that impractical, but it must support:

- deterministic mocked integration tests
- a manual DeepSeek validation path
- optional environment-driven compatibility smoke coverage if practical

## Observability

This phase should reuse current logs, metrics, run events, and assistant-visible status projection.

Tracing remains explicitly out of scope for this phase and stays aligned with the deferred roadmap.

## Migration And Compatibility

This phase should not break:

- current `/admin`
- current `/health`
- current `/metrics`
- current workflow APIs
- current run and approval APIs
- current local and container startup paths

Assistant features are additive.

## Acceptance Criteria

This phase is complete when all of the following are true:

1. the system supports a real `OpenAI-compatible` model provider
2. the provider can power real assistant chat responses
3. `/assistant` exists as a dedicated user workspace
4. `/assistant` supports both `chat` and `task` modes
5. assistant sessions and message history persist across reloads and later re-entry
6. chat mode can successfully use `rag_search`
7. task mode can create a run and display task progress and result
8. assistant flows can use knowledge-base list/status/ingest/reindex capabilities
9. pending approvals are visible and resolvable from the assistant experience
10. a real DeepSeek compatibility validation has been completed
11. test coverage exists for the assistant product-layer main flows
12. `/admin` remains the operator console and `/assistant` remains the user-facing workspace

## Recommended Next Step After Spec Approval

Once this spec is approved, the implementation plan should decompose the work into tasks in this order:

1. assistant persistence and repositories
2. compatible model provider
3. assistant application service
4. assistant APIs
5. `/assistant` workspace UI
6. integration tests and DeepSeek validation path
