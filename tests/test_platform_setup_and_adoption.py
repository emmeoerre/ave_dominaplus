"""Tests for platform setup_entry and adoption guard paths."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.ave_dominaplus import (
    binary_sensor,
    button,
    climate,
    cover,
    light,
    sensor,
    switch,
)
from custom_components.ave_dominaplus.web_server import AveWebServer
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady


def _new_server(hass: HomeAssistant, **overrides) -> AveWebServer:
    """Build a webserver with setup defaults for platform setup tests."""
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
    return AveWebServer(settings, hass, object())


@pytest.mark.parametrize(
    "setup_func",
    [
        light.async_setup_entry,
        cover.async_setup_entry,
        switch.async_setup_entry,
        button.async_setup_entry,
        sensor.async_setup_entry,
        binary_sensor.async_setup_entry,
        climate.async_setup_entry,
    ],
)
async def test_async_setup_entry_raises_when_runtime_missing(
    setup_func,
) -> None:
    """Each platform should raise ConfigEntryNotReady when runtime_data is missing."""
    entry = SimpleNamespace(runtime_data=None)

    with pytest.raises(ConfigEntryNotReady):
        await setup_func(None, entry, Mock())


async def test_light_setup_entry_registers_callbacks_and_adopts(
    hass: HomeAssistant,
) -> None:
    """Light setup should register callbacks and adopt existing entities."""
    server = _new_server(hass, fetch_lights=True)
    server.set_async_add_lg_entities = AsyncMock()
    server.set_update_light = AsyncMock()
    entry = SimpleNamespace(runtime_data=server, entry_id="entry-1")
    async_add = Mock()

    with patch(
        "custom_components.ave_dominaplus.light.adopt_existing_lights",
        new=AsyncMock(),
    ) as adopt:
        await light.async_setup_entry(None, entry, async_add)

    server.set_async_add_lg_entities.assert_awaited_once_with(async_add)
    server.set_update_light.assert_awaited_once_with(light.update_light)
    adopt.assert_awaited_once_with(server, entry)


async def test_cover_setup_entry_skips_adoption_when_fetch_disabled(
    hass: HomeAssistant,
) -> None:
    """Cover setup should skip adoption when fetch_covers is disabled."""
    server = _new_server(hass, fetch_covers=False)
    server.set_async_add_cv_entities = AsyncMock()
    server.set_update_cover = AsyncMock()
    entry = SimpleNamespace(runtime_data=server, entry_id="entry-1")

    with patch(
        "custom_components.ave_dominaplus.cover.adopt_existing_covers",
        new=AsyncMock(),
    ) as adopt:
        await cover.async_setup_entry(None, entry, Mock())

    adopt.assert_not_awaited()


async def test_switch_setup_entry_skips_adoption_when_lights_disabled(
    hass: HomeAssistant,
) -> None:
    """Switch setup should skip adoption when light fetching is disabled."""
    server = _new_server(hass, fetch_lights=False)
    server.set_async_add_sw_entities = AsyncMock()
    server.set_update_switch = AsyncMock()
    entry = SimpleNamespace(runtime_data=server, entry_id="entry-1")

    with patch(
        "custom_components.ave_dominaplus.switch.adopt_existing_sensors",
        new=AsyncMock(),
    ) as adopt:
        await switch.async_setup_entry(None, entry, Mock())

    adopt.assert_not_awaited()


async def test_button_setup_entry_registers_callbacks_and_adopts(
    hass: HomeAssistant,
) -> None:
    """Button setup should register callbacks and adopt existing button entities."""
    server = _new_server(hass, fetch_scenarios=True)
    server.set_async_add_bt_entities = AsyncMock()
    server.set_update_button = AsyncMock()
    entry = SimpleNamespace(runtime_data=server, entry_id="entry-1")
    async_add = Mock()

    with patch(
        "custom_components.ave_dominaplus.button.adopt_existing_buttons",
        new=AsyncMock(),
    ) as adopt:
        await button.async_setup_entry(None, entry, async_add)

    server.set_async_add_bt_entities.assert_awaited_once_with(async_add)
    server.set_update_button.assert_awaited_once_with(button.update_button)
    adopt.assert_awaited_once_with(server, entry)


async def test_button_setup_entry_skips_adoption_when_scenarios_disabled(
    hass: HomeAssistant,
) -> None:
    """Button setup should skip adoption when scenario fetching is disabled."""
    server = _new_server(hass, fetch_scenarios=False)
    server.set_async_add_bt_entities = AsyncMock()
    server.set_update_button = AsyncMock()
    entry = SimpleNamespace(runtime_data=server, entry_id="entry-1")

    with patch(
        "custom_components.ave_dominaplus.button.adopt_existing_buttons",
        new=AsyncMock(),
    ) as adopt:
        await button.async_setup_entry(None, entry, Mock())

    adopt.assert_not_awaited()


async def test_sensor_setup_entry_skips_adoption_when_thermostats_disabled(
    hass: HomeAssistant,
) -> None:
    """Offset sensor setup should skip adoption when thermostat fetching is disabled."""
    server = _new_server(hass, fetch_thermostats=False)
    server.set_async_add_number_entities = AsyncMock()
    server.set_update_th_offset = AsyncMock()
    entry = SimpleNamespace(runtime_data=server, entry_id="entry-1")

    with patch(
        "custom_components.ave_dominaplus.sensor.adopt_existing_sensors",
        new=AsyncMock(),
    ) as adopt:
        await sensor.async_setup_entry(None, entry, Mock())

    adopt.assert_not_awaited()


async def test_climate_setup_entry_always_attempts_adoption(
    hass: HomeAssistant,
) -> None:
    """Climate setup should attempt adoption before applying fetch_thermostats filter."""
    server = _new_server(hass, fetch_thermostats=False)
    server.set_async_add_th_entities = AsyncMock()
    server.set_update_thermostat = AsyncMock()
    entry = SimpleNamespace(runtime_data=server, entry_id="entry-1")

    with patch(
        "custom_components.ave_dominaplus.climate.adopt_existing_sensors",
        new=AsyncMock(),
    ) as adopt:
        await climate.async_setup_entry(None, entry, Mock())

    adopt.assert_awaited_once_with(server, entry)


async def test_binary_sensor_setup_adds_status_entity(hass: HomeAssistant) -> None:
    """Binary sensor setup should always add hub status sensor entity."""
    server = _new_server(hass)
    server.set_update_binary_sensor = AsyncMock()
    server.set_async_add_bs_entities = AsyncMock()
    entry = SimpleNamespace(runtime_data=server, entry_id="entry-1")
    async_add = Mock()

    with patch(
        "custom_components.ave_dominaplus.binary_sensor.adopt_existing_sensors",
        new=AsyncMock(),
    ):
        await binary_sensor.async_setup_entry(None, entry, async_add)

    async_add.assert_called_once()
    entities = async_add.call_args.args[0]
    assert len(entities) == 1
    assert isinstance(entities[0], binary_sensor.AveHubStatusBinarySensor)


async def test_adopt_existing_light_returns_when_registry_missing(
    hass: HomeAssistant,
) -> None:
    """Light adoption should safely return when entity registry is unavailable."""
    server = _new_server(hass)
    entry = SimpleNamespace(entry_id="entry-1")

    with patch(
        "custom_components.ave_dominaplus.light.er.async_get", return_value=None
    ):
        await light.adopt_existing_lights(server, entry)


async def test_adopt_existing_cover_returns_when_registry_missing(
    hass: HomeAssistant,
) -> None:
    """Cover adoption should safely return when entity registry is unavailable."""
    server = _new_server(hass)
    entry = SimpleNamespace(entry_id="entry-1")

    with patch(
        "custom_components.ave_dominaplus.cover.er.async_get", return_value=None
    ):
        await cover.adopt_existing_covers(server, entry)
