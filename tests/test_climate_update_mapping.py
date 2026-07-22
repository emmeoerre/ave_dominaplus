"""Tests for thermostat update mapping and routing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

from custom_components.ave_dominaplus.ave_thermostat import AveThermostatProperties
from custom_components.ave_dominaplus.climate import (
    _update_thermostat,
    set_sensor_uid,
    update_thermostat,
)
from custom_components.ave_dominaplus.const import AVE_FAMILY_THERMOSTAT
from custom_components.ave_dominaplus.web_server import AveWebServer
from homeassistant.core import HomeAssistant


def _new_server(hass: HomeAssistant, **overrides) -> AveWebServer:
    """Build a webserver with defaults suitable for climate tests."""
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
    server = AveWebServer(settings, hass, object())
    server.mac_address = "aa:bb:cc:dd:ee:ff"
    server.async_add_th_entities = Mock()
    return server


def _props(
    device_id: int = 4, name: str | None = "Thermostat Living"
) -> AveThermostatProperties:
    """Build thermostat properties for update tests."""
    props = AveThermostatProperties()
    props.device_id = device_id
    props.device_name = name
    props.fan_level = 1
    props.season = "1"
    props.temperature = 21.5
    props.mode = "M"
    props.set_point = 22.0
    props.local_off = 0
    return props


def test_update_thermostat_maps_wt_offset(hass: HomeAssistant) -> None:
    """WT/O updates should map to offset property with tenths conversion."""
    server = _new_server(hass)

    with patch("custom_components.ave_dominaplus.climate._update_thermostat") as update:
        update_thermostat(server, ["WT", "O", "4", "12"], [])

    update.assert_called_once_with(
        server=server,
        family=AVE_FAMILY_THERMOSTAT,
        ave_device_id=4,
        property_name="offset",
        property_value=1.2,
        address_dec=None,
    )


def test_update_thermostat_maps_tm_mode(hass: HomeAssistant) -> None:
    """TM updates should map to mode property for target thermostat device."""
    server = _new_server(hass)

    with patch("custom_components.ave_dominaplus.climate._update_thermostat") as update:
        update_thermostat(server, ["TM", "8", "M"], [])

    update.assert_called_once_with(
        server=server,
        family=AVE_FAMILY_THERMOSTAT,
        ave_device_id=8,
        property_name="mode",
        property_value="M",
        address_dec=None,
    )


def test_update_thermostat_maps_tp_setpoint(hass: HomeAssistant) -> None:
    """TP updates should map to set point with tenths conversion."""
    server = _new_server(hass)

    with patch("custom_components.ave_dominaplus.climate._update_thermostat") as update:
        update_thermostat(server, ["TP", "8", "205"], [])

    update.assert_called_once_with(
        server=server,
        family=AVE_FAMILY_THERMOSTAT,
        ave_device_id=8,
        property_name="set_point",
        property_value=20.5,
        address_dec=None,
    )


def test_update_thermostat_maps_tt_with_command_lookup(hass: HomeAssistant) -> None:
    """Command-ID updates should map using the command's thermostat device id."""
    server = _new_server(hass)
    command = SimpleNamespace(device_id=9)

    with patch("custom_components.ave_dominaplus.climate._update_thermostat") as update:
        update_thermostat(server, ["TT", "100", "230"], [], command=command)

    update.assert_called_once_with(
        server=server,
        family=AVE_FAMILY_THERMOSTAT,
        ave_device_id=9,
        property_name="temperature",
        property_value=23.0,
        address_dec=None,
    )


def test_update_thermostat_bulk_properties_uses_properties_device_id(
    hass: HomeAssistant,
) -> None:
    """Bulk update path should use properties.device_id for target thermostat."""
    server = _new_server(hass)
    props = _props(device_id=22)

    with patch("custom_components.ave_dominaplus.climate._update_thermostat") as update:
        update_thermostat(
            server,
            ["WT", "S", "22", "1"],
            [],
            properties=props,
            ave_device_id=999,
        )

    assert update.call_args_list[0].kwargs["ave_device_id"] == 22


