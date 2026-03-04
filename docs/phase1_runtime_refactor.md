# Phase 1A/1B Runtime Refactor Status

## Implemented

### 1A Transport Layer
- Added transport package:
  - `genesis/backend/transport/jsonrpc_ws_server.py`
  - `genesis/backend/transport/__init__.py`
- `JsonRpcWebSocketServer` now owns:
  - websocket client lifecycle,
  - JSON parsing,
  - JSON-RPC error envelopes,
  - response sending,
  - broadcast notifications.

### 1B Service Layer
- Added services package:
  - `session_service.py` (session/message lifecycle)
  - `chat_service.py` (chat orchestration + streaming events)
  - `runtime_service.py` (runtime metadata, workspace, health)
  - `tool_service.py` (phase-1 placeholder tool surface)
- Added provider package:
  - `providers/ollama_provider.py` for Ollama HTTP integration.

### Runtime Facade
- `genesis/backend/ollama_runtime.py` is now a facade that wires:
  - transport + services + provider.
- Public behavior kept stable:
  - same class name (`OllamaRuntime`),
  - same `start(host, port)` entrypoint,
  - same core RPC method names/events used by UI.

## Compatibility Notes
- JSON-RPC wire contract remains compatible with Phase 0 freeze.
- Notifications can interleave with responses (existing async behavior).
- Tool methods remain placeholders in Phase 1 and are intentionally not expanded yet.

## Validation
- `python -m compileall genesis app` passed.
- Direct dispatcher smoke tests passed.
- End-to-end websocket JSON-RPC smoke test passed.
