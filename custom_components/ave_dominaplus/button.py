"""Button platform for AVE dominaplus integration."""

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ws_commands
from .const import AVE_FAMILY_SCENARIO
from .device_info import (
    build_endpoint_device_info,
    ensure_scenarios_parent_device,
    sync_device_registry_name,
)
from .uid_v2 import build_uid, parse_uid
from .web_server import AveWebServer

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 1
SCENARIO_BUTTON_UID_SUFFIX = "button"


async def async_setup_entry(
    _hass: HomeAssistant | None,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up AVE dominaplus scenario buttons."""
    webserver: AveWebServer = entry.runtime_data
    if not webserver:
        _LOGGER.error("AVE dominaplus: Web server not initialized")
        connection_error = "Can't reach webserver"
        raise ConfigEntryNotReady(connection_error)

    await webserver.set_async_add_bt_entities(async_add_entities)
    await webserver.set_update_button(update_button)
    if not webserver.settings.fetch_scenarios:
        return

    ensure_scenarios_parent_device(webserver, entry.entry_id)

    await adopt_existing_buttons(webserver, entry)


async def adopt_existing_buttons(server: AveWebServer, entry: ConfigEntry) -> None:
    """Adopt existing scenario buttons from the entity registry."""
    try:
        entity_registry = er.async_get(server.hass)
        if entity_registry is None:
            return
        entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        for entity in entities:
            if not (entity.platform == "ave_dominaplus" and entity.domain == "button"):
                continue
            if entity.unique_id in server.buttons:
                continue

            parsed_uid = parse_uid(entity.unique_id)
            if parsed_uid is None:
                continue

            _uid_mac, family, ave_device_id, _address_dec, uid_suffix = parsed_uid
            if uid_suffix != SCENARIO_BUTTON_UID_SUFFIX:
                continue
            if family != AVE_FAMILY_SCENARIO or not server.settings.fetch_scenarios:
                continue

            ave_name = None
            if server.settings.get_entity_names and entity.original_name:
                ave_name = _scenario_source_name(entity.original_name, " Run")

            button = ScenarioButton(
                unique_id=entity.unique_id,
                family=family,
                ave_device_id=ave_device_id,
                webserver=server,
                name=None,
                ave_name=ave_name,
            )
            button.entity_id = entity.entity_id

            server.buttons[entity.unique_id] = button
            server.async_add_bt_entities([button])
            _LOGGER.info(
                "Adopted existing button entity with unique_id %s",
                button.unique_id,
            )
    except Exception:
        _LOGGER.exception("Error adopting existing buttons")


def set_button_uid(server: AveWebServer, family: int, ave_device_id: int) -> str:
    """Build scenario button unique id."""
    return build_uid(
        server.mac_address,
        family,
        ave_device_id,
        0,
        suffix=SCENARIO_BUTTON_UID_SUFFIX,
    )


def _scenario_source_name(original_name: str, suffix: str) -> str:
    """Recover an AVE scenario name from a legacy entity label."""
    # Existing registry names included the entity role, such as "Evening Run".
    if original_name.endswith(suffix):
        return original_name[: -len(suffix)]
    return original_name


def update_button(
    server: AveWebServer,
    family: int,
    ave_device_id: int,
    name: str | None = None,
    _address_dec: int | None = None,
) -> None:
    """Create or update scenario button entities from webserver events."""
    if family != AVE_FAMILY_SCENARIO:
        _LOGGER.debug(
            "Not updating button for family %s, device_id %s",
            family,
            ave_device_id,
        )
        return

    if not server.settings.fetch_scenarios:
        return

    unique_id = set_button_uid(server, family, ave_device_id)
    already_exists = unique_id in server.buttons

    if already_exists:
        button: ScenarioButton = server.buttons[unique_id]
        if name is not None and server.settings.get_entity_names:
            button.set_ave_name(name)
        return

    entity_ave_name = None
    if name is not None and server.settings.get_entity_names:
        entity_ave_name = name

    button = ScenarioButton(
        unique_id=unique_id,
        family=family,
        ave_device_id=ave_device_id,
        webserver=server,
        name=None,
        ave_name=entity_ave_name,
    )

    _LOGGER.info("Creating new button entity %s with unique_id %s", name, unique_id)
    server.buttons[unique_id] = button
    server.async_add_bt_entities([button])


class ScenarioButton(ButtonEntity):
    """Representation of an AVE scenario run button."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "scenario_run"

    def __init__(
        self,
        unique_id: str,
        family: int,
        ave_device_id: int,
        webserver: AveWebServer,
        name: str | None = None,
        ave_name: str | None = None,
    ) -> None:
        """Initialize the scenario button."""
        self._unique_id = unique_id
        self.family = family
        self.ave_device_id = ave_device_id
        self._webserver = webserver
        self.hass = webserver.hass
        self._ave_name = ave_name
        self._pending_state_write = False
        self._attr_device_info = build_endpoint_device_info(
            webserver,
            family,
            ave_device_id,
            ave_name=ave_name,
        )

    async def async_added_to_hass(self) -> None:
        """Handle entity added to Home Assistant."""
        await super().async_added_to_hass()
        self._webserver.register_availability_entity(self)
        if self._pending_state_write:
            self._pending_state_write = False
            self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Handle entity removal from Home Assistant."""
        self._webserver.buttons.pop(self._unique_id, None)
        self._webserver.unregister_availability_entity(self)
        await super().async_will_remove_from_hass()

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the entity."""
        return self._unique_id

    @property
    def available(self) -> bool:
        """Return if the backing webserver connection is available."""
        return self._webserver.connected

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        return {
            "AVE_family": self.family,
            "AVE_device_id": self.ave_device_id,
            "AVE_name": self._ave_name,
            "AVE webserver MAC": self._webserver.mac_address,
        }

    async def async_press(self) -> None:
        """Trigger scenario execution on the AVE webserver."""
        if self._webserver:
            await ws_commands.scenario_execute(self._webserver, self.ave_device_id)

    def set_ave_name(self, name: str | None) -> None:
        """Set AVE native name."""
        if name is not None:
            self._ave_name = name
            self._sync_device_name(name)
            self._write_state_or_defer()

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
            config_entry_id=self._webserver.config_entry_id,
        )

    def _write_state_or_defer(self) -> None:
        """Write state now when possible, otherwise defer until entity attach."""
        if self.hass is None or self.entity_id is None:
            self._pending_state_write = True
            return
        self.async_write_ha_state()
