"""Registry-level tests for naming migrations."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ave_dominaplus.const import AVE_FAMILY_THERMOSTAT, DOMAIN
from custom_components.ave_dominaplus.device_info import (
    build_endpoint_device_info,
    build_hub_device_info,
    ensure_thermostats_parent_device,
    migrate_primary_entity_areas,
    sync_device_registry_name,
)
from custom_components.ave_dominaplus.web_server import AveWebServer
from homeassistant.helpers import (
    area_registry as ar,
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


@pytest.mark.parametrize("domain", ["switch", "light", "cover", "climate"])
@pytest.mark.parametrize("device_has_area", [False, True])
async def test_primary_entity_area_migration_preserves_room_and_identity(
    hass, domain: str, device_has_area: bool
) -> None:
    """Legacy entity areas become device areas while IDs and names stay stable."""
    entry = MockConfigEntry(domain=DOMAIN, title="AVE test")
    entry.add_to_hass(hass)
    area = ar.async_get(hass).async_create("Kitchen")
    devices = dr.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "endpoint_test_light_2_34")},
        name="Kitchen lamp",
    )
    devices.async_update_device(device.id, name_by_user="Reading lamp")
    if device_has_area:
        devices.async_update_device(device.id, area_id=area.id)

    registry = er.async_get(hass)
    entity = registry.async_get_or_create(
        domain,
        DOMAIN,
        "stable-primary",
        suggested_object_id="kitchen_2",
        config_entry=entry,
        device_id=device.id,
        has_entity_name=True,
        original_name="Legacy name",
    )
    registry.async_update_entity(entity.entity_id, area_id=area.id)
    # Reproduce the 1.6.0 migration from a named entity to a primary entity.
    registry.async_get_or_create(domain, DOMAIN, entity.unique_id, original_name=None)

    migrate_primary_entity_areas(hass, entry.entry_id)
    await hass.async_block_till_done()

    migrated = registry.async_get(entity.entity_id)
    migrated_device = devices.async_get(device.id)
    assert migrated is not None
    assert migrated_device is not None
    assert migrated.entity_id == f"{domain}.kitchen_2"
    assert migrated.id == entity.id
    assert migrated.unique_id == entity.unique_id
    assert migrated.device_id == device.id
    assert migrated.name is None
    assert migrated.original_name is None
    assert migrated.area_id is None
    assert migrated_device.area_id == area.id
    assert migrated_device.name_by_user == "Reading lamp"

    # Subsequent reloads must leave the migrated registry entries alone.
    migrate_primary_entity_areas(hass, entry.entry_id)
    assert registry.async_get(entity.entity_id) is migrated
    assert devices.async_get(device.id) is migrated_device


@pytest.mark.parametrize(
    "case",
    [
        "device_area_conflict",
        "entity_area_conflict",
        "user_name",
        "original_name",
        "legacy_naming",
        "no_entity_area",
        "no_device",
        "parent_device",
        "foreign_device",
        "foreign_platform",
        "other_entry",
    ],
)
async def test_primary_entity_area_migration_preserves_other_assignments(
    hass, case: str
) -> None:
    """Conflicts, custom names and unrelated entries keep their assignments."""
    entry = MockConfigEntry(domain=DOMAIN, title="AVE test")
    entry.add_to_hass(hass)
    other_entry = MockConfigEntry(domain=DOMAIN, title="Other AVE hub")
    other_entry.add_to_hass(hass)
    areas = ar.async_get(hass)
    kitchen = areas.async_create("Kitchen")
    garage = areas.async_create("Garage")
    identifier = (DOMAIN, "endpoint_test_light_2_34")
    if case == "parent_device":
        identifier = (DOMAIN, "endpoint_test_lighting")
    elif case == "foreign_device":
        identifier = ("other_domain", "foreign_device")

    devices = dr.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={identifier},
        name="Lamp",
    )
    if case == "device_area_conflict":
        devices.async_update_device(device.id, area_id=garage.id)

    registry = er.async_get(hass)
    platform = "other_domain" if case == "foreign_platform" else DOMAIN
    entity_entry = other_entry if case == "other_entry" else entry
    entity = registry.async_get_or_create(
        "switch",
        platform,
        "stable-primary",
        config_entry=entity_entry,
        device_id=None if case == "no_device" else device.id,
        has_entity_name=case != "legacy_naming",
        original_name="Legacy name",
    )
    if case != "no_entity_area":
        registry.async_update_entity(entity.entity_id, area_id=kitchen.id)
    if case == "user_name":
        registry.async_update_entity(entity.entity_id, name="Reading light")
    if case != "original_name":
        registry.async_get_or_create(
            "switch", platform, entity.unique_id, original_name=None
        )
    if case == "entity_area_conflict":
        second = registry.async_get_or_create(
            "light",
            DOMAIN,
            "stable-secondary-primary",
            config_entry=entry,
            device_id=device.id,
            has_entity_name=True,
            original_name="Legacy name",
        )
        registry.async_update_entity(second.entity_id, area_id=garage.id)
        registry.async_get_or_create(
            "light", DOMAIN, second.unique_id, original_name=None
        )

    before_entity = registry.async_get(entity.entity_id)
    before_device = devices.async_get(device.id)
    migrate_primary_entity_areas(hass, entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(entity.entity_id) is before_entity
    assert devices.async_get(device.id) is before_device
    if case == "entity_area_conflict":
        assert registry.async_get(second.entity_id).area_id == garage.id
