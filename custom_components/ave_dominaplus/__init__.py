"""The AVE ws integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN
from .device_info import is_structural_parent_identifier
from .web_server import AveWebServer

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.COVER,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]
_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the AVE ws integration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AVE ws from a config entry."""
    webserver = AveWebServer(entry.data, hass, async_get_clientsession(hass))
    webserver.config_entry_id = entry.entry_id
    webserver.config_entry_unique_id = entry.unique_id
    if not await webserver.authenticate():
        raise ConfigEntryNotReady("Cannot connect to the AVE web server")

    entry.runtime_data = webserver
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await webserver.disconnect()
        raise

    await _async_cleanup_stale_devices(hass, entry)

    entry.async_create_background_task(
        hass,
        webserver.start(),
        "AVE Dominaplus websocket listener",
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        webserver: AveWebServer = entry.runtime_data
        await webserver.disconnect()

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    _config_entry: ConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow removing a device only when it no longer has entities."""
    entity_registry = er.async_get(hass)
    return (
        len(
            er.async_entries_for_device(
                entity_registry,
                device_entry.id,
                include_disabled_entities=True,
            )
        )
        == 0
    )


async def _async_cleanup_stale_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove stale AVE devices that are no longer linked to any entities."""
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    config_devices = list(
        dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    )
    parent_device_ids = {
        via_device_id
        for device in config_devices
        if (via_device_id := getattr(device, "via_device_id", None)) is not None
    }

    for device_entry in config_devices:
        if not any(identifier[0] == DOMAIN for identifier in device_entry.identifiers):
            continue

        if any(
            is_structural_parent_identifier(identifier)
            for identifier in device_entry.identifiers
        ):
            continue

        # Keep parent devices referenced by child endpoints (via_device).
        if device_entry.id in parent_device_ids:
            continue

        entities = er.async_entries_for_device(
            entity_registry,
            device_entry.id,
            include_disabled_entities=True,
        )
        if entities:
            continue

        _LOGGER.info(
            "Removing stale AVE device from registry",
            extra={"device_id": device_entry.id},
        )
        device_registry.async_remove_device(device_entry.id)
