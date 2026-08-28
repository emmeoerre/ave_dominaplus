"""Tests for AVE webserver connection and message helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from custom_components.ave_dominaplus.web_server import AveWebServer
from custom_components.ave_dominaplus.ws_connection_flow import wait_for_ldi
from homeassistant.core import HomeAssistant


def _new_server(hass: HomeAssistant, **overrides) -> AveWebServer:
    """Build a webserver instance for connection/message tests."""
    settings: dict[str, object] = {
        "ip_address": "192.168.1.10",
        "get_entities_names": True,
        "fetch_sensor_areas": True,
        "fetch_sensors": True,
        "fetch_lights": True,
        "fetch_covers": True,
        "fetch_thermostats": True,
        "on_off_lights_as_switch": True,
    }
    settings.update(overrides)
    return AveWebServer(settings, hass, object())


def test_iter_connection_entities_deduplicates_entities(hass: HomeAssistant) -> None:
    """Connection entity iterator should not return duplicate entity objects."""
    server = _new_server(hass)

    class _Entity:
        pass

    entity = _Entity()
    entity.hass = hass
    entity.entity_id = "light.a"

    server.register_availability_entity(entity)
    server.lights["u1"] = entity

    entities = list(server._iter_connection_entities())

    assert entities == [entity]


def test_notify_connection_state_changed_filters_and_handles_runtime_error(
    hass: HomeAssistant,
) -> None:
    """Availability notifier should skip invalid entities and tolerate write errors."""
    server = _new_server(hass)
    valid = SimpleNamespace(hass=hass, entity_id="light.a", async_write_ha_state=Mock())
    missing_hass = SimpleNamespace(
        hass=None, entity_id="light.b", async_write_ha_state=Mock()
    )
    missing_id = SimpleNamespace(hass=hass, entity_id=None, async_write_ha_state=Mock())
    runtime_error = SimpleNamespace(
        hass=hass,
        entity_id="light.c",
        async_write_ha_state=Mock(side_effect=RuntimeError("busy")),
    )
    server.lights = {
        "a": valid,
        "b": missing_hass,
        "c": missing_id,
        "d": runtime_error,
    }

    server._notify_connection_state_changed()

    valid.async_write_ha_state.assert_called_once()
    missing_hass.async_write_ha_state.assert_not_called()
    missing_id.async_write_ha_state.assert_not_called()


def test_set_connected_tracks_transitions(hass: HomeAssistant) -> None:
    """Connected flag transitions should update lifecycle flags."""
    server = _new_server(hass)
    server._notify_connection_state_changed = Mock()

    server._set_connected(True)
    assert server.connected is True
    assert server._has_connected_once is True

    server._set_connected(False)
    assert server.connected is False
    assert server._logged_unavailable is True

    server._set_connected(True)
    assert server._logged_unavailable is False


async def test_send_ws_command_sends_payload_when_connected(
    hass: HomeAssistant,
) -> None:
    """send_ws_command should build and send framed payload when connected."""
    server = _new_server(hass)
    ws_conn = SimpleNamespace(closed=False, send_str=AsyncMock())
    server.ws_conn = ws_conn

    await server.send_ws_command("EBI", ["7", "11"], [[1]])

    ws_conn.send_str.assert_awaited_once()
    sent_message = ws_conn.send_str.await_args.args[0]
    assert sent_message.startswith(chr(0x02) + "EBI")
    assert sent_message.endswith(chr(0x04))


async def test_send_ws_command_skips_when_disconnected(hass: HomeAssistant) -> None:
    """send_ws_command should no-op when websocket connection is unavailable."""
    server = _new_server(hass)
    server.ws_conn = None

    await server.send_ws_command("EBI", ["7", "11"])


async def test_send_ws_command_marks_disconnected_on_send_error(
    hass: HomeAssistant,
) -> None:
    """send_ws_command should set connection false if send_str raises."""
    server = _new_server(hass)
    server.ws_conn = SimpleNamespace(
        closed=False, send_str=AsyncMock(side_effect=RuntimeError("boom"))
    )
    server._set_connected = Mock()

    await server.send_ws_command("EBI", ["7", "11"])

    server._set_connected.assert_called_once_with(False)


async def test_on_message_parses_bytes_and_routes_command(hass: HomeAssistant) -> None:
    """on_message should decode bytes payload and route parsed commands."""
    server = _new_server(hass)
    server.manage_incoming_messages = AsyncMock()
    raw = (chr(0x02) + "ping" + chr(0x03) + "AA" + chr(0x04)).encode("utf-8")

    await server.on_message(raw)

    server.manage_incoming_messages.assert_awaited_once_with("ping", [], [])


async def test_wait_for_ldi_returns_false_on_timeout(hass: HomeAssistant) -> None:
    """LDI wait helper should return False if wait_for raises timeout."""
    server = _new_server(hass)

    async def _raise_timeout(coro, _timeout):
        coro.close()
        raise TimeoutError

    with patch(
        "custom_components.ave_dominaplus.ws_connection_flow.asyncio.wait_for",
        new=AsyncMock(side_effect=_raise_timeout),
    ):
        assert await wait_for_ldi(server) is False


async def test_wait_for_ldi_returns_true_when_event_set(hass: HomeAssistant) -> None:
    """LDI wait helper should return True when event is already set."""
    server = _new_server(hass)
    server.ldi_done.set()

    assert await wait_for_ldi(server) is True


async def test_build_crc_returns_two_hex_chars(hass: HomeAssistant) -> None:
    """CRC builder should return two uppercase hex characters."""
    server = _new_server(hass)

    crc = await server.build_crc(chr(0x02) + "PING" + chr(0x03))

    assert len(crc) == 2
    assert crc == crc.upper()
