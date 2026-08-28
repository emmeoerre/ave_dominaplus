"""Registry-level tests for naming migrations."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ave_dominaplus.const import AVE_FAMILY_THERMOSTAT, DOMAIN
from custom_components.ave_dominaplus.device_info import (
    build_endpoint_device_info,
    build_hub_device_info,
    ensure_thermostats_parent_device,
    sync_device_registry_name,
)
from custom_components.ave_dominaplus.web_server import AveWebServer
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    translation,
)


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("en", ("Thermostat {name}", "Run", "Running", "Offset", "Status")),
        ("it", ("Termostato {name}", "Esegui", "In esecuzione", "Offset", "Stato")),
    ],
)
@pytest.mark.asyncio
async def test_naming_translations_load(
    hass, language: str, expected: tuple[str, ...]
) -> None:
    """Device and secondary-entity names should load through HA translations."""
    device_translations = await translation.async_get_translations(
        hass, language, "device", {DOMAIN}
    )
    entity_translations = await translation.async_get_translations(
        hass, language, "entity", {DOMAIN}
    )

    prefix = f"component.{DOMAIN}"
    assert device_translations[f"{prefix}.device.thermostat_named.name"] == expected[0]
    assert (
        entity_translations[f"{prefix}.entity.button.scenario_run.name"] == expected[1]
    )
    assert (
        entity_translations[f"{prefix}.entity.binary_sensor.scenario_running.name"]
        == expected[2]
    )
    assert (
        entity_translations[f"{prefix}.entity.sensor.thermostat_offset.name"]
        == expected[3]
    )
    assert (
        entity_translations[f"{prefix}.entity.binary_sensor.status.name"] == expected[4]
    )


@pytest.mark.asyncio
async def test_entity_naming_migration_preserves_registry_choices(hass) -> None:
    """Re-registering naming metadata must preserve IDs and user names."""
    entry = MockConfigEntry(domain=DOMAIN, title="AVE test")
    entry.add_to_hass(hass)
    registry = er.async_get(hass)

    existing = registry.async_get_or_create(
        "light",
        DOMAIN,
        "stable-light-1",
        suggested_object_id="studio_applique_studio_applique",
        config_entry=entry,
        has_entity_name=True,
        original_name="Studio Applique",
    )
    registry.async_update_entity(existing.entity_id, name="Reading Light")

    migrated = registry.async_get_or_create(
        "light",
        DOMAIN,
        "stable-light-1",
        suggested_object_id="studio_applique",
        config_entry=entry,
        has_entity_name=True,
        original_name=None,
    )
    fresh = registry.async_get_or_create(
        "light",
        DOMAIN,
        "stable-light-2",
        suggested_object_id="studio_applique",
        config_entry=entry,
        has_entity_name=True,
        original_name=None,
    )

    assert migrated.entity_id == "light.studio_applique_studio_applique"
    assert migrated.unique_id == "stable-light-1"
    assert migrated.name == "Reading Light"
    assert migrated.original_name is None
    assert fresh.entity_id == "light.studio_applique"


@pytest.mark.asyncio
async def test_device_naming_migration_preserves_user_name(hass) -> None:
    """Translated device-name updates must preserve name_by_user and identity."""
    entry = MockConfigEntry(domain=DOMAIN, title="AVE test")
    entry.add_to_hass(hass)
    server = AveWebServer(
        {
            "ip_address": "192.0.2.1",
            "get_entities_names": True,
        },
        hass,
        object(),
    )
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    server.config_entry_id = entry.entry_id

    registry = dr.async_get(hass)
    registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        **build_hub_device_info(server),
    )
    await translation.async_get_translations(hass, "en", "device", {DOMAIN})
    ensure_thermostats_parent_device(server, entry.entry_id)

    original_info = build_endpoint_device_info(
        server,
        AVE_FAMILY_THERMOSTAT,
        34,
        ave_name="Studio",
    )
    sync_device_registry_name(
        hass,
        original_info,
        config_entry_id=entry.entry_id,
    )
    device = registry.async_get_device(identifiers=original_info["identifiers"])
    assert device is not None
    assert device.name == "Thermostat Studio"
    device_id = device.id
    registry.async_update_device(device_id, name_by_user="My Reading Light")

    updated_info = build_endpoint_device_info(
        server,
        AVE_FAMILY_THERMOSTAT,
        34,
        ave_name="Living",
    )
    sync_device_registry_name(
        hass,
        updated_info,
        config_entry_id=entry.entry_id,
    )

    updated = registry.async_get_device(identifiers=updated_info["identifiers"])
    assert updated is not None
    assert updated.id == device_id
    assert updated.name == "Thermostat Living"
    assert updated.name_by_user == "My Reading Light"
