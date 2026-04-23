"""Tests for binary sensor update flow."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from custom_components.ave_dominaplus.binary_sensor import (
    AveHubStatusBinarySensor,
    MotionBinarySensor,
    ScenarioRunningBinarySensor,
    set_sensor_uid,
    update_binary_sensor,
)
from custom_components.ave_dominaplus.const import (
    AVE_FAMILY_ANTITHEFT_AREA,
    AVE_FAMILY_MOTION_SENSOR,
    AVE_FAMILY_SCENARIO,
)
from custom_components.ave_dominaplus.web_server import AveWebServer
from homeassistant.core import HomeAssistant


def _new_server(hass: HomeAssistant, **overrides) -> AveWebServer:
    """Build a webserver with defaults suitable for binary sensor tests."""
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
    server = AveWebServer(settings, hass)
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    server.async_add_bs_entities = Mock()
    server.register_availability_entity = Mock()
    server.unregister_availability_entity = Mock()
    return server


def test_update_binary_sensor_creates_motion_sensor(hass: HomeAssistant) -> None:
    """Motion updates should create motion binary sensors."""
    server = _new_server(hass)

    update_binary_sensor(server, AVE_FAMILY_MOTION_SENSOR, 8, 1, name="Ignored")

    unique_id = set_sensor_uid(AVE_FAMILY_MOTION_SENSOR, 8)
    assert unique_id in server.binary_sensors
    created = server.binary_sensors[unique_id]
    assert created.translation_key == "antitheft_sensor"
    assert getattr(created, "translation_placeholders", {}) == {"id": "8"}
    server.async_add_bs_entities.assert_called_once()


def test_update_binary_sensor_creates_area_sensor_with_name(
    hass: HomeAssistant,
) -> None:
    """Area updates should keep AVE names when enabled."""
    server = _new_server(hass, get_entities_names=True)

    update_binary_sensor(server, AVE_FAMILY_ANTITHEFT_AREA, 3, 0, name="Area North")

    unique_id = set_sensor_uid(AVE_FAMILY_ANTITHEFT_AREA, 3)
    created = server.binary_sensors[unique_id]
    assert created.name == "Area North"


def test_update_binary_sensor_creates_scenario_running_sensor(
    hass: HomeAssistant,
) -> None:
    """Scenario updates should create running-state binary sensors."""
    server = _new_server(hass, get_entities_names=True)

    update_binary_sensor(server, AVE_FAMILY_SCENARIO, 12, 1, name="Morning")

    unique_id = set_sensor_uid(AVE_FAMILY_SCENARIO, 12, server)
    created = server.binary_sensors[unique_id]
    assert isinstance(created, ScenarioRunningBinarySensor)
    assert created.name == "Morning Running"
    assert created.is_on is True


def test_update_binary_sensor_skips_when_family_disabled(hass: HomeAssistant) -> None:
    """Family-specific fetch flags should suppress entity creation."""
    server = _new_server(
        hass,
        fetch_sensors=False,
        fetch_sensor_areas=False,
        fetch_scenarios=False,
    )

    update_binary_sensor(server, AVE_FAMILY_MOTION_SENSOR, 1, 1)
    update_binary_sensor(server, AVE_FAMILY_ANTITHEFT_AREA, 2, 1)
    update_binary_sensor(server, AVE_FAMILY_SCENARIO, 3, 1)

    assert server.binary_sensors == {}
    server.async_add_bs_entities.assert_not_called()


def test_update_binary_sensor_skips_unsupported_family(hass: HomeAssistant) -> None:
    """Unsupported binary sensor families should be ignored."""
    server = _new_server(hass)

    update_binary_sensor(server, 9999, 1, 1)

    assert server.binary_sensors == {}


def test_update_binary_sensor_existing_respects_manual_rename(
    hass: HomeAssistant,
) -> None:
    """Existing sensor updates should avoid overriding user-defined names."""
    server = _new_server(hass)
    unique_id = set_sensor_uid(AVE_FAMILY_ANTITHEFT_AREA, 4)
    sensor = MotionBinarySensor(
        unique_id,
        AVE_FAMILY_ANTITHEFT_AREA,
        4,
        0,
        hass,
        server,
        name="Area",
    )
    sensor.update_state = Mock()
    sensor.set_name = Mock()
    sensor.set_ave_name = Mock()
    server.binary_sensors[unique_id] = sensor

    with patch(
        "custom_components.ave_dominaplus.binary_sensor.check_name_changed",
        return_value=True,
    ):
        update_binary_sensor(
            server,
            AVE_FAMILY_ANTITHEFT_AREA,
            4,
            1,
            name="AVE Area",
        )

    sensor.update_state.assert_called_once_with(1)
    sensor.set_ave_name.assert_called_once_with("AVE Area")
    sensor.set_name.assert_not_called()


def test_update_scenario_binary_sensor_existing_respects_manual_rename(
    hass: HomeAssistant,
) -> None:
    """Scenario running updates should not overwrite HA user-renamed names."""
    server = _new_server(hass)
    unique_id = set_sensor_uid(AVE_FAMILY_SCENARIO, 14, server)
    sensor = ScenarioRunningBinarySensor(
        unique_id,
        AVE_FAMILY_SCENARIO,
        14,
        False,
        hass,
        server,
        name="Scenario 14 Running",
    )
    sensor.update_state = Mock()
    sensor.set_name = Mock()
    sensor.set_ave_name = Mock()
    server.binary_sensors[unique_id] = sensor

    with patch(
        "custom_components.ave_dominaplus.binary_sensor.check_name_changed",
        return_value=True,
    ):
        update_binary_sensor(
            server,
            AVE_FAMILY_SCENARIO,
            14,
            1,
            name="Evening",
        )

    sensor.update_state.assert_called_once_with(1)
    sensor.set_ave_name.assert_called_once_with("Evening")
    sensor.set_name.assert_not_called()


def test_update_scenario_binary_sensor_refreshes_device_info_name(
    hass: HomeAssistant,
) -> None:
    """Scenario device info name should refresh when AVE name arrives later."""
    server = _new_server(hass, get_entities_names=True)

    update_binary_sensor(server, AVE_FAMILY_SCENARIO, 29, 0, name=None)
    unique_id = set_sensor_uid(AVE_FAMILY_SCENARIO, 29, server)
    sensor = server.binary_sensors[unique_id]
    sensor.entity_id = "binary_sensor.scenario_29_running"
    sensor.async_write_ha_state = Mock()
    assert sensor._attr_device_info.get("name") == "Scenario 29"

    update_binary_sensor(server, AVE_FAMILY_SCENARIO, 29, 1, name="Wake Up")

    assert sensor.name == "Wake Up Running"
    assert sensor._attr_device_info.get("name") == "Scenario Wake Up"


def test_scenario_running_sync_device_name_respects_name_by_user(
    hass: HomeAssistant,
) -> None:
    """Device registry updates must not overwrite user-customized scenario devices."""
    server = _new_server(hass)
    sensor = ScenarioRunningBinarySensor(
        "uid",
        AVE_FAMILY_SCENARIO,
        31,
        False,
        hass,
        server,
    )
    sensor.entity_id = "binary_sensor.uid"
    sensor.async_write_ha_state = Mock()

    device_registry = Mock()
    device_registry.async_get_device.return_value = SimpleNamespace(
        id="dev-3",
        name_by_user="Custom",
        name="Old",
    )

    with patch(
        "custom_components.ave_dominaplus.binary_sensor.dr.async_get",
        return_value=device_registry,
    ):
        sensor.set_ave_name("Relax")

    assert sensor._attr_device_info.get("name") == "Scenario Relax"
    device_registry.async_update_device.assert_not_called()


def test_scenario_running_sync_device_name_updates_when_not_customized(
    hass: HomeAssistant,
) -> None:
    """Device registry name should update when there is no user override."""
    server = _new_server(hass)
    sensor = ScenarioRunningBinarySensor(
        "uid",
        AVE_FAMILY_SCENARIO,
        32,
        False,
        hass,
        server,
    )
    sensor.entity_id = "binary_sensor.uid"
    sensor.async_write_ha_state = Mock()

    device_registry = Mock()
    device_registry.async_get_device.return_value = SimpleNamespace(
        id="dev-4",
        name_by_user=None,
        name="Scenario 32",
    )

    with patch(
        "custom_components.ave_dominaplus.binary_sensor.dr.async_get",
        return_value=device_registry,
    ):
        sensor.set_ave_name("Party")

    device_registry.async_update_device.assert_called_once_with(
        device_id="dev-4",
        name="Scenario Party",
    )


def test_motion_sensor_update_state_tracks_timestamps(hass: HomeAssistant) -> None:
    """Motion sensor state changes should set revealed/cleared timestamps."""
    server = _new_server(hass)
    sensor = MotionBinarySensor(
        "uid",
        AVE_FAMILY_MOTION_SENSOR,
        5,
        0,
        hass,
        server,
    )
    sensor.async_write_ha_state = Mock()

    with patch(
        "custom_components.ave_dominaplus.binary_sensor.utcnow",
        side_effect=[
            SimpleNamespace(isoformat=lambda: "2026-04-14T10:00:00+00:00"),
            SimpleNamespace(isoformat=lambda: "2026-04-14T10:01:00+00:00"),
        ],
    ):
        sensor.update_state(1)
        sensor.update_state(0)

    assert sensor.extra_state_attributes["last_revealed"] == "2026-04-14T10:00:00+00:00"
    assert sensor.extra_state_attributes["last_cleared"] == "2026-04-14T10:01:00+00:00"
    assert sensor.async_write_ha_state.call_count == 2


async def test_hub_status_sensor_reports_connectivity_and_lifecycle(
    hass: HomeAssistant,
) -> None:
    """Hub status sensor should mirror connection state and register lifecycle hooks."""
    server = _new_server(hass)
    entry = SimpleNamespace(entry_id="entry-1")
    status = AveHubStatusBinarySensor(server, entry)

    server._set_connected(True)
    assert status.is_on is True
    assert status.extra_state_attributes["AVE webserver MAC"] == server.mac_address

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
        await status.async_added_to_hass()
        await status.async_will_remove_from_hass()

    server.register_availability_entity.assert_called_once_with(status)
    server.unregister_availability_entity.assert_called_once_with(status)
