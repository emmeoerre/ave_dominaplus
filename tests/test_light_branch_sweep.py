"""Additional branch coverage tests for AVE light platform."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.ave_dominaplus import ws_commands
from custom_components.ave_dominaplus.const import (
    AVE_FAMILY_DIMMER,
    AVE_FAMILY_ONOFFLIGHTS,
)
from custom_components.ave_dominaplus.light import (
    DimmerLight,
    adopt_existing_lights,
    async_setup_entry,
    check_name_changed,
    update_light,
)
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
async def test_async_setup_entry_returns_when_fetch_lights_disabled(hass) -> None:
    """Setup should register callbacks but skip adoption when feature is disabled."""
    server = make_server(hass, fetch_lights=False)
    server.set_async_add_lg_entities = AsyncMock()
    server.set_update_light = AsyncMock()
    add_entities = Mock()

    with patch(
        "custom_components.ave_dominaplus.light.adopt_existing_lights",
        new=AsyncMock(),
    ) as adopt_mock:
        await async_setup_entry(hass, _entry(server), add_entities)

    server.set_async_add_lg_entities.assert_awaited_once_with(add_entities)
    server.set_update_light.assert_awaited_once()
    adopt_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_adopt_existing_lights_filters_and_adopts_original_name(hass) -> None:
    """Adoption should exercise skip filters and adopt valid entities."""
    server = make_server(hass)
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    server.async_add_lg_entities = Mock()
    server.lights["uid-dup"] = object()
    entry = _entry(server, "entry-1")

    entities = [
        # Not a light domain -> early continue.
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="switch",
            unique_id="uid-skip-domain",
            name="Skip",
            original_name=None,
            entity_id="switch.skip",
        ),
        # Duplicate UID already present.
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="light",
            unique_id="uid-dup",
            name="Dup",
            original_name=None,
            entity_id="light.dup",
        ),
        # parse_uid returns None.
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="light",
            unique_id="uid-none",
            name="None",
            original_name=None,
            entity_id="light.none",
        ),
        # parse_uid raises ValueError.
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="light",
            unique_id="uid-error",
            name="Err",
            original_name=None,
            entity_id="light.err",
        ),
        # MAC mismatch.
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="light",
            unique_id="uid-mismatch",
            name="Mismatch",
            original_name=None,
            entity_id="light.mismatch",
        ),
        # Unsupported family.
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="light",
            unique_id="uid-wrongfam",
            name="WrongFam",
            original_name=None,
            entity_id="light.wrongfam",
        ),
        # Valid adoption path, name from original_name.
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="light",
            unique_id="uid-ok",
            name=None,
            original_name="Original Living",
            entity_id="light.living",
        ),
    ]

    def _parse_uid(uid: str):
        if uid == "uid-none":
            return None
        if uid == "uid-error":
            raise ValueError("bad uid")
        if uid == "uid-mismatch":
            return ("11:22:33:44:55:66", AVE_FAMILY_DIMMER, 1, 10, None)
        if uid == "uid-wrongfam":
            return ("aa:bb:cc:dd:ee:ff", 999, 2, 11, None)
        if uid == "uid-ok":
            return ("aa:bb:cc:dd:ee:ff", AVE_FAMILY_DIMMER, 3, 12, None)
        raise AssertionError(f"unexpected uid {uid}")

    with (
        patch(
            "custom_components.ave_dominaplus.light.er.async_get", return_value=Mock()
        ),
        patch(
            "custom_components.ave_dominaplus.light.er.async_entries_for_config_entry",
            return_value=entities,
        ),
        patch(
            "custom_components.ave_dominaplus.light.parse_uid", side_effect=_parse_uid
        ),
    ):
        await adopt_existing_lights(server, entry)

    assert "uid-ok" in server.lights
    assert isinstance(server.lights["uid-ok"], DimmerLight)
    assert server.lights["uid-ok"].name == "Original Living"
    server.async_add_lg_entities.assert_called_once()


@pytest.mark.asyncio
async def test_adopt_existing_lights_handles_registry_exceptions(hass) -> None:
    """Adoption should swallow unexpected registry exceptions."""
    server = make_server(hass)
    entry = _entry(server)

    with (
        patch(
            "custom_components.ave_dominaplus.light.er.async_get", return_value=Mock()
        ),
        patch(
            "custom_components.ave_dominaplus.light.er.async_entries_for_config_entry",
            side_effect=RuntimeError("registry failure"),
        ),
    ):
        await adopt_existing_lights(server, entry)


def test_update_light_ignores_unsupported_family(hass) -> None:
    """Unsupported family values should be ignored by update_light."""
    server = make_server(hass)
    server.async_add_lg_entities = Mock()

    update_light(
        server, 999, ave_device_id=5, device_status=1, name="x", address_dec=10
    )

    assert server.lights == {}
    server.async_add_lg_entities.assert_not_called()


def test_update_light_reuses_existing_unique_id_from_lookup(hass) -> None:
    """When address differs, update should reuse known UID for same device identity."""
    server = make_server(hass)
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    existing_uid = "existing-uid"
    light = DimmerLight(existing_uid, AVE_FAMILY_DIMMER, 9, 0, server, address_dec=20)
    light.handle_webserver_update = Mock()
    server.lights[existing_uid] = light

    with patch(
        "custom_components.ave_dominaplus.light.find_unique_id",
        return_value=existing_uid,
    ):
        update_light(
            server,
            AVE_FAMILY_DIMMER,
            ave_device_id=9,
            device_status=18,
            name="Living",
            address_dec=21,
        )

    light.handle_webserver_update.assert_called_once()


def test_update_light_builds_uid_when_initial_lookup_returns_none(hass) -> None:
    """Creation path should rebuild UID if initial uid resolution returns None."""
    server = make_server(hass)
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    server.async_add_lg_entities = Mock()

    with (
        patch(
            "custom_components.ave_dominaplus.light.build_uid",
            side_effect=[None, "rebuilt-uid"],
        ),
        patch(
            "custom_components.ave_dominaplus.light.find_unique_id", return_value=None
        ),
    ):
        update_light(
            server,
            AVE_FAMILY_DIMMER,
            ave_device_id=7,
            device_status=12,
            name="Kitchen",
            address_dec=16,
        )

    assert "rebuilt-uid" in server.lights
    server.async_add_lg_entities.assert_called_once()


def test_check_name_changed_handles_name_override_and_missing_entry(hass) -> None:
    """Name-change helper should detect renamed entities and missing entries."""
    registry = Mock()
    registry.async_get_entity_id.return_value = "light.test"
    registry.async_get.return_value = SimpleNamespace(name="New", original_name="Old")

    with patch(
        "custom_components.ave_dominaplus.light.er.async_get", return_value=registry
    ):
        assert check_name_changed(hass, "uid") is True

    registry.async_get_entity_id.return_value = None
    with patch(
        "custom_components.ave_dominaplus.light.er.async_get", return_value=registry
    ):
        assert check_name_changed(hass, "uid") is False


@pytest.mark.asyncio
async def test_entity_command_methods_cover_toggle_on_off_paths(hass) -> None:
    """Entity command methods should route by family and handle missing webserver."""
    server = make_server(hass)

    onoff = DimmerLight("uid-onoff", AVE_FAMILY_ONOFFLIGHTS, 3, 0, server)
    dimmer = DimmerLight("uid-dimmer", AVE_FAMILY_DIMMER, 4, 0, server)

    with (
        patch.object(ws_commands, "switch_toggle", new=AsyncMock()) as switch_toggle,
        patch.object(ws_commands, "dimmer_toggle", new=AsyncMock()) as dimmer_toggle,
        patch.object(ws_commands, "switch_turn_on", new=AsyncMock()) as switch_turn_on,
        patch.object(ws_commands, "dimmer_turn_on", new=AsyncMock()) as dimmer_turn_on,
        patch.object(
            ws_commands, "switch_turn_off", new=AsyncMock()
        ) as switch_turn_off,
        patch.object(
            ws_commands, "dimmer_turn_off", new=AsyncMock()
        ) as dimmer_turn_off,
    ):
        await onoff.async_toggle()
        await dimmer.async_toggle()
        await onoff.async_turn_on()
        await dimmer.async_turn_on()
        await onoff.async_turn_off()
        await dimmer.async_turn_off()

    switch_toggle.assert_awaited_once_with(server, 3)
    dimmer_toggle.assert_awaited_once_with(server, 4)
    switch_turn_on.assert_awaited_once_with(server, 3)
    dimmer_turn_on.assert_awaited_once_with(server, 4, 31)
    switch_turn_off.assert_awaited_once_with(server, 3)
    dimmer_turn_off.assert_awaited_once_with(server, 4)

    dimmer._webserver = None
    await dimmer.async_toggle()
    await dimmer.async_turn_on()
    await dimmer.async_turn_off()


def test_entity_state_properties_and_mutators_cover_remaining_branches(hass) -> None:
    """State/mutator helpers should update internal fields and emit deferred writes."""
    server = make_server(hass)
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    server._set_connected(True)
    light = DimmerLight("uid", AVE_FAMILY_DIMMER, 5, 0, server)
    light.async_write_ha_state = Mock()

    assert light.available is True
    assert light.brightness is None
    assert light.extra_state_attributes["AVE_family"] == AVE_FAMILY_DIMMER

    light.update_state(None)
    light.update_state(-1)
    light.set_name(None)
    light.entity_id = "light.kitchen"
    light.set_name("Kitchen")
    light.set_ave_name("AVE Kitchen")
    light.set_address_dec(17)
    assert light.extra_state_attributes["AVE address_hex"] == "11"

    light.entity_id = None
    light._write_state_or_defer()
    assert light._pending_state_write is True

    light.entity_id = "light.kitchen"
    light._pending_state_write = False
    light._write_state_or_defer()
    light.async_write_ha_state.assert_called()


def test_handle_webserver_update_applies_conditional_name_and_address(hass) -> None:
    """Webserver updates should gate name updates and apply address changes."""
    server = make_server(hass, get_entities_names=True)
    light = DimmerLight("uid", AVE_FAMILY_DIMMER, 6, 0, server, address_dec=10)
    light.update_state = Mock()
    light.set_name = Mock()
    light.set_ave_name = Mock()
    light.set_address_dec = Mock()

    light.handle_webserver_update(
        device_status=15,
        name="Bedroom",
        address_dec=11,
        allow_name_update=True,
    )

    light.update_state.assert_called_once_with(15)
    light.set_ave_name.assert_called_once_with("Bedroom")
    light.set_name.assert_called_once_with("Bedroom")
    light.set_address_dec.assert_called_once_with(11)
