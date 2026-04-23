"""Light platform for AVE dominaplus integration."""

import logging
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ws_commands
from .const import AVE_FAMILY_DIMMER, AVE_FAMILY_ONOFFLIGHTS
from .device_info import (
    build_endpoint_device_info,
    ensure_lighting_parent_device,
    sync_device_registry_name,
)
from .uid_v2 import build_uid, find_unique_id, parse_uid
from .web_server import AveWebServer

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 1


async def async_setup_entry(
    _hass: HomeAssistant | None,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AVE dominaplus dimmer lights."""
    webserver: AveWebServer = entry.runtime_data
    if not webserver:
        _LOGGER.error("AVE dominaplus: Web server not initialized")
        connection_error = "Can't reach webserver"
        raise ConfigEntryNotReady(connection_error)

    await webserver.set_async_add_lg_entities(async_add_entities)
    await webserver.set_update_light(update_light)
    if not webserver.settings.fetch_lights:
        return

    ensure_lighting_parent_device(webserver, entry.entry_id)

    await adopt_existing_lights(webserver, entry)


async def adopt_existing_lights(server: AveWebServer, entry: ConfigEntry) -> None:
    """Adopt existing light entities from the entity registry."""
    try:
        entity_registry = er.async_get(server.hass)
        if entity_registry is None:
            return
        entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        for entity in entities:
            if not (entity.platform == "ave_dominaplus" and entity.domain == "light"):
                continue
            if entity.unique_id in server.lights:
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
                    "Skipping light with unique_id %s due to MAC mismatch (%s != %s)",
                    entity.unique_id,
                    uid_mac,
                    server.mac_address,
                )
                continue

            if family not in (AVE_FAMILY_DIMMER, AVE_FAMILY_ONOFFLIGHTS):
                continue

            name = None
            if entity.name is not None:
                name = entity.name
            elif entity.original_name is not None:
                name = entity.original_name

            light = DimmerLight(
                unique_id=entity.unique_id,
                family=family,
                ave_device_id=ave_device_id,
                is_on=None,
                webserver=server,
                name=name,
                address_dec=ave_address_dec,
            )
            light.entity_id = entity.entity_id

            server.lights[entity.unique_id] = light
            server.async_add_lg_entities([light])
            _LOGGER.info(
                "Adopted existing light entity with name %s with unique_id %s",
                light.name,
                light.unique_id,
            )
    except Exception:
        _LOGGER.exception("Error adopting existing light entities")


def update_light(
    server: AveWebServer,
    family: int,
    ave_device_id: int,
    device_status: int,
    name: str | None = None,
    address_dec: int | None = None,
) -> None:
    """Create or update light entities from webserver events."""
    if family not in (AVE_FAMILY_DIMMER, AVE_FAMILY_ONOFFLIGHTS):
        _LOGGER.debug(
            "Not updating light for family %s, device_id %s",
            family,
            ave_device_id,
        )
        return

    if not server.settings.fetch_lights:
        return

    unique_id = None
    if address_dec is not None:
        unique_id = build_uid(server.mac_address, family, ave_device_id, address_dec)
        if unique_id not in server.lights:
            existing_unique_id = find_unique_id(
                server.lights,
                family,
                ave_device_id,
                server.mac_address or None,
            )
            if existing_unique_id is not None:
                unique_id = existing_unique_id
    else:
        unique_id = find_unique_id(
            server.lights,
            family,
            ave_device_id,
            server.mac_address or None,
        )

    already_exists = unique_id in server.lights if unique_id is not None else False

    if already_exists and unique_id is not None:
        allow_name_update = (
            name is not None
            and server.settings.get_entity_names
            and not check_name_changed(server.hass, unique_id)
        )

        light: DimmerLight = server.lights[unique_id]
        light.handle_webserver_update(
            device_status=device_status,
            name=name,
            address_dec=address_dec,
            allow_name_update=allow_name_update,
        )
    else:
        if address_dec is None:
            _LOGGER.error(
                "Cannot create light entity for family %s, device_id %s without address_dec",
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

        light = DimmerLight(
            unique_id=unique_id,
            family=family,
            ave_device_id=ave_device_id,
            is_on=device_status,
            webserver=server,
            name=entity_name,
            ave_name=entity_ave_name,
            address_dec=address_dec,
        )

        _LOGGER.info("Creating new light entity %s with unique_id %s", name, unique_id)
        server.lights[unique_id] = light
        server.async_add_lg_entities([light])


def check_name_changed(hass: HomeAssistant, unique_id: str) -> bool:
    """Check if the name of the entity has changed in HA registry."""
    entity_registry = er.async_get(hass)

    entry_id = entity_registry.async_get_entity_id("light", "ave_dominaplus", unique_id)
    if entry_id:
        entity_entry = entity_registry.async_get(entry_id)
        if entity_entry is not None:
            return (
                entity_entry.name is not None
                and entity_entry.original_name != entity_entry.name
            )
    return False


class DimmerLight(LightEntity):
    """Representation of an AVE dimmer light."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(
        self,
        unique_id: str,
        family: int,
        ave_device_id: int,
        is_on: int | None,
        webserver: AveWebServer,
        name=None,
        ave_name: str | None = None,
        address_dec: int | None = None,
    ) -> None:
        """Initialize the dimmer light."""
        self._unique_id = unique_id
        self.ave_device_id = ave_device_id
        self.family = family
        self._webserver = webserver
        self.hass = self._webserver.hass
        self._ave_name = ave_name
        self._address_dec = address_dec
        self._brightness = None
        self._pending_state_write = False
        self._attr_device_info = build_endpoint_device_info(
            webserver,
            family,
            ave_device_id,
            ave_name=ave_name,
        )

        if self.family == AVE_FAMILY_DIMMER:
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS
        else:
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_color_mode = ColorMode.ONOFF

        if name is None:
            if self.family == AVE_FAMILY_ONOFFLIGHTS:
                self._attr_translation_key = "light"
            else:
                self._attr_translation_key = "dimmer"
        else:
            self._attr_name = name

        self._attr_is_on = False
        if is_on is not None and is_on >= 0:
            self.update_state(is_on)

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
        self._webserver.lights.pop(self._unique_id, None)
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
        """Apply a websocket light update routed through lifecycle subscriptions."""
        if device_status >= 0:
            self.update_state(device_status)

        if name is not None and self._webserver.settings.get_entity_names:
            self.set_ave_name(name)
            if allow_name_update:
                self.set_name(name)

        if address_dec is not None:
            self.set_address_dec(address_dec)

    async def async_toggle(self, **kwargs: Any) -> None:
        """Toggle the light."""
        if not self._webserver:
            return

        if self.family == AVE_FAMILY_ONOFFLIGHTS:
            await ws_commands.switch_toggle(self._webserver, self.ave_device_id)
        elif self.family == AVE_FAMILY_DIMMER:
            await ws_commands.dimmer_toggle(self._webserver, self.ave_device_id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on, optionally setting brightness."""
        if not self._webserver:
            return

        if self.family == AVE_FAMILY_ONOFFLIGHTS:
            await ws_commands.switch_turn_on(self._webserver, self.ave_device_id)
            return

        if self.family == AVE_FAMILY_DIMMER:
            brightness_ha = kwargs.get(ATTR_BRIGHTNESS)
            if brightness_ha is None:
                await ws_commands.dimmer_turn_on(
                    self._webserver, self.ave_device_id, 31
                )
                return

            brightness_ave = max(1, int((int(brightness_ha) / 255) * 31))
            await ws_commands.dimmer_turn_on(
                self._webserver, self.ave_device_id, brightness_ave
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        if not self._webserver:
            return

        if self.family == AVE_FAMILY_ONOFFLIGHTS:
            await ws_commands.switch_turn_off(self._webserver, self.ave_device_id)
        elif self.family == AVE_FAMILY_DIMMER:
            await ws_commands.dimmer_turn_off(self._webserver, self.ave_device_id)

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the entity."""
        return self._unique_id

    @property
    def available(self) -> bool:
        """Return if the backing webserver connection is available."""
        return self._webserver.connected

    @property
    def brightness(self) -> int | None:
        """Return the current brightness in HA scale (0..255)."""
        return self._brightness

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
        """Update internal on/off and brightness state."""
        if value is None or int(value) < 0:
            return

        value = int(value)
        changed = False

        new_is_on = value > 0
        if self._attr_is_on != new_is_on:
            self._attr_is_on = new_is_on
            changed = True

        if self.family == AVE_FAMILY_DIMMER and value > 0:
            new_brightness = int((max(0, min(value, 31)) / 31) * 255)
            if self._brightness != new_brightness:
                self._brightness = new_brightness
                changed = True

        if changed:
            self._write_state_or_defer()

    def set_name(self, name: str | None) -> None:
        """Set the entity name."""
        if name is None:
            return
        self._attr_name = name
        self._write_state_or_defer()

    def set_ave_name(self, name: str | None) -> None:
        """Set AVE native name."""
        if name is not None:
            self._ave_name = name
            self._sync_device_info(name)
            self._write_state_or_defer()

    def _sync_device_info(self, ave_name: str | None = None) -> None:
        """Sync device registry metadata for this light endpoint."""
        updated_device_info = build_endpoint_device_info(
            self._webserver,
            self.family,
            self.ave_device_id,
            ave_name=ave_name if ave_name is not None else self._ave_name,
        )
        self._attr_device_info = updated_device_info
        sync_device_registry_name(self.hass, updated_device_info)

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
        if self.family == AVE_FAMILY_ONOFFLIGHTS:
            return f"Light {self.ave_device_id}"
        return f"Dimmer {self.ave_device_id}"
