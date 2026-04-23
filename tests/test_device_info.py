"""Tests for AVE hub device registry metadata."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

from custom_components.ave_dominaplus.const import (
    AVE_FAMILY_DIMMER,
    AVE_FAMILY_MOTION_SENSOR,
    AVE_FAMILY_ONOFFLIGHTS,
    AVE_FAMILY_SCENARIO,
    AVE_FAMILY_SHUTTER_ROLLING,
    AVE_FAMILY_THERMOSTAT,
    DOMAIN,
)
from custom_components.ave_dominaplus.device_info import (
    build_endpoint_device_info,
    build_hub_device_info,
    ensure_covers_parent_device,
    ensure_lighting_parent_device,
    ensure_scenarios_parent_device,
    ensure_thermostats_parent_device,
    sync_device_registry_name,
)
from custom_components.ave_dominaplus.web_server import AveWebServer
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC


def _server_stub(
    *,
    mac: str = "",
    config_entry_unique_id: str | None = None,
    config_entry_id: str | None = None,
    host: str = "192.168.1.10",
):
    """Build a light-weight server stub for device_info tests."""
    return SimpleNamespace(
        mac_address=mac,
        config_entry_unique_id=config_entry_unique_id,
        config_entry_id=config_entry_id,
        settings=SimpleNamespace(host=host),
    )


def test_device_info_uses_mac_identifier_and_connection() -> None:
    """Use MAC as primary stable identifier when available."""
    server = _server_stub(mac="AA:BB:CC:DD:EE:FF")

    info = build_hub_device_info(cast(AveWebServer, server))

    assert info.get("identifiers") == {(DOMAIN, "hub_aa:bb:cc:dd:ee:ff")}
    assert info.get("connections") == {(CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")}


def test_device_info_falls_back_to_entry_unique_id() -> None:
    """Fallback to config entry unique id if MAC is not available."""
    server = _server_stub(config_entry_unique_id="AA:BB:CC:DD:EE:FF")

    info = build_hub_device_info(cast(AveWebServer, server))

    assert info.get("identifiers") == {(DOMAIN, "hub_aa:bb:cc:dd:ee:ff")}
    assert info.get("connections") == set()


def test_device_info_falls_back_to_entry_id() -> None:
    """Fallback to config entry id when MAC and unique id are missing."""
    server = _server_stub(config_entry_id="entry-123")

    info = build_hub_device_info(cast(AveWebServer, server))

    assert info.get("identifiers") == {(DOMAIN, "hub_entry-123")}


def test_device_info_falls_back_to_host() -> None:
    """Last-resort fallback uses host when no identifiers are available."""
    server = _server_stub(host="10.0.0.99")

    info = build_hub_device_info(cast(AveWebServer, server))

    assert info.get("identifiers") == {(DOMAIN, "hub_10.0.0.99")}
    assert info.get("manufacturer") == "AVE"
    assert info.get("model") == "AVE dominaplus webserver"
    assert info.get("translation_key") == "hub"
    assert info.get("configuration_url") == "http://10.0.0.99"


def test_endpoint_device_info_is_nested_under_hub() -> None:
    """Lighting endpoints should be child devices under shared lighting parent."""
    server = _server_stub(mac="AA:BB:CC:DD:EE:FF", host="10.0.0.99")

    info = build_endpoint_device_info(
        cast(AveWebServer, server),
        family=AVE_FAMILY_DIMMER,
        ave_device_id=45,
    )

    assert info.get("identifiers") == {
        (DOMAIN, "endpoint_aa:bb:cc:dd:ee:ff_light_2_45")
    }
    assert info.get("via_device") == (DOMAIN, "endpoint_aa:bb:cc:dd:ee:ff_lighting")
    assert info.get("name") == "Dimmer 45"
    assert info.get("model") == "AVE dominaplus lighting"
    assert info.get("manufacturer") == "AVE"
    assert info.get("configuration_url") == "http://10.0.0.99"


def test_endpoint_onoff_light_uses_own_child_identifier() -> None:
    """On/off lights should get per-device child identifiers and names."""
    server = _server_stub(config_entry_id="entry-123")

    info = build_endpoint_device_info(
        cast(AveWebServer, server),
        family=AVE_FAMILY_ONOFFLIGHTS,
        ave_device_id=11,
    )

    assert info.get("identifiers") == {(DOMAIN, "endpoint_entry-123_light_1_11")}
    assert info.get("via_device") == (DOMAIN, "endpoint_entry-123_lighting")
    assert info.get("name") == "Light 11"


def test_ensure_lighting_parent_device_registers_under_hub(hass) -> None:
    """Ensure helper creates shared lighting parent device linked to hub."""
    server = _server_stub(mac="AA:BB:CC:DD:EE:FF", host="10.0.0.99")
    server.hass = hass

    with patch("custom_components.ave_dominaplus.device_info.dr.async_get") as get_reg:
        registry = get_reg.return_value
        ensure_lighting_parent_device(cast(AveWebServer, server), "entry-123")

    registry.async_get_or_create.assert_called_once_with(
        config_entry_id="entry-123",
        identifiers={(DOMAIN, "endpoint_aa:bb:cc:dd:ee:ff_lighting")},
        manufacturer="AVE",
        model="AVE dominaplus lighting",
        translation_key="lighting",
        name=None,
        via_device=(DOMAIN, "hub_aa:bb:cc:dd:ee:ff"),
        configuration_url="http://10.0.0.99",
    )


def test_ensure_scenarios_parent_device_registers_under_hub(hass) -> None:
    """Ensure helper creates shared scenarios parent device linked to hub."""
    server = _server_stub(mac="AA:BB:CC:DD:EE:FF", host="10.0.0.99")
    server.hass = hass

    with patch("custom_components.ave_dominaplus.device_info.dr.async_get") as get_reg:
        registry = get_reg.return_value
        ensure_scenarios_parent_device(cast(AveWebServer, server), "entry-123")

    registry.async_get_or_create.assert_called_once_with(
        config_entry_id="entry-123",
        identifiers={(DOMAIN, "endpoint_aa:bb:cc:dd:ee:ff_scenarios")},
        manufacturer="AVE",
        model="AVE dominaplus scenarios",
        translation_key="scenarios",
        name=None,
        via_device=(DOMAIN, "hub_aa:bb:cc:dd:ee:ff"),
        configuration_url="http://10.0.0.99",
    )


def test_ensure_covers_parent_device_registers_under_hub(hass) -> None:
    """Ensure helper creates shared covers parent device linked to hub."""
    server = _server_stub(mac="AA:BB:CC:DD:EE:FF", host="10.0.0.99")
    server.hass = hass

    with patch("custom_components.ave_dominaplus.device_info.dr.async_get") as get_reg:
        registry = get_reg.return_value
        ensure_covers_parent_device(cast(AveWebServer, server), "entry-123")

    registry.async_get_or_create.assert_called_once_with(
        config_entry_id="entry-123",
        identifiers={(DOMAIN, "endpoint_aa:bb:cc:dd:ee:ff_covers")},
        manufacturer="AVE",
        model="AVE dominaplus covers",
        translation_key="covers",
        name=None,
        via_device=(DOMAIN, "hub_aa:bb:cc:dd:ee:ff"),
        configuration_url="http://10.0.0.99",
    )


def test_ensure_thermostats_parent_device_registers_under_hub(hass) -> None:
    """Ensure helper creates shared thermostats parent device linked to hub."""
    server = _server_stub(mac="AA:BB:CC:DD:EE:FF", host="10.0.0.99")
    server.hass = hass

    with patch("custom_components.ave_dominaplus.device_info.dr.async_get") as get_reg:
        registry = get_reg.return_value
        ensure_thermostats_parent_device(cast(AveWebServer, server), "entry-123")

    registry.async_get_or_create.assert_called_once_with(
        config_entry_id="entry-123",
        identifiers={(DOMAIN, "endpoint_aa:bb:cc:dd:ee:ff_thermostats")},
        manufacturer="AVE",
        model="AVE dominaplus thermostats",
        translation_key="thermostats",
        name=None,
        via_device=(DOMAIN, "hub_aa:bb:cc:dd:ee:ff"),
        configuration_url="http://10.0.0.99",
    )


def test_sync_device_registry_name_updates_name_and_via() -> None:
    """Shared sync helper should update device name and parent linkage."""
    hass = object()
    registry = SimpleNamespace()
    child = SimpleNamespace(
        id="child-id",
        name="Old",
        name_by_user=None,
        via_device_id=None,
    )
    parent = SimpleNamespace(id="parent-id")

    def _get_device(*, identifiers):
        identifier = next(iter(identifiers))
        if identifier == (DOMAIN, "endpoint_entry-123_light_2_45"):
            return child
        if identifier == (DOMAIN, "endpoint_entry-123_lighting"):
            return parent
        return None

    registry.async_get_device = Mock(side_effect=_get_device)
    registry.async_update_device = Mock()

    sync_device_registry_name(
        hass,
        {
            "identifiers": {(DOMAIN, "endpoint_entry-123_light_2_45")},
            "name": "Kitchen",
            "via_device": (DOMAIN, "endpoint_entry-123_lighting"),
        },
        device_registry_getter=lambda _hass: registry,
    )

    registry.async_update_device.assert_called_once_with(
        device_id="child-id",
        name="Kitchen",
        via_device_id="parent-id",
    )


def test_sync_device_registry_name_respects_user_name_but_updates_via() -> None:
    """User device names should be preserved while still updating parent linkage."""
    hass = object()
    registry = SimpleNamespace()
    child = SimpleNamespace(
        id="child-id",
        name="Old",
        name_by_user="Custom",
        via_device_id=None,
    )
    parent = SimpleNamespace(id="parent-id")

    def _get_device(*, identifiers):
        identifier = next(iter(identifiers))
        if identifier == (DOMAIN, "endpoint_entry-123_light_1_11"):
            return child
        if identifier == (DOMAIN, "endpoint_entry-123_lighting"):
            return parent
        return None

    registry.async_get_device = Mock(side_effect=_get_device)
    registry.async_update_device = Mock()

    sync_device_registry_name(
        hass,
        {
            "identifiers": {(DOMAIN, "endpoint_entry-123_light_1_11")},
            "name": "Hall",
            "via_device": (DOMAIN, "endpoint_entry-123_lighting"),
        },
        device_registry_getter=lambda _hass: registry,
    )

    registry.async_update_device.assert_called_once_with(
        device_id="child-id",
        via_device_id="parent-id",
    )


def test_endpoint_device_info_uses_entry_fallback_identifier() -> None:
    """Endpoint identifier should fall back to config entry id when needed."""
    server = _server_stub(config_entry_id="entry-123")

    info = build_endpoint_device_info(
        cast(AveWebServer, server),
        family=AVE_FAMILY_THERMOSTAT,
        ave_device_id=7,
    )

    assert info.get("identifiers") == {(DOMAIN, "endpoint_entry-123_thermostat_7")}
    assert info.get("via_device") == (DOMAIN, "endpoint_entry-123_thermostats")
    assert info.get("name") == "Thermostat 7"


def test_endpoint_cover_uses_per_device_identifier_and_parent() -> None:
    """Cover endpoints should be grouped under a shared covers parent."""
    server = _server_stub(config_entry_id="entry-123")

    info = build_endpoint_device_info(
        cast(AveWebServer, server),
        family=AVE_FAMILY_SHUTTER_ROLLING,
        ave_device_id=14,
    )

    assert info.get("identifiers") == {(DOMAIN, "endpoint_entry-123_cover_3_14")}
    assert info.get("via_device") == (DOMAIN, "endpoint_entry-123_covers")
    assert info.get("name") == "Shutter 14"


def test_endpoint_thermostat_name_is_cleaned_for_offset_suffix() -> None:
    """Thermostat device names should drop an "offset" suffix when present."""
    server = _server_stub(config_entry_id="entry-123")

    info = build_endpoint_device_info(
        cast(AveWebServer, server),
        family=AVE_FAMILY_THERMOSTAT,
        ave_device_id=9,
        ave_name="Living Room Offset",
    )

    assert info.get("identifiers") == {(DOMAIN, "endpoint_entry-123_thermostat_9")}
    assert info.get("name") == "Thermostat Living Room"


def test_endpoint_thermostat_name_keeps_existing_prefix() -> None:
    """Thermostat names that already include prefix should not be doubled."""
    server = _server_stub(config_entry_id="entry-123")

    info = build_endpoint_device_info(
        cast(AveWebServer, server),
        family=AVE_FAMILY_THERMOSTAT,
        ave_device_id=10,
        ave_name="Thermostat Studio",
    )

    assert info.get("name") == "Thermostat Studio"


def test_endpoint_motion_sensors_are_grouped() -> None:
    """All antitheft motion sensors should map to one grouped child device."""
    server = _server_stub(config_entry_id="entry-123")

    info = build_endpoint_device_info(
        cast(AveWebServer, server),
        family=AVE_FAMILY_MOTION_SENSOR,
        ave_device_id=44,
    )

    assert info.get("identifiers") == {(DOMAIN, "endpoint_entry-123_antitheft_sensors")}
    assert info.get("translation_key") == "antitheft_sensors"


def test_endpoint_scenario_name_falls_back_to_device_id() -> None:
    """Scenario devices should use id-based fallback when AVE name is missing."""
    server = _server_stub(config_entry_id="entry-123")

    info = build_endpoint_device_info(
        cast(AveWebServer, server),
        family=AVE_FAMILY_SCENARIO,
        ave_device_id=29,
    )

    assert info.get("identifiers") == {(DOMAIN, "endpoint_entry-123_scenario_29")}
    assert info.get("via_device") == (DOMAIN, "endpoint_entry-123_scenarios")
    assert info.get("name") == "Scenario 29"


def test_endpoint_scenario_name_adds_prefix_when_needed() -> None:
    """Scenario names should be prefixed consistently when AVE omits it."""
    server = _server_stub(config_entry_id="entry-123")

    info = build_endpoint_device_info(
        cast(AveWebServer, server),
        family=AVE_FAMILY_SCENARIO,
        ave_device_id=31,
        ave_name="Evening",
    )

    assert info.get("name") == "Scenario Evening"


def test_endpoint_scenario_name_keeps_existing_prefix() -> None:
    """Scenario names that already include prefix should not be doubled."""
    server = _server_stub(config_entry_id="entry-123")

    info = build_endpoint_device_info(
        cast(AveWebServer, server),
        family=AVE_FAMILY_SCENARIO,
        ave_device_id=32,
        ave_name="Scenario Night",
    )

    assert info.get("name") == "Scenario Night"
