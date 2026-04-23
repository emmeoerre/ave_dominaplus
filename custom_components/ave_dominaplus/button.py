"""Button platform for AVE dominaplus integration."""

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

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
    async_add_entities: AddEntitiesCallback,
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

            name = entity.name if entity.name is not None else entity.original_name

            button = ScenarioButton(
                unique_id=entity.unique_id,
                family=family,
                ave_device_id=ave_device_id,
                webserver=server,
                name=name,
            )
            button.entity_id = entity.entity_id

            server.buttons[entity.unique_id] = button
            server.async_add_bt_entities([button])
            _LOGGER.info(
                "Adopted existing button entity with name %s with unique_id %s",
                button.name,
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


def _format_button_name(ave_name: str) -> str:
    """Return the entity name derived from AVE native scenario name."""
    return ave_name


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
            if not check_name_changed(server.hass, unique_id):
                button.set_name(_format_button_name(name))
        return

    entity_name = None
    entity_ave_name = None
    if name is not None and server.settings.get_entity_names:
        entity_name = _format_button_name(name)
        entity_ave_name = name

    button = ScenarioButton(
        unique_id=unique_id,
        family=family,
        ave_device_id=ave_device_id,
        webserver=server,
        name=entity_name,
        ave_name=entity_ave_name,
    )

    _LOGGER.info("Creating new button entity %s with unique_id %s", name, unique_id)
    server.buttons[unique_id] = button
    server.async_add_bt_entities([button])


def check_name_changed(hass: HomeAssistant, unique_id: str) -> bool:
    """Check if the name of the entity has changed in HA registry."""
    entity_registry = er.async_get(hass)

    entry_id = entity_registry.async_get_entity_id(
        "button", "ave_dominaplus", unique_id
    )
    if entry_id:
        entity_entry = entity_registry.async_get(entry_id)
        if entity_entry is not None:
            return (
                entity_entry.name is not None
                and entity_entry.original_name != entity_entry.name
            )
    return False


class ScenarioButton(ButtonEntity):
    """Representation of an AVE scenario run button."""

    _attr_has_entity_name = True
    _attr_should_poll = False

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

        if name is None:
            self._attr_translation_key = "scenario_run"
        else:
            self._attr_name = name

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

    def set_name(self, name: str | None) -> None:
        """Set entity name."""
        if name is None:
            return
        self._attr_name = name
        self._write_state_or_defer()

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
            device_registry_getter=dr.async_get,
        )

    def _write_state_or_defer(self) -> None:
        """Write state now when possible, otherwise defer until entity attach."""
        if self.hass is None or self.entity_id is None:
            self._pending_state_write = True
            return
        self.async_write_ha_state()

    def build_name(self) -> str:
        """Build default entity name."""
        return f"Scenario {self.ave_device_id} Run"
