from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

import websockets
from websockets.server import WebSocketServerProtocol

Dispatcher = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class JsonRpcWebSocketServer:
    """WebSocket JSON-RPC transport with pluggable method dispatcher."""

    def __init__(
        self,
        dispatcher: Dispatcher,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._logger = logger or logging.getLogger("genesis.transport")
        self._clients: set[WebSocketServerProtocol] = set()
        self._server = None

    async def start(self, host: str, port: int):
        self._server = await websockets.serve(self._ws_handler, host, port)
        return self._server

    async def _ws_handler(self, ws: WebSocketServerProtocol) -> None:
        self._clients.add(ws)
        try:
            async for raw in ws:
                request, parse_error = self._decode_request(raw)
                if parse_error is not None:
                    await self._send_error(ws, None, -32700, parse_error)
                    continue

                req_id = request.get("id")
                method = str(request.get("method", "")).strip()
                params = request.get("params", {})

                if not method:
                    await self._send_error(ws, req_id, -32600, "Invalid Request")
                    continue
                if not isinstance(params, dict):
                    params = {}

                try:
                    result = await self._dispatcher(method, params)
                    if req_id is not None:
                        await ws.send(
                            json.dumps(
                                {"jsonrpc": "2.0", "id": req_id, "result": result},
                                ensure_ascii=False,
                            )
                        )
                except Exception as exc:
                    self._logger.exception("RPC method failed: %s", method)
                    if req_id is not None:
                        await self._send_error(ws, req_id, -32000, str(exc))
        finally:
            self._clients.discard(ws)

    @staticmethod
    def _decode_request(raw: str) -> tuple[dict[str, Any], str | None]:
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return {}, "Parse error"
        if not isinstance(decoded, dict):
            return {}, "Invalid Request"
        return decoded, None

    async def _send_error(
        self,
        ws: WebSocketServerProtocol,
        req_id: Any,
        code: int,
        message: str,
    ) -> None:
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }
        await ws.send(json.dumps(payload, ensure_ascii=False))

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        if not self._clients:
            return
        packet = json.dumps({"jsonrpc": "2.0", "method": method, "params": params}, ensure_ascii=False)
        dead: list[WebSocketServerProtocol] = []
        for ws in self._clients:
            try:
                await ws.send(packet)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)
