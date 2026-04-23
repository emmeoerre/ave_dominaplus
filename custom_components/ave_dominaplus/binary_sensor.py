"""Binary sensor platform for AVE dominaplus integration."""

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.dt import utcnow

from .const import (
    AVE_FAMILY_ANTITHEFT_AREA,
    AVE_FAMILY_MOTION_SENSOR,
    AVE_FAMILY_SCENARIO,
)
from .device_info import (
    build_endpoint_device_info,
    build_hub_device_info,
    ensure_scenarios_parent_device,
    sync_device_registry_name,
)
from .uid_v2 import build_uid, parse_uid
from .web_server import AveWebServer

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 1
SCENARIO_RUNNING_UID_SUFFIX = "running"


async def async_setup_entry(
    _hass: HomeAssistant | None,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
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
        connection_error = "Can't reach webserver"
        raise ConfigEntryNotReady(connection_error)
    await webserver.set_update_binary_sensor(update_binary_sensor)
    await webserver.set_async_add_bs_entities(async_add_entities)
    if webserver.settings.fetch_scenarios:
        ensure_scenarios_parent_device(webserver, entry.entry_id)
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
                entity.platform == "ave_dominaplus" and entity.domain == "binary_sensor"
            ):
                continue
            if entity.unique_id in server.binary_sensors:
                continue

            name = entity.name if entity.name is not None else entity.original_name
            original_device_class = getattr(entity, "original_device_class", None)
            sensor = None

            motion_uid = _parse_motion_uid(entity.unique_id)
            if motion_uid is not None:
                if original_device_class not in ("motion", None):
                    continue
                family, ave_device_id = motion_uid
                if (
                    family == AVE_FAMILY_ANTITHEFT_AREA
                    and not server.settings.fetch_sensor_areas
                ):
                    continue
                if (
                    family == AVE_FAMILY_MOTION_SENSOR
                    and not server.settings.fetch_sensors
                ):
                    continue
                sensor = MotionBinarySensor(
                    unique_id=entity.unique_id,
                    family=family,
                    ave_device_id=ave_device_id,
                    is_motion_detected=None,
                    name=name,
                    hass=server.hass,
                    webserver=server,
                )

            scenario_uid = parse_uid(entity.unique_id)
            if scenario_uid is not None:
                if original_device_class not in ("running", None):
                    continue
                _uid_mac, family, ave_device_id, _address_dec, uid_suffix = scenario_uid
                if uid_suffix != SCENARIO_RUNNING_UID_SUFFIX:
                    continue
                if family != AVE_FAMILY_SCENARIO or not server.settings.fetch_scenarios:
                    continue
                sensor = ScenarioRunningBinarySensor(
                    unique_id=entity.unique_id,
                    family=family,
                    ave_device_id=ave_device_id,
                    is_running=None,
                    name=name,
                    hass=server.hass,
                    webserver=server,
                )

            if sensor is None:
                continue

            server.binary_sensors[entity.unique_id] = sensor
            server.async_add_bs_entities([sensor])
            _LOGGER.info(
                "Adopted existing binary sensor entity with name %s with unique_id %s",
                sensor.name,
                sensor.unique_id,
            )
    except Exception:
        _LOGGER.exception("Error adopting existing sensors")
        # raise ConfigEntryNotReady("Error adopting existing sensors") from e


def set_sensor_uid(
    family: int,
    device_id: int,
    server: AveWebServer | None = None,
) -> str:
    """Set the unique ID for the sensor."""
    if family == AVE_FAMILY_SCENARIO:
        if server is None:
            msg = "server is required for scenario running UID generation"
            raise ValueError(msg)
        return build_uid(
            server.mac_address,
            family,
            device_id,
            0,
            suffix=SCENARIO_RUNNING_UID_SUFFIX,
        )
    return f"ave_motion_{family}_{device_id}"


def _parse_motion_uid(unique_id: str) -> tuple[int, int] | None:
    """Parse a motion/area binary sensor unique id."""
    parts = unique_id.split("_")
    if len(parts) != 4 or parts[0:2] != ["ave", "motion"]:
        return None
    try:
        return int(parts[2]), int(parts[3])
    except ValueError:
        return None


def _scenario_running_name(ave_name: str) -> str:
    """Build scenario running entity name from AVE native name."""
    return ave_name


