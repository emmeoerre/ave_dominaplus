"""The AVE ws integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .web_server import AveWebServer

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SWITCH]
_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the AVE ws integration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AVE ws from a config entry."""

    webserver = AveWebServer(entry.data, hass)
    if not await webserver.authenticate():
        _LOGGER.error("AVE dominaplus: Cannot connect to the web server")

    entry.runtime_data = webserver

    # # Fetch the list of binary sensors already registered in Home Assistant
    # entity_registry = er.async_get(hass)
    # if entity_registry is not None:
    #     entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    #     registered_sensors = {
    #         entity.unique_id: {
    #             "original_name": entity.original_name,
    #             "name": entity.name,
    #         }
    #         for entity in entities
    #         if entity.platform == "ave_dominaplus" and entity.domain == "binary_sensor"
    #     }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    hass.loop.create_task(webserver.start())

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Disconnect the WebSocket server
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
