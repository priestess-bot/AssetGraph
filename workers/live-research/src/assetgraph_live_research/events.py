from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import websockets

from .storage import RawEventBatchWriter


BatchCallback = Callable[[dict[str, Any]], Awaitable[None]]
EventCallback = Callable[[dict[str, Any]], Awaitable[None]]


class DouyinLiveEventCollector:
    def __init__(
        self,
        *,
        websocket_base_url: str,
        batch_writer: RawEventBatchWriter,
        batch_size: int = 500,
        flush_seconds: float = 30.0,
    ):
        if not websocket_base_url.startswith(("ws://127.0.0.1:", "ws://localhost:")):
            raise ValueError("douyinLive WebSocket must remain loopback-local")
        if batch_size < 1 or batch_size > 5000:
            raise ValueError("batch_size must be between 1 and 5000")
        if flush_seconds <= 0:
            raise ValueError("flush_seconds must be positive")
        self.websocket_base_url = websocket_base_url.rstrip("/")
        self.batch_writer = batch_writer
        self.batch_size = batch_size
        self.flush_seconds = flush_seconds

    async def collect(
        self,
        *,
        room_id: str,
        session_code: str,
        register_batch: BatchCallback,
        stop_event: asyncio.Event,
        first_batch_index: int = 0,
        event_callback: EventCallback | None = None,
    ) -> int:
        if not room_id or "/" in room_id:
            raise ValueError("room_id must be a single non-empty path component")
        url = f"{self.websocket_base_url}/ws/{quote(room_id, safe='')}"
        batch: list[dict[str, Any]] = []
        batch_index = first_batch_index
        async with websockets.connect(
            url,
            open_timeout=20,
            close_timeout=10,
            ping_interval=20,
            ping_timeout=20,
            max_size=8 * 1024 * 1024,
        ) as websocket:
            while not stop_event.is_set():
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=self.flush_seconds)
                except TimeoutError:
                    if batch:
                        await self._flush(session_code, batch_index, batch, register_batch)
                        batch_index += 1
                        batch = []
                    continue
                decoded = self._decode_message(message)
                if event_callback is not None:
                    await event_callback(decoded)
                batch.append(decoded)
                if len(batch) >= self.batch_size:
                    await self._flush(session_code, batch_index, batch, register_batch)
                    batch_index += 1
                    batch = []
            if batch:
                await self._flush(session_code, batch_index, batch, register_batch)
                batch_index += 1
        return batch_index

    async def _flush(
        self,
        session_code: str,
        batch_index: int,
        events: list[dict[str, Any]],
        register_batch: BatchCallback,
    ) -> None:
        metadata = self.batch_writer.write(
            session_code=session_code,
            batch_index=batch_index,
            events=events,
        )
        await register_batch(metadata)

    @staticmethod
    def _decode_message(message: str | bytes) -> dict[str, Any]:
        if isinstance(message, bytes):
            message = message.decode("utf-8")
        received_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            payload = {"raw_text": message, "decode_status": "invalid_json"}
        if not isinstance(payload, dict):
            payload = {"value": payload}
        event_type = payload.get("event_type") or payload.get("method") or payload.get("type")
        if payload.get("type") == "system" and payload.get("event"):
            event_type = f"system.{payload['event']}"
        server_at = _extract_server_time(payload)
        return {
            "schema_version": "douyin-event-envelope.v1",
            "event_type": str(event_type),
            "received_at": received_at,
            "server_at": server_at,
            "payload": payload,
        }


def _extract_server_time(payload: dict[str, Any]) -> str | None:
    for key in ("server_at", "event_time", "timestamp", "create_time"):
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, (int, float)):
            seconds = float(value)
            if seconds > 10_000_000_000:
                seconds /= 1000
            try:
                return datetime.fromtimestamp(seconds, UTC).isoformat().replace("+00:00", "Z")
            except (OSError, OverflowError, ValueError):
                continue
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.tzinfo is not None:
                return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return None
