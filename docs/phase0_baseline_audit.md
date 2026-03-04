# Phase 0A Baseline Audit

## Scope
This audit captures the runtime/UI behavior that currently exists before refactor work starts.
It is the "as-is" baseline for Phase 0.

## Code Surfaces Audited
- `genesis/backend/ollama_runtime.py`
- `app/ui/shell.py`
- `app/ui/chat_page/view.py`
- `app/ui/sidebar_view.py`
- `app/ui/terminal_container.py`
- `app/ui/terminal_process.py`

## Runtime Transport Baseline
- Runtime uses WebSocket + JSON-RPC 2.0 envelope.
- Runtime is embedded/auto-launched by the UI bridge when no existing runtime is found.
- Runtime state is process-local and in-memory:
  - sessions/messages are held in `_sessions` dict,
  - no persistence across application restart.

## Runtime Methods (Current)
- `workspace.set`
- `session.list`
- `session.create`
- `session.open`
- `chat.send`
- stubbed pass-through responses for:
  - `tool.list`
  - `tool.call`
  - `tool.execute`
  - `tool.result`
  - `ui.event`
  - `openml.status`
  - `openml.dataset.export`
- runtime metadata/health methods added in Phase 0 freeze:
  - `runtime.info`
  - `runtime.health`
  - `runtime.api_version`

## Runtime Notifications (Current)
- `session.updated`
- `chat.begin`
- `chat.delta`
- `chat.message`

## Chat Flow Baseline
1. UI sends `chat.send`.
2. Runtime appends user message in session memory.
3. Runtime streams Ollama `/api/chat`.
4. Runtime emits:
   - `chat.begin`,
   - many `chat.delta`,
   - final `chat.message`,
   - `session.updated`.
5. UI side updates message list and sidebar session state.

## UI Baseline
- Sidebar supports new chat, refresh, select conversation.
- Chat page supports streaming rendering and local optimistic user messages.
- Shell has a settings panel toggle and terminal panel toggle.
- Terminal currently uses a WebView wrapper (`terminal.html` + JS/CSS), not full native control composition.

## Terminal Baseline
- Process model is long-lived subprocess shell.
- Input is forwarded from UI WebView messages.
- Output is streamed char-by-char back to WebView.
- Terminal reliability concerns:
  - char-by-char pumping may be noisy/heavy,
  - WebView bridge adds another integration layer,
  - no first-class runtime terminal event contract yet.

## Observed Gaps (Must Address in Next Phases)
- No persistent storage for sessions/messages.
- No cancellation API for in-flight generation.
- Tool methods are placeholders, no real execution lifecycle.
- Runtime and service logic are in one file.
- Runtime metadata and health were previously not structured.
- Protocol contract was implicit in code, not documented.

## Regression Guardrails for Refactor
- Keep JSON-RPC request/response shape stable.
- Keep event names stable unless versioned migration is provided.
- Keep UI optimistic message behavior.
- Keep session switch behavior and active-session semantics.
- Keep terminal open/close interaction stable while migrating internals.
