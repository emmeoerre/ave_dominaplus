"""Tests for scenario button entity update flow."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from custom_components.ave_dominaplus import ws_commands
from custom_components.ave_dominaplus.button import (
    ScenarioButton,
    set_button_uid,
    update_button,
)
from custom_components.ave_dominaplus.const import AVE_FAMILY_SCENARIO
from custom_components.ave_dominaplus.uid_v2 import build_uid
from custom_components.ave_dominaplus.web_server import AveWebServer
from homeassistant.core import HomeAssistant


def _new_server(hass: HomeAssistant, **overrides) -> AveWebServer:
    """Build a webserver with defaults suitable for button tests."""
    settings: dict[str, object] = {
        "ip_address": "192.168.1.10",
        "get_entities_names": True,
        "fetch_sensor_areas": True,
        "fetch_sensors": True,
        "fetch_lights": True,
        "fetch_covers": True,
        "fetch_scenarios": True,
        "fetch_thermostats": True,
        "on_off_lights_as_switch": True,
    }
    settings.update(overrides)
    server = AveWebServer(settings, hass, object())
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    server.async_add_bt_entities = Mock()
    server.register_availability_entity = Mock()
    server.unregister_availability_entity = Mock()
    return server


def test_update_button_creates_scenario_button_with_ave_name(
    hass: HomeAssistant,
) -> None:
    """Scenario updates should create scenario button entities."""
    server = _new_server(hass)

    update_button(server, AVE_FAMILY_SCENARIO, 8, name="Evening")

    unique_id = set_button_uid(server, AVE_FAMILY_SCENARIO, 8)
    assert unique_id in server.buttons
    created = server.buttons[unique_id]
    assert created.name == "Evening Run"
    server.async_add_bt_entities.assert_called_once()
    assert unique_id == build_uid(
        server.mac_address,
        AVE_FAMILY_SCENARIO,
        8,
        0,
        suffix="button",
    )


def test_update_button_skips_when_feature_disabled(hass: HomeAssistant) -> None:
    """Scenario button creation is ignored when fetch_scenarios is disabled."""
    server = _new_server(hass, fetch_scenarios=False)

    update_button(server, AVE_FAMILY_SCENARIO, 8, name="Evening")

    assert server.buttons == {}
    server.async_add_bt_entities.assert_not_called()


def test_update_button_existing_respects_manual_rename(hass: HomeAssistant) -> None:
    """Existing scenario button updates should not overwrite user-defined names."""
    server = _new_server(hass)
    unique_id = set_button_uid(server, AVE_FAMILY_SCENARIO, 8)
    button = ScenarioButton(unique_id, AVE_FAMILY_SCENARIO, 8, server)
    button.set_name = Mock()
    button.set_ave_name = Mock()
    server.buttons[unique_id] = button

    with patch(
        "custom_components.ave_dominaplus.button.check_name_changed",
        return_value=True,
    ):
        update_button(server, AVE_FAMILY_SCENARIO, 8, name="Evening")

    button.set_ave_name.assert_called_once_with("Evening")
    button.set_name.assert_not_called()


def test_update_button_existing_refreshes_device_info_name(hass: HomeAssistant) -> None:
    """Scenario device info name should refresh when AVE name arrives later."""
    server = _new_server(hass, get_entities_names=True)

    update_button(server, AVE_FAMILY_SCENARIO, 21, name=None)
    unique_id = set_button_uid(server, AVE_FAMILY_SCENARIO, 21)
    button = server.buttons[unique_id]
    assert button._attr_device_info.get("name") == "Scenario 21"

    update_button(server, AVE_FAMILY_SCENARIO, 21, name="Evening")

    assert button.name == "Evening Run"
    assert button._attr_device_info.get("name") == "Scenario Evening"


def test_scenario_button_sync_device_name_respects_name_by_user(
    hass: HomeAssistant,
) -> None:
    """Device registry updates must not overwrite user-customized device names."""
    server = _new_server(hass)
    button = ScenarioButton("uid", AVE_FAMILY_SCENARIO, 17, server)
    button.entity_id = "button.uid"
    button.async_write_ha_state = Mock()

    device_registry = Mock()
    device_registry.async_get_device.return_value = SimpleNamespace(
        id="dev-1",
        name_by_user="Custom",
        name="Old",
    )

    with patch(
        "custom_components.ave_dominaplus.button.dr.async_get",
        return_value=device_registry,
    ):
        button.set_ave_name("Evening")

    assert button._attr_device_info.get("name") == "Scenario Evening"
    device_registry.async_update_device.assert_not_called()


def test_scenario_button_sync_device_name_updates_when_not_customized(
    hass: HomeAssistant,
) -> None:
    """Device registry name should update when no user override exists."""
    server = _new_server(hass)
    button = ScenarioButton("uid", AVE_FAMILY_SCENARIO, 18, server)
    button.entity_id = "button.uid"
    button.async_write_ha_state = Mock()

    device_registry = Mock()
    device_registry.async_get_device.return_value = SimpleNamespace(
        id="dev-2",
        name_by_user=None,
        name="Scenario 18",
    )

    with patch(
        "custom_components.ave_dominaplus.button.dr.async_get",
        return_value=device_registry,
    ):
        button.set_ave_name("Night")

    device_registry.async_update_device.assert_called_once_with(
        device_id="dev-2",
        name="Scenario Night",
    )


async def test_scenario_button_press_routes_to_webserver(hass: HomeAssistant) -> None:
    """Scenario button presses should execute the matching scenario."""
    server = _new_server(hass)
    button = ScenarioButton("uid", AVE_FAMILY_SCENARIO, 11, server)

    with patch.object(ws_commands, "scenario_execute", new=AsyncMock()) as execute:
        await button.async_press()

    execute.assert_awaited_once_with(server, 11)


async def test_scenario_button_lifecycle_registers_availability(
    hass: HomeAssistant,
) -> None:
    """Lifecycle hooks should register and unregister availability listeners."""
    server = _new_server(hass)
    button = ScenarioButton("uid", AVE_FAMILY_SCENARIO, 11, server)
    button.async_write_ha_state = Mock()
    button._pending_state_write = True
    server.buttons["uid"] = button

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
        await button.async_added_to_hass()
        await button.async_will_remove_from_hass()

    server.register_availability_entity.assert_called_once_with(button)
    server.unregister_availability_entity.assert_called_once_with(button)
    button.async_write_ha_state.assert_called_once()
    assert "uid" not in server.buttons
