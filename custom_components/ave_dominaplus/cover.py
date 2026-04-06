"""Cover platform for AVE Dominaplus integration (shutters/blinds)."""

import logging
from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    AVE_FAMILY_SHUTTER_16,
    AVE_FAMILY_SHUTTER_19,
    AVE_FAMILY_SHUTTER_3,
    BRAND_PREFIX,
)
from .web_server import AveWebServer

_LOGGER = logging.getLogger(__name__)

# AVE shutter status values received via UPD WS and GSF responses.
# Verified by capturing WebSocket traffic on a live AVE Dominaplus system.
# AVE convention: 1 = raised/open, 2 or 3 = lowered/closed
AVE_SHUTTER_STATUS_OPEN = 1       # fully raised (shutter up, light passes through)
AVE_SHUTTER_STATUS_CLOSED = 2     # fully lowered (shutter down)
AVE_SHUTTER_STATUS_CLOSED_ALT = 3 # fully lowered, alternate value seen in some firmware
AVE_SHUTTER_STATUS_MOVING = 4     # in motion
AVE_SHUTTER_STATUS_STOPPED = 5    # stopped halfway

# EAI command action codes for shutters.
# Verified by capturing WebSocket traffic on a live AVE Dominaplus system.
# 8 = raise (open) — also stops if shutter is moving down
# 9 = lower (close) — also stops if shutter is moving up
# AVE has no dedicated stop command; both 8 and 9 act as stop when moving.
AVE_SHUTTER_CMD_OPEN = "8"
AVE_SHUTTER_CMD_CLOSE = "9"
AVE_SHUTTER_CMD_STOP = "9"

SHUTTER_FAMILIES = {AVE_FAMILY_SHUTTER_3, AVE_FAMILY_SHUTTER_16, AVE_FAMILY_SHUTTER_19}


