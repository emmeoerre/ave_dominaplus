"""Tests for switch entity update flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

from custom_components.ave_dominaplus import ws_commands
from custom_components.ave_dominaplus.const import (
    AVE_FAMILY_ONOFFLIGHTS,
    AVE_FAMILY_SCENARIO,
)
from custom_components.ave_dominaplus.switch import (
    LightSwitch,
    set_sensor_uid,
    update_switch,
)
from custom_components.ave_dominaplus.web_server import AveWebServer
from homeassistant.core import HomeAssistant


def _new_server(hass: HomeAssistant, **overrides) -> AveWebServer:
    """Build a webserver with defaults suitable for switch tests."""
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
    server.async_add_sw_entities = Mock()
    server.register_availability_entity = Mock()
    server.unregister_availability_entity = Mock()
    return server


def test_update_switch_creates_entity_for_onoff_family(hass: HomeAssistant) -> None:
    """A new switch should be created for ON/OFF light family updates."""
    server = _new_server(hass)

    update_switch(
        server,
        AVE_FAMILY_ONOFFLIGHTS,
        ave_device_id=5,
        device_status=1,
        name="Kitchen",
        address_dec=22,
    )

    unique_id = set_sensor_uid(server, AVE_FAMILY_ONOFFLIGHTS, 5)
    assert unique_id in server.switches
    server.async_add_sw_entities.assert_called_once()
    assert server.switches[unique_id].name == "Kitchen"


def test_update_switch_skips_unsupported_family(hass: HomeAssistant) -> None:
    """Families outside ON/OFF lights should be ignored by update_switch."""
    server = _new_server(hass)

    update_switch(server, AVE_FAMILY_SCENARIO, 7, 1, name="Scenario")

    assert server.switches == {}
    server.async_add_sw_entities.assert_not_called()


def test_update_switch_skips_when_lights_feature_disabled(hass: HomeAssistant) -> None:
    """ON/OFF switch updates are ignored when fetch_lights is disabled."""
    server = _new_server(hass, fetch_lights=False)

    update_switch(server, AVE_FAMILY_ONOFFLIGHTS, 5, 1)

    assert server.switches == {}
    server.async_add_sw_entities.assert_not_called()


def test_update_switch_existing_respects_manual_rename(hass: HomeAssistant) -> None:
    """Existing switch updates should not overwrite HA user-renamed names."""
    server = _new_server(hass)
    unique_id = set_sensor_uid(server, AVE_FAMILY_ONOFFLIGHTS, 5)
    switch = LightSwitch(unique_id, AVE_FAMILY_ONOFFLIGHTS, 5, 0, server)
    switch.update_state = Mock()
    switch.set_name = Mock()
    switch.set_ave_name = Mock()
    switch.set_address_dec = Mock()
    server.switches[unique_id] = switch

    with patch(
        "custom_components.ave_dominaplus.switch.check_name_changed",
        return_value=True,
    ):
        update_switch(server, AVE_FAMILY_ONOFFLIGHTS, 5, 1, name="AVE", address_dec=9)

    switch.update_state.assert_called_once_with(1)
    switch.set_ave_name.assert_called_once_with("AVE")
    switch.set_name.assert_not_called()
    switch.set_address_dec.assert_called_once_with(9)


def test_update_switch_existing_updates_name_when_allowed(hass: HomeAssistant) -> None:
    """Existing switch updates should apply AVE name when no user override exists."""
    server = _new_server(hass)
    unique_id = set_sensor_uid(server, AVE_FAMILY_ONOFFLIGHTS, 5)
    switch = LightSwitch(unique_id, AVE_FAMILY_ONOFFLIGHTS, 5, 0, server)
    switch.set_name = Mock()
    switch.set_ave_name = Mock()
    server.switches[unique_id] = switch

    with patch(
        "custom_components.ave_dominaplus.switch.check_name_changed",
        return_value=False,
    ):
        update_switch(server, AVE_FAMILY_ONOFFLIGHTS, 5, 1, name="AVE")

    switch.set_ave_name.assert_called_once_with("AVE")
    switch.set_name.assert_called_once_with("AVE")


async def test_switch_commands_route_to_webserver(hass: HomeAssistant) -> None:
    """Switch command methods should route to webserver command APIs."""
    server = _new_server(hass)
    switch = LightSwitch("uid", AVE_FAMILY_ONOFFLIGHTS, 11, 0, server)

    with (
        patch.object(ws_commands, "switch_turn_on", new=AsyncMock()) as switch_turn_on,
        patch.object(
            ws_commands, "switch_turn_off", new=AsyncMock()
        ) as switch_turn_off,
        patch.object(ws_commands, "switch_toggle", new=AsyncMock()) as switch_toggle,
    ):
        await switch.async_turn_on()
        await switch.async_turn_off()
        await switch.async_toggle()

    switch_turn_on.assert_awaited_once_with(server, 11)
    switch_turn_off.assert_awaited_once_with(server, 11)
    switch_toggle.assert_awaited_once_with(server, 11)


async def test_switch_lifecycle_registers_and_unregisters_availability(
    hass: HomeAssistant,
) -> None:
    """Lifecycle hooks should register and unregister availability listeners."""
    server = _new_server(hass)
    switch = LightSwitch("uid", AVE_FAMILY_ONOFFLIGHTS, 11, 0, server)
    switch.async_write_ha_state = Mock()
    switch._pending_state_write = True

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
        await switch.async_added_to_hass()
        await switch.async_will_remove_from_hass()

    server.register_availability_entity.assert_called_once_with(switch)
    server.unregister_availability_entity.assert_called_once_with(switch)
    switch.async_write_ha_state.assert_called_once()


def test_switch_build_name_covers_scenario_family(hass: HomeAssistant) -> None:
    """Scenario family should get a scenario-oriented default name."""
    server = _new_server(hass)
    switch = LightSwitch("uid", AVE_FAMILY_SCENARIO, 33, 0, server)

    assert switch.translation_key == "scenario_switch"
    assert switch.translation_placeholders == {"id": "33"}


def test_switch_set_ave_name_updates_device_info_name(hass: HomeAssistant) -> None:
    """AVE name updates should refresh switch endpoint device_info display name."""
    server = _new_server(hass)
    switch = LightSwitch(
        "uid",
        AVE_FAMILY_ONOFFLIGHTS,
        12,
        0,
        server,
        name="Light 12",
    )
    switch.entity_id = "switch.uid"
    switch.async_write_ha_state = Mock()

    assert switch._attr_device_info.get("name") == "Light 12"

    switch.set_ave_name("Kitchen")

    assert switch._attr_device_info.get("name") == "Kitchen"
