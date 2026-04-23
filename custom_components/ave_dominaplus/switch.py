"""Switch platform for AVE dominaplus integration."""

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ws_commands
from .const import AVE_FAMILY_ONOFFLIGHTS, AVE_FAMILY_SCENARIO
from .device_info import (
    build_endpoint_device_info,
    ensure_lighting_parent_device,
    sync_device_registry_name,
)
from .web_server import AveWebServer

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 1


async def async_setup_entry(
    _hass: HomeAssistant | None,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AVE dominaplus binary sensors.

    Args:
        _hass: Home Assistant instance.
        entry: Config entry for the integration.
        async_add_entities: Callback to add entities to Home Assistant.

    """
    webserver: AveWebServer = entry.runtime_data
    if not webserver:
        _LOGGER.error("AVE dominaplus: Web server not initialized")
        connection_error = "Can't reach webserver"
        raise ConfigEntryNotReady(connection_error)

    await webserver.set_async_add_sw_entities(async_add_entities)
    await webserver.set_update_switch(update_switch)
    if not webserver.settings.fetch_lights:
        return
    ensure_lighting_parent_device(webserver, entry.entry_id)
    await adopt_existing_sensors(webserver, entry)


async def adopt_existing_sensors(server: AveWebServer, entry: ConfigEntry) -> None:
    """Adopt existing sensors from the entity registry."""
    try:
        entity_registry = er.async_get(server.hass)
        if entity_registry is None:
            return
        entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        for entity in entities:
            if not (entity.platform == "ave_dominaplus" and entity.domain == "switch"):
                continue
            # Check if the sensor is already registered
            if entity.unique_id not in server.switches:
                # Create a new sensor instance
                family = int(entity.unique_id.split("_")[2])
                ave_device_id = int(entity.unique_id.split("_")[3])
                name = None
                if entity.name is not None:
                    name = entity.name
                elif entity.original_name is not None:
                    name = entity.original_name

                sensor = LightSwitch(
                    unique_id=entity.unique_id,
                    family=family,
                    ave_device_id=ave_device_id,
                    is_on=None,
                    webserver=server,
                    name=name,
                )
                sensor.entity_id = entity.entity_id

                server.switches[entity.unique_id] = sensor
                server.async_add_sw_entities([sensor])
                _LOGGER.info(
                    "Adopted existing switch entity with name %s with unique_id %s",
                    sensor.name,
                    sensor.unique_id,
                )
    except Exception:
        _LOGGER.exception("Error adopting existing sensors")
        # raise ConfigEntryNotReady("Error adopting existing sensors") from e


def set_sensor_uid(webserver: AveWebServer, family, ave_device_id) -> str:
    """Set the unique ID for the sensor."""
    # TODO: This will ready up for multi-hub configurations
    # but may break existing installations
    # return f"ave_{webserver.mac_address}_switch_{family}_{ave_device_id}"
    return f"ave_switch_{family}_{ave_device_id}"


def update_switch(
    server: AveWebServer,
    family,
    ave_device_id,
    device_status,
    name=None,
    address_dec=None,
) -> None:
    """Update switch based on the family and device status."""
    if family == AVE_FAMILY_ONOFFLIGHTS:
        if not server.settings.fetch_lights:
            return
    else:
        _LOGGER.debug(
            " Not updating switch for family %s, device_id %s",
            family,
            ave_device_id,
        )
        return

    _LOGGER.debug(" Updating switch for family %s, device_id %s", family, ave_device_id)

    unique_id = set_sensor_uid(server, family, ave_device_id)
    already_exists = unique_id in server.switches
    if already_exists:
        # Update the existing sensor's state
        switch: LightSwitch = server.switches[unique_id]
        if device_status >= 0:
            switch.update_state(device_status)
        if name is not None and server.settings.get_entity_names:
            switch.set_ave_name(name)
            if not check_name_changed(server.hass, unique_id):
                switch.set_name(name)
        if address_dec is not None:
            switch.set_address_dec(address_dec)
    else:
        # Create a new switch sensor
        entity_name = None
        entity_ave_name = None
        if name is not None and server.settings.get_entity_names:
            entity_name = name
            entity_ave_name = name

        switch = LightSwitch(
            unique_id=unique_id,
            is_on=device_status,
            family=family,
            ave_device_id=ave_device_id,
            webserver=server,
            name=entity_name,
            ave_name=entity_ave_name,
            address_dec=address_dec,
        )

        _LOGGER.info("Creating new switch entity %s, unique_id %s", name, unique_id)
        server.switches[unique_id] = switch
        server.async_add_sw_entities([switch])  # Add the new sensor to Home Assistant


def check_name_changed(hass: HomeAssistant, unique_id: str) -> bool:
    """Check if the name of the sensor has changed."""
    entity_registry = er.async_get(hass)

    entry_id = entity_registry.async_get_entity_id(
        "switch", "ave_dominaplus", unique_id
    )
    if entry_id:
        entity_entry = entity_registry.async_get(entry_id)
        if entity_entry is not None:
            return (
                entity_entry.name is not None
                and entity_entry.original_name != entity_entry.name
            )
    return False


class LightSwitch(SwitchEntity):
    """Representation of a light switch."""

    _attr_has_entity_name = True
    _attr_should_poll = False

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
        """Initialize the motion detection sensor."""
        self._unique_id = unique_id
        self._is_on = is_on
        self.ave_device_id = ave_device_id
        self.family = family
        self._webserver = webserver
        self._ave_name = ave_name
        self._address_dec = address_dec
        self.hass = self._webserver.hass
        self._pending_state_write = False
        self._attr_device_info = build_endpoint_device_info(
            webserver,
            family,
            ave_device_id,
            ave_name=ave_name,
        )

        if is_on is not None and is_on >= 0:
            self._attr_is_on = bool(is_on)  # Initialize the state

        if name is None:
            if self.family == AVE_FAMILY_ONOFFLIGHTS:
                self._attr_translation_key = "light_switch"
            elif self.family == AVE_FAMILY_SCENARIO:
                self._attr_translation_key = "scenario_switch"
            else:
                self._attr_translation_key = "generic_switch"
                self._attr_translation_placeholders = {
                    "family": str(self.family),
                    "id": str(self.ave_device_id),
                }

            if not hasattr(self, "_attr_translation_placeholders"):
                self._attr_translation_placeholders = {"id": str(self.ave_device_id)}
        else:
            self._attr_name = name

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
        self._webserver.unregister_availability_entity(self)
        await super().async_will_remove_from_hass()

    async def async_toggle(self, **kwargs: Any) -> None:
        """Toggle the switch."""
        if self._webserver:
            await ws_commands.switch_toggle(self._webserver, self.ave_device_id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        if self._webserver:
            await ws_commands.switch_turn_on(self._webserver, self.ave_device_id)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        if self._webserver:
            await ws_commands.switch_turn_off(self._webserver, self.ave_device_id)

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return self._unique_id

    @property
    def available(self) -> bool:
        """Return if the backing webserver connection is available."""
        return self._webserver.connected

    @property
    def device_class(self) -> SwitchDeviceClass | None:
        """Return the device class of the sensor."""
        return SwitchDeviceClass.SWITCH

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
            "AVE webserver MAC": self._webserver.mac_address
            if self._webserver
            else None,
        }

    def update_state(self, is_on: int) -> None:
        """Update the state of the switch."""
        if is_on is None:
            return
        if is_on < 0:
            return
        self._attr_is_on = bool(is_on)  # Set the state to True (on) or False (off)
        self._write_state_or_defer()

    def set_name(self, name: str | None) -> None:
        """Set the name of the sensor."""
        if name is None:
            return
        self._attr_name = name
        self._write_state_or_defer()

    def set_ave_name(self, name: str | None) -> None:
        """Set the AVE name of the sensor."""
        if name is not None:
            self._ave_name = name
            self._sync_device_info(name)
            self._write_state_or_defer()

    def _sync_device_info(self, ave_name: str | None = None) -> None:
        """Sync device registry metadata for this light switch endpoint."""
        updated_device_info = build_endpoint_device_info(
            self._webserver,
            self.family,
            self.ave_device_id,
            ave_name=ave_name if ave_name is not None else self._ave_name,
        )
        self._attr_device_info = updated_device_info
        sync_device_registry_name(self.hass, updated_device_info)

    def set_address_dec(self, address_dec: int | None) -> None:
        """Set the address_dec attribute of the sensor."""
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
        """Build the name of the sensor based on its family and device ID."""
        suffix = f"Switch {self.family}"
        if self.family == AVE_FAMILY_ONOFFLIGHTS:
            suffix = "Light"
        elif self.family == AVE_FAMILY_SCENARIO:
            suffix = "Scenario"
        return f"{suffix} {self.ave_device_id}"
