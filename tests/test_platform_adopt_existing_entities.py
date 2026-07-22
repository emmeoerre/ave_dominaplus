"""Tests for adopting existing entity registry entries across platforms."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

from custom_components.ave_dominaplus import (
    binary_sensor,
    button,
    climate,
    cover,
    light,
    sensor,
    switch,
)
from custom_components.ave_dominaplus.const import (
    AVE_FAMILY_DIMMER,
    AVE_FAMILY_MOTION_SENSOR,
    AVE_FAMILY_ONOFFLIGHTS,
    AVE_FAMILY_SCENARIO,
    AVE_FAMILY_SHUTTER_ROLLING,
    AVE_FAMILY_THERMOSTAT,
)
from custom_components.ave_dominaplus.sensor import set_sensor_uid as set_offset_uid
from custom_components.ave_dominaplus.uid_v2 import build_uid
from custom_components.ave_dominaplus.web_server import AveWebServer
from homeassistant.core import HomeAssistant


def _new_server(hass: HomeAssistant) -> AveWebServer:
    """Build server fixture with broad feature flags enabled."""
    settings = {
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
    server = AveWebServer(settings, hass, object())
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    server.async_add_lg_entities = Mock()
    server.async_add_cv_entities = Mock()
    server.async_add_sw_entities = Mock()
    server.async_add_bt_entities = Mock()
    server.async_add_bs_entities = Mock()
    server.async_add_th_entities = Mock()
    server.async_add_number_entities = Mock()
    return server


async def test_adopt_existing_light_adds_entity(hass: HomeAssistant) -> None:
    """Light adopter should restore compatible light entities from registry."""
    server = _new_server(hass)
    unique_id = build_uid(server.mac_address, AVE_FAMILY_DIMMER, 9, 10)
    entry = SimpleNamespace(entry_id="entry-1")
    entity = SimpleNamespace(
        platform="ave_dominaplus",
        domain="light",
        unique_id=unique_id,
        name="Kitchen",
        original_name=None,
        entity_id="light.kitchen",
    )

    with (
        patch(
            "custom_components.ave_dominaplus.light.er.async_get", return_value=object()
        ),
        patch(
            "custom_components.ave_dominaplus.light.er.async_entries_for_config_entry",
            return_value=[entity],
        ),
    ):
        await light.adopt_existing_lights(server, entry)

    assert unique_id in server.lights
    server.async_add_lg_entities.assert_called_once()


async def test_adopt_existing_cover_adds_entity(hass: HomeAssistant) -> None:
    """Cover adopter should restore compatible cover entities from registry."""
    server = _new_server(hass)
    unique_id = build_uid(server.mac_address, AVE_FAMILY_SHUTTER_ROLLING, 7, 14)
    entry = SimpleNamespace(entry_id="entry-1")
    entity = SimpleNamespace(
        platform="ave_dominaplus",
        domain="cover",
        unique_id=unique_id,
        name="Living",
        original_name=None,
        entity_id="cover.living",
    )

    with (
        patch(
            "custom_components.ave_dominaplus.cover.er.async_get", return_value=object()
        ),
        patch(
            "custom_components.ave_dominaplus.cover.er.async_entries_for_config_entry",
            return_value=[entity],
        ),
    ):
        await cover.adopt_existing_covers(server, entry)

    assert unique_id in server.covers
    server.async_add_cv_entities.assert_called_once()


async def test_adopt_existing_switch_adds_entity(hass: HomeAssistant) -> None:
    """Switch adopter should restore compatible switch entities from registry."""
    server = _new_server(hass)
    entry = SimpleNamespace(entry_id="entry-1")
    unique_id = f"ave_switch_{AVE_FAMILY_ONOFFLIGHTS}_4"
    entity = SimpleNamespace(
        platform="ave_dominaplus",
        domain="switch",
        unique_id=unique_id,
        name="Legacy switch",
        original_name=None,
        entity_id="switch.legacy",
    )

    with (
        patch(
            "custom_components.ave_dominaplus.switch.er.async_get",
            return_value=object(),
        ),
        patch(
            "custom_components.ave_dominaplus.switch.er.async_entries_for_config_entry",
            return_value=[entity],
        ),
    ):
        await switch.adopt_existing_sensors(server, entry)

    assert unique_id in server.switches
    server.async_add_sw_entities.assert_called_once()


async def test_adopt_existing_button_adds_entity(hass: HomeAssistant) -> None:
    """Button adopter should restore scenario button entities from registry."""
    server = _new_server(hass)
    entry = SimpleNamespace(entry_id="entry-1")
    unique_id = build_uid(
        server.mac_address,
        AVE_FAMILY_SCENARIO,
        4,
        0,
        suffix="button",
    )
    entity = SimpleNamespace(
        platform="ave_dominaplus",
        domain="button",
        unique_id=unique_id,
        name="Legacy scenario run",
        original_name=None,
        entity_id="button.legacy_scenario",
    )

    with (
        patch(
            "custom_components.ave_dominaplus.button.er.async_get",
            return_value=object(),
        ),
        patch(
            "custom_components.ave_dominaplus.button.er.async_entries_for_config_entry",
            return_value=[entity],
        ),
    ):
        await button.adopt_existing_buttons(server, entry)

    assert unique_id in server.buttons
    server.async_add_bt_entities.assert_called_once()


async def test_adopt_existing_binary_sensor_adds_motion_entity(
    hass: HomeAssistant,
) -> None:
    """Binary sensor adopter should restore motion entities when enabled."""
    server = _new_server(hass)
    entry = SimpleNamespace(entry_id="entry-1")
    unique_id = f"ave_motion_{AVE_FAMILY_MOTION_SENSOR}_6"
    entity = SimpleNamespace(
        platform="ave_dominaplus",
        domain="binary_sensor",
        original_device_class="motion",
        unique_id=unique_id,
        name="Motion 6",
        original_name=None,
        entity_id="binary_sensor.motion_6",
    )

    with (
        patch(
            "custom_components.ave_dominaplus.binary_sensor.er.async_get",
            return_value=object(),
        ),
        patch(
            "custom_components.ave_dominaplus.binary_sensor.er.async_entries_for_config_entry",
            return_value=[entity],
        ),
    ):
        await binary_sensor.adopt_existing_sensors(server, entry)

    assert unique_id in server.binary_sensors
    server.async_add_bs_entities.assert_called_once()


async def test_adopt_existing_binary_sensor_adds_scenario_running_entity(
    hass: HomeAssistant,
) -> None:
    """Binary sensor adopter should restore scenario running entities when enabled."""
    server = _new_server(hass)
    entry = SimpleNamespace(entry_id="entry-1")
    unique_id = build_uid(
        server.mac_address,
        AVE_FAMILY_SCENARIO,
        6,
        0,
        suffix="running",
    )
    entity = SimpleNamespace(
        platform="ave_dominaplus",
        domain="binary_sensor",
        original_device_class="running",
        unique_id=unique_id,
        name="Scenario 6 Running",
        original_name=None,
        entity_id="binary_sensor.scenario_6_running",
    )

    with (
        patch(
            "custom_components.ave_dominaplus.binary_sensor.er.async_get",
            return_value=object(),
        ),
        patch(
            "custom_components.ave_dominaplus.binary_sensor.er.async_entries_for_config_entry",
            return_value=[entity],
        ),
    ):
        await binary_sensor.adopt_existing_sensors(server, entry)

    assert unique_id in server.binary_sensors
    server.async_add_bs_entities.assert_called_once()


async def test_adopt_existing_climate_adds_thermostat(hass: HomeAssistant) -> None:
    """Climate adopter should restore legacy thermostat entities."""
    server = _new_server(hass)
    entry = SimpleNamespace(entry_id="entry-1")
    unique_id = f"ave_{server.mac_address}_thermostat_{AVE_FAMILY_THERMOSTAT}_3"
    entity = SimpleNamespace(
        platform="ave_dominaplus",
        domain="climate",
        unique_id=unique_id,
        name="Thermostat 3",
        original_name=None,
        entity_id="climate.thermostat_3",
    )

    with (
        patch(
            "custom_components.ave_dominaplus.climate.er.async_get",
            return_value=object(),
        ),
        patch(
            "custom_components.ave_dominaplus.climate.er.async_entries_for_config_entry",
            return_value=[entity],
        ),
    ):
        await climate.adopt_existing_sensors(server, entry)

    assert unique_id in server.thermostats
    server.async_add_th_entities.assert_called_once()


async def test_adopt_existing_offset_sensor_adds_entity(hass: HomeAssistant) -> None:
    """Offset sensor adopter should restore thermostat offset entities."""
    server = _new_server(hass)
    entry = SimpleNamespace(entry_id="entry-1")
    unique_id = set_offset_uid(server, AVE_FAMILY_THERMOSTAT, 3)
    entity = SimpleNamespace(
        platform="ave_dominaplus",
        domain="sensor",
        unique_id=unique_id,
        name="Thermostat offset 3",
        original_name=None,
        entity_id="sensor.thermostat_offset_3",
    )

    with (
        patch(
            "custom_components.ave_dominaplus.sensor.er.async_get",
            return_value=object(),
        ),
        patch(
            "custom_components.ave_dominaplus.sensor.er.async_entries_for_config_entry",
            return_value=[entity],
        ),
    ):
        await sensor.adopt_existing_sensors(server, entry)

    assert unique_id in server.numbers
    server.async_add_number_entities.assert_called_once()
