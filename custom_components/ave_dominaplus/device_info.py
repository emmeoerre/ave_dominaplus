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
    if server.mac_address:
        return server.mac_address.lower()
    if server.config_entry_unique_id:
        return server.config_entry_unique_id.lower()
    if server.config_entry_id:
        return server.config_entry_id
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


def _endpoint_naming(
    family: int, ave_device_id: int, ave_name: str | None
) -> tuple[str | None, str | None, dict[str, str] | None]:
    """Return explicit or translated endpoint device naming metadata."""
    clean_name = _clean_ave_device_name(ave_name)
    if family in (AVE_FAMILY_ONOFFLIGHTS, AVE_FAMILY_DIMMER):
        if clean_name:
            return clean_name, None, None
        key = "light" if family == AVE_FAMILY_ONOFFLIGHTS else "dimmer"
        return None, key, {"id": str(ave_device_id)}
    if family in (
        AVE_FAMILY_SHUTTER_ROLLING,
        AVE_FAMILY_SHUTTER_SLIDING,
        AVE_FAMILY_SHUTTER_HUNG,
    ):
        if clean_name:
            return clean_name, None, None
        key = {
            AVE_FAMILY_SHUTTER_ROLLING: "shutter",
            AVE_FAMILY_SHUTTER_SLIDING: "blind",
            AVE_FAMILY_SHUTTER_HUNG: "window",
        }[family]
        return None, key, {"id": str(ave_device_id)}
    if family == AVE_FAMILY_THERMOSTAT:
        if clean_name and clean_name.lower().startswith("thermostat "):
            return clean_name, None, None
        if clean_name:
            return None, "thermostat_named", {"name": clean_name}
        return None, "thermostat", {"id": str(ave_device_id)}
    if family == AVE_FAMILY_SCENARIO:
        if clean_name and clean_name.lower().startswith("scenario "):
            return clean_name, None, None
        if clean_name:
            return None, "scenario_named", {"name": clean_name}
        return None, "scenario", {"id": str(ave_device_id)}
    group = _FAMILY_TO_GROUP.get(family)
    if group:
        return None, group, None
    return None, "device_family", {"family": str(family)}


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

    name, translation_key, translation_placeholders = _endpoint_naming(
        family, ave_device_id, ave_name
    )

    return DeviceInfo(
        identifiers={endpoint_identifier},
        manufacturer="AVE",
        model=_endpoint_model(family),
        name=name,
        translation_key=translation_key,
        translation_placeholders=translation_placeholders,
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
    config_entry_id: str | None = None,
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
    if config_entry_id:
        try:
            device_registry.async_get_or_create(
                config_entry_id=config_entry_id,
                configuration_url=device_info.get("configuration_url"),
                connections=device_info.get("connections"),
                identifiers=resolved_identifiers,
                manufacturer=device_info.get("manufacturer"),
                model=device_info.get("model"),
                name=device_info.get("name"),
                translation_key=device_info.get("translation_key"),
                translation_placeholders=device_info.get("translation_placeholders"),
                via_device=device_info.get("via_device"),
            )
        except HomeAssistantError:
            # Tests and early setup may not have a registered config entry yet.
            pass
        else:
            return

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
        if via_entry is not None and via_entry.id not in {
            device_entry.id,
            current_via_device_id,
        }:
            updates["via_device_id"] = via_entry.id

    if updates:
        device_registry.async_update_device(device_id=device_entry.id, **updates)
