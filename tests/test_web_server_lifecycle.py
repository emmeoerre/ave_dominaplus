"""Tests for AVE webserver lifecycle paths (auth/start/retry)."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import aiohttp

from homeassistant.core import HomeAssistant

from .web_server_harness import (
    FakeClientSession,
    FakeWSConnection,
    FakeWSMessage,
    make_server,
)


async def test_authenticate_success_sets_connected_and_metadata(
    hass: HomeAssistant,
) -> None:
    """Successful authenticate should set connection state and metadata."""
    server = make_server(hass)
    ws_conn = FakeWSConnection()
    session = FakeClientSession(ws_conn=ws_conn)
    server.tryget_mac_address = AsyncMock(return_value="aa:bb:cc:dd:ee:ff")
    server.tryget_systeminfo = AsyncMock(return_value={"firmware": "1.2.3"})

    with patch(
        "custom_components.ave_dominaplus.web_server.aiohttp.ClientSession",
        return_value=session,
    ):
        ok = await server.authenticate()

    assert ok is True
    assert server.connected is True
    assert server.ws_conn is ws_conn
    assert server.mac_address == "aa:bb:cc:dd:ee:ff"
    assert server.systeminfo == {"firmware": "1.2.3"}
    assert session.ws_connect_calls[0][0] == "ws://192.168.1.10:14001"


async def test_authenticate_client_error_cleans_up_resources(
    hass: HomeAssistant,
) -> None:
    """Client errors should close stale resources and return False."""
    server = make_server(hass)
    stale_ws = FakeWSConnection()
    server.ws_conn = stale_ws
    failing_session = FakeClientSession(ws_exc=aiohttp.ClientError("network"))

    with patch(
        "custom_components.ave_dominaplus.web_server.aiohttp.ClientSession",
        return_value=failing_session,
    ):
        ok = await server.authenticate()

    assert ok is False
    assert stale_ws.closed is True
    assert server.ws_conn is None
    assert failing_session.closed is True
    assert server._ws_session is None


async def test_authenticate_unexpected_error_cleans_up_resources(
    hass: HomeAssistant,
) -> None:
    """Unexpected authenticate errors should also close resources and return False."""
    server = make_server(hass)
    stale_ws = FakeWSConnection()
    server.ws_conn = stale_ws
    failing_session = FakeClientSession(ws_exc=RuntimeError("boom"))

    with patch(
        "custom_components.ave_dominaplus.web_server.aiohttp.ClientSession",
        return_value=failing_session,
    ):
        ok = await server.authenticate()

    assert ok is False
    assert stale_ws.closed is True
    assert server.ws_conn is None
    assert failing_session.closed is True
    assert server._ws_session is None


async def test_disconnect_cancels_tasks_and_closes_connections(
    hass: HomeAssistant,
) -> None:
    """Disconnect should cancel pending tasks and close ws/session."""
    server = make_server(hass)
    pending_connect_task = Mock()
    pending_connect_task.done.return_value = False
    pending_connect_task.cancel = Mock()
    pending_thermostat_task = Mock()
    pending_thermostat_task.done.return_value = False
    pending_thermostat_task.cancel = Mock()

    ws_conn = FakeWSConnection()
    session = FakeClientSession(ws_conn=FakeWSConnection())
    server.connect_actions_task = pending_connect_task
    server.thermostat_fetch_task = pending_thermostat_task
    server.ws_conn = ws_conn
    server._ws_session = session
    server._set_connected = Mock()

    await server.disconnect()

    assert server.closed is True
    pending_connect_task.cancel.assert_called_once()
    pending_thermostat_task.cancel.assert_called_once()
    assert ws_conn.closed is True
    assert session.closed is True
    server._set_connected.assert_called_once_with(False, log_transition=False)


async def test_start_retries_after_auth_failure_without_timing_coupling(
    hass: HomeAssistant,
) -> None:
    """Start loop should retry on auth failure and stop when externally closed."""
    server = make_server(hass)
    server.authenticate = AsyncMock(return_value=False)

    async def _sleep_and_stop(_seconds: int) -> None:
        server.closed = True

    with patch(
        "custom_components.ave_dominaplus.web_server.asyncio.sleep",
        new=AsyncMock(side_effect=_sleep_and_stop),
    ):
        await server.start()

    assert server.started is True
    server.authenticate.assert_awaited_once()


async def test_start_handles_ws_iteration_error_and_retries(
    hass: HomeAssistant,
) -> None:
    """Start loop should recover from websocket iteration errors."""
    server = make_server(hass)
    ws_conn = FakeWSConnection(messages=[RuntimeError("ws broken")])

    async def _authenticate() -> bool:
        server.ws_conn = ws_conn
        server._set_connected(True)
        return True

    def _create_task(coro):
        coro.close()
        return Mock(done=Mock(return_value=True))

    async def _sleep_and_stop(_seconds: int) -> None:
        server.closed = True

    server.authenticate = AsyncMock(side_effect=_authenticate)

    with (
        patch(
            "custom_components.ave_dominaplus.web_server.asyncio.create_task",
            side_effect=_create_task,
        ),
        patch(
            "custom_components.ave_dominaplus.web_server.asyncio.sleep",
            new=AsyncMock(side_effect=_sleep_and_stop),
        ),
    ):
        await server.start()

    assert server.connected is False
    server.authenticate.assert_awaited()


async def test_start_processes_binary_messages_then_exits_when_closed(
    hass: HomeAssistant,
) -> None:
    """Start loop should route binary messages through on_message callback."""
    server = make_server(hass)
    ws_conn = FakeWSConnection(
        messages=[FakeWSMessage(aiohttp.WSMsgType.BINARY, b"payload")]
    )

    async def _authenticate() -> bool:
        server.ws_conn = ws_conn
        server._set_connected(True)
        return True

    async def _on_message(_data: bytes) -> None:
        server.closed = True

    def _create_task(coro):
        coro.close()
        return Mock(done=Mock(return_value=True))

    server.authenticate = AsyncMock(side_effect=_authenticate)
    server.on_message = AsyncMock(side_effect=_on_message)

    with patch(
        "custom_components.ave_dominaplus.web_server.asyncio.create_task",
        side_effect=_create_task,
    ):
        await server.start()

    server.on_message.assert_awaited_once_with(b"payload")


async def test_on_message_invalid_utf8_is_swallowed(hass: HomeAssistant) -> None:
    """Decode errors in on_message should not raise out of the handler."""
    server = make_server(hass)
    server.manage_incoming_messages = AsyncMock()

    await server.on_message(b"\xff")

    server.manage_incoming_messages.assert_not_awaited()
