"""Additional branch coverage tests for AVE binary sensor platform."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.ave_dominaplus.binary_sensor import (
    MotionBinarySensor,
    ScenarioRunningBinarySensor,
    _parse_motion_uid,
    adopt_existing_sensors,
    async_setup_entry,
    check_name_changed,
    set_sensor_uid,
    update_binary_sensor,
)
from custom_components.ave_dominaplus.const import (
    AVE_FAMILY_ANTITHEFT_AREA,
    AVE_FAMILY_MOTION_SENSOR,
    AVE_FAMILY_SCENARIO,
)
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
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
async def test_async_setup_entry_registers_callbacks_and_adds_status_sensor(
    hass,
) -> None:
    """Setup should register callbacks, run adoption, and add hub status entity."""
    server = make_server(hass)
    server.set_update_binary_sensor = AsyncMock()
    server.set_async_add_bs_entities = AsyncMock()

    with patch(
        "custom_components.ave_dominaplus.binary_sensor.adopt_existing_sensors",
        new=AsyncMock(),
    ) as adopt_mock:
        add_entities = Mock()
        await async_setup_entry(hass, _entry(server), add_entities)

    server.set_update_binary_sensor.assert_awaited_once()
    server.set_async_add_bs_entities.assert_awaited_once_with(add_entities)
    adopt_mock.assert_awaited_once()
    add_entities.assert_called_once()
    assert len(add_entities.call_args.args[0]) == 1


@pytest.mark.asyncio
async def test_adopt_existing_sensors_returns_when_registry_missing(hass) -> None:
    """Adoption should return cleanly when entity registry is unavailable."""
    server = make_server(hass)

    with patch(
        "custom_components.ave_dominaplus.binary_sensor.er.async_get",
        return_value=None,
    ):
        await adopt_existing_sensors(server, _entry(server))


@pytest.mark.asyncio
async def test_adopt_existing_sensors_filters_disabled_and_adopts_valid_motion(
    hass,
) -> None:
    """Adoption should filter by class/settings and adopt valid motion entries."""
    server = make_server(hass, fetch_sensor_areas=False, fetch_sensors=True)
    server.async_add_bs_entities = Mock()
    server.binary_sensors["ave_motion_13_8"] = object()

    entities = [
        # Wrong domain
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="switch",
            original_device_class="motion",
            unique_id="ave_motion_13_1",
            name="skip",
            original_name=None,
            entity_id="switch.skip",
        ),
        # Wrong device class
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="binary_sensor",
            original_device_class="opening",
            unique_id="ave_motion_13_2",
            name="skip",
            original_name=None,
            entity_id="binary_sensor.skip",
        ),
        # Area family but disabled
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="binary_sensor",
            original_device_class="motion",
            unique_id=f"ave_motion_{AVE_FAMILY_ANTITHEFT_AREA}_3",
            name="Area",
            original_name=None,
            entity_id="binary_sensor.area",
        ),
        # Duplicate existing
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="binary_sensor",
            original_device_class="motion",
            unique_id="ave_motion_13_8",
            name="dup",
            original_name=None,
            entity_id="binary_sensor.dup",
        ),
        # Valid entry, name from original_name fallback
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="binary_sensor",
            original_device_class="motion",
            unique_id=f"ave_motion_{AVE_FAMILY_MOTION_SENSOR}_9",
            name=None,
            original_name="Hall Motion",
            entity_id="binary_sensor.hall_motion",
        ),
    ]

    with (
        patch(
            "custom_components.ave_dominaplus.binary_sensor.er.async_get",
            return_value=Mock(),
        ),
        patch(
            "custom_components.ave_dominaplus.binary_sensor.er.async_entries_for_config_entry",
            return_value=entities,
        ),
    ):
        await adopt_existing_sensors(server, _entry(server))

    expected_uid = f"ave_motion_{AVE_FAMILY_MOTION_SENSOR}_9"
    assert expected_uid in server.binary_sensors
    assert server.binary_sensors[expected_uid].name == "Hall Motion"
    server.async_add_bs_entities.assert_called_once()


@pytest.mark.asyncio
async def test_adopt_existing_sensors_handles_bad_unique_id_exception(hass) -> None:
    """Adoption should swallow errors from malformed legacy unique IDs."""
    server = make_server(hass)
    bad_entity = SimpleNamespace(
        platform="ave_dominaplus",
        domain="binary_sensor",
        original_device_class="motion",
        unique_id="bad_uid",
        name="Bad",
        original_name=None,
        entity_id="binary_sensor.bad",
    )

    with (
        patch(
            "custom_components.ave_dominaplus.binary_sensor.er.async_get",
            return_value=Mock(),
        ),
        patch(
            "custom_components.ave_dominaplus.binary_sensor.er.async_entries_for_config_entry",
            return_value=[bad_entity],
        ),
    ):
        await adopt_existing_sensors(server, _entry(server))


@pytest.mark.asyncio
async def test_adopt_existing_sensors_handles_parse_uid_exception(hass) -> None:
    """Adoption should swallow parse_uid errors and continue cleanly."""
    server = make_server(hass)
    entity = SimpleNamespace(
        platform="ave_dominaplus",
        domain="binary_sensor",
        original_device_class="running",
        unique_id="uid-raise",
        name="Scenario",
        original_name=None,
        entity_id="binary_sensor.uid_raise",
    )

    with (
        patch(
            "custom_components.ave_dominaplus.binary_sensor.er.async_get",
            return_value=Mock(),
        ),
        patch(
            "custom_components.ave_dominaplus.binary_sensor.er.async_entries_for_config_entry",
            return_value=[entity],
        ),
        patch(
            "custom_components.ave_dominaplus.binary_sensor.parse_uid",
            side_effect=RuntimeError("parse failed"),
        ),
    ):
        await adopt_existing_sensors(server, _entry(server))


def test_check_name_changed_true_and_false_branches(hass) -> None:
    """Name-change helper should detect override and missing entry paths."""
    registry = Mock()
    registry.async_get_entity_id.return_value = "binary_sensor.test"
    registry.async_get.return_value = SimpleNamespace(name="New", original_name="Old")

    with patch(
        "custom_components.ave_dominaplus.binary_sensor.er.async_get",
        return_value=registry,
    ):
        assert check_name_changed(hass, "uid") is True

    registry.async_get_entity_id.return_value = None
    with patch(
        "custom_components.ave_dominaplus.binary_sensor.er.async_get",
        return_value=registry,
    ):
        assert check_name_changed(hass, "uid") is False


@pytest.mark.asyncio
async def test_motion_sensor_lifecycle_and_property_branches(hass) -> None:
    """Motion entity should cover lifecycle hooks and property guard branches."""
    server = make_server(hass)
    server._set_connected(True)

    motion = MotionBinarySensor(
        unique_id="uid-motion",
        family=AVE_FAMILY_MOTION_SENSOR,
        ave_device_id=5,
        is_motion_detected=None,
        hass=hass,
        webserver=server,
    )
    motion.async_write_ha_state = Mock()

    assert motion.unique_id == "uid-motion"
    assert motion.available is True
    assert motion.is_on is None
    assert motion.device_class == BinarySensorDeviceClass.MOTION
    assert "AVE_name" not in motion.extra_state_attributes

    area = MotionBinarySensor(
        unique_id="uid-area",
        family=AVE_FAMILY_ANTITHEFT_AREA,
        ave_device_id=2,
        is_motion_detected=1,
        hass=hass,
        webserver=server,
        ave_name="Area A",
    )
    area.async_write_ha_state = Mock()
    assert area.extra_state_attributes["AVE_name"] == "Area A"
    assert area.build_name() == "Antitheft Area 2"

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
        await motion.async_added_to_hass()
        await motion.async_will_remove_from_hass()

    # Trigger exception branch in update_state timestamp handling.
    with patch(
        "custom_components.ave_dominaplus.binary_sensor.utcnow",
        side_effect=RuntimeError("clock"),
    ):
        motion.update_state(1)

    # set_name None path and set_ave_name write path.
    motion.set_name(None)
    motion.set_ave_name("Motion")

    # set_name write guarded by hass truthiness.
    motion.hass = None
    motion.set_name("NoWrite")


def test_set_sensor_uid_and_parse_motion_uid_guard_branches(hass) -> None:
    """Utility helpers should cover scenario server guard and parse failures."""
    server = make_server(hass)

    with pytest.raises(ValueError):
        set_sensor_uid(AVE_FAMILY_SCENARIO, 10)

    scenario_uid = set_sensor_uid(AVE_FAMILY_SCENARIO, 10, server)
    assert scenario_uid.endswith("_0x00_running")
    assert _parse_motion_uid("ave_motion_13_x") is None


@pytest.mark.asyncio
async def test_adopt_existing_sensors_filters_scenario_and_motion_paths(hass) -> None:
    """Adoption should filter scenario entries and skip disabled motion families."""
    server = make_server(hass, fetch_sensors=False, fetch_scenarios=True)
    server.async_add_bs_entities = Mock()

    entities = [
        # Motion family disabled by settings.
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="binary_sensor",
            original_device_class="motion",
            unique_id=f"ave_motion_{AVE_FAMILY_MOTION_SENSOR}_4",
            name="Motion",
            original_name=None,
            entity_id="binary_sensor.motion",
        ),
        # Scenario uid but wrong device class.
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="binary_sensor",
            original_device_class="motion",
            unique_id="uid-wrong-class",
            name="Wrong Class",
            original_name=None,
            entity_id="binary_sensor.wrong_class",
        ),
        # Scenario uid with wrong suffix.
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="binary_sensor",
            original_device_class="running",
            unique_id="uid-wrong-suffix",
            name="Wrong Suffix",
            original_name=None,
            entity_id="binary_sensor.wrong_suffix",
        ),
        # Scenario uid with wrong family.
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="binary_sensor",
            original_device_class="running",
            unique_id="uid-wrong-family",
            name="Wrong Family",
            original_name=None,
            entity_id="binary_sensor.wrong_family",
        ),
        # Valid scenario entry, using original_name fallback.
        SimpleNamespace(
            platform="ave_dominaplus",
            domain="binary_sensor",
            original_device_class="running",
            unique_id="uid-scenario-valid",
            name=None,
            original_name="Movie",
            entity_id="binary_sensor.movie_running",
        ),
    ]

    def _parse_uid(uid: str):
        if uid == "uid-wrong-class":
            return ("aa:bb:cc:dd:ee:ff", AVE_FAMILY_SCENARIO, 1, 0, "running")
        if uid == "uid-wrong-suffix":
            return ("aa:bb:cc:dd:ee:ff", AVE_FAMILY_SCENARIO, 2, 0, "button")
        if uid == "uid-wrong-family":
            return ("aa:bb:cc:dd:ee:ff", AVE_FAMILY_ANTITHEFT_AREA, 3, 0, "running")
        if uid == "uid-scenario-valid":
            return ("aa:bb:cc:dd:ee:ff", AVE_FAMILY_SCENARIO, 8, 0, "running")
        return None

    with (
        patch(
            "custom_components.ave_dominaplus.binary_sensor.er.async_get",
            return_value=Mock(),
        ),
        patch(
            "custom_components.ave_dominaplus.binary_sensor.er.async_entries_for_config_entry",
            return_value=entities,
        ),
        patch(
            "custom_components.ave_dominaplus.binary_sensor.parse_uid",
            side_effect=_parse_uid,
        ),
    ):
        await adopt_existing_sensors(server, _entry(server))

    assert len(server.binary_sensors) == 1
    adopted = next(iter(server.binary_sensors.values()))
    assert isinstance(adopted, ScenarioRunningBinarySensor)
    assert adopted.name == "Movie"
    server.async_add_bs_entities.assert_called_once_with([adopted])


def test_update_binary_sensor_existing_sets_names_when_not_user_renamed(hass) -> None:
    """Existing sensors should refresh names when registry rename protection allows it."""
    server = make_server(hass)

    area_uid = set_sensor_uid(AVE_FAMILY_ANTITHEFT_AREA, 4)
    area = MotionBinarySensor(
        unique_id=area_uid,
        family=AVE_FAMILY_ANTITHEFT_AREA,
        ave_device_id=4,
        is_motion_detected=0,
        hass=hass,
        webserver=server,
    )
    area.update_state = Mock()
    area.set_name = Mock()
    area.set_ave_name = Mock()
    server.binary_sensors[area_uid] = area

    scenario_uid = set_sensor_uid(AVE_FAMILY_SCENARIO, 9, server)
    scenario = ScenarioRunningBinarySensor(
        unique_id=scenario_uid,
        family=AVE_FAMILY_SCENARIO,
        ave_device_id=9,
        is_running=False,
        hass=hass,
        webserver=server,
    )
    scenario.update_state = Mock()
    scenario.set_name = Mock()
    scenario.set_ave_name = Mock()
    server.binary_sensors[scenario_uid] = scenario

    with patch(
        "custom_components.ave_dominaplus.binary_sensor.check_name_changed",
        return_value=False,
    ):
        update_binary_sensor(server, AVE_FAMILY_ANTITHEFT_AREA, 4, 1, name="Area 4")
        update_binary_sensor(server, AVE_FAMILY_SCENARIO, 9, 1, name="Evening")

    area.update_state.assert_called_once_with(1)
    area.set_ave_name.assert_called_once_with("Area 4")
    area.set_name.assert_called_once_with("Area 4")

    scenario.update_state.assert_called_once_with(1)
    scenario.set_ave_name.assert_called_once_with("Evening")
    scenario.set_name.assert_called_once_with("Evening Running")


@pytest.mark.asyncio
async def test_scenario_running_sensor_lifecycle_and_state_branches(hass) -> None:
    """Scenario running sensor should cover lifecycle, properties, and state branches."""
    server = make_server(hass)
    server._set_connected(True)
    server.register_availability_entity = Mock()
    server.unregister_availability_entity = Mock()
    sensor = ScenarioRunningBinarySensor(
        unique_id="uid-scenario",
        family=AVE_FAMILY_SCENARIO,
        ave_device_id=12,
        is_running=False,
        hass=hass,
        webserver=server,
        ave_name="Morning",
    )
    sensor.async_write_ha_state = Mock()

    assert sensor.name == "Scenario 12 Running"
    assert sensor.unique_id == "uid-scenario"
    assert sensor.available is True
    assert sensor.is_on is False
    assert sensor.device_class == BinarySensorDeviceClass.RUNNING
    assert sensor.extra_state_attributes["AVE_name"] == "Morning"
    assert sensor.build_name() == "Scenario 12 Running"

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
        await sensor.async_added_to_hass()
        await sensor.async_will_remove_from_hass()

    assert server.register_availability_entity.call_args.args[0] is sensor
    assert server.unregister_availability_entity.call_args.args[0] is sensor

    sensor.update_state(None)
    assert sensor.async_write_ha_state.call_count == 0

    with patch(
        "custom_components.ave_dominaplus.binary_sensor.utcnow",
        side_effect=[
            SimpleNamespace(isoformat=lambda: "2026-04-15T10:00:00+00:00"),
            SimpleNamespace(isoformat=lambda: "2026-04-15T10:01:00+00:00"),
        ],
    ):
        sensor.update_state(1)
        sensor.update_state(0)

    assert sensor.extra_state_attributes["last_started"] == "2026-04-15T10:00:00+00:00"
    assert sensor.extra_state_attributes["last_stopped"] == "2026-04-15T10:01:00+00:00"

    with patch(
        "custom_components.ave_dominaplus.binary_sensor.utcnow",
        side_effect=RuntimeError("clock"),
    ):
        sensor.update_state(1)

    writes_before = sensor.async_write_ha_state.call_count
    sensor.set_name(None)
    sensor.set_ave_name("Updated")
    sensor.set_name("Renamed")
    assert sensor.async_write_ha_state.call_count == writes_before + 2

    sensor.hass = None
    writes_before = sensor.async_write_ha_state.call_count
    sensor.set_name("NoWrite")
    assert sensor.async_write_ha_state.call_count == writes_before


def test_motion_sensor_is_on_false_and_set_name_writes_state(hass) -> None:
    """Motion sensor should expose false state and write on name update when attached."""
    server = make_server(hass)
    motion = MotionBinarySensor(
        unique_id="uid-motion-false",
        family=AVE_FAMILY_MOTION_SENSOR,
        ave_device_id=6,
        is_motion_detected=0,
        hass=hass,
        webserver=server,
    )
    motion.async_write_ha_state = Mock()

    assert motion.is_on is False
    motion.set_name("Motion 6")
    motion.set_ave_name("Motion Name")
    assert motion.async_write_ha_state.call_count == 2
