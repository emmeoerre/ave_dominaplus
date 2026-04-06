"""The AVE ws integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .web_server import AveWebServer

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.COVER,
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
    webserver = AveWebServer(entry.data, hass)
    if not await webserver.authenticate():
        _LOGGER.error("AVE dominaplus: Cannot connect to the web server")

    entry.runtime_data = webserver
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    hass.loop.create_task(webserver.start())
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Disconnect the WebSocket server
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
