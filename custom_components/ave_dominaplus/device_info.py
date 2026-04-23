"""Helpers for Home Assistant device registry metadata."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo

from .const import (
    AVE_FAMILY_ANTITHEFT_AREA,
    AVE_FAMILY_DIMMER,
    AVE_FAMILY_MOTION_SENSOR,
    AVE_FAMILY_ONOFFLIGHTS,
    AVE_FAMILY_SCENARIO,
    AVE_FAMILY_SHUTTER_HUNG,
    AVE_FAMILY_SHUTTER_ROLLING,
    AVE_FAMILY_SHUTTER_SLIDING,
    AVE_FAMILY_THERMOSTAT,
    DOMAIN,
)
from .web_server import AveWebServer

_GROUP_LIGHTING = "lighting"
_GROUP_COVERS = "covers"
_GROUP_THERMOSTATS = "thermostats"
_GROUP_ANTITHEFT_SENSORS = "antitheft_sensors"
_GROUP_ANTITHEFT_AREAS = "antitheft_areas"
_GROUP_SCENARIOS = "scenarios"

_FAMILY_TO_GROUP: dict[int, str] = {
    AVE_FAMILY_ONOFFLIGHTS: _GROUP_LIGHTING,
    AVE_FAMILY_DIMMER: _GROUP_LIGHTING,
    AVE_FAMILY_SHUTTER_ROLLING: _GROUP_COVERS,
    AVE_FAMILY_SHUTTER_SLIDING: _GROUP_COVERS,
    AVE_FAMILY_SHUTTER_HUNG: _GROUP_COVERS,
    AVE_FAMILY_MOTION_SENSOR: _GROUP_ANTITHEFT_SENSORS,
    AVE_FAMILY_ANTITHEFT_AREA: _GROUP_ANTITHEFT_AREAS,
    AVE_FAMILY_SCENARIO: _GROUP_SCENARIOS,
}

_GROUP_MODELS: dict[str, str] = {
    _GROUP_LIGHTING: "AVE dominaplus lighting",
    _GROUP_COVERS: "AVE dominaplus covers",
    _GROUP_THERMOSTATS: "AVE dominaplus thermostats",
    _GROUP_ANTITHEFT_SENSORS: "AVE dominaplus antitheft sensors",
    _GROUP_ANTITHEFT_AREAS: "AVE dominaplus antitheft areas",
    _GROUP_SCENARIOS: "AVE dominaplus scenarios",
}

_GROUP_NAMES: dict[str, str] = {
    _GROUP_LIGHTING: "Dominaplus Lighting",
    _GROUP_COVERS: "Dominaplus Covers",
    _GROUP_THERMOSTATS: "Dominaplus Thermostats",
    _GROUP_ANTITHEFT_SENSORS: "Dominaplus Antitheft Sensors",
    _GROUP_ANTITHEFT_AREAS: "Dominaplus Antitheft Areas",
    _GROUP_SCENARIOS: "Dominaplus Scenarios",
}

_PROTECTED_DEVICE_SUFFIXES = (
    f"_{_GROUP_LIGHTING}",
    f"_{_GROUP_COVERS}",
    f"_{_GROUP_THERMOSTATS}",
    f"_{_GROUP_ANTITHEFT_SENSORS}",
    f"_{_GROUP_ANTITHEFT_AREAS}",
    f"_{_GROUP_SCENARIOS}",
)


def is_structural_parent_identifier(identifier: tuple[str, str]) -> bool:
    """Return True when identifier belongs to a structural parent device.

    Structural parents are devices used for topology/grouping (hub or parent nodes)
    that may legitimately have no direct entities attached.
    """
    domain, value = identifier
    if domain != DOMAIN:
        return False
    return value.startswith("hub_") or value.endswith(_PROTECTED_DEVICE_SUFFIXES)


def _hub_identifier(server: AveWebServer) -> str:
    """Build a stable hub identifier for the device registry."""
    if server.config_entry_id:
        return server.config_entry_id
    if server.mac_address:
        return server.mac_address.lower()
    if server.config_entry_unique_id:
        return server.config_entry_unique_id.lower()
    return server.settings.host


def _hub_device_identifier(server: AveWebServer) -> tuple[str, str]:
    """Return the DeviceInfo identifier tuple for the integration hub."""
    return (DOMAIN, f"hub_{_hub_identifier(server)}")


def _endpoint_model(family: int) -> str:
    """Return an endpoint model label based on AVE family."""
    if family == AVE_FAMILY_THERMOSTAT:
        return "AVE dominaplus thermostat"
    group = _FAMILY_TO_GROUP.get(family)
    if group:
        return _GROUP_MODELS[group]
    return f"AVE dominaplus endpoint family {family}"


def _endpoint_group_key(family: int, ave_device_id: int) -> str:
    """Return stable grouping key for endpoint devices under the hub."""
    if family in (AVE_FAMILY_ONOFFLIGHTS, AVE_FAMILY_DIMMER):
        return f"light_{family}_{ave_device_id}"
    if family in (
        AVE_FAMILY_SHUTTER_ROLLING,
        AVE_FAMILY_SHUTTER_SLIDING,
        AVE_FAMILY_SHUTTER_HUNG,
    ):
        return f"cover_{family}_{ave_device_id}"
    if family == AVE_FAMILY_THERMOSTAT:
        return f"thermostat_{ave_device_id}"
    if family == AVE_FAMILY_SCENARIO:
        return f"scenario_{ave_device_id}"
    group = _FAMILY_TO_GROUP.get(family)
    if group:
        return group
    return f"family_{family}_{ave_device_id}"


def _clean_ave_device_name(ave_name: str | None) -> str | None:
    """Normalize AVE-provided names for registry device labels."""
    if not ave_name:
        return None
    clean_name = ave_name.strip()
    if clean_name.lower().endswith(" offset"):
        clean_name = clean_name[:-7].strip()
    return clean_name or None


def _thermostat_device_name(ave_device_id: int, ave_name: str | None) -> str:
    """Build thermostat device name from AVE name or fallback device id."""
    clean_name = _clean_ave_device_name(ave_name)
    if not clean_name:
        return f"Thermostat {ave_device_id}"
    if clean_name.lower().startswith("thermostat "):
        return clean_name
    return f"Thermostat {clean_name}"


def _scenario_device_name(ave_device_id: int, ave_name: str | None) -> str:
    """Build scenario device name from AVE name or fallback device id."""
    clean_name = _clean_ave_device_name(ave_name)
    if not clean_name:
        return f"Scenario {ave_device_id}"
    if clean_name.lower().startswith("scenario "):
        return clean_name
    return f"Scenario {clean_name}"


def _lighting_device_name(family: int, ave_device_id: int, ave_name: str | None) -> str:
    """Build lighting endpoint device name from AVE name or fallback id."""
    clean_name = _clean_ave_device_name(ave_name)
    if clean_name:
        return clean_name
    if family == AVE_FAMILY_ONOFFLIGHTS:
        return f"Light {ave_device_id}"
    return f"Dimmer {ave_device_id}"


def _cover_device_name(family: int, ave_device_id: int, ave_name: str | None) -> str:
    """Build cover endpoint device name from AVE name or fallback id."""
    clean_name = _clean_ave_device_name(ave_name)
    if clean_name:
        return clean_name
    if family == AVE_FAMILY_SHUTTER_ROLLING:
        return f"Shutter {ave_device_id}"
    if family == AVE_FAMILY_SHUTTER_SLIDING:
        return f"Blind {ave_device_id}"
    if family == AVE_FAMILY_SHUTTER_HUNG:
        return f"Window {ave_device_id}"
    return f"Cover {ave_device_id}"


def _endpoint_name(family: int, ave_device_id: int, ave_name: str | None) -> str:
    """Return a stable endpoint device name."""
    if family in (AVE_FAMILY_ONOFFLIGHTS, AVE_FAMILY_DIMMER):
        return _lighting_device_name(family, ave_device_id, ave_name)
    if family in (
        AVE_FAMILY_SHUTTER_ROLLING,
        AVE_FAMILY_SHUTTER_SLIDING,
        AVE_FAMILY_SHUTTER_HUNG,
    ):
        return _cover_device_name(family, ave_device_id, ave_name)
    if family == AVE_FAMILY_THERMOSTAT:
        return _thermostat_device_name(ave_device_id, ave_name)
    if family == AVE_FAMILY_SCENARIO:
        return _scenario_device_name(ave_device_id, ave_name)
    group = _FAMILY_TO_GROUP.get(family)
    if group:
        return _GROUP_NAMES[group]
    return f"Dominaplus Device Family {family}"


def _lighting_parent_device_identifier(server: AveWebServer) -> tuple[str, str]:
    """Return the DeviceInfo identifier tuple for the lighting parent device."""
    return (DOMAIN, f"endpoint_{_hub_identifier(server)}_{_GROUP_LIGHTING}")


def _scenarios_parent_device_identifier(server: AveWebServer) -> tuple[str, str]:
    """Return the DeviceInfo identifier tuple for the scenarios parent device."""
    return (DOMAIN, f"endpoint_{_hub_identifier(server)}_{_GROUP_SCENARIOS}")


def _covers_parent_device_identifier(server: AveWebServer) -> tuple[str, str]:
    """Return the DeviceInfo identifier tuple for the covers parent device."""
    return (DOMAIN, f"endpoint_{_hub_identifier(server)}_{_GROUP_COVERS}")


def _thermostats_parent_device_identifier(server: AveWebServer) -> tuple[str, str]:
    """Return the DeviceInfo identifier tuple for the thermostats parent device."""
    return (DOMAIN, f"endpoint_{_hub_identifier(server)}_{_GROUP_THERMOSTATS}")


def build_hub_device_info(server: AveWebServer) -> DeviceInfo:
    """Return device_info for the AVE hub.

    Keep this stable to avoid changing existing entity IDs/friendly names.
    """
    connections = set()
    if server.mac_address:
        connections.add((CONNECTION_NETWORK_MAC, server.mac_address.lower()))

    return DeviceInfo(
        identifiers={_hub_device_identifier(server)},
        connections=connections,
        manufacturer="AVE",
        model="AVE dominaplus webserver",
        translation_key="hub",
        name=None,
        configuration_url=f"http://{server.settings.host}",
    )


def build_endpoint_device_info(
    server: AveWebServer,
    family: int,
    ave_device_id: int,
    *,
    ave_name: str | None = None,
) -> DeviceInfo:
    """Return device_info for a child endpoint routed through the hub.

    Device identifiers include the hub identifier to avoid collisions across hubs.
    """
    group_key = _endpoint_group_key(family, ave_device_id)
    endpoint_identifier = (
        DOMAIN,
        f"endpoint_{_hub_identifier(server)}_{group_key}",
    )

    via_device = _hub_device_identifier(server)
    if family in (AVE_FAMILY_ONOFFLIGHTS, AVE_FAMILY_DIMMER):
        via_device = _lighting_parent_device_identifier(server)
    elif family in (
        AVE_FAMILY_SHUTTER_ROLLING,
        AVE_FAMILY_SHUTTER_SLIDING,
        AVE_FAMILY_SHUTTER_HUNG,
    ):
        via_device = _covers_parent_device_identifier(server)
    elif family == AVE_FAMILY_THERMOSTAT:
        via_device = _thermostats_parent_device_identifier(server)
    elif family == AVE_FAMILY_SCENARIO:
        via_device = _scenarios_parent_device_identifier(server)

    device_name: str | None = _endpoint_name(family, ave_device_id, ave_name)
    translation_key: str | None = None

    if group_key in (_GROUP_ANTITHEFT_SENSORS, _GROUP_ANTITHEFT_AREAS):
        translation_key = group_key
        device_name = None

    return DeviceInfo(
        identifiers={endpoint_identifier},
        manufacturer="AVE",
        model=_endpoint_model(family),
        name=device_name,
        translation_key=translation_key,
        via_device=via_device,
        configuration_url=f"http://{server.settings.host}",
    )


def ensure_lighting_parent_device(server: AveWebServer, config_entry_id: str) -> None:
    """Ensure the shared lighting parent device exists in the device registry."""
    if server.hass is None:
        return

    device_registry = dr.async_get(server.hass)
    try:
        device_registry.async_get_or_create(
            config_entry_id=config_entry_id,
            identifiers={_lighting_parent_device_identifier(server)},
            manufacturer="AVE",
            model=_GROUP_MODELS[_GROUP_LIGHTING],
            translation_key=_GROUP_LIGHTING,
            name=None,
            via_device=_hub_device_identifier(server),
            configuration_url=f"http://{server.settings.host}",
        )
    except HomeAssistantError:
        # Can happen in tests or during early setup before the entry is registered.
        return


def ensure_scenarios_parent_device(server: AveWebServer, config_entry_id: str) -> None:
    """Ensure the shared scenarios parent device exists in the device registry."""
    if server.hass is None:
        return

    device_registry = dr.async_get(server.hass)
    try:
        device_registry.async_get_or_create(
            config_entry_id=config_entry_id,
            identifiers={_scenarios_parent_device_identifier(server)},
            manufacturer="AVE",
            model=_GROUP_MODELS[_GROUP_SCENARIOS],
            translation_key=_GROUP_SCENARIOS,
            name=None,
            via_device=_hub_device_identifier(server),
            configuration_url=f"http://{server.settings.host}",
        )
    except HomeAssistantError:
        # Can happen in tests or during early setup before the entry is registered.
        return


def ensure_covers_parent_device(server: AveWebServer, config_entry_id: str) -> None:
    """Ensure the shared covers parent device exists in the device registry."""
    if server.hass is None:
        return

    device_registry = dr.async_get(server.hass)
    try:
        device_registry.async_get_or_create(
            config_entry_id=config_entry_id,
            identifiers={_covers_parent_device_identifier(server)},
            manufacturer="AVE",
            model=_GROUP_MODELS[_GROUP_COVERS],
            translation_key=_GROUP_COVERS,
            name=None,
            via_device=_hub_device_identifier(server),
            configuration_url=f"http://{server.settings.host}",
        )
    except HomeAssistantError:
        # Can happen in tests or during early setup before the entry is registered.
        return


def ensure_thermostats_parent_device(
    server: AveWebServer, config_entry_id: str
) -> None:
    """Ensure the shared thermostats parent device exists in the device registry."""
    if server.hass is None:
        return

    device_registry = dr.async_get(server.hass)
    try:
        device_registry.async_get_or_create(
            config_entry_id=config_entry_id,
            identifiers={_thermostats_parent_device_identifier(server)},
            manufacturer="AVE",
            model=_GROUP_MODELS[_GROUP_THERMOSTATS],
            translation_key=_GROUP_THERMOSTATS,
            name=None,
            via_device=_hub_device_identifier(server),
            configuration_url=f"http://{server.settings.host}",
        )
    except HomeAssistantError:
        # Can happen in tests or during early setup before the entry is registered.
        return


def sync_device_registry_name(
    hass: HomeAssistant | None,
    device_info: DeviceInfo,
    *,
    identifiers: set[tuple[str, str]] | None = None,
    device_registry_getter: Callable[[HomeAssistant], Any] | None = None,
) -> None:
    """Sync registry device metadata from device_info.

    Updates the device name unless user customized it in HA, and updates
    parent linkage (via_device) when resolvable.
    """
    if hass is None:
        return

    resolved_identifiers = identifiers or device_info.get("identifiers")
    if not resolved_identifiers:
        return

    get_registry = device_registry_getter or dr.async_get
    device_registry = get_registry(hass)
    device_entry = device_registry.async_get_device(identifiers=resolved_identifiers)
    if device_entry is None:
        return

    # Respect user-chosen device names from the HA UI.
    updates: dict[str, Any] = {}
    resolved_name = device_info.get("name")
    if (
        device_entry.name_by_user is None
        and resolved_name
        and device_entry.name != resolved_name
    ):
        updates["name"] = resolved_name

    via_identifier = device_info.get("via_device")
    if isinstance(via_identifier, tuple) and len(via_identifier) == 2:
        via_entry = device_registry.async_get_device(identifiers={via_identifier})
        current_via_device_id = getattr(device_entry, "via_device_id", None)
        if (
            via_entry is not None  # noqa: PLR1714
            and via_entry.id != device_entry.id
            and current_via_device_id != via_entry.id
        ):
            updates["via_device_id"] = via_entry.id

    if updates:
        device_registry.async_update_device(device_id=device_entry.id, **updates)
