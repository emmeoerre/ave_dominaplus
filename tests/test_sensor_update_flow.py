"""Tests for thermostat offset sensor update flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

from custom_components.ave_dominaplus.const import AVE_FAMILY_THERMOSTAT
from custom_components.ave_dominaplus.sensor import (
    ThermostatOffset,
    set_sensor_uid,
    update_th_offset,
)
from custom_components.ave_dominaplus.web_server import AveWebServer
from homeassistant.core import HomeAssistant


def _new_server(hass: HomeAssistant, **overrides) -> AveWebServer:
    """Build a webserver with defaults suitable for offset sensor tests."""
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
    server = AveWebServer(settings, hass, object())
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    server.async_add_number_entities = Mock()
    server.register_availability_entity = Mock()
    server.unregister_availability_entity = Mock()
    return server


def test_update_th_offset_creates_entity_for_thermostat(hass: HomeAssistant) -> None:
    """Offset updates should create thermostat offset entities when needed."""
    server = _new_server(hass)

    update_th_offset(
        server,
        AVE_FAMILY_THERMOSTAT,
        ave_device_id=7,
        offset_value=1.5,
        name="Living",
        address_dec=12,
    )

    unique_id = set_sensor_uid(server, AVE_FAMILY_THERMOSTAT, 7)
    assert unique_id in server.numbers
    created = server.numbers[unique_id]
    assert created.native_value == 1.5
    assert created.extra_state_attributes["AVE address_dec"] == 12
    server.async_add_number_entities.assert_called_once()


def test_update_th_offset_skips_when_thermostats_disabled(hass: HomeAssistant) -> None:
    """Offset updates are ignored when thermostat fetching is disabled."""
    server = _new_server(hass, fetch_thermostats=False)

    update_th_offset(server, AVE_FAMILY_THERMOSTAT, 7, 1.2)

    assert server.numbers == {}
    server.async_add_number_entities.assert_not_called()


def test_update_th_offset_skips_unsupported_family(hass: HomeAssistant) -> None:
    """Unsupported families should be ignored by offset updater."""
    server = _new_server(hass)

    update_th_offset(server, 9999, 7, 1.2)

    assert server.numbers == {}
    server.async_add_number_entities.assert_not_called()


def test_update_th_offset_updates_existing_entity(hass: HomeAssistant) -> None:
    """Existing offset entity should update value/address without recreation."""
    server = _new_server(hass)
    unique_id = set_sensor_uid(server, AVE_FAMILY_THERMOSTAT, 7)
    sensor = ThermostatOffset(
        unique_id,
        AVE_FAMILY_THERMOSTAT,
        7,
        server,
        value=0.5,
    )
    sensor.update_value = Mock()
    sensor.set_address_dec = Mock()
    server.numbers[unique_id] = sensor

    update_th_offset(server, AVE_FAMILY_THERMOSTAT, 7, 1.8, address_dec=10)

    sensor.update_value.assert_called_once_with(1.8)
    sensor.set_address_dec.assert_called_once_with(10)
    server.async_add_number_entities.assert_not_called()


def test_new_offset_uses_generated_name_when_names_disabled(
    hass: HomeAssistant,
) -> None:
    """Generated naming should be used when AVE names are disabled."""
    server = _new_server(hass, get_entities_names=False)

    update_th_offset(server, AVE_FAMILY_THERMOSTAT, 9, 0.7, name="Living")

    unique_id = set_sensor_uid(server, AVE_FAMILY_THERMOSTAT, 9)
    created = server.numbers[unique_id]
    assert created.name == "Thermostat Offset 9"


def test_thermostat_offset_set_ave_name_appends_suffix(hass: HomeAssistant) -> None:
    """Setting AVE name should append offset suffix for source tracking."""
    server = _new_server(hass)
    sensor = ThermostatOffset("uid", AVE_FAMILY_THERMOSTAT, 5, server, value=0.2)
    sensor.async_write_ha_state = Mock()
    sensor.entity_id = "sensor.test"

    sensor.set_ave_name("Kitchen")

    assert sensor.extra_state_attributes["AVE_source_name"] == "Kitchen offset"


async def test_offset_sensor_lifecycle_registers_and_unregisters_availability(
    hass: HomeAssistant,
) -> None:
    """Lifecycle hooks should register and unregister availability listeners."""
    server = _new_server(hass)
    sensor = ThermostatOffset("uid", AVE_FAMILY_THERMOSTAT, 7, server, value=0.0)
    sensor.async_write_ha_state = Mock()
    sensor._pending_state_write = True

    with (
        patch(
            "homeassistant.helpers.entity.Entity.async_added_to_hass",
            new=AsyncMock(),
        ),
        patch(
            "homeassistant.helpers.entity.Entity.async_will_remove_from_hass",
            new=AsyncMock(),
        ),
    ):
        await sensor.async_added_to_hass()
        await sensor.async_will_remove_from_hass()

    server.register_availability_entity.assert_called_once_with(sensor)
    server.unregister_availability_entity.assert_called_once_with(sensor)
    sensor.async_write_ha_state.assert_called_once()
