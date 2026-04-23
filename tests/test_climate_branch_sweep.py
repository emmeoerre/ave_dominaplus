"""Additional branch coverage tests for AVE climate platform."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.ave_dominaplus import ws_commands
from custom_components.ave_dominaplus.ave_thermostat import AveThermostatProperties
from custom_components.ave_dominaplus.climate import (
    PRESET_MANUAL,
    AveThermostat,
    adopt_existing_sensors,
    async_setup_entry,
    check_name_changed,
    update_thermostat,
)
from custom_components.ave_dominaplus.const import AVE_FAMILY_THERMOSTAT
from homeassistant.exceptions import ConfigEntryNotReady

from .web_server_harness import make_server


def _entry(runtime_data, entry_id: str = "entry-1"):
    return SimpleNamespace(runtime_data=runtime_data, entry_id=entry_id)


def _props(
    *,
    device_id: int = 7,
    name: str | None = "Living",
    fan_level: int = 1,
    season: str = "1",
    mode: str = "M",
    set_point: float | None = 21.0,
    local_off: int | None = 0,
) -> AveThermostatProperties:
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


@pytest.mark.asyncio
async def test_async_setup_entry_raises_when_webserver_missing() -> None:
    """Setup should raise ConfigEntryNotReady when runtime_data is missing."""
    with pytest.raises(ConfigEntryNotReady):
        await async_setup_entry(None, _entry(None), Mock())


@pytest.mark.asyncio
async def test_async_setup_entry_registers_callbacks_and_adopts(hass) -> None:
    """Setup should register callbacks and run adoption logic."""
    server = make_server(hass, fetch_thermostats=False)
    server.set_async_add_th_entities = AsyncMock()
    server.set_update_thermostat = AsyncMock()

    with patch(
        "custom_components.ave_dominaplus.climate.adopt_existing_sensors",
        new=AsyncMock(),
    ) as adopt_mock:
        await async_setup_entry(hass, _entry(server), Mock())

    server.set_async_add_th_entities.assert_awaited_once()
    server.set_update_thermostat.assert_awaited_once()
    adopt_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_adopt_existing_sensors_registry_none_and_exception_paths(hass) -> None:
    """Adoption should handle missing registry and malformed UIDs safely."""
    server = make_server(hass)

    with patch(
        "custom_components.ave_dominaplus.climate.er.async_get",
        return_value=None,
    ):
        await adopt_existing_sensors(server, _entry(server))

    bad_entity = SimpleNamespace(
        platform="ave_dominaplus",
        domain="climate",
        unique_id="bad_uid",
        name="Bad",
        original_name=None,
        entity_id="climate.bad",
    )
    with (
        patch(
            "custom_components.ave_dominaplus.climate.er.async_get",
            return_value=Mock(),
        ),
        patch(
            "custom_components.ave_dominaplus.climate.er.async_entries_for_config_entry",
            return_value=[bad_entity],
        ),
    ):
        await adopt_existing_sensors(server, _entry(server))


@pytest.mark.asyncio
async def test_adopt_existing_sensors_filters_and_adopts_valid_entry(hass) -> None:
    """Adoption should skip non-climate and adopt valid legacy thermostat entries."""
    server = make_server(hass)
    server.async_add_th_entities = Mock()
    uid = f"ave_{server.mac_address}_thermostat_{AVE_FAMILY_THERMOSTAT}_3"

    entities = [
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="switch",
            unique_id=uid,
            name="Skip",
            original_name=None,
            entity_id="switch.skip",
        ),
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="climate",
            unique_id=uid,
            name=None,
            original_name="Thermostat 3",
            entity_id="climate.thermostat_3",
        ),
    ]

    with (
        patch(
            "custom_components.ave_dominaplus.climate.er.async_get",
            return_value=Mock(),
        ),
        patch(
            "custom_components.ave_dominaplus.climate.er.async_entries_for_config_entry",
            return_value=entities,
        ),
    ):
        await adopt_existing_sensors(server, _entry(server))

    assert uid in server.thermostats
    server.async_add_th_entities.assert_called_once()


def test_update_thermostat_maps_remaining_command_and_wt_variants(hass) -> None:
    """Routing should cover TL/TLO/TO/TS and WT S/T/L/Z/TW branches."""
    server = make_server(hass)
    command = SimpleNamespace(device_id=8)

    with patch("custom_components.ave_dominaplus.climate._update_thermostat") as update:
        update_thermostat(server, ["TL", "10", "2"], [], command=command)
        update_thermostat(server, ["TLO", "10", "0"], [], command=command)
        update_thermostat(server, ["TO", "10", "3"], [], command=command)
        update_thermostat(server, ["TS", "10", "1"], [], command=command)
        update_thermostat(server, ["WT", "S", "5", "1"], [])
        update_thermostat(server, ["WT", "T", "5", "210"], [])
        update_thermostat(server, ["WT", "L", "5", "2"], [])
        update_thermostat(server, ["WT", "Z", "5", "1"], [])
        update_thermostat(server, ["TW", "5", "open"], [])

    assert update.call_count == 9


def test_check_name_changed_true_and_false_branches(hass) -> None:
    """Name-change helper should detect override and missing entry paths."""
    registry = Mock()
    registry.async_get_entity_id.return_value = "climate.test"
    registry.async_get.return_value = SimpleNamespace(name="New", original_name="Old")

    with patch(
        "custom_components.ave_dominaplus.climate.er.async_get",
        return_value=registry,
    ):
        assert check_name_changed(hass, "uid") is True

    registry.async_get_entity_id.return_value = None
    with patch(
        "custom_components.ave_dominaplus.climate.er.async_get",
        return_value=registry,
    ):
        assert check_name_changed(hass, "uid") is False


@pytest.mark.asyncio
async def test_thermostat_entity_edge_paths_and_lifecycle(hass) -> None:
    """Thermostat entity should cover lifecycle, guards, and sync-device branches."""
    server = make_server(hass)
    thermostat = AveThermostat(
        unique_id="uid",
        family=AVE_FAMILY_THERMOSTAT,
        ave_properties=_props(
            device_id=9, name=None, fan_level=3, season="0", mode="A"
        ),
        webserver=server,
        name=None,
    )
    thermostat.async_write_ha_state = Mock()

    assert thermostat.unique_id == "uid"
    assert thermostat.translation_key == "thermostat"

    assert thermostat.available is False

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
        await thermostat.async_added_to_hass()
        await thermostat.async_will_remove_from_hass()

    thermostat.update_from_wts(
        ["9"], [["resp", "3", "cfg", "0", "1", "210", "M", "215", "0", "0"]]
    )
    thermostat.update_specific_property("window_state", "open")
    thermostat.update_specific_property("season", "1")
    thermostat.update_specific_property("mode", "A")
    thermostat.update_ave_properties(_props(device_id=9, name="New"))

    with (
        patch.object(
            ws_commands, "send_thermostat_sts", new=AsyncMock()
        ) as send_thermostat_sts,
        patch.object(
            ws_commands, "thermostat_on_off", new=AsyncMock()
        ) as thermostat_on_off,
    ):
        thermostat.ave_properties.season = ""
        await thermostat.async_set_temperature(temperature=21)
        thermostat.ave_properties.season = "1"
        await thermostat.async_set_temperature()

        thermostat.ave_properties.season = ""
        await thermostat.async_set_preset_mode(PRESET_MANUAL)
        thermostat.ave_properties.season = "1"
        thermostat._attr_target_temperature = None
        await thermostat.async_set_preset_mode(PRESET_MANUAL)

        thermostat._attr_target_temperature = None
        await thermostat.async_set_hvac_mode(hvac_mode="heat")

    send_thermostat_sts.assert_not_awaited()
    thermostat_on_off.assert_not_awaited()

    # Cover sync-device early return branches.
    thermostat.hass = None
    thermostat._sync_device_name("NoHass")
    thermostat.hass = server.hass
    thermostat._attr_device_info = {}
    thermostat._sync_device_name("NoIdentifiers")
    thermostat._attr_device_info = {"identifiers": {("ave", "id")}}

    registry = Mock()
    registry.async_get_device.return_value = None
    with patch(
        "custom_components.ave_dominaplus.climate.dr.async_get", return_value=registry
    ):
        thermostat._sync_device_name("NoDevice")

    registry.async_get_device.return_value = SimpleNamespace(
        id="dev", name_by_user=None, name="Old"
    )
    with (
        patch(
            "custom_components.ave_dominaplus.climate.build_endpoint_device_info",
            return_value={"identifiers": {("ave", "id")}, "name": "Resolved"},
        ),
        patch(
            "custom_components.ave_dominaplus.climate.dr.async_get",
            return_value=registry,
        ),
    ):
        thermostat._sync_device_name("Resolved")

    thermostat.set_ave_name(None)
    thermostat.set_address_dec(25)
    assert thermostat.build_name() == "Thermostat 9"
