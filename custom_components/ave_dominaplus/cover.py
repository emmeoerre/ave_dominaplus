"""Cover platform for AVE dominaplus integration."""

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
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ws_commands
from .const import (
    AVE_FAMILY_SHUTTER_HUNG,
    AVE_FAMILY_SHUTTER_ROLLING,
    AVE_FAMILY_SHUTTER_SLIDING,
)
from .device_info import (
    build_endpoint_device_info,
    ensure_covers_parent_device,
    sync_device_registry_name,
)
from .uid_v2 import build_uid, find_unique_id, parse_uid
from .web_server import AveWebServer

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 1

COVER_FAMILIES = (
    AVE_FAMILY_SHUTTER_ROLLING,
    AVE_FAMILY_SHUTTER_SLIDING,
    AVE_FAMILY_SHUTTER_HUNG,
)


async def async_setup_entry(
    _hass: HomeAssistant | None,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AVE dominaplus covers."""
    webserver: AveWebServer = entry.runtime_data
    if not webserver:
        _LOGGER.error("AVE dominaplus: Web server not initialized")
        connection_error = "Can't reach webserver"
        raise ConfigEntryNotReady(connection_error)

    await webserver.set_async_add_cv_entities(async_add_entities)
    await webserver.set_update_cover(update_cover)
    if not webserver.settings.fetch_covers:
        return

    ensure_covers_parent_device(webserver, entry.entry_id)

    await adopt_existing_covers(webserver, entry)


async def adopt_existing_covers(server: AveWebServer, entry: ConfigEntry) -> None:
    """Adopt existing cover entities from the entity registry."""
    try:
        entity_registry = er.async_get(server.hass)
        if entity_registry is None:
            return
        entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        for entity in entities:
            if not (entity.platform == "ave_dominaplus" and entity.domain == "cover"):
                continue
            if entity.unique_id in server.covers:
                continue

            try:
                parsed_uid = parse_uid(entity.unique_id)
                if parsed_uid is None:
                    continue
                uid_mac, family, ave_device_id, ave_address_dec, uid_suffix = parsed_uid
            except ValueError:
                continue

            if uid_suffix is not None:
                continue

            if uid_mac and server.mac_address and uid_mac != server.mac_address:
                _LOGGER.debug(
                    "Skipping cover with unique_id %s due to MAC mismatch (%s != %s)",
                    entity.unique_id,
                    uid_mac,
                    server.mac_address,
                )
                continue

            if family not in COVER_FAMILIES:
                continue

            name = None
            if entity.name is not None:
                name = entity.name
            elif entity.original_name is not None:
                name = entity.original_name

            cover = AveCover(
                unique_id=entity.unique_id,
                family=family,
                ave_device_id=ave_device_id,
                position=None,
                webserver=server,
                name=name,
                address_dec=ave_address_dec,
            )
            cover.entity_id = entity.entity_id

            server.covers[entity.unique_id] = cover
            server.async_add_cv_entities([cover])
            _LOGGER.info(
                "Adopted existing cover entity with name %s with unique_id %s",
                cover.name,
                cover.unique_id,
            )
    except Exception:
        _LOGGER.exception("Error adopting existing cover entities")


def update_cover(
    server: AveWebServer,
    family: int,
    ave_device_id: int,
    device_status: int,
    name: str | None = None,
    address_dec: int | None = None,
) -> None:
    """Create or update cover entities from webserver events."""
    if family not in COVER_FAMILIES:
        _LOGGER.debug(
            "Not updating cover for family %s, device_id %s",
            family,
            ave_device_id,
        )
        return

    if not server.settings.fetch_covers:
        return

    unique_id = None
    if address_dec is not None:
        unique_id = build_uid(server.mac_address, family, ave_device_id, address_dec)
        if unique_id not in server.covers:
            existing_unique_id = find_unique_id(
                server.covers,
                family,
                ave_device_id,
                server.mac_address or None,
            )
            if existing_unique_id is not None:
                unique_id = existing_unique_id
    else:
        unique_id = find_unique_id(
            server.covers,
            family,
            ave_device_id,
            server.mac_address or None,
        )

    already_exists = unique_id in server.covers if unique_id is not None else False

    if already_exists and unique_id is not None:
        allow_name_update = (
            name is not None
            and server.settings.get_entity_names
            and not check_name_changed(server.hass, unique_id)
        )
        cover = server.covers.get(unique_id)
        if cover is None:
            return

        try:
            cover.handle_webserver_update(
                device_status=device_status,
                name=name,
                address_dec=address_dec,
                allow_name_update=allow_name_update,
            )
        except Exception:
            _LOGGER.exception(
                "Failed updating cover entity; dropping stale runtime reference",
                extra={"unique_id": unique_id},
            )
            server.covers.pop(unique_id, None)
    else:
        if address_dec is None:
            _LOGGER.error(
                "Cannot create cover entity for family %s, device_id %s without address_dec",
                family,
                ave_device_id,
            )
            return
        if unique_id is None:
            unique_id = build_uid(
                server.mac_address, family, ave_device_id, address_dec
            )

        entity_name = None
        entity_ave_name = None
        if name is not None and server.settings.get_entity_names:
            entity_name = name
            entity_ave_name = name

        cover = AveCover(
            unique_id=unique_id,
            family=family,
            ave_device_id=ave_device_id,
            position=device_status,
            webserver=server,
            name=entity_name,
            ave_name=entity_ave_name,
            address_dec=address_dec,
        )

        _LOGGER.info("Creating new cover entity %s with unique_id %s", name, unique_id)
        server.covers[unique_id] = cover
        server.async_add_cv_entities([cover])


def check_name_changed(hass: HomeAssistant, unique_id: str) -> bool:
    """Check if the name of the entity has changed in HA registry."""
    entity_registry = er.async_get(hass)

    entry_id = entity_registry.async_get_entity_id("cover", "ave_dominaplus", unique_id)
    if entry_id:
        entity_entry = entity_registry.async_get(entry_id)
        if entity_entry is not None:
            return (
                entity_entry.name is not None
                and entity_entry.original_name != entity_entry.name
            )
    return False


class AveCover(CoverEntity):
    """Representation of an AVE cover."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )

    def __init__(
        self,
        unique_id: str,
        family: int,
        ave_device_id: int,
        position: int | None,
        webserver: AveWebServer,
        name: str | None = None,
        ave_name: str | None = None,
        address_dec: int | None = None,
    ) -> None:
        """Initialize the cover entity."""
        self._unique_id = unique_id
        self.ave_device_id = ave_device_id
        self.family = family
        self._webserver = webserver
        self.hass = self._webserver.hass
        self._ave_name = ave_name
        self._address_dec = address_dec
        self._pending_state_write = False
        self._attr_device_info = build_endpoint_device_info(
            webserver,
            family,
            ave_device_id,
            ave_name=ave_name,
        )

        self._attr_device_class = CoverDeviceClass.SHUTTER

        if name is None:
            if self.family == AVE_FAMILY_SHUTTER_ROLLING:
                self._attr_translation_key = "shutter"
            elif self.family == AVE_FAMILY_SHUTTER_SLIDING:
                self._attr_translation_key = "blind"
            elif self.family == AVE_FAMILY_SHUTTER_HUNG:
                self._attr_translation_key = "window"
            else:
                self._attr_translation_key = "cover"
        else:
            self._attr_name = name

        self._position = 3
        if position is not None:
            self.update_state(position)

    async def async_added_to_hass(self) -> None:
        """Handle entity added to Home Assistant."""
        await super().async_added_to_hass()
        self._webserver.register_availability_entity(self)
        self._sync_device_info()
        if self._pending_state_write:
            self._pending_state_write = False
            self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Handle entity removal from Home Assistant."""
        self._webserver.covers.pop(self._unique_id, None)
        self._webserver.unregister_availability_entity(self)
        await super().async_will_remove_from_hass()

    def handle_webserver_update(
        self,
        *,
        device_status: int,
        name: str | None = None,
        address_dec: int | None = None,
        allow_name_update: bool = False,
    ) -> None:
        """Apply a websocket cover update in a single guarded path."""
        if device_status in (1, 2, 3, 4, 5):
            self.update_state(device_status)

        if name is not None and self._webserver.settings.get_entity_names:
            self.set_ave_name(name)
            if allow_name_update:
                self.set_name(name)

        if address_dec is not None:
            self.set_address_dec(address_dec)

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        if self._webserver:
            await ws_commands.cover_open(self._webserver, self.ave_device_id)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        if self._webserver:
            await ws_commands.cover_close(self._webserver, self.ave_device_id)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover following AVE direction-sensitive behavior."""
        if not self._webserver:
            return

        if self._position == 2:
            stop_command = "8"
        elif self._position == 4:
            stop_command = "9"
        else:
            return

        await ws_commands.cover_stop(self._webserver, self.ave_device_id, stop_command)

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the entity."""
        return self._unique_id

    @property
    def available(self) -> bool:
        """Return if the backing webserver connection is available."""
        return self._webserver.connected

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is fully closed."""
        return self._position == 3

    @property
    def is_opening(self) -> bool:
        """Return if the cover is opening."""
        return self._position == 2

    @property
    def is_closing(self) -> bool:
        """Return if the cover is closing."""
        return self._position == 4

    @property
    def current_cover_position(self) -> int | None:
        """Return HA cover position.

        AVE reports discrete states instead of full percentages.
        """
        if self._position == 1:
            return 100
        if self._position == 3:
            return 0
        return 50

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        return {
            "AVE_family": self.family,
            "AVE_device_id": self.ave_device_id,
            "AVE_name": self._ave_name,
            "AVE address_dec": self._address_dec,
            "AVE address_hex": format(self._address_dec & 0xFF, "02X")
            if self._address_dec is not None
            else "",
            "AVE webserver MAC": self._webserver.mac_address,
        }

    def update_state(self, value: int) -> None:
        """Update cover state from AVE value (1..5)."""
        if value is None:
            return
        value = int(value)
        if value < 1 or value > 5:
            return

        if self._position != value:
            self._position = value
            self._write_state_or_defer()

    def set_name(self, name: str | None) -> None:
        """Set the entity name."""
        if name is None:
            return
        self._attr_name = name
        self._sync_device_info(name)
        self._write_state_or_defer()

    def set_ave_name(self, name: str | None) -> None:
        """Set AVE native name."""
        if name is not None:
            self._ave_name = name
            self._sync_device_info(name)
            self._write_state_or_defer()

    def _sync_device_info(self, ave_name: str | None = None) -> None:
        """Sync device registry metadata for this cover endpoint."""
        if self.hass is None:
            return

        updated_device_info = build_endpoint_device_info(
            self._webserver,
            self.family,
            self.ave_device_id,
            ave_name=ave_name if ave_name is not None else self._ave_name,
        )
        identifiers = self._attr_device_info.get("identifiers")
        if not identifiers:
            return

        sync_device_registry_name(
            self.hass,
            updated_device_info,
            identifiers=identifiers,
        )
        self._attr_device_info = updated_device_info

    def set_address_dec(self, address_dec: int | None) -> None:
        """Set the AVE decimal address."""
        if address_dec is not None and self._address_dec != address_dec:
            self._address_dec = address_dec
            self._write_state_or_defer()

    def _write_state_or_defer(self) -> None:
        """Write state now when possible, otherwise defer until entity attach."""
        if self.hass is None or self.entity_id is None:
            self._pending_state_write = True
            return
        self.async_write_ha_state()

    def build_name(self) -> str:
        """Build default entity name."""
        if self.family == AVE_FAMILY_SHUTTER_ROLLING:
            suffix = "Shutter"
        elif self.family == AVE_FAMILY_SHUTTER_SLIDING:
            suffix = "Blind"
        elif self.family == AVE_FAMILY_SHUTTER_HUNG:
            suffix = "Window"
        else:
            suffix = "Cover"
        return f"{suffix} {self.ave_device_id}"
