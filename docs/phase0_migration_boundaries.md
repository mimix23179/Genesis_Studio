# Phase 0C Migration Boundaries

## Purpose
Define strict boundaries so refactor work can proceed without UI/backend drift.

## Boundary 1: UI vs Runtime
- UI (`app/ui/*`) is responsible for:
  - view state,
  - rendering,
  - dispatching user actions via RPC.
- Runtime (`genesis/backend/*`) is responsible for:
  - session lifecycle,
  - model interaction,
  - tool execution,
  - event emission.

Rule: UI must not directly call provider APIs (Ollama HTTP) or read backend storage files.

## Boundary 2: Transport vs Services
- Transport layer handles JSON-RPC framing, client sockets, request dispatch.
- Service layer handles business logic.

Rule: no business logic in websocket handler beyond validation/routing/error wrapping.

## Boundary 3: Provider vs Orchestrator
- Provider adapter handles Ollama HTTP protocol and stream parsing.
- Chat/Coding orchestrator handles prompt/context/tool workflow.

Rule: provider returns normalized events/data, never UI objects.

## Boundary 4: Storage vs Domain
- Storage repository persists sessions/messages/events/settings.
- Domain services apply lifecycle rules and compose storage operations.

Rule: UI and provider modules must not perform raw SQL/file persistence directly.

## Boundary 5: Terminal UI vs Terminal Runtime
- Terminal UI component handles display, input capture, focus, layout.
- Terminal runtime service handles process/PTY lifecycle and output streaming.

Rule: terminal process manager never depends on ButterflyUI classes.

## Frozen Integration Points (Phase 0)
- Keep method/event names from `docs/runtime_rpc.md`.
- Keep request/response envelope JSON-RPC compatible.
- Keep optimistic message rendering behavior in chat page.
- Keep sidebar session switching behavior.

## Explicitly Deferred (Not in Phase 0)
- Replacing in-memory sessions with SQLite.
- Implementing real tool execution.
- Full terminal architecture replacement.
- Provider multi-backend routing.

## Phase 0 Exit Checklist
- Baseline audit doc exists and reflects real code.
- RPC contract doc exists and matches runtime behavior.
- Runtime exposes:
  - `runtime.api_version`
  - `runtime.info`
  - `runtime.health`
- Migration boundaries are documented and agreed.
