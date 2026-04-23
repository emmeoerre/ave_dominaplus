"""Sensor platform for AVE dominaplus integration."""

import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import AVE_FAMILY_THERMOSTAT
from .device_info import build_endpoint_device_info
from .web_server import AveWebServer

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant | None,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AVE dominaplus number entities.

    Args:
        hass: Home Assistant instance.
        entry: Config entry for the integration.
        async_add_entities: Callback to add entities to Home Assistant.

    """
    webserver: AveWebServer = entry.runtime_data
    if not webserver:
        _LOGGER.error("AVE dominaplus: Web server not initialized")
        connection_error = "Can't reach webserver"
        raise ConfigEntryNotReady(connection_error)

    await webserver.set_async_add_number_entities(async_add_entities)
    await webserver.set_update_th_offset(update_th_offset)
    if not webserver.settings.fetch_thermostats:
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
            if not (entity.platform == "ave_dominaplus" and entity.domain == "sensor"):
                continue
            # Check if the sensor is already registered
            if entity.unique_id not in server.numbers:
                # Create a new sensor instance
                family = int(entity.unique_id.split("_")[4])
                ave_device_id = int(entity.unique_id.split("_")[5])
                name = None
                if entity.name is not None:
                    name = entity.name
                elif entity.original_name is not None:
                    name = entity.original_name

                sensor = ThermostatOffset(
                    unique_id=entity.unique_id,
                    family=family,
                    ave_device_id=ave_device_id,
                    webserver=server,
                    name=name,
                    value=None,
                )
                sensor.entity_id = entity.entity_id

                server.numbers[entity.unique_id] = sensor
                server.async_add_number_entities([sensor])
                _LOGGER.info(
                    "Adopted existing number entity with name %s with unique_id %s",
                    sensor.name,
                    sensor.unique_id,
                )
    except Exception:
        _LOGGER.exception("Error adopting existing sensors")
        # raise ConfigEntryNotReady("Error adopting existing sensors") from e


def set_sensor_uid(webserver: AveWebServer, family, ave_device_id) -> str:
    """Set the unique ID for the sensor."""
    if family == AVE_FAMILY_THERMOSTAT:
        return f"ave_{webserver.mac_address}_thermostat_offset_{family}_{ave_device_id}"
    return f"ave_{webserver.mac_address}_number_{family}_{ave_device_id}"


def update_th_offset(
    server: AveWebServer,
    family,
    ave_device_id,
    offset_value,
    name=None,
    address_dec: int | None = None,
) -> None:
    """Update switch based on the family and device status."""
    if family == AVE_FAMILY_THERMOSTAT:
        if not server.settings.fetch_thermostats:
            return
    else:
        _LOGGER.debug(
            " Not updating number entity for family %s, device_id %s",
            family,
            ave_device_id,
        )
        return

    _LOGGER.debug(
        " Updating number entity for family %s, device_id %s",
        family,
        ave_device_id,
    )

    unique_id = set_sensor_uid(server, family, ave_device_id)
    already_exists = unique_id in server.numbers
    if already_exists:
        # Update the existing sensor's state
        number: ThermostatOffset = server.numbers[unique_id]
        number.update_value(offset_value)
        if address_dec is not None:
            number.set_address_dec(address_dec)
    else:
        # Create a new switch sensor
        entity_ave_name = None
        if name is not None and server.settings.get_entity_names:
            entity_ave_name = name

        number = ThermostatOffset(
            unique_id=unique_id,
            family=family,
            ave_device_id=ave_device_id,
            webserver=server,
            name=None,
            ave_name=entity_ave_name,
            value=offset_value,
            address_dec=address_dec,
        )

        _LOGGER.info("Creating new number entity %s", name)
        server.numbers[unique_id] = number
        server.async_add_number_entities(
            [number]
        )  # Add the new sensor to Home Assistant


def check_name_changed(hass: HomeAssistant, unique_id: str) -> bool:
    """Check if the name of the sensor has changed."""
    entity_registry = er.async_get(hass)

    entry_id = entity_registry.async_get_entity_id(
        "sensor", "ave_dominaplus", unique_id
    )
    if entry_id:
        entity_entry = entity_registry.async_get(entry_id)
        if entity_entry is not None:
            return (
                entity_entry.name is not None
                and entity_entry.original_name != entity_entry.name
            )
    return False


class ThermostatOffset(SensorEntity):
    """Representation of a thermostat offset."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    _attr_native_max_value = 5.0
    _attr_native_min_value = -5.0
    _attr_native_step = 0.1
    _attr_native_unit_of_measurement = "°C"

    def __init__(
        self,
        unique_id: str,
        family: int,
        ave_device_id: int,
        webserver: AveWebServer,
        name=None,
        ave_name: str | None = None,
        value: float | None = None,
        address_dec: int | None = None,
    ) -> None:
        """Initialize the thermostat offset."""
        self._unique_id = unique_id
        self.ave_device_id = ave_device_id
        self.family = family
        self._ave_name = ave_name
        self._webserver = webserver
        self.hass = self._webserver.hass
        self._address_dec = address_dec
        self._pending_state_write = False
        self._attr_device_info = build_endpoint_device_info(
            webserver,
            family,
            ave_device_id,
            ave_name=ave_name,
        )

        if name is None:
            if webserver.settings.get_entity_names:
                self._attr_name = (
                    f"Thermostat offset {self._ave_name or self.ave_device_id}"
                )
            else:
                self._attr_name = self.build_name()
        else:
            self._attr_name = name

        if value is not None:
            self.update_value(value, first_update=True)

    async def async_added_to_hass(self) -> None:
        """Handle entity added to Home Assistant."""
        await super().async_added_to_hass()
        self._webserver.register_availability_entity(self)
        if self._pending_state_write:
            self._pending_state_write = False
            self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Handle entity removal from Home Assistant."""
        self._webserver.unregister_availability_entity(self)
        await super().async_will_remove_from_hass()

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return self._unique_id

    @property
    def available(self) -> bool:
        """Return if the backing webserver connection is available."""
        return self._webserver.connected

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Return the device class of the sensor."""
        return SensorDeviceClass.TEMPERATURE_DELTA

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        return {
            "AVE_source_device_family": self.family,
            "AVE_source_device_id": self.ave_device_id,
            "AVE_source_name": self._ave_name,
            "AVE webserver MAC": self._webserver.mac_address
            if self._webserver
            else None,
            "AVE address_dec": self._address_dec,
            "AVE address_hex": format(self._address_dec & 0xFF, "02X")
            if self._address_dec is not None
            else "",
        }

    def update_value(self, offset_value: float, first_update=False) -> None:
        """Update the state of the thermostat offset."""
        if offset_value is None:
            return
        self._attr_native_value = offset_value
        if not first_update:
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
            self._ave_name = name + " offset"
            self._write_state_or_defer()

    def set_address_dec(self, address_dec: int | None) -> None:
        """Set the address_dec attribute of the sensor."""
        if address_dec is not None and self._address_dec != address_dec:
            self._address_dec = address_dec
            self._write_state_or_defer()

    def build_name(self) -> str:
        """Build the name of the sensor based on its family and device ID."""
        device_name = self._ave_name or self.ave_device_id
        return f"Thermostat Offset {device_name}"

    def _write_state_or_defer(self) -> None:
        """Write state now when possible, otherwise defer until entity attach."""
        if self.hass is None or self.entity_id is None:
            self._pending_state_write = True
            return
        self.async_write_ha_state()