def update_binary_sensor(
    server: AveWebServer, family, ave_device_id, device_status, name=None
) -> None:
    """Update binary sensors based on the family and device status."""
    if family == AVE_FAMILY_ANTITHEFT_AREA:
        if not server.settings.fetch_sensor_areas:
            return
    elif family == AVE_FAMILY_MOTION_SENSOR:
        if not server.settings.fetch_sensors:
            return
    elif family == AVE_FAMILY_SCENARIO:
        if not server.settings.fetch_scenarios:
            return
    else:
        _LOGGER.debug(
            " Not updating binary sensor for family %s, device_id %s, status %s",
            family,
            ave_device_id,
            device_status,
        )
        return

    _LOGGER.debug(
        " Updating binary sensor for family %s, device_id %s, status %s",
        family,
        ave_device_id,
        device_status,
    )

    unique_id = set_sensor_uid(family, ave_device_id, server)
    already_exists = unique_id in server.binary_sensors

    # Check if the sensor already exists
    if already_exists:
        # Update the existing sensor's state
        sensor = server.binary_sensors[unique_id]
        if device_status >= 0:
            sensor.update_state(device_status)
        if name is not None and server.settings.get_entity_names:
            sensor.set_ave_name(name)
            if not check_name_changed(server.hass, unique_id):
                if family == AVE_FAMILY_SCENARIO:
                    sensor.set_name(_scenario_running_name(name))
                else:
                    sensor.set_name(name)
    else:
        entity_name = None
        entity_ave_name = None
        if family == AVE_FAMILY_MOTION_SENSOR:
            entity_name = None
            entity_ave_name = None
        elif name is not None and server.settings.get_entity_names:
            entity_name = (
                _scenario_running_name(name) if family == AVE_FAMILY_SCENARIO else name
            )
            entity_ave_name = name

        if family == AVE_FAMILY_SCENARIO:
            sensor = ScenarioRunningBinarySensor(
                unique_id=unique_id,
                is_running=None if device_status < 0 else device_status > 0,
                family=family,
                ave_device_id=ave_device_id,
                hass=server.hass,
                webserver=server,
                name=entity_name,
                ave_name=entity_ave_name,
            )
        else:
            # Create a new motion detection sensor
            sensor = MotionBinarySensor(
                unique_id=unique_id,
                is_motion_detected=device_status > 0,
                family=family,
                ave_device_id=ave_device_id,
                hass=server.hass,
                webserver=server,
                name=entity_name,
                ave_name=entity_ave_name,
            )

        _LOGGER.info("Creating new binary sensor entity %s", sensor.name)
        server.binary_sensors[unique_id] = sensor
        # Add the new sensor to Home Assistant
        server.async_add_bs_entities([sensor])


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
                entity_entry.name is not None
                and entity_entry.original_name != entity_entry.name
            )
    return False


class AveHubStatusBinarySensor(BinarySensorEntity):
    """Binary sensor for AVE dominaplus hub status."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, ws: AveWebServer, entry) -> None:
        """Initialize the binary sensor."""
        self._ws = ws
        self._attr_name = "Status"
        self._attr_unique_id = f"ave_hub_status_{entry.entry_id}"
        self._attr_device_info = build_hub_device_info(ws)

    async def async_added_to_hass(self) -> None:
        """Handle entity added to Home Assistant."""
        await super().async_added_to_hass()
        self._ws.register_availability_entity(self)

    async def async_will_remove_from_hass(self) -> None:
        """Handle entity removal from Home Assistant."""
        self._ws.unregister_availability_entity(self)
        await super().async_will_remove_from_hass()

    @property
    def is_on(self) -> bool | None:
        """Return the status of the hub."""
        return self._ws.connected

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        return {
            "AVE webserver MAC": self._ws.mac_address if self._ws else None,
        }


class MotionBinarySensor(BinarySensorEntity):
    """Representation of a motion detection binary sensor."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        unique_id: str,
        family: int,
        ave_device_id: int,
        is_motion_detected: int | None,
        hass: HomeAssistant,
        webserver: AveWebServer,
        name=None,
        ave_name=None,
    ) -> None:
        """Initialize the motion detection sensor."""
        self._unique_id = unique_id
        self._is_motion_detected = is_motion_detected
        self.ave_device_id = ave_device_id
        self.family = family
        self._last_revealed: str | None = None
        self._last_cleared: str | None = None
        self._ave_name: str | None = ave_name
        self._webserver = webserver
        self.hass = hass
        self._attr_device_info = build_endpoint_device_info(
            webserver, family, ave_device_id
        )

        self._attr_family = family
        if name is None:
            if self.family == AVE_FAMILY_MOTION_SENSOR:
                self._attr_name = f"Sensor {self.ave_device_id}"
            elif self.family == AVE_FAMILY_ANTITHEFT_AREA:
                self._attr_name = f"Area {self.ave_device_id}"
            else:
                self._attr_name = self.build_name()
        else:
            self._attr_name = name

    async def async_added_to_hass(self) -> None:
        """Handle entity added to Home Assistant."""
        await super().async_added_to_hass()
        self._webserver.register_availability_entity(self)

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
        if self.family != AVE_FAMILY_MOTION_SENSOR:
            info["AVE_name"] = self._ave_name
        return info

    def update_state(self, is_motion_detected: int | None) -> None:
        """Update the state of the sensor."""
        if is_motion_detected is not None:
            try:
                if is_motion_detected > 0:
                    self._last_revealed = utcnow().isoformat()
                elif self._is_motion_detected:
                    self._last_cleared = utcnow().isoformat()
            except Exception:
                _LOGGER.exception("Error updating last revealed state")
            self._is_motion_detected = is_motion_detected
            # Notify Home Assistant of the state change
            if self.hass:
                self.async_write_ha_state()

    def set_name(self, name: str | None) -> None:
        """Set the name of the sensor."""
        if name is None:
            return
        self._attr_name = name
        if self.hass:
            self.async_write_ha_state()

    def set_ave_name(self, name: str | None) -> None:
        """Set the original name of the sensor."""
        if name is not None:
            self._ave_name = name
            # Notify Home Assistant of the state change
            self.async_write_ha_state()

    def build_name(self) -> str:
        """Build the name of the sensor based on its family and device ID."""
        suffix = f"Sensor {self.family}"
        if self.family == AVE_FAMILY_ANTITHEFT_AREA:
            suffix = "Antitheft Area"
        elif self.family == AVE_FAMILY_MOTION_SENSOR:
            suffix = "Antitheft Sensor"
        return f"{suffix} {self.ave_device_id}"


