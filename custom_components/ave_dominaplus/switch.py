"""Binary sensor platform for AVE dominaplus integration."""

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import BRAND_PREFIX
from .web_server import AveWebServer

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant | None,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up AVE dominaplus binary sensors.

    Args:
        hass: Home Assistant instance.
        entry: Config entry for the integration.
        async_add_entities: Callback to add entities to Home Assistant.

    """
    webserver: AveWebServer = entry.runtime_data
    if not webserver:
        _LOGGER.error("AVE dominaplus: Web server not initialized")
        raise ConfigEntryNotReady("Can't reach webserver")

    await webserver.set_async_add_sw_entities(async_add_entities)
    await webserver.set_update_switch(update_switch)
    if not webserver.settings.fetch_lights:
        return
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
                    name=name,
                )
                sensor.hass = server.hass
                sensor.entity_id = entity.entity_id

                server.switches[entity.unique_id] = sensor
                server.async_add_sw_entities([sensor])
    except Exception as e:  # noqa: BLE001
        _LOGGER.error("Error adopting existing sensors: %s", str(e))
        # raise ConfigEntryNotReady("Error adopting existing sensors") from e


def set_sensor_uid(family, ave_device_id):
    """Set the unique ID for the sensor."""
    return f"ave_switch_{family}_{ave_device_id}"  # Unique ID for the sensor


def update_switch(
    server: AveWebServer, family, ave_device_id, device_status, name=None
):
    """Update switch based on the family and device status."""
    if family == 1:
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

    unique_id = set_sensor_uid(family, ave_device_id)
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
    else:
        # Create a new motion detection sensor
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
        )

        _LOGGER.info("Creating new switch entity %s", name)
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

    def __init__(
        self,
        unique_id: str,
        family: int,
        ave_device_id: int,
        is_on: int | None,
        name=None,
        webserver: AveWebServer | None = None,
        ave_name: str | None = None,
    ) -> None:
        """Initialize the motion detection sensor."""
        self._unique_id = unique_id
        self._is_on = is_on
        self.ave_device_id = ave_device_id
        self.family = family
        self._webserver = webserver
        self._ave_name = ave_name
        self.hass = self._webserver.hass

        if is_on is not None and is_on >= 0:
            self._attr_is_on = bool(is_on)  # Initialize the state

        if name is None:
            self._name = self.build_name()
        else:
            self._name = name

    async def async_toggle(self, **kwargs: Any) -> None:
        """Toggle the switch."""
        if self._webserver:
            await self._webserver.switch_toggle(self.ave_device_id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        if self._webserver:
            await self._webserver.switch_turn_on(self.ave_device_id)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        if self._webserver:
            await self._webserver.switch_turn_off(self.ave_device_id)

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return self._unique_id

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return self._name

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
        }

    def update_state(self, is_on: int):
        """Update the state of the switch."""
        if is_on is None:
            return
        if is_on < 0:
            return
        self._attr_is_on = bool(is_on)  # Set the state to True (on) or False (off)
        self.async_write_ha_state()

    def set_name(self, name: str | None):
        """Set the name of the sensor."""
        if name is None:
            return
        self._name = name
        self.async_write_ha_state()

    def set_ave_name(self, name: str | None):
        """Set the AVE name of the sensor."""
        if name is not None:
            self._ave_name = name
            self.async_write_ha_state()

    def build_name(self) -> str:
        """Build the name of the sensor based on its family and device ID."""
        suffix = "sensor type " + str(self.family)
        if self.family == 1:
            suffix = "light"
        elif self.family == 6:
            suffix = "sccenario"
        return f"{BRAND_PREFIX} {suffix} {self.ave_device_id}"
