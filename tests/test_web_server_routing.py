"""Tests for AVE web server update routing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from custom_components.ave_dominaplus import ws_routing
from custom_components.ave_dominaplus.const import (
    AVE_FAMILY_ANTITHEFT_AREA,
    AVE_FAMILY_DIMMER,
    AVE_FAMILY_MOTION_SENSOR,
    AVE_FAMILY_ONOFFLIGHTS,
    AVE_FAMILY_SCENARIO,
    AVE_FAMILY_SHUTTER_ROLLING,
    AVE_FAMILY_THERMOSTAT,
    AVE_UNHANDLED_UPD,
)
from custom_components.ave_dominaplus.web_server import AveWebServer
from homeassistant.core import HomeAssistant


def _new_server(hass: HomeAssistant, **overrides) -> AveWebServer:
    """Build a web server instance with test-friendly defaults."""
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


def _wire_callbacks(server: AveWebServer) -> None:
    """Wire all update callbacks with mocks for routing assertions."""
    server.update_switch = Mock()
    server.update_button = Mock()
    server.update_light = Mock()
    server.update_cover = Mock()
    server.update_binary_sensor = Mock()
    server.update_thermostat = Mock()
    server.update_th_offset = Mock()


def test_manage_upd_routes_onoff_to_switch_when_enabled(hass: HomeAssistant) -> None:
    """ON/OFF light updates route to switch callback when configured."""
    server = _new_server(hass, on_off_lights_as_switch=True)
    _wire_callbacks(server)

    ws_routing.manage_upd(server, ["WS", "1", "10", "1"], [])

    server.update_switch.assert_called_once_with(
        server, AVE_FAMILY_ONOFFLIGHTS, 10, 1, None
    )
    server.update_light.assert_not_called()


def test_manage_upd_routes_onoff_to_light_when_disabled(hass: HomeAssistant) -> None:
    """ON/OFF light updates route to light callback when switch mode is disabled."""
    server = _new_server(hass, on_off_lights_as_switch=False)
    _wire_callbacks(server)

    ws_routing.manage_upd(server, ["WS", "1", "11", "0"], [])

    server.update_light.assert_called_once_with(
        server, AVE_FAMILY_ONOFFLIGHTS, 11, 0, None
    )
    server.update_switch.assert_not_called()


def test_manage_upd_routes_dimmer_to_light(hass: HomeAssistant) -> None:
    """Dimmer updates route to light callback."""
    server = _new_server(hass)
    _wire_callbacks(server)

    ws_routing.manage_upd(server, ["WS", "2", "3", "31"], [])

    server.update_light.assert_called_once_with(server, AVE_FAMILY_DIMMER, 3, 31, None)


def test_manage_upd_routes_cover_family_to_cover(hass: HomeAssistant) -> None:
    """Cover family updates route to cover callback."""
    server = _new_server(hass)
    _wire_callbacks(server)

    ws_routing.manage_upd(server, ["WS", "3", "21", "2"], [])

    server.update_cover.assert_called_once_with(
        server, AVE_FAMILY_SHUTTER_ROLLING, 21, 2, None
    )


def test_manage_upd_routes_scenario_to_binary_sensor(hass: HomeAssistant) -> None:
    """Scenario WS updates route to running binary sensor callback."""
    server = _new_server(hass, fetch_scenarios=True)
    _wire_callbacks(server)

    ws_routing.manage_upd(server, ["WS", "6", "31", "1"], [])

    server.update_binary_sensor.assert_called_once_with(
        server, AVE_FAMILY_SCENARIO, 31, 1, None
    )


def test_manage_upd_skips_ws_routes_when_lights_disabled(hass: HomeAssistant) -> None:
    """WS light family updates are ignored when fetch_lights is disabled."""
    server = _new_server(hass, fetch_lights=False)
    _wire_callbacks(server)

    ws_routing.manage_upd(server, ["WS", "1", "10", "1"], [])
    ws_routing.manage_upd(server, ["WS", "2", "10", "1"], [])

    server.update_switch.assert_not_called()
    server.update_light.assert_not_called()


def test_manage_upd_routes_antitheft_area(hass: HomeAssistant) -> None:
    """Antitheft area updates map clear flag to binary sensor state."""
    server = _new_server(hass, fetch_sensor_areas=True)
    _wire_callbacks(server)

    ws_routing.manage_upd(server, ["X", "A", "7", "0", "0", "0", "1"], [])

    server.update_binary_sensor.assert_called_once_with(
        server, AVE_FAMILY_ANTITHEFT_AREA, 7, 0
    )


def test_manage_upd_routes_antitheft_sensor(hass: HomeAssistant) -> None:
    """Antitheft sensor updates route to motion sensor callback."""
    server = _new_server(hass, fetch_sensors=True)
    _wire_callbacks(server)

    ws_routing.manage_upd(server, ["X", "S", "12", "0", "1"], [])

    server.update_binary_sensor.assert_called_once_with(
        server, AVE_FAMILY_MOTION_SENSOR, 12, 1
    )


def test_manage_upd_routes_thermostat_offset_update(hass: HomeAssistant) -> None:
    """WT/O updates route both thermostat state and thermostat offset entity."""
    server = _new_server(hass)
    _wire_callbacks(server)

    ws_routing.manage_upd(server, ["WT", "O", "4", "12"], [])

    server.update_thermostat.assert_called_once()
    kwargs = server.update_thermostat.call_args.kwargs
    assert kwargs["server"] is server
    assert kwargs["parameters"] == ["WT", "O", "4", "12"]
    assert kwargs["command"] is None

    server.update_th_offset.assert_called_once_with(
        server=server,
        family=AVE_FAMILY_THERMOSTAT,
        ave_device_id=4,
        offset_value=1.2,
    )


def test_manage_upd_routes_direct_thermostat_temperature(
    hass: HomeAssistant,
) -> None:
    """WT/T temperature updates route to the thermostat entity."""
    server = _new_server(hass)
    _wire_callbacks(server)

    ws_routing.manage_upd(server, ["WT", "T", "12", "239"], [])

    server.update_thermostat.assert_called_once_with(
        server=server,
        parameters=["WT", "T", "12", "239"],
        records=[],
        command=None,
        properties=None,
        ave_device_id=None,
    )
    server.update_th_offset.assert_not_called()


def test_manage_upd_skips_tt_until_map_and_commands_loaded(hass: HomeAssistant) -> None:
    """Thermostat command-ID updates are ignored before map metadata is ready."""
    server = _new_server(hass)
    _wire_callbacks(server)

    server.ave_map.areas_loaded = False
    server.ave_map.command_loaded = False

    ws_routing.manage_upd(server, ["TT", "99", "205"], [])

    server.update_thermostat.assert_not_called()


def test_manage_upd_routes_tt_when_map_and_command_ready(hass: HomeAssistant) -> None:
    """Thermostat command-ID updates route once map and command metadata exist."""
    server = _new_server(hass)
    _wire_callbacks(server)

    command = SimpleNamespace(device_id=8)
    server.ave_map.areas_loaded = True
    server.ave_map.command_loaded = True
    server.ave_map.get_command_by_id_and_family = Mock(return_value=command)

    ws_routing.manage_upd(server, ["TT", "99", "205"], [])

    server.update_thermostat.assert_called_once()
    kwargs = server.update_thermostat.call_args.kwargs
    assert kwargs["server"] is server
    assert kwargs["parameters"] == ["TT", "99", "205"]
    assert kwargs["command"] is command


def test_manage_ldi_li2_routes_onoff_with_address(hass: HomeAssistant) -> None:
    """LI2 on/off records route with parsed address information."""
    server = _new_server(hass, on_off_lights_as_switch=True)
    _wire_callbacks(server)

    ws_routing.manage_ldi_li2(server, [], [["100", "Kitchen", "1", "15"]], "li2")

    server.update_switch.assert_called_once_with(
        server,
        AVE_FAMILY_ONOFFLIGHTS,
        100,
        -1,
        "Kitchen",
        15,
    )
    assert server.raw_ldi == [
        {
            "device_id": 100,
            "device_name": "Kitchen",
            "device_type": 1,
            "address_dec": 15,
            "address_hex": "0F",
        }
    ]
    assert server.ldi_done.is_set()


def test_manage_ldi_li2_routes_scenario_button_and_sensor(hass: HomeAssistant) -> None:
    """LI2 scenario records should create both button and running sensor entities."""
    server = _new_server(hass)
    _wire_callbacks(server)

    ws_routing.manage_ldi_li2(server, [], [["200", "Evening", "6", "21"]], "li2")

    server.update_button.assert_called_once_with(
        server,
        AVE_FAMILY_SCENARIO,
        200,
        "Evening",
        21,
    )
    server.update_binary_sensor.assert_called_once_with(
        server,
        AVE_FAMILY_SCENARIO,
        200,
        -1,
        "Evening",
    )


def test_manage_ldi_li2_handles_bad_records_without_raising(
    hass: HomeAssistant,
) -> None:
    """Malformed LDI/LI2 records are handled and do not abort processing."""
    server = _new_server(hass)
    _wire_callbacks(server)

    ws_routing.manage_ldi_li2(server, [], [["bad-record"]], "li2")

    server.update_switch.assert_not_called()
    server.update_light.assert_not_called()
    server.update_cover.assert_not_called()
    assert server.ldi_done.is_set()


async def test_manage_incoming_messages_routes_ping_to_pong(
    hass: HomeAssistant,
) -> None:
    """PING command should result in a PONG command response."""
    server = _new_server(hass)
    server.send_ws_command = AsyncMock()

    await server.manage_incoming_messages("ping", [], [])

    server.send_ws_command.assert_awaited_once_with("PONG")


def test_manage_upd_handles_all_unhandled_upd(hass, caplog) -> None:
    """Call `manage_upd` for every unhandled UPD key and assert it logs."""
    server = _new_server(hass)
    _wire_callbacks(server)

    ws_routing.manage_ldi_li2(server, [], [["bad-record"]], "li2")

    for key in AVE_UNHANDLED_UPD:
        # manage_upd expects a parameters list where parameters[0] is the UPD key
        ws_routing.manage_upd(server, [key], [])

        server.update_binary_sensor.assert_not_called()
        server.update_thermostat.assert_not_called()
        server.update_th_offset.assert_not_called()
        server.update_binary_sensor.assert_not_called()
        server.update_button.assert_not_called()
        server.update_switch.assert_not_called()
        server.update_light.assert_not_called()
        server.update_cover.assert_not_called()