async def async_setup_entry(
    _hass: HomeAssistant | None,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up AVE Dominaplus cover entities.

    Args:
        _hass: Home Assistant instance.
        entry: Config entry for the integration.
        async_add_entities: Callback to add entities to Home Assistant.

    """
    webserver: AveWebServer = entry.runtime_data
    if not webserver:
        _LOGGER.error("AVE Dominaplus: Web server not initialized")
        connection_error = "Can't reach webserver"
        raise ConfigEntryNotReady(connection_error)

    await webserver.set_async_add_cover_entities(async_add_entities)
    await webserver.set_update_cover(update_cover)

    if not webserver.settings.fetch_shutters:
        return

    await adopt_existing_covers(webserver, entry)


async def adopt_existing_covers(server: AveWebServer, entry: ConfigEntry) -> None:
    """Adopt existing cover entities from the entity registry on restart."""
    try:
        entity_registry = er.async_get(server.hass)
        if entity_registry is None:
            return
        entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        for entity in entities:
            if not (entity.platform == "ave_dominaplus" and entity.domain == "cover"):
                continue
            if entity.unique_id not in server.covers:
                family = int(entity.unique_id.split("_")[2])
                ave_device_id = int(entity.unique_id.split("_")[3])
                name = entity.name or entity.original_name

                cover = AveShutter(
                    unique_id=entity.unique_id,
                    family=family,
                    ave_device_id=ave_device_id,
                    status=None,
                    webserver=server,
                    name=name,
                )
                cover.entity_id = entity.entity_id
                server.covers[entity.unique_id] = cover
                server.async_add_cover_entities([cover])
                _LOGGER.info(
                    "Adopted existing cover entity '%s' (unique_id=%s)",
                    cover.name,
                    cover.unique_id,
                )
    except Exception:
        _LOGGER.exception("Error adopting existing cover entities")


def set_cover_uid(family: int, ave_device_id: int) -> str:
    """Build a unique ID for a cover entity."""
    return f"ave_cover_{family}_{ave_device_id}"


def update_cover(
    server: AveWebServer,
    family: int,
    ave_device_id: int,
    device_status: int,
    name: str | None = None,
) -> None:
    """Create or update a cover entity based on incoming AVE data."""
    if family not in SHUTTER_FAMILIES:
        _LOGGER.debug(
            "Not updating cover for family %s, device_id %s", family, ave_device_id
        )
        return

    if not server.settings.fetch_shutters:
        return

    _LOGGER.debug("Updating cover family=%s device_id=%s status=%s", family, ave_device_id, device_status)

    unique_id = set_cover_uid(family, ave_device_id)
    if unique_id in server.covers:
        cover: AveShutter = server.covers[unique_id]
        if device_status >= 0:
            cover.update_status(device_status)
        if name is not None and server.settings.get_entity_names:
            cover.set_ave_name(name)
            if not _check_name_changed(server.hass, unique_id):
                cover.set_name(name)
    else:
        entity_name = name if (name and server.settings.get_entity_names) else None
        cover = AveShutter(
            unique_id=unique_id,
            family=family,
            ave_device_id=ave_device_id,
            status=device_status,
            webserver=server,
            name=entity_name,
            ave_name=entity_name,
        )
        _LOGGER.info("Creating new cover entity '%s' (unique_id=%s)", name, unique_id)
        server.covers[unique_id] = cover
        server.async_add_cover_entities([cover])


def _check_name_changed(hass: HomeAssistant, unique_id: str) -> bool:
    """Return True if the user has customised the entity name in the registry."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("cover", "ave_dominaplus", unique_id)
    if entity_id:
        entry = registry.async_get(entity_id)
        if entry is not None:
            return entry.name is not None and entry.original_name != entry.name
    return False


class AveShutter(CoverEntity):
    """Representation of an AVE Dominaplus shutter/blind."""

    _attr_should_poll = False
    _attr_device_class = CoverDeviceClass.SHUTTER
    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )
    _attr_is_closed: bool | None = None
    _attr_is_opening: bool = False
    _attr_is_closing: bool = False

    def __init__(
        self,
        unique_id: str,
        family: int,
        ave_device_id: int,
        status: int | None,
        webserver: AveWebServer,
        name: str | None = None,
        ave_name: str | None = None,
    ) -> None:
        """Initialise the shutter entity."""
        self._unique_id = unique_id
        self.family = family
        self.ave_device_id = ave_device_id
        self._webserver = webserver
        self._ave_name = ave_name
        self.hass = webserver.hass
        self._name = name if name is not None else self._build_name()

        if status is not None and status >= 0:
            self._apply_status(status)

    # ------------------------------------------------------------------
    # HA entity properties
    # ------------------------------------------------------------------

    @property
    def unique_id(self) -> str:
        """Return the unique ID."""
        return self._unique_id

    @property
    def name(self) -> str:
        """Return the display name."""
        return self._name

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose AVE-specific attributes for diagnostics."""
        return {
            "AVE_family": self.family,
            "AVE_device_id": self.ave_device_id,
            "AVE_name": self._ave_name,
            "AVE webserver MAC": (
                self._webserver.mac_address if self._webserver else None
            ),
        }

    # ------------------------------------------------------------------
    # Cover actions
    # ------------------------------------------------------------------

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Send open (up) command."""
        if self._webserver:
            await self._webserver.shutter_open(self.ave_device_id)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Send close (down) command."""
        if self._webserver:
            await self._webserver.shutter_close(self.ave_device_id)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Send stop command."""
        if self._webserver:
            await self._webserver.shutter_stop(self.ave_device_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def update_status(self, status: int) -> None:
        """Apply a raw AVE status value and push the new state to HA."""
        if status < 0:
            return
        self._apply_status(status)
        self.async_write_ha_state()

    def _apply_status(self, status: int) -> None:
        """Map AVE status integer to HA cover state flags.

        AVE status values (verified from WebSocket traffic):
          1 = fully open
          2 = fully closed
          3 = fully closed (alternate firmware value)
          4 = in motion
          5 = stopped halfway

        When is_closed is None, HA shows both open and close buttons,
        which is the correct behaviour for status 4 and 5.
        """
        if status in (AVE_SHUTTER_STATUS_CLOSED, AVE_SHUTTER_STATUS_CLOSED_ALT):
            self._attr_is_closed = True
            self._attr_is_opening = False
            self._attr_is_closing = False
        elif status == AVE_SHUTTER_STATUS_OPEN:
            self._attr_is_closed = False
            self._attr_is_opening = False
            self._attr_is_closing = False
        else:
            # Status 4 (moving) or 5 (stopped halfway): unknown position.
            # Setting is_closed=None makes HA show both open and close buttons.
            self._attr_is_closed = None
            self._attr_is_opening = False
            self._attr_is_closing = False

    def set_name(self, name: str | None) -> None:
        """Update the display name."""
        if name is None:
            return
        self._name = name
        self.async_write_ha_state()

    def set_ave_name(self, name: str | None) -> None:
        """Update the stored AVE name."""
        if name is not None:
            self._ave_name = name
            self.async_write_ha_state()

    def _build_name(self) -> str:
        """Build a default name when none is provided by the webserver."""
        return f"{BRAND_PREFIX} shutter {self.ave_device_id}"