class ScenarioRunningBinarySensor(BinarySensorEntity):
    """Representation of a scenario running state binary sensor."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        unique_id: str,
        family: int,
        ave_device_id: int,
        is_running: bool | None,
        hass: HomeAssistant,
        webserver: AveWebServer,
        name=None,
        ave_name=None,
    ) -> None:
        """Initialize the scenario running sensor."""
        self._unique_id = unique_id
        self._is_running = is_running
        self.ave_device_id = ave_device_id
        self.family = family
        self._last_started: str | None = None
        self._last_stopped: str | None = None
        self._ave_name: str | None = ave_name
        self._webserver = webserver
        self.hass = hass
        self._attr_device_info = build_endpoint_device_info(
            webserver,
            family,
            ave_device_id,
            ave_name=ave_name,
        )

        if name is None:
            self._attr_translation_key = "scenario_running"
        else:
            self._attr_name = name

    async def async_added_to_hass(self) -> None:
        """Handle entity added to Home Assistant."""
        await super().async_added_to_hass()
        self._webserver.register_availability_entity(self)

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
    def is_on(self) -> bool | None:
        """Return True if the scenario is currently running."""
        return self._is_running

    @property
    def device_class(self) -> BinarySensorDeviceClass | None:
        """Return the device class of the sensor."""
        return BinarySensorDeviceClass.RUNNING

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        return {
            "last_started": self._last_started,
            "last_stopped": self._last_stopped,
            "AVE_family": self.family,
            "AVE_device_id": self.ave_device_id,
            "AVE_name": self._ave_name,
        }

    def update_state(self, is_running: int | None) -> None:
        """Update the state of the sensor."""
        if is_running is None:
            return

        running = is_running > 0
        try:
            if running:
                self._last_started = utcnow().isoformat()
            elif self._is_running:
                self._last_stopped = utcnow().isoformat()
        except Exception:
            _LOGGER.exception("Error updating scenario running timestamps")

        self._is_running = running
        if self.hass:
            self.async_write_ha_state()

    def set_name(self, name: str | None) -> None:
        """Set the name of the sensor."""
        if name is None:
            return
        self._attr_name = name
        if self.hass:
            self.async_write_ha_state()

    def set_ave_name(self, name: str | None) -> None:
        """Set the original name of the sensor."""
        if name is not None:
            self._ave_name = name
            self._sync_device_name(name)
            if self.hass:
                self.async_write_ha_state()

    def _sync_device_name(self, ave_name: str) -> None:
        """Sync scenario device name unless user customized it in HA."""
        updated_device_info = build_endpoint_device_info(
            self._webserver,
            self.family,
            self.ave_device_id,
            ave_name=ave_name,
        )
        self._attr_device_info = updated_device_info
        sync_device_registry_name(
            self.hass,
            updated_device_info,
            device_registry_getter=dr.async_get,
        )

    def build_name(self) -> str:
        """Build the default name for this sensor."""
        return f"Scenario {self.ave_device_id} Running"
