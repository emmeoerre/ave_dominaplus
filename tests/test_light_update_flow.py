"""Tests for light entity update flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

from custom_components.ave_dominaplus import ws_commands
from custom_components.ave_dominaplus.const import (
    AVE_FAMILY_DIMMER,
    AVE_FAMILY_ONOFFLIGHTS,
)
from custom_components.ave_dominaplus.light import DimmerLight, update_light
from custom_components.ave_dominaplus.uid_v2 import build_uid
from custom_components.ave_dominaplus.web_server import AveWebServer
from homeassistant.core import HomeAssistant


def _new_server(hass: HomeAssistant, **overrides) -> AveWebServer:
    """Build a webserver with defaults suitable for light tests."""
    settings: dict[str, object] = {
        "ip_address": "192.168.1.10",
        "get_entities_names": True,
        "fetch_sensor_areas": True,
        "fetch_sensors": True,
        "fetch_lights": True,
        "fetch_covers": True,
        "fetch_thermostats": True,
        "on_off_lights_as_switch": True,
    }
    settings.update(overrides)
    server = AveWebServer(settings, hass)
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    server.async_add_lg_entities = Mock()
    server.register_availability_entity = Mock()
    server.unregister_availability_entity = Mock()
    return server


def test_update_light_creates_entity_when_address_available(
    hass: HomeAssistant,
) -> None:
    """A new light should be created when address_dec is available."""
    server = _new_server(hass)

    update_light(
        server,
        AVE_FAMILY_DIMMER,
        ave_device_id=5,
        device_status=20,
        name="Kitchen",
        address_dec=16,
    )

    unique_id = build_uid(server.mac_address, AVE_FAMILY_DIMMER, 5, 16)
    assert unique_id in server.lights
    server.async_add_lg_entities.assert_called_once()
    created = server.lights[unique_id]
    assert created.name == "Kitchen"


def test_update_light_does_not_create_without_address(hass: HomeAssistant) -> None:
    """A new light should not be created when address_dec is missing."""
    server = _new_server(hass)

    update_light(
        server,
        AVE_FAMILY_DIMMER,
        ave_device_id=5,
        device_status=20,
        name="Kitchen",
        address_dec=None,
    )

    assert server.lights == {}
    server.async_add_lg_entities.assert_not_called()


def test_update_light_skips_when_feature_disabled(hass: HomeAssistant) -> None:
    """Light updates are ignored when fetch_lights is disabled."""
    server = _new_server(hass, fetch_lights=False)

    update_light(server, AVE_FAMILY_DIMMER, 5, 20, name="Kitchen", address_dec=16)

    assert server.lights == {}
    server.async_add_lg_entities.assert_not_called()


def test_update_light_existing_entity_uses_override_protection(
    hass: HomeAssistant,
) -> None:
    """Existing light updates should respect HA user rename protection."""
    server = _new_server(hass)
    unique_id = build_uid(server.mac_address, AVE_FAMILY_DIMMER, 5, 16)
    light = DimmerLight(unique_id, AVE_FAMILY_DIMMER, 5, 0, server, address_dec=16)
    light.handle_webserver_update = Mock()
    server.lights[unique_id] = light

    with patch(
        "custom_components.ave_dominaplus.light.check_name_changed",
        return_value=True,
    ):
        update_light(
            server,
            AVE_FAMILY_DIMMER,
            ave_device_id=5,
            device_status=22,
            name="Renamed at AVE",
            address_dec=16,
        )

    light.handle_webserver_update.assert_called_once_with(
        device_status=22,
        name="Renamed at AVE",
        address_dec=16,
        allow_name_update=False,
    )


def test_update_light_existing_entity_allows_name_update(hass: HomeAssistant) -> None:
    """Existing light updates should allow AVE name changes when user did not rename."""
    server = _new_server(hass)
    unique_id = build_uid(server.mac_address, AVE_FAMILY_DIMMER, 5, 16)
    light = DimmerLight(unique_id, AVE_FAMILY_DIMMER, 5, 0, server, address_dec=16)
    light.handle_webserver_update = Mock()
    server.lights[unique_id] = light

    with patch(
        "custom_components.ave_dominaplus.light.check_name_changed",
        return_value=False,
    ):
        update_light(
            server,
            AVE_FAMILY_DIMMER,
            ave_device_id=5,
            device_status=22,
            name="Renamed at AVE",
            address_dec=16,
        )

    light.handle_webserver_update.assert_called_once_with(
        device_status=22,
        name="Renamed at AVE",
        address_dec=16,
        allow_name_update=True,
    )


def test_update_light_finds_existing_without_address(hass: HomeAssistant) -> None:
    """Existing light should still update when runtime update lacks address_dec."""
    server = _new_server(hass)
    unique_id = build_uid(server.mac_address, AVE_FAMILY_DIMMER, 9, 18)
    light = DimmerLight(unique_id, AVE_FAMILY_DIMMER, 9, 0, server, address_dec=18)
    light.handle_webserver_update = Mock()
    server.lights[unique_id] = light

    update_light(
        server,
        AVE_FAMILY_DIMMER,
        ave_device_id=9,
        device_status=31,
        name=None,
        address_dec=None,
    )

    light.handle_webserver_update.assert_called_once_with(
        device_status=31,
        name=None,
        address_dec=None,
        allow_name_update=False,
    )


def test_update_light_uses_default_name_when_entity_names_disabled(
    hass: HomeAssistant,
) -> None:
    """New light should keep generated name when AVE names are disabled."""
    server = _new_server(hass, get_entities_names=False)

    update_light(
        server,
        AVE_FAMILY_DIMMER,
        ave_device_id=4,
        device_status=10,
        name="AVE Kitchen",
        address_dec=12,
    )

    unique_id = build_uid(server.mac_address, AVE_FAMILY_DIMMER, 4, 12)
    created = server.lights[unique_id]
    assert created.translation_key == "dimmer"
    assert created.name is None


def test_light_set_ave_name_updates_device_info_name(hass: HomeAssistant) -> None:
    """AVE name updates should refresh the endpoint device_info display name."""
    server = _new_server(hass)
    light = DimmerLight(
        "uid",
        AVE_FAMILY_ONOFFLIGHTS,
        12,
        0,
        server,
        name="Light 12",
    )
    light.entity_id = "light.uid"
    light.async_write_ha_state = Mock()

    assert light._attr_device_info.get("name") == "Light 12"

    light.set_ave_name("Kitchen")

    assert light._attr_device_info.get("name") == "Kitchen"


async def test_dimmer_turn_on_converts_brightness_scale(hass: HomeAssistant) -> None:
    """Dimmer turn_on should convert HA brightness (0..255) to AVE (1..31)."""
    server = _new_server(hass)
    light = DimmerLight("uid", AVE_FAMILY_DIMMER, 7, 0, server)

    with patch.object(ws_commands, "dimmer_turn_on", new=AsyncMock()) as dimmer_turn_on:
        await light.async_turn_on(brightness=128)

    dimmer_turn_on.assert_awaited_once_with(server, 7, 15)


async def test_onoff_light_turn_on_routes_to_switch(hass: HomeAssistant) -> None:
    """ON/OFF light turn_on should call switch turn_on API."""
    server = _new_server(hass)
    light = DimmerLight("uid", AVE_FAMILY_ONOFFLIGHTS, 11, 0, server)

    with (
        patch.object(ws_commands, "switch_turn_on", new=AsyncMock()) as switch_turn_on,
        patch.object(ws_commands, "dimmer_turn_on", new=AsyncMock()) as dimmer_turn_on,
    ):
        await light.async_turn_on()

    switch_turn_on.assert_awaited_once_with(server, 11)
    dimmer_turn_on.assert_not_awaited()


async def test_light_lifecycle_registers_and_unregisters_availability(
    hass: HomeAssistant,
) -> None:
    """Lifecycle hooks should register and unregister availability listeners."""
    server = _new_server(hass)
    light = DimmerLight("uid", AVE_FAMILY_DIMMER, 7, 0, server)
    light.async_write_ha_state = Mock()
    light._pending_state_write = True
    server.lights["uid"] = light

    with (
        patch(
            "homeassistant.helpers.entity.Entity.async_added_to_hass",
            new=AsyncMock(),
        ),
        patch(
            "homeassistant.helpers.entity.Entity.async_will_remove_from_hass",
            new=AsyncMock(),
        ),
    ):
        await light.async_added_to_hass()
        await light.async_will_remove_from_hass()

    server.register_availability_entity.assert_called_once_with(light)
    server.unregister_availability_entity.assert_called_once_with(light)
    light.async_write_ha_state.assert_called_once()
    assert "uid" not in server.lights
