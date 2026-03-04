# Genesis Runtime RPC Contract (Phase 0 Freeze)

## Status
- Version: `0.1.0`
- Transport: WebSocket
- Envelope: JSON-RPC 2.0

This document freezes the runtime contract for refactor safety.

## 1. Envelope

### Request
```json
{
  "jsonrpc": "2.0",
  "id": 101,
  "method": "session.list",
  "params": {}
}
```

### Success Response
```json
{
  "jsonrpc": "2.0",
  "id": 101,
  "result": {}
}
```

### Error Response
```json
{
  "jsonrpc": "2.0",
  "id": 101,
  "error": {
    "code": -32000,
    "message": "Runtime method failed"
  }
}
```

### Notification
```json
{
  "jsonrpc": "2.0",
  "method": "chat.delta",
  "params": {}
}
```

## 2. Method Catalog

### runtime.api_version
- Params: `{}`
- Result:
```json
{
  "api_version": "0.1.0"
}
```

### runtime.info
- Params: `{}`
- Result keys:
  - `ok`
  - `name`
  - `backend`
  - `protocol`
  - `api_version`
  - `model`
  - `ollama_base_url`
  - `workspace_root`
  - `uptime_sec`
  - `session_count`
  - `supported_methods`
  - `notify_events`

### runtime.health
- Params: `{}`
- Result keys:
  - `ok`
  - `backend`
  - `api_version`
  - `model`
  - `ollama_base_url`
  - `workspace_root`
  - `session_count`
  - `ollama_reachable`
  - `available_models` (when reachable)
  - `model_loaded` (when reachable)
  - `error` (when not reachable)

### workspace.set
- Params:
```json
{
  "root": "C:/path/to/workspace"
}
```
- Result:
```json
{
  "ok": true,
  "root": "C:/path/to/workspace"
}
```

### session.list
- Params: `{}`
- Result:
```json
{
  "sessions": [
    { "id": "s_abc123", "title": "New Conversation" }
  ]
}
```

### session.create
- Params:
```json
{
  "title": "New Conversation"
}
```
- Result:
```json
{
  "session_id": "s_abc123",
  "title": "New Conversation"
}
```

### session.open
- Params:
```json
{
  "session_id": "s_abc123"
}
```
- Result:
```json
{
  "session_id": "s_abc123",
  "title": "New Conversation",
  "messages": [
    {
      "id": "m_001",
      "role": "assistant",
      "content": [{ "type": "text", "text": "Hello" }],
      "created_at": 1730000000.0
    }
  ]
}
```

### chat.send
- Params:
```json
{
  "session_id": "s_abc123",
  "message": {
    "role": "user",
    "content": [{ "type": "text", "text": "Hello" }]
  }
}
```
- Result:
```json
{
  "ok": true,
  "session_id": "s_abc123",
  "message_id": "m_assistant"
}
```

### Placeholder Methods (frozen names, behavior may evolve)
- `tool.list`
- `tool.call`
- `tool.execute`
- `tool.result`
- `ui.event`
- `openml.status`
- `openml.dataset.export`

Current behavior: returns `{ "ok": true, "backend": "ollama", "method": "<name>" }`.

## 3. Notification Catalog

### session.updated
```json
{
  "session_id": "s_abc123",
  "action": "created|message"
}
```

### chat.begin
```json
{
  "session_id": "s_abc123",
  "message_id": "m_assistant"
}
```

### chat.delta
```json
{
  "session_id": "s_abc123",
  "message_id": "m_assistant",
  "delta": "token text"
}
```

### chat.message
```json
{
  "session_id": "s_abc123",
  "message": {
    "id": "m_assistant",
    "role": "assistant",
    "content": [{ "type": "text", "text": "final text" }],
    "created_at": 1730000000.0
  }
}
```

## 4. Error Semantics
- `-32700`: parse error.
- `-32600`: invalid request.
- `-32000`: runtime/handler exception.

Error `message` should be user-readable and safe to display in UI status.

## 5. Compatibility Rules
- Do not rename or remove frozen methods/events in `0.1.x`.
- New fields are additive and optional for clients.
- Breaking changes require a major API version increment.
- UI should tolerate unknown fields in responses/events.
