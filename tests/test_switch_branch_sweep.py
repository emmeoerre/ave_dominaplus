"""Additional branch coverage tests for AVE switch platform."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.ave_dominaplus.const import AVE_FAMILY_ONOFFLIGHTS
from custom_components.ave_dominaplus.switch import (
    LightSwitch,
    adopt_existing_sensors,
    async_setup_entry,
    check_name_changed,
)
from homeassistant.components.switch import SwitchDeviceClass
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
async def test_async_setup_entry_calls_adoption_when_enabled(hass) -> None:
    """Setup should invoke adoption when switch fetching is enabled."""
    server = make_server(hass, fetch_lights=True)
    server.set_async_add_sw_entities = AsyncMock()
    server.set_update_switch = AsyncMock()

    with patch(
        "custom_components.ave_dominaplus.switch.adopt_existing_sensors",
        new=AsyncMock(),
    ) as adopt_mock:
        await async_setup_entry(hass, _entry(server), Mock())

    adopt_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_adopt_existing_switches_handles_registry_none(hass) -> None:
    """Adoption should return cleanly when entity registry is unavailable."""
    server = make_server(hass)

    with patch(
        "custom_components.ave_dominaplus.switch.er.async_get", return_value=None
    ):
        await adopt_existing_sensors(server, _entry(server))


@pytest.mark.asyncio
async def test_adopt_existing_switches_filters_and_uses_original_name(hass) -> None:
    """Adoption should skip non-switch entries and adopt with original_name fallback."""
    server = make_server(hass)
    server.async_add_sw_entities = Mock()

    entities = [
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="light",
            unique_id="ave_switch_1_1",
            name="Skip",
            original_name=None,
            entity_id="light.skip",
        ),
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="switch",
            unique_id="ave_switch_1_10",
            name=None,
            original_name="Original Switch",
            entity_id="switch.ok",
        ),
    ]

    with (
        patch(
            "custom_components.ave_dominaplus.switch.er.async_get", return_value=Mock()
        ),
        patch(
            "custom_components.ave_dominaplus.switch.er.async_entries_for_config_entry",
            return_value=entities,
        ),
    ):
        await adopt_existing_sensors(server, _entry(server))

    assert "ave_switch_1_10" in server.switches
    assert server.switches["ave_switch_1_10"].name == "Original Switch"
    server.async_add_sw_entities.assert_called_once()


@pytest.mark.asyncio
async def test_adopt_existing_switches_handles_exceptions(hass) -> None:
    """Adoption should swallow unexpected parsing/runtime exceptions."""
    server = make_server(hass)
    bad_entity = SimpleNamespace(
        platform="ave_dominaplus",
        domain="switch",
        unique_id="bad_uid",
        name="Bad",
        original_name=None,
        entity_id="switch.bad",
    )

    with (
        patch(
            "custom_components.ave_dominaplus.switch.er.async_get", return_value=Mock()
        ),
        patch(
            "custom_components.ave_dominaplus.switch.er.async_entries_for_config_entry",
            return_value=[bad_entity],
        ),
    ):
        await adopt_existing_sensors(server, _entry(server))


def test_switch_name_changed_helper_true_and_false(hass) -> None:
    """Name-change helper should detect override and missing entry cases."""
    registry = Mock()
    registry.async_get_entity_id.return_value = "switch.test"
    registry.async_get.return_value = SimpleNamespace(name="New", original_name="Old")

    with patch(
        "custom_components.ave_dominaplus.switch.er.async_get", return_value=registry
    ):
        assert check_name_changed(hass, "uid") is True

    registry.async_get_entity_id.return_value = None
    with patch(
        "custom_components.ave_dominaplus.switch.er.async_get", return_value=registry
    ):
        assert check_name_changed(hass, "uid") is False


def test_switch_properties_mutators_and_write_paths(hass) -> None:
    """Switch entity should cover property and mutator guard branches."""
    server = make_server(hass)
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    server._set_connected(True)
    entity = LightSwitch("uid", AVE_FAMILY_ONOFFLIGHTS, 11, 0, server)
    entity.async_write_ha_state = Mock()

    assert entity.available is True
    assert entity.device_class == SwitchDeviceClass.SWITCH
    assert entity.extra_state_attributes["AVE webserver MAC"] == "aa:bb:cc:dd:ee:ff"

    entity.update_state(None)
    entity.update_state(-1)
    entity.set_name(None)
    entity.set_ave_name("AVE Name")
    entity.set_address_dec(14)

    entity.entity_id = None
    entity._write_state_or_defer()
    assert entity._pending_state_write is True

    entity.entity_id = "switch.test"
    entity._pending_state_write = False
    entity.set_name("Switch Name")
    entity.async_write_ha_state.assert_called()
