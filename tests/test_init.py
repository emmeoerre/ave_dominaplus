"""Tests for integration setup and unload lifecycle."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.ave_dominaplus import (
    _async_cleanup_stale_devices,
    async_remove_config_entry_device,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.ave_dominaplus.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady


async def test_async_setup_returns_true(hass: HomeAssistant) -> None:
    """Test integration async_setup always returns True."""
    assert await async_setup(hass, {DOMAIN: {}}) is True


async def test_async_setup_entry_success(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Test setup entry success path."""
    mock_webserver = AsyncMock()
    mock_webserver.authenticate.return_value = True
    mock_webserver.disconnect = AsyncMock()
    mock_webserver.start = AsyncMock()
    session = Mock()

    with (
        patch(
            "custom_components.ave_dominaplus.AveWebServer", return_value=mock_webserver
        ) as webserver_class,
        patch(
            "custom_components.ave_dominaplus.async_get_clientsession",
            return_value=session,
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=AsyncMock(return_value=True),
        ) as forward_setups,
        patch.object(
            mock_config_entry,
            "async_create_background_task",
            wraps=mock_config_entry.async_create_background_task,
        ) as create_background_task,
    ):
        result = await async_setup_entry(hass, mock_config_entry)
        await hass.async_block_till_done()

    assert result is True
    webserver_class.assert_called_once_with(mock_config_entry.data, hass, session)
    assert mock_config_entry.runtime_data is mock_webserver
    forward_setups.assert_awaited_once()
    mock_webserver.authenticate.assert_awaited_once()
    create_background_task.assert_called_once()
    assert create_background_task.call_args.args[0] is hass
    assert create_background_task.call_args.args[2] == (
        "AVE Dominaplus websocket listener"
    )
    mock_webserver.start.assert_awaited_once()


