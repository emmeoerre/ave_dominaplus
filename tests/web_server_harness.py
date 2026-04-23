"""Reusable fakes for AVE webserver tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from custom_components.ave_dominaplus.web_server import AveWebServer
from homeassistant.core import HomeAssistant


def make_server(hass: HomeAssistant, **overrides: object) -> AveWebServer:
    """Create an AveWebServer with deterministic defaults for tests."""
    settings: dict[str, object] = {
        "ip_address": "192.168.1.10",
        "get_entities_names": True,
        "fetch_sensor_areas": True,
        "fetch_sensors": True,
        "fetch_lights": True,
        "fetch_covers": True,
        "fetch_scenarios": True,
        "fetch_thermostats": True,
        "on_off_lights_as_switch": True,
    }
    settings.update(overrides)
    return AveWebServer(settings, hass)


@dataclass
class FakeWSMessage:
    """Minimal websocket message shape used by start loop tests."""

    type: Any
    data: Any = None


class FakeWSConnection:
    """Simple async websocket connection fake."""

    def __init__(
        self,
        messages: list[Any] | None = None,
        *,
        closed: bool = False,
        send_exc: Exception | None = None,
    ) -> None:
        """Initialize the fake websocket connection."""
        self._messages: list[Any] = list(messages or [])
        self.closed = closed
        self.send_exc = send_exc
        self.sent_messages: list[str] = []

    async def send_str(self, message: str) -> None:
        """Simulate websocket text send."""
        if self.send_exc is not None:
            raise self.send_exc
        self.sent_messages.append(message)

    async def close(self) -> None:
        """Close the websocket connection."""
        self.closed = True

    def __aiter__(self):
        """Return async iterator for `async for` loops."""
        return self

    async def __anext__(self):
        """Yield queued messages and exceptions, then stop."""
        if self.closed or not self._messages:
            raise StopAsyncIteration

        item = self._messages.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClientSession:
    """Minimal aiohttp ClientSession fake for websocket auth tests."""

    def __init__(
        self,
        ws_conn: FakeWSConnection | None = None,
        *,
        ws_exc: Exception | None = None,
        closed: bool = False,
    ) -> None:
        """Initialize the fake client session."""
        self._ws_conn = ws_conn
        self._ws_exc = ws_exc
        self.closed = closed
        self.ws_connect_calls: list[tuple[str, list[str] | None, int | None]] = []

    async def ws_connect(
        self,
        url: str,
        *,
        protocols: list[str] | None = None,
        heartbeat: int | None = None,
    ) -> FakeWSConnection:
        """Simulate aiohttp ws_connect."""
        self.ws_connect_calls.append((url, protocols, heartbeat))
        if self._ws_exc is not None:
            raise self._ws_exc
        if self._ws_conn is None:
            raise RuntimeError("FakeClientSession has no configured ws_conn")
        return self._ws_conn

    async def close(self) -> None:
        """Close the fake session."""
        self.closed = True
