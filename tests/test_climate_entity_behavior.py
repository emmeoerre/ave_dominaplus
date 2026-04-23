"""Tests for AveThermostat entity behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from custom_components.ave_dominaplus import ws_commands
from custom_components.ave_dominaplus.ave_thermostat import AveThermostatProperties
from custom_components.ave_dominaplus.climate import (
    PRESET_MANUAL,
    PRESET_SCHEDULE,
    AveThermostat,
)
from custom_components.ave_dominaplus.const import AVE_FAMILY_THERMOSTAT
from custom_components.ave_dominaplus.web_server import AveWebServer
from homeassistant.components.climate.const import (
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_OFF,
    HVACAction,
    HVACMode,
)
from homeassistant.core import HomeAssistant


def _new_server(hass: HomeAssistant) -> AveWebServer:
    """Build a webserver with thermostat-friendly defaults."""
    settings = {
        "ip_address": "192.168.1.10",
        "get_entities_names": True,
        "fetch_sensor_areas": True,
        "fetch_sensors": True,
        "fetch_lights": True,
        "fetch_covers": True,
        "fetch_thermostats": True,
        "on_off_lights_as_switch": True,
    }
    server = AveWebServer(settings, hass)
    return server  # noqa: RET504


def _props(
    *,
    device_id: int = 7,
    name: str = "Living",
    fan_level: int = 1,
    season: str = "1",
    mode: str = "M",
    set_point: float | None = 21.0,
    local_off: int | None = 0,
) -> AveThermostatProperties:
    """Build thermostat properties for behavior tests."""
    props = AveThermostatProperties()
    props.device_id = device_id
    props.device_name = name
    props.fan_level = fan_level
    props.season = season
    props.mode = mode
    props.temperature = 20.0
    props.set_point = set_point
    props.local_off = local_off
    props.offset = 0.0
    return props


def test_update_all_properties_sets_modes_and_action(hass: HomeAssistant) -> None:
    """Bulk property update should set HVAC mode/preset/action consistently."""
    server = _new_server(hass)
    thermostat = AveThermostat("uid", AVE_FAMILY_THERMOSTAT, _props(), server)
    thermostat.async_write_ha_state = Mock()

    thermostat.update_all_properties(_props(fan_level=2, season="0", mode="A"))

    assert thermostat.hvac_mode == HVACMode.COOL
    assert thermostat.preset_mode == PRESET_SCHEDULE
    assert thermostat.hvac_action == HVACAction.COOLING
    assert thermostat.fan_mode == FAN_MEDIUM
    thermostat.async_write_ha_state.assert_called()


def test_update_specific_property_temperature_and_setpoint(hass: HomeAssistant) -> None:
    """Specific property updates should update exposed current and target temperatures."""
    server = _new_server(hass)
    thermostat = AveThermostat("uid", AVE_FAMILY_THERMOSTAT, _props(), server)
    thermostat.async_write_ha_state = Mock()

    thermostat.update_specific_property("temperature", 23.2)
    thermostat.update_specific_property("set_point", 19.4)

    assert thermostat.current_temperature == 23.2
    assert thermostat.target_temperature == 19.4


def test_update_specific_property_mode_and_fan_level(hass: HomeAssistant) -> None:
    """Mode and fan-level updates should map to HA preset and fan constants."""
    server = _new_server(hass)
    thermostat = AveThermostat("uid", AVE_FAMILY_THERMOSTAT, _props(), server)
    thermostat.async_write_ha_state = Mock()

    thermostat.update_specific_property("mode", "M")
    assert thermostat.preset_mode == PRESET_MANUAL

    thermostat.update_specific_property("fan_level", 3)
    assert thermostat.fan_mode == FAN_HIGH


def test_update_specific_property_local_off_and_season(hass: HomeAssistant) -> None:
    """Local off and season updates should control HVAC mode transitions."""
    server = _new_server(hass)
    thermostat = AveThermostat("uid", AVE_FAMILY_THERMOSTAT, _props(season="1"), server)
    thermostat.async_write_ha_state = Mock()

    thermostat.update_specific_property("local_off", 1)
    assert thermostat.hvac_mode == HVACMode.OFF

    thermostat.update_specific_property("local_off", 0)
    assert thermostat.hvac_mode == HVACMode.HEAT

    thermostat.update_specific_property("season", "0")
    assert thermostat.hvac_mode == HVACMode.COOL


def test_update_from_fan_level_covers_all_modes(hass: HomeAssistant) -> None:
    """Fan-level mapping should expose all expected fan mode labels."""
    server = _new_server(hass)
    thermostat = AveThermostat("uid", AVE_FAMILY_THERMOSTAT, _props(), server)

    thermostat.update_from_fan_level(0, first_update=True)
    assert thermostat.fan_mode == FAN_OFF

    thermostat.update_from_fan_level(1, first_update=True)
    assert thermostat.fan_mode == FAN_LOW

    thermostat.update_from_fan_level(2, first_update=True)
    assert thermostat.fan_mode == FAN_MEDIUM


async def test_async_set_temperature_dispatches_sts(hass: HomeAssistant) -> None:
    """Setting target temperature should dispatch STS with tenths conversion."""
    server = _new_server(hass)
    thermostat = AveThermostat(
        "uid", AVE_FAMILY_THERMOSTAT, _props(device_id=10), server
    )

    with patch.object(
        ws_commands, "send_thermostat_sts", new=AsyncMock()
    ) as send_thermostat_sts:
        await thermostat.async_set_temperature(temperature=21.5)

    send_thermostat_sts.assert_awaited_once_with(
        server,
        parameters=["10"],
        records=[["1", 1, 215]],
    )


async def test_async_set_temperature_skips_without_temperature(
    hass: HomeAssistant,
) -> None:
    """Setting temperature should abort if no temperature value was provided."""
    server = _new_server(hass)
    thermostat = AveThermostat(
        "uid", AVE_FAMILY_THERMOSTAT, _props(device_id=10), server
    )

    with patch.object(
        ws_commands, "send_thermostat_sts", new=AsyncMock()
    ) as send_thermostat_sts:
        await thermostat.async_set_temperature()

    send_thermostat_sts.assert_not_awaited()


async def test_async_set_preset_mode_dispatches_sts(hass: HomeAssistant) -> None:
    """Preset mode updates should dispatch STS with manual/schedule mapping."""
    server = _new_server(hass)
    thermostat = AveThermostat(
        "uid", AVE_FAMILY_THERMOSTAT, _props(device_id=11), server
    )

    with patch.object(
        ws_commands, "send_thermostat_sts", new=AsyncMock()
    ) as send_thermostat_sts:
        await thermostat.async_set_preset_mode(PRESET_SCHEDULE)

    send_thermostat_sts.assert_awaited_once_with(
        server,
        parameters=["11"],
        records=[["1", 0, 210]],
    )


async def test_async_set_hvac_mode_off_dispatches_on_off(hass: HomeAssistant) -> None:
    """HVAC OFF should map to thermostat on_off command with value 0."""
    server = _new_server(hass)
    thermostat = AveThermostat(
        "uid", AVE_FAMILY_THERMOSTAT, _props(device_id=12), server
    )

    with patch.object(
        ws_commands, "thermostat_on_off", new=AsyncMock()
    ) as thermostat_on_off:
        await thermostat.async_set_hvac_mode(HVACMode.OFF)

    thermostat_on_off.assert_awaited_once_with(server, device_id=12, on_off=0)


async def test_async_set_hvac_mode_heat_from_off_turns_on_then_sts(
    hass: HomeAssistant,
) -> None:
    """Changing from OFF to HEAT should turn device on first, then send STS."""
    server = _new_server(hass)
    thermostat = AveThermostat(
        "uid", AVE_FAMILY_THERMOSTAT, _props(device_id=13), server
    )
    thermostat._attr_hvac_mode = HVACMode.OFF

    with (
        patch.object(
            ws_commands, "thermostat_on_off", new=AsyncMock()
        ) as thermostat_on_off,
        patch.object(
            ws_commands, "send_thermostat_sts", new=AsyncMock()
        ) as send_thermostat_sts,
        patch(
            "custom_components.ave_dominaplus.climate.asyncio.sleep",
            new=AsyncMock(),
        ),
    ):
        await thermostat.async_set_hvac_mode(HVACMode.HEAT)

    thermostat_on_off.assert_awaited_once_with(server, device_id=13, on_off=1)
    send_thermostat_sts.assert_awaited_once_with(
        server,
        parameters=["13"],
        records=[[1, 1, 210]],
    )


async def test_async_turn_on_off_dispatches_on_off(hass: HomeAssistant) -> None:
    """Turn on/off methods should proxy thermostat on_off commands."""
    server = _new_server(hass)
    thermostat = AveThermostat(
        "uid", AVE_FAMILY_THERMOSTAT, _props(device_id=14), server
    )

    with patch.object(
        ws_commands, "thermostat_on_off", new=AsyncMock()
    ) as thermostat_on_off:
        await thermostat.async_turn_on()
        await thermostat.async_turn_off()

    thermostat_on_off.assert_any_await(server, device_id=14, on_off=1)
    thermostat_on_off.assert_any_await(server, device_id=14, on_off=0)


def test_set_name_updates_entity_and_syncs_device_name(hass: HomeAssistant) -> None:
    """Setting thermostat name should invoke device-name sync hook."""
    server = _new_server(hass)
    thermostat = AveThermostat("uid", AVE_FAMILY_THERMOSTAT, _props(), server)
    thermostat.async_write_ha_state = Mock()
    thermostat._sync_device_name = Mock()

    thermostat.set_name("Thermostat Kitchen")

    assert thermostat.name == "Thermostat Kitchen"
    thermostat._sync_device_name.assert_called_once_with("Thermostat Kitchen")
    thermostat.async_write_ha_state.assert_called_once()


def test_sync_device_name_respects_name_by_user(hass: HomeAssistant) -> None:
    """Device registry sync should not overwrite user-selected device names."""
    server = _new_server(hass)
    thermostat = AveThermostat(
        "uid", AVE_FAMILY_THERMOSTAT, _props(device_id=15), server
    )

    device_registry = Mock()
    device_registry.async_get_device.return_value = SimpleNamespace(
        id="dev-1",
        name_by_user="Custom",
        name="Old",
    )

    with patch(
        "custom_components.ave_dominaplus.climate.dr.async_get",
        return_value=device_registry,
    ):
        thermostat._sync_device_name("Thermostat Living")

    device_registry.async_update_device.assert_not_called()


def test_set_address_dec_updates_state(hass: HomeAssistant) -> None:
    """Address updates should trigger a state write when value changes."""
    server = _new_server(hass)
    thermostat = AveThermostat("uid", AVE_FAMILY_THERMOSTAT, _props(), server)
    thermostat.async_write_ha_state = Mock()

    thermostat.set_address_dec(22)

    assert thermostat.extra_state_attributes["AVE address_dec"] == 22
    thermostat.async_write_ha_state.assert_called_once()