async def test_async_setup_entry_not_ready_on_auth_failure(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Test setup entry raises ConfigEntryNotReady when auth fails."""
    mock_webserver = AsyncMock()
    mock_webserver.authenticate.return_value = False

    with (
        patch(
            "custom_components.ave_dominaplus.AveWebServer", return_value=mock_webserver
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=AsyncMock(return_value=True),
        ) as forward_setups,
        pytest.raises(ConfigEntryNotReady),
    ):
        await async_setup_entry(hass, mock_config_entry)

    forward_setups.assert_not_awaited()


async def test_async_setup_entry_disconnects_on_forward_error(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Test setup entry disconnects webserver if platform forwarding fails."""
    mock_webserver = AsyncMock()
    mock_webserver.authenticate.return_value = True
    mock_webserver.disconnect = AsyncMock()

    with (
        patch(
            "custom_components.ave_dominaplus.AveWebServer", return_value=mock_webserver
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=AsyncMock(side_effect=RuntimeError("forward failed")),
        ),
        pytest.raises(RuntimeError, match="forward failed"),
    ):
        await async_setup_entry(hass, mock_config_entry)

    mock_webserver.disconnect.assert_awaited_once()


async def test_async_unload_entry_disconnects_on_success(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Test unload entry disconnects webserver when unload succeeds."""
    mock_webserver = AsyncMock()
    mock_webserver.disconnect = AsyncMock()
    mock_config_entry.runtime_data = mock_webserver

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        new=AsyncMock(return_value=True),
    ) as unload_platforms:
        result = await async_unload_entry(hass, mock_config_entry)

    assert result is True
    unload_platforms.assert_awaited_once()
    mock_webserver.disconnect.assert_awaited_once()


async def test_async_unload_entry_no_disconnect_on_failure(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Test unload entry does not disconnect webserver when unload fails."""
    mock_webserver = AsyncMock()
    mock_webserver.disconnect = AsyncMock()
    mock_config_entry.runtime_data = mock_webserver

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        new=AsyncMock(return_value=False),
    ) as unload_platforms:
        result = await async_unload_entry(hass, mock_config_entry)

    assert result is False
    unload_platforms.assert_awaited_once()
    mock_webserver.disconnect.assert_not_awaited()


async def test_cleanup_stale_devices_removes_orphans(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Cleanup should remove AVE devices with no linked entities."""
    mock_device_registry = Mock()
    mock_device_registry.async_remove_device = Mock()
    mock_entity_registry = Mock()

    stale_device = SimpleNamespace(
        id="stale-device",
        identifiers={(DOMAIN, "endpoint_entry-123_old")},
    )
    active_device = SimpleNamespace(
        id="active-device",
        identifiers={(DOMAIN, "endpoint_entry-123_lighting")},
    )
    foreign_device = SimpleNamespace(
        id="foreign-device",
        identifiers={("other_domain", "dev")},
    )

    with (
        patch(
            "custom_components.ave_dominaplus.dr.async_get",
            return_value=mock_device_registry,
        ),
        patch(
            "custom_components.ave_dominaplus.er.async_get",
            return_value=mock_entity_registry,
        ),
        patch(
            "custom_components.ave_dominaplus.dr.async_entries_for_config_entry",
            return_value=[stale_device, active_device, foreign_device],
        ),
        patch(
            "custom_components.ave_dominaplus.er.async_entries_for_device",
            side_effect=[[], [SimpleNamespace(entity_id="light.x")]],
        ) as entries_for_device,
    ):
        await _async_cleanup_stale_devices(hass, mock_config_entry)

    mock_device_registry.async_remove_device.assert_called_once_with("stale-device")
    assert entries_for_device.call_count == 1


async def test_cleanup_stale_devices_keeps_parent_with_children(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Cleanup should keep parent devices that have child devices via via_device_id."""
    mock_device_registry = Mock()
    mock_device_registry.async_remove_device = Mock()
    mock_entity_registry = Mock()

    parent_device = SimpleNamespace(
        id="parent-device",
        identifiers={(DOMAIN, "endpoint_entry-123_lighting")},
        via_device_id=None,
    )
    child_device = SimpleNamespace(
        id="child-device",
        identifiers={(DOMAIN, "endpoint_entry-123_light_2_45")},
        via_device_id="parent-device",
    )

    with (
        patch(
            "custom_components.ave_dominaplus.dr.async_get",
            return_value=mock_device_registry,
        ),
        patch(
            "custom_components.ave_dominaplus.er.async_get",
            return_value=mock_entity_registry,
        ),
        patch(
            "custom_components.ave_dominaplus.dr.async_entries_for_config_entry",
            return_value=[parent_device, child_device],
        ),
        patch(
            "custom_components.ave_dominaplus.er.async_entries_for_device",
            side_effect=[[SimpleNamespace(entity_id="light.kitchen")]],
        ) as entries_for_device,
    ):
        await _async_cleanup_stale_devices(hass, mock_config_entry)

    mock_device_registry.async_remove_device.assert_not_called()
    entries_for_device.assert_called_once_with(
        mock_entity_registry,
        "child-device",
        include_disabled_entities=True,
    )


async def test_cleanup_stale_devices_keeps_structural_parent_without_children(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Cleanup should keep structural parent devices even without children."""
    mock_device_registry = Mock()
    mock_device_registry.async_remove_device = Mock()
    mock_entity_registry = Mock()

    lighting_parent = SimpleNamespace(
        id="lighting-parent",
        identifiers={(DOMAIN, "endpoint_entry-123_lighting")},
        via_device_id=None,
    )

    with (
        patch(
            "custom_components.ave_dominaplus.dr.async_get",
            return_value=mock_device_registry,
        ),
        patch(
            "custom_components.ave_dominaplus.er.async_get",
            return_value=mock_entity_registry,
        ),
        patch(
            "custom_components.ave_dominaplus.dr.async_entries_for_config_entry",
            return_value=[lighting_parent],
        ),
        patch(
            "custom_components.ave_dominaplus.er.async_entries_for_device",
        ) as entries_for_device,
    ):
        await _async_cleanup_stale_devices(hass, mock_config_entry)

    mock_device_registry.async_remove_device.assert_not_called()
    entries_for_device.assert_not_called()


async def test_async_remove_config_entry_device_only_allows_empty_device(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Config entry device removal should be blocked when entities exist."""
    mock_entity_registry = Mock()
    device_entry = SimpleNamespace(id="device-1")

    with (
        patch(
            "custom_components.ave_dominaplus.er.async_get",
            return_value=mock_entity_registry,
        ),
        patch(
            "custom_components.ave_dominaplus.er.async_entries_for_device",
            return_value=[SimpleNamespace(entity_id="climate.t1")],
        ),
    ):
        can_remove = await async_remove_config_entry_device(
            hass,
            mock_config_entry,
            device_entry,
        )

    assert can_remove is False


async def test_async_remove_config_entry_device_allows_orphan(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Config entry device removal should be allowed when no entities exist."""
    mock_entity_registry = Mock()
    device_entry = SimpleNamespace(id="device-1")

    with (
        patch(
            "custom_components.ave_dominaplus.er.async_get",
            return_value=mock_entity_registry,
        ),
        patch(
            "custom_components.ave_dominaplus.er.async_entries_for_device",
            return_value=[],
        ),
    ):
        can_remove = await async_remove_config_entry_device(
            hass,
            mock_config_entry,
            device_entry,
        )

    assert can_remove is True
