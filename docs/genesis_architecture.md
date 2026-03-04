# Genesis Studio Architecture (Ollama + ButterflyUI)

## 1. Goal
Build a production-grade local AI assistant that:
- uses Ollama as the model backend,
- supports coding workflows (read/edit/run/fix loops),
- persists conversations and state,
- ships with a first-class ButterflyUI terminal experience.

This replaces the old deleted backend with a maintainable architecture, not a temporary shim.

## 2. Current State Snapshot
- UI exists in ButterflyUI and already talks to a JSON-RPC runtime.
- Runtime exists but is mostly monolithic/in-memory.
- Sessions/messages are not yet fully persistent.
- Tool execution and coding loops are not fully implemented end-to-end.
- Terminal exists but needs a full ButterflyUI-native rebuild and hardening.

## 3. Target System Design
- `app/`: ButterflyUI desktop shell (chat, sidebar, settings, terminal).
- `genesis/backend/transport`: WebSocket JSON-RPC server and event push.
- `genesis/backend/services`: session/chat/tool orchestration services.
- `genesis/backend/providers`: Ollama provider adapter(s).
- `genesis/backend/agent`: coding loop planner/executor.
- `genesis/backend/storage`: SQLite models, migrations, repositories.
- `genesis/backend/tools`: safe filesystem and command tools.
- `genesis/backend/terminal`: PTY/shell bridge for terminal runtime.
- `docs/`: architecture, protocol, operations docs.

## 4. Delivery Plan (Phases + Subphases)

### Phase 0: Foundation and Contracts
#### 0A. Baseline Audit
- Inventory current runtime/UI behaviors.
- Capture existing RPC methods/events in use.
- Record known regressions and must-keep behavior.

#### 0B. Contract Freeze
- Define canonical JSON-RPC methods and event payloads.
- Add explicit request/response/error schemas.
- Version protocol (`runtime.api_version`).

#### 0C. Migration Boundaries
- Define what stays in UI vs backend.
- Define compatibility layer so current UI keeps working during refactor.

### Phase 1: Runtime Core Refactor
#### 1A. Transport Layer
- Split websocket server from business logic.
- Add request router and unified error handling.

#### 1B. Service Layer
- Introduce `SessionService`, `ChatService`, `ToolService`, `RuntimeService`.
- Remove hidden state coupling.

#### 1C. Config + Health
- Central config loader for host/port/model/timeouts.
- Runtime health method (`runtime.info`, `runtime.health`).

### Phase 2: Persistence and Session Engine
#### 2A. SQLite Schema + Migrations
- Create tables for sessions/messages/events/tool_runs/settings.
- Add startup migration runner.

#### 2B. Repository Abstractions
- Implement data access classes with deterministic ordering and paging.
- Add soft-delete and archival fields where needed.

#### 2C. Session Lifecycle
- Persist session create/open/list/rename/delete.
- Persist streaming messages and recovery after restart.
- Rehydrate chat page state from storage.

### Phase 3: Ollama Provider Hardening
#### 3A. Provider Interface
- Define `LLMProvider` interface (chat, stream, cancel, list_models, health).
- Implement `OllamaProvider` with normalized events.

#### 3B. Streaming + Reliability
- Add retry/backoff policy for transient failures.
- Add timeout and cancellation support per request.
- Handle partial stream errors gracefully.

#### 3C. Model Profiles
- Add profiles (chat/coder/fast) with tunables.
- Add model warmup/availability checks.

### Phase 4: Context and Memory Pipeline
#### 4A. Prompt Policy
- System/developer/user prompt composition rules.
- Clear tool-use and formatting constraints.

#### 4B. Context Builder
- Context windowing (recent turns + summaries + selected files).
- Token budgeting and truncation strategy.

#### 4C. Memory Strategy
- Session summaries for long threads.
- Optional retrieval hooks for workspace knowledge.

### Phase 5: Coding Agent and Tooling
#### 5A. Tool Registry
- Tool schemas and input validation.
- Built-in tools: read/search/list/patch/run.

#### 5B. Code Loop Orchestrator
- Plan -> patch -> validate -> iterate loop.
- Structured patch format and apply workflow.

#### 5C. Safety and Policy
- Workspace boundary enforcement.
- Command allow/deny and timeout controls.
- Audit trail of tool calls and outputs.

### Phase 6: ButterflyUI Terminal 2.0 (New Terminal)
#### 6A. Terminal Domain Model
- Define terminal sessions, tabs, buffers, command history entities.
- Define terminal event protocol (`terminal.open`, `terminal.input`, `terminal.output`, `terminal.exit`).

#### 6B. ButterflyUI Terminal Layout
- Build fully native ButterflyUI terminal container and controls.
- Add tab bar, status bar, shell selector, reconnect indicator.
- Ensure responsive layout for small and large screens.

#### 6C. Process/PTY Bridge
- Implement backend PTY/shell process manager.
- Stream stdout/stderr with backpressure handling.
- Support graceful close, kill, restart.

#### 6D. UX Features
- History navigation and clear behavior.
- Copy/paste safe handling and scrollback limits.
- Command latency/status indicators.

#### 6E. Agent Integration
- Surface tool and command execution logs in terminal.
- Allow "send to terminal" actions from chat/code workflow.

### Phase 7: UI Integration and Settings
#### 7A. Settings Surface
- Backend URL/model/profile controls.
- Timeouts and safety policy toggles.

#### 7B. Chat + Sidebar Integration
- Reliable session switching, rename/delete, active state.
- Better stream state indicators and cancel button.

#### 7C. Diagnostics UI
- Runtime status panel (provider health, db state, terminal state).

### Phase 8: Test and Quality Gates
#### 8A. Unit Tests
- Storage repos, context builder, provider adapters, tool policy.

#### 8B. Integration Tests
- WebSocket RPC contracts and stream event order.
- Session persistence and resume behavior.

#### 8C. End-to-End Desktop Tests
- New chat, switch session, stream response, tool run, terminal command.

### Phase 9: Release and Operations
#### 9A. Documentation
- Setup, troubleshooting, and architecture docs.
- Model/profile selection and operational playbooks.

#### 9B. Performance Pass
- Streaming latency and UI refresh optimization.
- Memory and log retention tuning.

#### 9C. Release Criteria
- All critical tests green.
- No data-loss bugs in session persistence.
- Terminal stable across repeated open/close cycles.

## 5. Milestones and Exit Criteria
- Milestone A (Phases 0-2): stable persistent runtime with session recovery.
- Milestone B (Phases 3-5): reliable Ollama chat + coding agent loop.
- Milestone C (Phase 6): fully rebuilt ButterflyUI terminal integrated with backend.
- Milestone D (Phases 7-9): production hardening, diagnostics, and release readiness.

## 6. Non-Negotiable Requirements
- No in-memory-only conversation state for primary workflows.
- All stream events are ordered and idempotent for UI reconciliation.
- Tool executions are logged with timestamps and outcomes.
- Terminal is ButterflyUI-native and not treated as an afterthought component.

## 7. Risks and Mitigations
- Streaming instability from provider:
  - Mitigation: retry, timeout, cancel, health checks, clear UI state machine.
- Data corruption or migration breakage:
  - Mitigation: migration tests and backup-before-migrate strategy.
- Unsafe code execution flows:
  - Mitigation: strict workspace boundaries and command policy layer.
- UI/backend drift:
  - Mitigation: protocol versioning + contract tests.
