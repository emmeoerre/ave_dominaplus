"""Tests for cover entity update flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

from custom_components.ave_dominaplus import ws_commands
from custom_components.ave_dominaplus.const import (
    AVE_FAMILY_SHUTTER_HUNG,
    AVE_FAMILY_SHUTTER_ROLLING,
)
from custom_components.ave_dominaplus.cover import AveCover, update_cover
from custom_components.ave_dominaplus.uid_v2 import build_uid
from custom_components.ave_dominaplus.web_server import AveWebServer
from homeassistant.core import HomeAssistant


def _new_server(hass: HomeAssistant, **overrides) -> AveWebServer:
    """Build a webserver with defaults suitable for cover tests."""
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
    server = AveWebServer(settings, hass, object())
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    server.async_add_cv_entities = Mock()
    server.register_availability_entity = Mock()
    server.unregister_availability_entity = Mock()
    return server


def test_update_cover_creates_entity_when_address_available(
    hass: HomeAssistant,
) -> None:
    """A new cover should be created when address_dec is available."""
    server = _new_server(hass)

    update_cover(
        server,
        AVE_FAMILY_SHUTTER_ROLLING,
        ave_device_id=5,
        device_status=3,
        name="Living Room",
        address_dec=16,
    )

    unique_id = build_uid(server.mac_address, AVE_FAMILY_SHUTTER_ROLLING, 5, 16)
    assert unique_id in server.covers
    server.async_add_cv_entities.assert_called_once()
    created = server.covers[unique_id]
    assert created.name is None
    assert created._ave_name == "Living Room"
    assert created._attr_device_info.get("name") == "Living Room"


def test_update_cover_does_not_create_without_address(hass: HomeAssistant) -> None:
    """A new cover should not be created when address_dec is missing."""
    server = _new_server(hass)

    update_cover(
        server,
        AVE_FAMILY_SHUTTER_ROLLING,
        ave_device_id=5,
        device_status=3,
        name="Living Room",
        address_dec=None,
    )

    assert server.covers == {}
    server.async_add_cv_entities.assert_not_called()


def test_update_cover_skips_when_feature_disabled(hass: HomeAssistant) -> None:
    """Cover updates are ignored when fetch_covers is disabled."""
    server = _new_server(hass, fetch_covers=False)

    update_cover(
        server,
        AVE_FAMILY_SHUTTER_ROLLING,
        ave_device_id=5,
        device_status=3,
        name="Living Room",
        address_dec=16,
    )

    assert server.covers == {}
    server.async_add_cv_entities.assert_not_called()


def test_update_cover_existing_entity_respects_manual_rename(
    hass: HomeAssistant,
) -> None:
    """Existing cover updates should not overwrite HA user-renamed names."""
    server = _new_server(hass)
    unique_id = build_uid(server.mac_address, AVE_FAMILY_SHUTTER_ROLLING, 5, 16)
    cover = AveCover(
        unique_id, AVE_FAMILY_SHUTTER_ROLLING, 5, 3, server, address_dec=16
    )
    cover.set_name = Mock()
    cover.set_ave_name = Mock()
    cover.update_state = Mock()
    cover.set_address_dec = Mock()
    server.covers[unique_id] = cover

    update_cover(
        server,
        AVE_FAMILY_SHUTTER_ROLLING,
        ave_device_id=5,
        device_status=4,
        name="AVE Name",
        address_dec=16,
    )

    cover.update_state.assert_called_once_with(4)
    cover.set_ave_name.assert_called_once_with("AVE Name")
    cover.set_name.assert_not_called()
    cover.set_address_dec.assert_called_once_with(16)


def test_update_cover_existing_entity_updates_name_when_allowed(
    hass: HomeAssistant,
) -> None:
    """Existing cover updates should apply AVE name when no user override exists."""
    server = _new_server(hass)
    unique_id = build_uid(server.mac_address, AVE_FAMILY_SHUTTER_ROLLING, 5, 16)
    cover = AveCover(
        unique_id, AVE_FAMILY_SHUTTER_ROLLING, 5, 3, server, address_dec=16
    )
    cover.set_name = Mock()
    cover.set_ave_name = Mock()
    cover.update_state = Mock()
    server.covers[unique_id] = cover

    update_cover(
        server,
        AVE_FAMILY_SHUTTER_ROLLING,
        ave_device_id=5,
        device_status=2,
        name="AVE Name",
        address_dec=16,
    )

    cover.set_name.assert_not_called()
    cover.set_ave_name.assert_called_once_with("AVE Name")


def test_update_cover_finds_existing_without_address(hass: HomeAssistant) -> None:
    """Existing cover should still update when runtime update has no address_dec."""
    server = _new_server(hass)
    unique_id = build_uid(server.mac_address, AVE_FAMILY_SHUTTER_ROLLING, 6, 21)
    cover = AveCover(
        unique_id, AVE_FAMILY_SHUTTER_ROLLING, 6, 3, server, address_dec=21
    )
    cover.update_state = Mock()
    server.covers[unique_id] = cover

    update_cover(
        server,
        AVE_FAMILY_SHUTTER_ROLLING,
        ave_device_id=6,
        device_status=2,
        name=None,
        address_dec=None,
    )

    cover.update_state.assert_called_once_with(2)


async def test_cover_open_close_and_stop_commands(hass: HomeAssistant) -> None:
    """Cover command APIs should route to ws command helpers."""
    server = _new_server(hass)
    cover = AveCover("uid", AVE_FAMILY_SHUTTER_HUNG, 9, 3, server)

    with (
        patch.object(ws_commands, "cover_open", new=AsyncMock()) as cover_open,
        patch.object(ws_commands, "cover_close", new=AsyncMock()) as cover_close,
        patch.object(ws_commands, "cover_stop", new=AsyncMock()) as cover_stop,
    ):
        await cover.async_open_cover()
        await cover.async_close_cover()

        cover.update_state(2)
        await cover.async_stop_cover()

        cover.update_state(4)
        await cover.async_stop_cover()

    cover_open.assert_awaited_once_with(server, 9)
    cover_close.assert_awaited_once_with(server, 9)
    assert cover_stop.await_count == 2
    cover_stop.assert_any_await(server, 9, "8")
    cover_stop.assert_any_await(server, 9, "9")


async def test_cover_stop_ignored_when_not_moving(hass: HomeAssistant) -> None:
    """Stop command should be ignored when cover is not opening/closing."""
    server = _new_server(hass)
    cover = AveCover("uid", AVE_FAMILY_SHUTTER_ROLLING, 9, 3, server)

    with patch.object(ws_commands, "cover_stop", new=AsyncMock()) as cover_stop:
        await cover.async_stop_cover()

    cover_stop.assert_not_awaited()


async def test_cover_lifecycle_registers_and_unregisters_availability(
    hass: HomeAssistant,
) -> None:
    """Lifecycle hooks should register and unregister availability listeners."""
    server = _new_server(hass)
    cover = AveCover("uid", AVE_FAMILY_SHUTTER_ROLLING, 7, 3, server)
    cover.async_write_ha_state = Mock()
    cover._pending_state_write = True

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
        await cover.async_added_to_hass()
        await cover.async_will_remove_from_hass()

    server.register_availability_entity.assert_called_once_with(cover)
    server.unregister_availability_entity.assert_called_once_with(cover)
    cover.async_write_ha_state.assert_called_once()
