"""Tests for AVE webserver command dispatch helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from custom_components.ave_dominaplus import ws_commands, ws_routing
from custom_components.ave_dominaplus.ave_thermostat import AveThermostatProperties
from custom_components.ave_dominaplus.const import AVE_FAMILY_THERMOSTAT
from custom_components.ave_dominaplus.web_server import AveWebServer
from homeassistant.core import HomeAssistant


def _new_server(hass: HomeAssistant, **overrides) -> AveWebServer:
    """Build a webserver instance suitable for command dispatch tests."""
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
    return AveWebServer(settings, hass, object())


async def test_switch_and_cover_commands_dispatch_when_connected(
    hass: HomeAssistant,
) -> None:
    """Switch and cover methods should dispatch expected websocket commands."""
    server = _new_server(hass)
    server.ws_conn = SimpleNamespace(closed=False)
    server.send_ws_command = AsyncMock()

    await ws_commands.switch_turn_on(server, 7)
    await ws_commands.switch_turn_off(server, 7)
    await ws_commands.switch_toggle(server, 7)
    await ws_commands.cover_open(server, 8)
    await ws_commands.cover_close(server, 8)
    await ws_commands.cover_stop(server, 8, "9")

    server.send_ws_command.assert_any_await("EBI", ["7", "11"])
    server.send_ws_command.assert_any_await("EBI", ["7", "12"])
    server.send_ws_command.assert_any_await("EBI", ["7", "10"])
    server.send_ws_command.assert_any_await("EAI", ["8", "8"])
    server.send_ws_command.assert_any_await("EAI", ["8", "9"])
    assert server.send_ws_command.await_count == 6


async def test_scenario_execute_dispatches_when_connected(
    hass: HomeAssistant,
) -> None:
    """Scenario execution helper should dispatch ESI websocket command."""
    server = _new_server(hass)
    server.ws_conn = SimpleNamespace(closed=False)
    server.send_ws_command = AsyncMock()

    await ws_commands.scenario_execute(server, 15)

    server.send_ws_command.assert_awaited_once_with("ESI", ["15", "0"])


async def test_dimmer_turn_on_clamps_and_dispatches(hass: HomeAssistant) -> None:
    """Dimmer turn-on should clamp brightness and send EBI+SIL commands."""
    server = _new_server(hass)
    server.ws_conn = SimpleNamespace(closed=False)
    server.send_ws_command = AsyncMock()

    await ws_commands.dimmer_turn_on(server, 3, 99)

    server.send_ws_command.assert_any_await("EBI", ["3", "3"])
    server.send_ws_command.assert_any_await("SIL", ["3"], [[31]])


async def test_dimmer_turn_on_zero_routes_to_turn_off(hass: HomeAssistant) -> None:
    """Zero brightness should be normalized to dimmer_turn_off path."""
    server = _new_server(hass)
    with patch.object(
        ws_commands, "dimmer_turn_off", new=AsyncMock()
    ) as dimmer_turn_off:
        await ws_commands.dimmer_turn_on(server, 5, 0)

    dimmer_turn_off.assert_awaited_once_with(server, 5)


async def test_dimmer_toggle_and_off_dispatch_when_connected(
    hass: HomeAssistant,
) -> None:
    """Dimmer toggle/off should dispatch EBI commands when connected."""
    server = _new_server(hass)
    server.ws_conn = SimpleNamespace(closed=False)
    server.send_ws_command = AsyncMock()

    await ws_commands.dimmer_toggle(server, 4)
    await ws_commands.dimmer_turn_off(server, 4)

    server.send_ws_command.assert_any_await("EBI", ["4", "2"])
    server.send_ws_command.assert_any_await("EBI", ["4", "4"])


async def test_thermostat_commands_dispatch_when_connected(hass: HomeAssistant) -> None:
    """Thermostat helpers should route through STS and TOO websocket commands."""
    server = _new_server(hass)
    server.ws_conn = SimpleNamespace(closed=False)
    server.send_ws_command = AsyncMock()

    await ws_commands.send_thermostat_sts(server, ["4"], [[1, 1, 210]])
    await ws_commands.thermostat_on_off(server, 4, 1)

    server.send_ws_command.assert_any_await("STS", ["4"], [[1, 1, 210]])
    server.send_ws_command.assert_any_await("TOO", ["4", "1"])


async def test_commands_noop_when_not_connected(hass: HomeAssistant) -> None:
    """Command methods should not dispatch when websocket is unavailable."""
    server = _new_server(hass)
    server.ws_conn = None
    server.send_ws_command = AsyncMock()

    await ws_commands.switch_turn_on(server, 1)
    await ws_commands.dimmer_turn_off(server, 2)
    await ws_commands.cover_open(server, 3)
    await ws_commands.send_thermostat_sts(server, ["1"], [[1, 1, 210]])

    server.send_ws_command.assert_not_awaited()


def test_manage_wts_routes_name_and_offset_updates(hass: HomeAssistant) -> None:
    """WTS handling should route bulk thermostat update and optional offset update."""
    server = _new_server(hass, get_entities_names=True)
    server.update_thermostat = Mock()
    server.update_th_offset = Mock()
    server.all_thermostats_raw = {4: {"device_name": "Living", "address_dec": 12}}

    props = AveThermostatProperties()
    props.device_id = 4
    props.offset = 1.3

    with patch(
        "custom_components.ave_dominaplus.ws_routing.AveThermostatProperties.from_wts",
        return_value=props,
    ):
        ws_routing.manage_wts(server, ["4"], [["ignored"]])

    assert props.device_name == "Living"
    server.update_thermostat.assert_called_once()
    server.update_th_offset.assert_called_once_with(
        server=server,
        family=AVE_FAMILY_THERMOSTAT,
        ave_device_id=4,
        offset_value=1.3,
        name="Living",
        address_dec=12,
    )


def test_manage_wts_skips_offset_update_when_missing(hass: HomeAssistant) -> None:
    """WTS handling should skip thermostat offset update when offset is unavailable."""
    server = _new_server(hass, get_entities_names=False)
    server.update_thermostat = Mock()
    server.update_th_offset = Mock()
    server.all_thermostats_raw = {4: {"device_name": "Living", "address_dec": 12}}

    props = AveThermostatProperties()
    props.device_id = 4
    props.offset = None

    with patch(
        "custom_components.ave_dominaplus.ws_routing.AveThermostatProperties.from_wts",
        return_value=props,
    ):
        ws_routing.manage_wts(server, ["4"], [["ignored"]])

    assert props.device_name == "thermostat_4"
    server.update_thermostat.assert_called_once()
    server.update_th_offset.assert_not_called()
