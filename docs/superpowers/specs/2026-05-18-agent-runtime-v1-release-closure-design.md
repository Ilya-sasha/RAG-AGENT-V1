# Agent Runtime V1 Release Closure Design

**Date:** 2026-05-18

**Status:** Draft for review

## 1. Goal

Close the first deliverable version of the project as a runnable, handoff-ready release that other developers can start, verify, and operate without needing hidden session context.

This phase is not about adding a new product capability. It is about turning the current implementation into a version that is:

- runnable on the current local machine through the existing `agent_rag` environment
- reproducible for another developer starting from a fresh environment
- startable through standardized local and containerized paths
- documented well enough for basic and standard operations

## 2. Scope

### In Scope

- define the v1 release boundary and freeze non-essential feature expansion
- document two supported development paths:
  - local quick-start using the existing `agent_rag` environment
  - standard setup from a fresh Python environment
- provide a standardized local startup path
- provide a containerized startup path
- provide a more production-oriented container deployment recommendation path
- document configuration and environment variables
- document data, model, and runtime directory expectations
- document basic and standard operations:
  - start
  - stop
  - logs
  - health checks
  - configuration notes
  - data directory notes
  - upgrade and rollback cautions
- define a repeatable v1 acceptance flow from setup to validation
- run final verification and record the release evidence

### Out of Scope

- `version-browser views`
- workflow-to-run history views
- governance and audit query APIs
- execution-surface enhancement beyond the current behavior
- tracing expansion
- cleanup of existing `aiosqlite` thread warnings
- additional workflow-management feature expansion beyond what is already implemented
- production infrastructure automation beyond practical deployment guidance

## 3. Release Position

### 3.1 What V1 Must Already Support

The release is built on the already completed product surface:

- workflow lifecycle management
- workflow list query
- workflow detail with header metadata
- workflow launch
- workflow-template compatibility routes
- current knowledge-base, run-lifecycle, approval, and multi-agent runtime capabilities already present in the project

### 3.2 What V1 Does Not Need Before Closure

The following do not block first release closure:

- richer workflow browsing experiences
- additional management APIs outside current approved phases
- warning cleanup work already tracked as deferred technical follow-up

## 4. Key Decisions

### Delivery Strategy

- prefer release closure over more product expansion
- close the first version around the current implemented feature set
- only fill gaps that directly affect handoff, startup, or verification

### Environment Strategy

- support both a user-specific fast path and a generic developer path
- treat the existing `agent_rag` environment as a convenience path, not the only supported path
- keep the standard path explicit so the project remains reproducible outside the current machine

### Runtime Strategy

- provide a standardized local run path for development and demonstration
- provide a containerized path for structured startup
- provide a more production-oriented deployment recommendation without pretending to ship a fully production-hardened stack

### Operations Strategy

- cover the operational tasks another engineer will actually need first
- document known limitations explicitly instead of hiding them
- preserve deferred work as tracked follow-up rather than smuggling it into release closure

## 5. Architecture Of The Closure Work

This phase is primarily a packaging, documentation, and verification phase.

### Workstreams

1. **Runtime entrypoint standardization**
   - define the supported local startup command or script
   - ensure the path is explicit and documented

2. **Environment and configuration documentation**
   - document required dependencies
   - document how to configure paths, models, and runtime parameters
   - document machine-specific assumptions that still exist

3. **Containerization and deployment guidance**
   - define a supported container startup path
   - define a more production-oriented container deployment recommendation

4. **Operations documentation**
   - explain start, stop, health-check, logging, and common troubleshooting
   - explain configuration and runtime-data expectations
   - explain upgrade and rollback cautions at a practical level

5. **Release verification**
   - validate local quick-start
   - validate generic environment setup
   - validate container startup
   - validate no-regression test results

## 6. Expected Deliverables

### 6.1 Local Development Deliverables

- one documented quick-start path using `agent_rag`
- one documented standard path using a fresh environment
- one standardized local run command or script

### 6.2 Container Deliverables

- one supported container startup path for the application
- one documented, more production-oriented deployment structure or recommendation

The goal is not a complete infrastructure product. The goal is a credible, reproducible deployment story for v1.

### 6.3 Documentation Deliverables

- setup instructions
- startup instructions
- environment variable/configuration reference
- data directory/model directory notes
- health-check and verification steps
- operational runbook for standard day-1 tasks

### 6.4 Verification Deliverables

- repeatable acceptance checklist
- final test evidence
- explicit note of remaining deferred items and known warnings

## 7. Supported Runtime Paths

### 7.1 Local Quick Path

Target user:

- the current machine/operator

Assumptions:

- `agent_rag` already exists
- local model paths may already be present
- environment activation is already possible on the machine

Expected outcome:

- the application can be started quickly for development, smoke checks, and demonstration

### 7.2 Standard Developer Path

Target user:

- another developer cloning the repository with no pre-existing environment

Requirements:

- explicit environment creation steps
- dependency installation steps
- required path/configuration notes
- startup and validation instructions

Expected outcome:

- another developer can reproduce the runtime without relying on undocumented local state

### 7.3 Container Path

Target user:

- developers or operators who want a more structured startup path

Requirements:

- documented build and run flow
- clear mapping for configuration, ports, volumes, and model/data paths
- practical distinction between “development container run” and “more production-oriented deployment recommendation”

## 8. Operations Coverage

### 8.1 Basic Operations

The release documentation must cover:

- how to start the service
- how to stop the service
- how to check logs
- how to call the health endpoint
- how to confirm the service is responding correctly

### 8.2 Standard Operations

The release documentation must also cover:

- key configuration items and where they are applied
- data directory expectations
- model directory expectations
- upgrade cautions
- rollback cautions
- common startup and environment failure modes

### 8.3 Known Limitation Handling

Known technical debt that is not fixed in this phase must be documented explicitly, including:

- current deferred warning cleanup items
- any environment assumptions that remain local-machine-sensitive

## 9. Acceptance Criteria

V1 release closure is complete when:

- a user on the current machine can start and verify the project through the documented quick path
- another developer can create a fresh environment and start the project through the documented standard path
- the project has a documented containerized startup path
- the project has a documented more production-oriented container deployment recommendation
- setup, startup, configuration, and operational documentation are present and internally consistent
- the final verification flow is documented and reproducible
- workflow-focused and full test regression evidence is captured
- deferred items are clearly separated from release-blocking items

## 10. Deferred Follow-Up

The following remain intentionally outside the v1 closure phase:

- `version-browser views`
- workflow-to-run history APIs or views
- governance and audit APIs
- execution-surface expansion
- tracing work
- `aiosqlite` warning cleanup
- deeper production hardening beyond practical v1 deployment guidance

## 11. Closure Principle

The purpose of this phase is to stop feature drift and produce a first version that can be handed over and operated with confidence.

If a task does not materially improve:

- startup reproducibility
- deployment clarity
- operational usability
- release verification

then it should not be added to the v1 closure scope.
