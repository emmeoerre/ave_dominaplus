"""Additional branch coverage tests for AVE thermostat offset sensor platform."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.ave_dominaplus.const import AVE_FAMILY_THERMOSTAT
from custom_components.ave_dominaplus.sensor import (
    ThermostatOffset,
    adopt_existing_sensors,
    async_setup_entry,
    check_name_changed,
    set_sensor_uid,
)
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.exceptions import ConfigEntryNotReady

from .web_server_harness import make_server


def _entry(runtime_data, entry_id: str = "entry-1"):
    return SimpleNamespace(runtime_data=runtime_data, entry_id=entry_id)


@pytest.mark.asyncio
async def test_async_setup_entry_raises_when_webserver_missing() -> None:
    """Setup should raise ConfigEntryNotReady when runtime_data is missing."""
    with pytest.raises(ConfigEntryNotReady):
        await async_setup_entry(None, _entry(None), Mock())


@pytest.mark.asyncio
async def test_async_setup_entry_calls_adoption_when_enabled(hass) -> None:
    """Setup should invoke adoption when thermostat fetching is enabled."""
    server = make_server(hass, fetch_thermostats=True)
    server.set_async_add_number_entities = AsyncMock()
    server.set_update_th_offset = AsyncMock()

    with patch(
        "custom_components.ave_dominaplus.sensor.adopt_existing_sensors",
        new=AsyncMock(),
    ) as adopt_mock:
        await async_setup_entry(hass, _entry(server), Mock())

    adopt_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_adopt_existing_numbers_handles_registry_none(hass) -> None:
    """Adoption should return cleanly when entity registry is unavailable."""
    server = make_server(hass)

    with patch(
        "custom_components.ave_dominaplus.sensor.er.async_get", return_value=None
    ):
        await adopt_existing_sensors(server, _entry(server))


@pytest.mark.asyncio
async def test_adopt_existing_numbers_filters_and_uses_original_name(hass) -> None:
    """Adoption should skip non-sensor entries and adopt with original_name fallback."""
    server = make_server(hass)
    server.async_add_number_entities = Mock()

    entities = [
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="switch",
            unique_id="ave_x_thermostat_offset_16_9",
            name="Skip",
            original_name=None,
            entity_id="switch.skip",
        ),
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="sensor",
            unique_id="ave_x_thermostat_offset_16_9",
            name=None,
            original_name="Original Offset",
            entity_id="sensor.ok",
        ),
    ]

    with (
        patch(
            "custom_components.ave_dominaplus.sensor.er.async_get", return_value=Mock()
        ),
        patch(
            "custom_components.ave_dominaplus.sensor.er.async_entries_for_config_entry",
            return_value=entities,
        ),
    ):
        await adopt_existing_sensors(server, _entry(server))

    assert "ave_x_thermostat_offset_16_9" in server.numbers
    assert server.numbers["ave_x_thermostat_offset_16_9"].name == "Original Offset"
    server.async_add_number_entities.assert_called_once()


@pytest.mark.asyncio
async def test_adopt_existing_numbers_handles_exceptions(hass) -> None:
    """Adoption should swallow unexpected parsing/runtime exceptions."""
    server = make_server(hass)
    bad_entity = SimpleNamespace(
        platform="ave_dominaplus",
        domain="sensor",
        unique_id="bad_uid",
        name="Bad",
        original_name=None,
        entity_id="sensor.bad",
    )

    with (
        patch(
            "custom_components.ave_dominaplus.sensor.er.async_get", return_value=Mock()
        ),
        patch(
            "custom_components.ave_dominaplus.sensor.er.async_entries_for_config_entry",
            return_value=[bad_entity],
        ),
    ):
        await adopt_existing_sensors(server, _entry(server))


def test_sensor_uid_helper_covers_non_thermostat_branch(hass) -> None:
    """UID helper should use fallback prefix for non-thermostat families."""
    server = make_server(hass)
    server.mac_address = "aa:bb"

    uid = set_sensor_uid(server, 999, 4)

    assert uid == "ave_aa:bb_number_999_4"


def test_sensor_name_changed_helper_true_and_false(hass) -> None:
    """Name-change helper should detect override and missing entry cases."""
    registry = Mock()
    registry.async_get_entity_id.return_value = "number.test"
    registry.async_get.return_value = SimpleNamespace(name="New", original_name="Old")

    with patch(
        "custom_components.ave_dominaplus.sensor.er.async_get", return_value=registry
    ):
        assert check_name_changed(hass, "uid") is True

    registry.async_get_entity_id.return_value = None
    with patch(
        "custom_components.ave_dominaplus.sensor.er.async_get", return_value=registry
    ):
        assert check_name_changed(hass, "uid") is False


def test_sensor_properties_mutators_and_write_paths(hass) -> None:
    """Thermostat offset entity should cover property and mutator guard branches."""
    server = make_server(hass)
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    server._set_connected(True)
    entity = ThermostatOffset(
        "uid",
        AVE_FAMILY_THERMOSTAT,
        7,
        server,
        ave_name="Living",
        value=None,
    )
    entity.async_write_ha_state = Mock()

    assert entity.available is True
    assert entity.device_class == SensorDeviceClass.TEMPERATURE_DELTA
    assert entity.extra_state_attributes["AVE webserver MAC"] == "aa:bb:cc:dd:ee:ff"

    entity.update_value(None)
    entity.update_value(1.2)
    entity.set_name(None)
    entity.set_name("Offset Name")
    entity.set_address_dec(25)

    entity.entity_id = None
    entity._write_state_or_defer()
    assert entity._pending_state_write is True

    entity.entity_id = "sensor.offset"
    entity._pending_state_write = False
    entity.set_ave_name("Living")
    entity.async_write_ha_state.assert_called()