def test__update_thermostat_updates_existing_with_properties(
    hass: HomeAssistant,
) -> None:
    """Existing thermostat should apply full properties and optional name updates."""
    server = _new_server(hass, get_entities_names=True)
    unique_id = set_sensor_uid(server, AVE_FAMILY_THERMOSTAT, 4)
    thermostat = Mock()
    server.thermostats[unique_id] = thermostat
    props = _props(device_id=4, name="Living")

    _update_thermostat(
        server=server,
        family=AVE_FAMILY_THERMOSTAT,
        ave_device_id=4,
        properties=props,
        address_dec=18,
    )

    thermostat.update_all_properties.assert_called_once_with(props)
    thermostat.set_ave_name.assert_called_once_with("Living")
    thermostat.set_name.assert_not_called()
    thermostat.set_address_dec.assert_called_once_with(18)


def test__update_thermostat_existing_respects_name_override(
    hass: HomeAssistant,
) -> None:
    """Existing thermostat should not overwrite user name when override is detected."""
    server = _new_server(hass)
    unique_id = set_sensor_uid(server, AVE_FAMILY_THERMOSTAT, 4)
    thermostat = Mock()
    server.thermostats[unique_id] = thermostat
    props = _props(device_id=4, name="Living")

    _update_thermostat(
        server=server,
        family=AVE_FAMILY_THERMOSTAT,
        ave_device_id=4,
        properties=props,
    )

    thermostat.set_ave_name.assert_called_once_with("Living")
    thermostat.set_name.assert_not_called()


def test__update_thermostat_updates_specific_property_on_existing(
    hass: HomeAssistant,
) -> None:
    """Specific-property updates should target existing thermostat instance."""
    server = _new_server(hass)
    unique_id = set_sensor_uid(server, AVE_FAMILY_THERMOSTAT, 4)
    thermostat = Mock()
    server.thermostats[unique_id] = thermostat

    _update_thermostat(
        server=server,
        family=AVE_FAMILY_THERMOSTAT,
        ave_device_id=4,
        property_name="set_point",
        property_value=20.0,
    )

    thermostat.update_specific_property.assert_called_once_with("set_point", 20.0)


def test__update_thermostat_does_not_create_without_properties(
    hass: HomeAssistant,
) -> None:
    """New thermostat creation should be skipped when properties are missing."""
    server = _new_server(hass)

    _update_thermostat(
        server=server,
        family=AVE_FAMILY_THERMOSTAT,
        ave_device_id=4,
        properties=None,
    )

    assert server.thermostats == {}
    server.async_add_th_entities.assert_not_called()


def test__update_thermostat_requires_name_when_entity_names_enabled(
    hass: HomeAssistant,
) -> None:
    """Creation should wait when names are enabled but thermostat name is unavailable."""
    server = _new_server(hass, get_entities_names=True)
    props = _props(device_id=4, name=None)

    _update_thermostat(
        server=server,
        family=AVE_FAMILY_THERMOSTAT,
        ave_device_id=4,
        properties=props,
    )

    assert server.thermostats == {}
    server.async_add_th_entities.assert_not_called()


def test__update_thermostat_creates_new_entity(hass: HomeAssistant) -> None:
    """Creation path should instantiate thermostat and add it to Home Assistant."""
    server = _new_server(hass, get_entities_names=True)
    props = _props(device_id=4, name="Living")
    created = Mock()

    with patch(
        "custom_components.ave_dominaplus.climate.AveThermostat",
        return_value=created,
    ) as thermostat_cls:
        _update_thermostat(
            server=server,
            family=AVE_FAMILY_THERMOSTAT,
            ave_device_id=4,
            properties=props,
            address_dec=7,
        )

    unique_id = set_sensor_uid(server, AVE_FAMILY_THERMOSTAT, 4)
    assert server.thermostats[unique_id] is created
    thermostat_cls.assert_called_once()
    server.async_add_th_entities.assert_called_once_with([created])
