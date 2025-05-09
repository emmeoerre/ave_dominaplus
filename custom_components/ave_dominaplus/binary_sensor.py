"""Binary sensor platform for AVE dominaplus integration."""

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.dt import utcnow

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
    await webserver.set_update_binary_sensor(update_binary_sensor)
    await webserver.set_async_add_bs_entities(async_add_entities)
    await adopt_existing_sensors(webserver, entry)
    status_sensor = AveHubStatusBinarySensor(webserver, entry)
    async_add_entities([status_sensor])


async def adopt_existing_sensors(server: AveWebServer, entry: ConfigEntry) -> None:
    """Adopt existing sensors from the entity registry."""
    try:
        entity_registry = er.async_get(server.hass)
        if entity_registry is None:
            return
        entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        for entity in entities:
            if not (
                entity.platform == "ave_dominaplus"
                and entity.domain == "binary_sensor"
                and entity.original_device_class == "motion"
            ):
                continue
            # Check if the sensor is already registered
            if entity.unique_id not in server.binary_sensors:
                # Create a new sensor instance
                family = int(entity.unique_id.split("_")[2])
                if family == 12 and not server.settings.fetch_sensor_areas:
                    continue
                if family == 1007 and not server.settings.fetch_sensors:
                    continue
                ave_device_id = int(entity.unique_id.split("_")[3])
                sensor = MotionBinarySensor(
                    unique_id=entity.unique_id,
                    family=family,
                    ave_device_id=ave_device_id,
                    is_motion_detected=None,
                )
                # Set the name of the sensor
                if entity.has_entity_name:
                    sensor.set_name(entity.name)
                elif entity.original_name is not None:
                    sensor.set_name(entity.original_name)

                server.binary_sensors[entity.unique_id] = sensor
                server.async_add_bs_entities([sensor])
    except Exception as e:  # noqa: BLE001
        _LOGGER.error("Error adopting existing sensors: %s", str(e))
        # raise ConfigEntryNotReady("Error adopting existing sensors") from e


def set_sensor_uid(family, device_id):
    """Set the unique ID for the sensor."""
    return f"ave_motion_{family}_{device_id}"  # Unique ID for the sensor


def update_binary_sensor(
    server: AveWebServer, family, ave_device_id, device_status, name=None
):
    """Update binary sensors based on the family and device status."""

    if family == 12:
        if not server.settings.fetch_sensor_areas:
            return
    elif family == 1007:
        if not server.settings.fetch_sensors:
            return
    else:
        _LOGGER.debug(
            " Not updating binary sensor for family %s, device_id %s",
            family,
            ave_device_id,
        )
        return

    _LOGGER.debug(
        " Updating binary sensor for family %s, device_id %s", family, ave_device_id
    )

    unique_id = set_sensor_uid(family, ave_device_id)
    already_exists = unique_id in server.binary_sensors

    # Check if the sensor already exists
    if already_exists:
        # Update the existing sensor's state
        sensor: MotionBinarySensor = server.binary_sensors[unique_id]
        if device_status >= 0:
            sensor.update_state(device_status)
        if name is not None and server.settings.get_entity_names:
            sensor.set_ave_name(name)
            if not check_name_changed(server.hass, unique_id):
                sensor.set_name(name)
    else:
        # Create a new motion detection sensor
        sensor = MotionBinarySensor(
            unique_id=unique_id,
            is_motion_detected=device_status > 0,
            family=family,
            ave_device_id=ave_device_id,
        )
        if family == 1007:
            name = sensor.build_name()
            if not check_name_changed(server.hass, unique_id):
                sensor.set_name(name)
        elif name is not None and server.settings.get_entity_names:
            if not check_name_changed(server.hass, unique_id):
                sensor.set_ave_name(name)
                sensor.set_name(name)
        _LOGGER.info("Creating new binary sensor entity %s", sensor.name)
        server.binary_sensors[unique_id] = sensor
        server.async_add_bs_entities([sensor])  # Add the new sensor to Home Assistant


def check_name_changed(hass: HomeAssistant, unique_id: str) -> bool:
    """Check if the name of the sensor has changed."""
    entity_registry = er.async_get(hass)

    entry_id = entity_registry.async_get_entity_id(
        "binary_sensor", "ave_dominaplus", unique_id
    )
    if entry_id:
        entity_entry = entity_registry.async_get(entry_id)
        if entity_entry is not None:
            return (
                entity_entry.has_entity_name
                and entity_entry.original_name != entity_entry.name
            )
    return False


class AveHubStatusBinarySensor(BinarySensorEntity):
    """Binary sensor for AVE dominaplus hub status."""

    def __init__(self, ws: AveWebServer, entry) -> None:
        """Initialize the binary sensor."""
        self._ws = ws
        self._attr_name = "AVE Hub Status"
        self._attr_unique_id = f"ave_hub_status_{entry.entry_id}"
        self._attr_is_on = None

    @property
    def is_on(self) -> bool | None:
        """Return the status of the hub."""
        return self._attr_is_on

    async def async_update(self) -> None:
        """Fetch the latest status from the web server."""
        self._attr_is_on = await self._ws.is_connected()


class MotionBinarySensor(BinarySensorEntity):
    """Representation of a motion detection binary sensor."""

    def __init__(
        self,
        unique_id: str,
        family: int,
        ave_device_id: int,
        is_motion_detected: int | None,
        name=None,
    ) -> None:
        """Initialize the motion detection sensor."""
        self._unique_id = unique_id
        self._is_motion_detected = is_motion_detected
        self.ave_device_id = ave_device_id
        self.family = family
        self._last_revealed: str | None = None
        self._last_cleared: str | None = None
        self._ave_name: str | None = None

        if name is None:
            self._name = self.build_name()
        else:
            self._name = name
        self._attr_family = family

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return self._unique_id

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return self._name

    @property
    def is_on(self) -> bool | None:
        """Return True if motion is detected."""
        if self._is_motion_detected is None:
            return None
        return self._is_motion_detected > 0

    @property
    def device_class(self) -> BinarySensorDeviceClass | None:
        """Return the device class of the sensor."""
        return BinarySensorDeviceClass.MOTION

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        info = {
            "last_revealed": self._last_revealed,
            "last_cleared": self._last_cleared,
            "AVE_family": self.family,
            "AVE_device_id": self.ave_device_id,
        }
        if self.family != 1007:
            info["AVE_name"] = self._ave_name
        return info

    def update_state(self, is_motion_detected: int | None):
        """Update the state of the sensor."""
        if is_motion_detected is not None:
            try:
                if is_motion_detected > 0:
                    self._last_revealed = utcnow().isoformat()
                elif self._is_motion_detected:
                    self._last_cleared = utcnow().isoformat()
            except Exception as e:  # noqa: BLE001
                _LOGGER.error("Error updating last revealed state: %s", str(e))
            self._is_motion_detected = is_motion_detected
            self.async_write_ha_state()  # Notify Home Assistant of the state change

    def set_name(self, name: str | None):
        """Set the name of the sensor."""
        if name is None:
            return
        self._name = name

    def set_ave_name(self, name: str | None):
        """Set the original name of the sensor."""
        if name is not None:
            self._ave_name = name
            self.async_write_ha_state()  # Notify Home Assistant of the state change

    def build_name(self) -> str:
        """Build the name of the sensor based on its family and device ID."""
        suffix = "sensor type " + str(self.family)
        if self.family == 12:
            suffix = "antitheft area"
        elif self.family == 1007:
            suffix = "antitheft sensor"
        return f"{BRAND_PREFIX} {suffix} {self.ave_device_id}"
