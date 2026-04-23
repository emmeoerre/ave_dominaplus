"""Additional branch coverage tests for AVE scenario button platform."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.ave_dominaplus.button import (
    ScenarioButton,
    adopt_existing_buttons,
    async_setup_entry,
    check_name_changed,
    set_button_uid,
    update_button,
)
from custom_components.ave_dominaplus.const import AVE_FAMILY_SCENARIO
from homeassistant.exceptions import ConfigEntryNotReady

from .web_server_harness import make_server


def _entry(runtime_data, entry_id: str = "entry-1"):
    return SimpleNamespace(runtime_data=runtime_data, entry_id=entry_id)


@pytest.mark.asyncio
async def test_async_setup_entry_raises_when_webserver_missing() -> None:
    """Setup should raise ConfigEntryNotReady when runtime_data is missing."""
    with pytest.raises(ConfigEntryNotReady):
        await async_setup_entry(None, _entry(None), Mock())


@pytest.mark.asyncio
async def test_async_setup_entry_registers_callbacks_and_adopts(hass) -> None:
    """Setup should register callbacks and adopt existing button entities."""
    server = make_server(hass)
    server.set_async_add_bt_entities = AsyncMock()
    server.set_update_button = AsyncMock()
    entry = _entry(server)

    with patch(
        "custom_components.ave_dominaplus.button.adopt_existing_buttons",
        new=AsyncMock(),
    ) as adopt_mock:
        add_entities = Mock()
        await async_setup_entry(hass, entry, add_entities)

    server.set_async_add_bt_entities.assert_awaited_once_with(add_entities)
    server.set_update_button.assert_awaited_once()
    adopt_mock.assert_awaited_once_with(server, entry)


@pytest.mark.asyncio
async def test_async_setup_entry_skips_adopt_when_scenarios_disabled(hass) -> None:
    """Setup should return early when scenario feature is disabled."""
    server = make_server(hass, fetch_scenarios=False)
    server.set_async_add_bt_entities = AsyncMock()
    server.set_update_button = AsyncMock()
    entry = _entry(server)

    with patch(
        "custom_components.ave_dominaplus.button.adopt_existing_buttons",
        new=AsyncMock(),
    ) as adopt_mock:
        await async_setup_entry(hass, entry, Mock())

    server.set_async_add_bt_entities.assert_awaited_once()
    server.set_update_button.assert_awaited_once()
    adopt_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_adopt_existing_buttons_returns_when_registry_missing(hass) -> None:
    """Adoption should return cleanly when entity registry is unavailable."""
    server = make_server(hass)

    with patch(
        "custom_components.ave_dominaplus.button.er.async_get",
        return_value=None,
    ):
        await adopt_existing_buttons(server, _entry(server))


@pytest.mark.asyncio
async def test_adopt_existing_buttons_filters_and_adopts_valid_entry(hass) -> None:
    """Adoption should filter invalid entries and adopt valid scenario buttons."""
    server = make_server(hass, fetch_scenarios=True)
    server.async_add_bt_entities = Mock()
    server.buttons["uid-dup"] = object()

    entities = [
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="switch",
            unique_id="uid-switch",
            name="Skip",
            original_name=None,
            entity_id="switch.skip",
        ),
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="button",
            unique_id="uid-dup",
            name="Duplicate",
            original_name=None,
            entity_id="button.dup",
        ),
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="button",
            unique_id="uid-parse-none",
            name="No Parse",
            original_name=None,
            entity_id="button.no_parse",
        ),
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="button",
            unique_id="uid-suffix",
            name="Wrong Suffix",
            original_name=None,
            entity_id="button.wrong_suffix",
        ),
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="button",
            unique_id="uid-family",
            name="Wrong Family",
            original_name=None,
            entity_id="button.wrong_family",
        ),
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="button",
            unique_id="uid-valid",
            name=None,
            original_name="Night",
            entity_id="button.night",
        ),
    ]

    def _parse_uid(uid: str):
        if uid == "uid-parse-none":
            return None
        if uid == "uid-suffix":
            return ("aa:bb:cc:dd:ee:ff", AVE_FAMILY_SCENARIO, 1, 0, "running")
        if uid == "uid-family":
            return ("aa:bb:cc:dd:ee:ff", 999, 2, 0, "button")
        if uid == "uid-valid":
            return ("aa:bb:cc:dd:ee:ff", AVE_FAMILY_SCENARIO, 9, 0, "button")
        return None

    with (
        patch(
            "custom_components.ave_dominaplus.button.er.async_get",
            return_value=Mock(),
        ),
        patch(
            "custom_components.ave_dominaplus.button.er.async_entries_for_config_entry",
            return_value=entities,
        ),
        patch(
            "custom_components.ave_dominaplus.button.parse_uid", side_effect=_parse_uid
        ),
    ):
        await adopt_existing_buttons(server, _entry(server))

    adopted = server.buttons["uid-valid"]
    assert isinstance(adopted, ScenarioButton)
    assert adopted.name == "Night"
    assert adopted.entity_id == "button.night"
    server.async_add_bt_entities.assert_called_once_with([adopted])


@pytest.mark.asyncio
async def test_adopt_existing_buttons_handles_registry_exceptions(hass) -> None:
    """Adoption should swallow unexpected registry errors."""
    server = make_server(hass)

    with (
        patch(
            "custom_components.ave_dominaplus.button.er.async_get",
            return_value=Mock(),
        ),
        patch(
            "custom_components.ave_dominaplus.button.er.async_entries_for_config_entry",
            side_effect=RuntimeError("registry failed"),
        ),
    ):
        await adopt_existing_buttons(server, _entry(server))


def test_update_button_ignores_non_scenario_family(hass) -> None:
    """Only scenario family updates should create or update button entities."""
    server = make_server(hass)
    server.async_add_bt_entities = Mock()

    update_button(server, 999, 1, name="Ignored")

    assert server.buttons == {}
    server.async_add_bt_entities.assert_not_called()


def test_update_button_existing_sets_name_when_not_user_renamed(hass) -> None:
    """Existing scenario buttons should update HA name when rename protection allows it."""
    server = make_server(hass)
    unique_id = set_button_uid(server, AVE_FAMILY_SCENARIO, 4)
    button = ScenarioButton(unique_id, AVE_FAMILY_SCENARIO, 4, server)
    button.set_name = Mock()
    button.set_ave_name = Mock()
    server.buttons[unique_id] = button

    with patch(
        "custom_components.ave_dominaplus.button.check_name_changed",
        return_value=False,
    ):
        update_button(server, AVE_FAMILY_SCENARIO, 4, name="Evening")

    button.set_ave_name.assert_called_once_with("Evening")
    button.set_name.assert_called_once_with("Evening Run")


def test_check_name_changed_true_and_false_branches(hass) -> None:
    """Name-change helper should detect override and missing entry paths."""
    registry = Mock()
    registry.async_get_entity_id.return_value = "button.test"
    registry.async_get.return_value = SimpleNamespace(name="New", original_name="Old")

    with patch(
        "custom_components.ave_dominaplus.button.er.async_get",
        return_value=registry,
    ):
        assert check_name_changed(hass, "uid") is True

    registry.async_get_entity_id.return_value = None
    with patch(
        "custom_components.ave_dominaplus.button.er.async_get",
        return_value=registry,
    ):
        assert check_name_changed(hass, "uid") is False


def test_scenario_button_properties_and_state_write_paths(hass) -> None:
    """Scenario button should cover property and deferred state write branches."""
    server = make_server(hass)
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    server._set_connected(True)

    button = ScenarioButton(
        unique_id="uid",
        family=AVE_FAMILY_SCENARIO,
        ave_device_id=7,
        webserver=server,
        ave_name="Night",
    )
    button.async_write_ha_state = Mock()

    assert button.unique_id == "uid"
    assert button.translation_key == "scenario_run"
    assert button.translation_placeholders == {"id": "7"}
    assert button.available is True
    assert button.extra_state_attributes == {
        "AVE_family": AVE_FAMILY_SCENARIO,
        "AVE_device_id": 7,
        "AVE_name": "Night",
        "AVE webserver MAC": "aa:bb:cc:dd:ee:ff",
    }

    # Exercise deferred state writes when entity is not yet fully attached.
    button.hass = None
    button.set_name("Deferred")
    assert button._pending_state_write is True
    button.hass = hass
    button.entity_id = None
    button.set_ave_name("Night Updated")
    assert button._pending_state_write is True
    button.entity_id = "button.uid"

    writes_before = button.async_write_ha_state.call_count
    button.set_name("Immediate")
    assert button.async_write_ha_state.call_count == writes_before + 1

    writes_before = button.async_write_ha_state.call_count
    button.set_name(None)
    button.set_ave_name(None)
    assert button.async_write_ha_state.call_count == writes_before
