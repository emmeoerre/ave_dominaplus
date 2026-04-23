"""Additional branch coverage tests for AVE cover platform."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.ave_dominaplus import ws_commands
from custom_components.ave_dominaplus.const import (
    AVE_FAMILY_SHUTTER_HUNG,
    AVE_FAMILY_SHUTTER_ROLLING,
    AVE_FAMILY_SHUTTER_SLIDING,
)
from custom_components.ave_dominaplus.cover import (
    AveCover,
    adopt_existing_covers,
    async_setup_entry,
    build_uid,
    check_name_changed,
    update_cover,
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
async def test_async_setup_entry_returns_when_fetch_covers_disabled(hass) -> None:
    """Setup should register callbacks but skip adoption when covers are disabled."""
    server = make_server(hass, fetch_covers=False)
    server.set_async_add_cv_entities = AsyncMock()
    server.set_update_cover = AsyncMock()
    add_entities = Mock()

    with patch(
        "custom_components.ave_dominaplus.cover.adopt_existing_covers",
        new=AsyncMock(),
    ) as adopt_mock:
        await async_setup_entry(hass, _entry(server), add_entities)

    server.set_async_add_cv_entities.assert_awaited_once_with(add_entities)
    server.set_update_cover.assert_awaited_once()
    adopt_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_setup_entry_calls_adoption_when_fetch_enabled(hass) -> None:
    """Setup should invoke adoption when covers are enabled."""
    server = make_server(hass, fetch_covers=True)
    server.set_async_add_cv_entities = AsyncMock()
    server.set_update_cover = AsyncMock()

    with (
        patch(
            "custom_components.ave_dominaplus.cover.adopt_existing_covers",
            new=AsyncMock(),
        ) as adopt_mock,
        patch(
            "custom_components.ave_dominaplus.cover.ensure_covers_parent_device"
        ) as ensure_parent,
    ):
        await async_setup_entry(hass, _entry(server), Mock())

    ensure_parent.assert_called_once_with(server, "entry-1")
    adopt_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_adopt_existing_covers_filters_and_adopts_original_name(hass) -> None:
    """Adoption should exercise skip filters and adopt only valid cover entities."""
    server = make_server(hass)
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    server.async_add_cv_entities = Mock()
    server.covers["uid-dup"] = object()
    entry = _entry(server, "entry-1")

    entities = [
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="light",
            unique_id="uid-skip-domain",
            name="Skip",
            original_name=None,
            entity_id="light.skip",
        ),
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="cover",
            unique_id="uid-dup",
            name="Dup",
            original_name=None,
            entity_id="cover.dup",
        ),
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="cover",
            unique_id="uid-none",
            name="None",
            original_name=None,
            entity_id="cover.none",
        ),
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="cover",
            unique_id="uid-error",
            name="Err",
            original_name=None,
            entity_id="cover.err",
        ),
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="cover",
            unique_id="uid-mismatch",
            name="Mismatch",
            original_name=None,
            entity_id="cover.mismatch",
        ),
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="cover",
            unique_id="uid-wrongfam",
            name="WrongFam",
            original_name=None,
            entity_id="cover.wrongfam",
        ),
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="cover",
            unique_id="uid-ok",
            name=None,
            original_name="Original Cover",
            entity_id="cover.ok",
        ),
    ]

    def _parse_uid(uid: str):
        if uid == "uid-none":
            return None
        if uid == "uid-error":
            raise ValueError("bad uid")
        if uid == "uid-mismatch":
            return ("11:22:33:44:55:66", AVE_FAMILY_SHUTTER_ROLLING, 1, 10, None)
        if uid == "uid-wrongfam":
            return ("aa:bb:cc:dd:ee:ff", 999, 2, 11, None)
        if uid == "uid-ok":
            return ("aa:bb:cc:dd:ee:ff", AVE_FAMILY_SHUTTER_HUNG, 3, 12, None)
        raise AssertionError(f"unexpected uid {uid}")

    with (
        patch(
            "custom_components.ave_dominaplus.cover.er.async_get", return_value=Mock()
        ),
        patch(
            "custom_components.ave_dominaplus.cover.er.async_entries_for_config_entry",
            return_value=entities,
        ),
        patch(
            "custom_components.ave_dominaplus.cover.parse_uid", side_effect=_parse_uid
        ),
    ):
        await adopt_existing_covers(server, entry)

    assert "uid-ok" in server.covers
    assert isinstance(server.covers["uid-ok"], AveCover)
    assert server.covers["uid-ok"].name == "Original Cover"
    server.async_add_cv_entities.assert_called_once()


@pytest.mark.asyncio
async def test_adopt_existing_covers_handles_registry_exceptions(hass) -> None:
    """Adoption should swallow unexpected registry exceptions."""
    server = make_server(hass)

    with (
        patch(
            "custom_components.ave_dominaplus.cover.er.async_get", return_value=Mock()
        ),
        patch(
            "custom_components.ave_dominaplus.cover.er.async_entries_for_config_entry",
            side_effect=RuntimeError("registry failure"),
        ),
    ):
        await adopt_existing_covers(server, _entry(server))


@pytest.mark.asyncio
async def test_adopt_existing_covers_returns_when_registry_missing(hass) -> None:
    """Adoption should return cleanly when entity registry is unavailable."""
    server = make_server(hass)

    with patch(
        "custom_components.ave_dominaplus.cover.er.async_get", return_value=None
    ):
        await adopt_existing_covers(server, _entry(server))


@pytest.mark.asyncio
async def test_adopt_existing_covers_prefers_entity_name(hass) -> None:
    """Adoption should prefer entity.name over original_name when both are present."""
    server = make_server(hass)
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    server.async_add_cv_entities = Mock()
    entity = SimpleNamespace(
        platform="ave_dominaplus",
        domain="cover",
        unique_id="uid-name",
        name="Registry Name",
        original_name="Original Name",
        entity_id="cover.name",
    )

    with (
        patch(
            "custom_components.ave_dominaplus.cover.er.async_get", return_value=Mock()
        ),
        patch(
            "custom_components.ave_dominaplus.cover.er.async_entries_for_config_entry",
            return_value=[entity],
        ),
        patch(
            "custom_components.ave_dominaplus.cover.parse_uid",
            return_value=("aa:bb:cc:dd:ee:ff", AVE_FAMILY_SHUTTER_ROLLING, 9, 40, None),
        ),
    ):
        await adopt_existing_covers(server, _entry(server))

    assert server.covers["uid-name"].name == "Registry Name"


def test_update_cover_ignores_unsupported_family(hass) -> None:
    """Unsupported family values should be ignored by update_cover."""
    server = make_server(hass)
    server.async_add_cv_entities = Mock()

    update_cover(
        server, 999, ave_device_id=5, device_status=3, name="x", address_dec=10
    )

    assert server.covers == {}
    server.async_add_cv_entities.assert_not_called()


def test_update_cover_reuses_existing_unique_id_from_lookup(hass) -> None:
    """When address differs, update should reuse known UID for same cover identity."""
    server = make_server(hass)
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    existing_uid = "existing-cover"
    cover = AveCover(
        existing_uid, AVE_FAMILY_SHUTTER_ROLLING, 9, 3, server, address_dec=20
    )
    cover.handle_webserver_update = Mock()
    server.covers[existing_uid] = cover

    with patch(
        "custom_components.ave_dominaplus.cover.find_unique_id",
        return_value=existing_uid,
    ):
        update_cover(
            server,
            AVE_FAMILY_SHUTTER_ROLLING,
            ave_device_id=9,
            device_status=2,
            name="Living",
            address_dec=21,
        )

    cover.handle_webserver_update.assert_called_once()


def test_update_cover_drops_stale_entity_when_update_raises(hass) -> None:
    """Existing cover references should be removed if runtime update raises."""
    server = make_server(hass)
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    uid = build_uid(server.mac_address, AVE_FAMILY_SHUTTER_ROLLING, 1, 10)
    cover = AveCover(uid, AVE_FAMILY_SHUTTER_ROLLING, 1, 3, server, address_dec=10)
    cover.handle_webserver_update = Mock(side_effect=RuntimeError("boom"))
    server.covers[uid] = cover

    update_cover(
        server,
        AVE_FAMILY_SHUTTER_ROLLING,
        ave_device_id=1,
        device_status=2,
        name="Living",
        address_dec=10,
    )

    assert uid not in server.covers


def test_update_cover_returns_when_existing_lookup_yields_none_entity(hass) -> None:
    """Existing branch should safely return when runtime mapping has no entity object."""
    server = make_server(hass)
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    uid = build_uid(server.mac_address, AVE_FAMILY_SHUTTER_ROLLING, 2, 11)

    class _CoversMapping(dict):
        def __contains__(self, key):
            return key == uid

        def get(self, key, default=None):
            if key == uid:
                return None
            return super().get(key, default)

    server.covers = _CoversMapping()

    update_cover(
        server,
        AVE_FAMILY_SHUTTER_ROLLING,
        ave_device_id=2,
        device_status=3,
        name="Missing Entity",
        address_dec=11,
    )


def test_update_cover_builds_uid_when_initial_lookup_returns_none(hass) -> None:
    """Creation path should rebuild UID if first uid computation returns None."""
    server = make_server(hass)
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    server.async_add_cv_entities = Mock()

    with (
        patch(
            "custom_components.ave_dominaplus.cover.build_uid",
            side_effect=[None, "rebuilt-cover-uid"],
        ),
        patch(
            "custom_components.ave_dominaplus.cover.find_unique_id", return_value=None
        ),
    ):
        update_cover(
            server,
            AVE_FAMILY_SHUTTER_ROLLING,
            ave_device_id=7,
            device_status=3,
            name="Kitchen",
            address_dec=16,
        )

    assert "rebuilt-cover-uid" in server.covers
    server.async_add_cv_entities.assert_called_once()


def test_check_name_changed_handles_name_override_and_missing_entry(hass) -> None:
    """Name-change helper should detect renamed entities and missing entries."""
    registry = Mock()
    registry.async_get_entity_id.return_value = "cover.test"
    registry.async_get.return_value = SimpleNamespace(name="New", original_name="Old")

    with patch(
        "custom_components.ave_dominaplus.cover.er.async_get", return_value=registry
    ):
        assert check_name_changed(hass, "uid") is True

    registry.async_get_entity_id.return_value = None
    with patch(
        "custom_components.ave_dominaplus.cover.er.async_get", return_value=registry
    ):
        assert check_name_changed(hass, "uid") is False


@pytest.mark.asyncio
async def test_cover_entity_methods_and_properties_cover_remaining_paths(hass) -> None:
    """Cover entity helpers should handle stop/no-webserver and property branches."""
    server = make_server(hass)
    server._set_connected(True)

    cover = AveCover("uid", AVE_FAMILY_SHUTTER_ROLLING, 5, 1, server)
    cover.async_write_ha_state = Mock()

    assert cover.translation_key == "shutter"
    assert cover.translation_placeholders == {"id": "5"}
    assert cover.available is True
    assert cover.is_closed is False
    assert cover.is_opening is False
    assert cover.is_closing is False
    assert cover.current_cover_position == 100

    cover.update_state(3)
    assert cover.is_closed is True
    assert cover.current_cover_position == 0
    cover.update_state(2)
    assert cover.is_opening is True
    assert cover.current_cover_position == 50
    cover.update_state(4)
    assert cover.is_closing is True

    with (
        patch.object(ws_commands, "cover_open", new=AsyncMock()) as cover_open,
        patch.object(ws_commands, "cover_close", new=AsyncMock()) as cover_close,
        patch.object(ws_commands, "cover_stop", new=AsyncMock()) as cover_stop,
    ):
        await cover.async_open_cover()
        await cover.async_close_cover()

        await cover.async_stop_cover()
        cover_stop.assert_awaited_once_with(server, 5, "9")

        cover._webserver = None
        await cover.async_stop_cover()

    cover_open.assert_awaited_once_with(server, 5)
    cover_close.assert_awaited_once_with(server, 5)


def test_cover_mutators_and_write_defer_paths(hass) -> None:
    """Mutators should guard None values and trigger deferred or immediate writes."""
    server = make_server(hass)
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    cover = AveCover("uid", AVE_FAMILY_SHUTTER_SLIDING, 6, None, server)
    cover.async_write_ha_state = Mock()

    assert cover.translation_key == "blind"
    assert cover.translation_placeholders == {"id": "6"}
    assert cover.extra_state_attributes["AVE address_hex"] == ""

    cover.update_state(None)
    cover.update_state(0)
    cover.update_state(6)

    cover.set_name(None)
    cover.set_ave_name("AVE Blind")
    cover.set_address_dec(33)
    assert cover.extra_state_attributes["AVE address_hex"] == "21"

    cover.entity_id = None
    cover._write_state_or_defer()
    assert cover._pending_state_write is True

    cover.entity_id = "cover.blind"
    cover._pending_state_write = False
    cover.set_name("Blind Custom")
    cover.async_write_ha_state.assert_called()


def test_cover_build_name_variants(hass) -> None:
    """Default name builder should map known families and fallback for unknown."""
    server = make_server(hass)

    rolling = AveCover("u1", AVE_FAMILY_SHUTTER_ROLLING, 1, None, server)
    sliding = AveCover("u2", AVE_FAMILY_SHUTTER_SLIDING, 2, None, server)
    hung = AveCover("u3", AVE_FAMILY_SHUTTER_HUNG, 3, None, server)
    unknown = AveCover("u4", 999, 4, None, server)

    assert rolling.translation_key == "shutter"
    assert rolling.name is None
    assert sliding.translation_key == "blind"
    assert hung.translation_key == "window"
    assert unknown.translation_key == "cover"
