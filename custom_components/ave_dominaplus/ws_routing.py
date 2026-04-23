"""Routing helpers for AVE webserver messages."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .ave_thermostat import AveThermostatProperties
from .const import (
    AVE_FAMILY_ANTITHEFT,
    AVE_FAMILY_ANTITHEFT_AREA,
    AVE_FAMILY_CAMERA,
    AVE_FAMILY_DIMMER,
    AVE_FAMILY_KEYPAD,
    AVE_FAMILY_MOTION_SENSOR,
    AVE_FAMILY_ONOFFLIGHTS,
    AVE_FAMILY_SCENARIO,
    AVE_FAMILY_SHUTTER_HUNG,
    AVE_FAMILY_SHUTTER_ROLLING,
    AVE_FAMILY_SHUTTER_SLIDING,
    AVE_FAMILY_THERMOSTAT,
    AVE_UNHANDLED_UPD,
)

if TYPE_CHECKING:
    from .web_server import AveWebServer

_LOGGER = logging.getLogger(__name__)


def manage_upd(
    server: AveWebServer, parameters: list[Any], records: list[list[Any]]
) -> None:
    """Manage UPD commands received from the web server."""
    _LOGGER.debug(
        "Received UPD command. Parameters: %s | Records: %s",
        parameters,
        records,
    )
    if parameters[0] == "WS":
        device_type, device_id, device_status = (
            int(parameters[1]),
            int(parameters[2]),
            int(parameters[3]),
        )
        manage_upd_ws(server, device_type, device_id, device_status)
    elif parameters[0] == "X" and parameters[1] == "A":  # ANTITHEFT AREA
        if not server.settings.fetch_sensor_areas:
            return

        """parameters[2] is the area ID.
        all other parameters are == 0 when triggered,
        parameters[6] == 1 when cleared"""

        area_progressive = int(parameters[2])
        # area_engaged = int(parameters[3])
        # area_in_alarm = int(parameters[5])
        area_clear = int(parameters[6])
        status = 1
        if area_clear > 0:
            status = 0
        server.update_binary_sensor(
            server, AVE_FAMILY_ANTITHEFT_AREA, area_progressive, status
        )
        # f"XA - areaID: {area_progressive}
        # - engaged: {area_engaged}
        # - clear: {area_clear}
        # - alarm: {area_in_alarm}")
    elif parameters[0] == "X" and parameters[1] == "S":  # ANTITHEFT SENSOR
        if not server.settings.fetch_sensors:
            return
        server.update_binary_sensor(
            server, AVE_FAMILY_MOTION_SENSOR, int(parameters[2]), int(parameters[4])
        )
    elif parameters[0] == "X" and parameters[1] == "U":
        # ANTITHEFT UNIT (requires SU2)
        _LOGGER.debug("XU Antitheft Unit - engaged", extra={"id": parameters[2]})
    elif parameters[0] == "WT":
        # Several updates for thermostats, using Device ID as identifier
        if parameters[1] == "O":
            server.update_thermostat(
                server=server,
                parameters=parameters,
                records=records,
                command=None,
                properties=None,
                ave_device_id=None,
            )
            server.update_th_offset(
                server=server,
                family=AVE_FAMILY_THERMOSTAT,
                ave_device_id=int(parameters[2]),
                offset_value=int(parameters[3]) / 10,
            )
    elif parameters[0] in ["TM", "TW", "TP"]:
        # Thermostats update with device ID as identifier
        server.update_thermostat(
            server=server,
            parameters=parameters,
            records=records,
            command=None,
            properties=None,
            ave_device_id=None,
        )
    elif parameters[0] in ["TT", "TR", "TL", "TLO", "TO", "TS"]:
        # THERMOSTAT updates with command ID as identifier
        if (
            not server.ave_map
            or not server.ave_map.areas_loaded
            or not server.ave_map.command_loaded
        ):
            _LOGGER.debug("Received th update before map/commands loaded; skipping")
            return
        command = server.ave_map.get_command_by_id_and_family(
            int(parameters[1]), AVE_FAMILY_THERMOSTAT
        )
        if not command:
            _LOGGER.debug(
                "Received th update for unknown command ID %s; skipping",
                parameters[1],
            )
            return
        server.update_thermostat(
            server=server,
            parameters=parameters,
            records=records,
            command=command,
            properties=None,
            ave_device_id=None,
        )
    elif parameters[0] in AVE_UNHANDLED_UPD:
        pass
    else:
        _LOGGER.debug(
            "Received not unknown UPD %s",
            parameters[0],
            extra={"parameters": parameters},
        )


def manage_upd_ws(
    server: AveWebServer,
    device_type: int,
    device_id: int,
    device_status: int,
) -> None:
    """Manage UPD WS (status update) commands based on device type."""
    if device_id > 200000:
        # Devices with ID > 2000000 must be scenarios or something...
        return
    if device_type == AVE_FAMILY_ONOFFLIGHTS and server.settings.fetch_lights:
        if server.settings.on_off_lights_as_switch:
            server.update_switch(server, device_type, device_id, device_status, None)
        else:
            server.update_light(server, device_type, device_id, device_status, None)
    elif device_type == AVE_FAMILY_DIMMER and server.settings.fetch_lights:
        server.update_light(server, device_type, device_id, device_status, None)
    elif (
        device_type
        in (
            AVE_FAMILY_SHUTTER_ROLLING,
            AVE_FAMILY_SHUTTER_SLIDING,
            AVE_FAMILY_SHUTTER_HUNG,
        )
        and server.settings.fetch_covers
    ):
        server.update_cover(server, device_type, device_id, device_status, None)
    elif device_type == AVE_FAMILY_SCENARIO and server.settings.fetch_scenarios:
        server.update_binary_sensor(
            server, AVE_FAMILY_SCENARIO, device_id, device_status, None
        )


def manage_gsf(
    server: AveWebServer,
    parameters: list[Any],
    records: list[list[Any]],
) -> None:
    """Manage GSF Get Status by Family responses."""
    _LOGGER.debug(
        "Received GSF (Get status by family) response for family %s, parameters: %s | records: %s",
        parameters[0],
        parameters,
        records,
    )
    if parameters[0] in [
        str(AVE_FAMILY_ANTITHEFT),
        str(AVE_FAMILY_ANTITHEFT_AREA),
    ]:  # Motion detection types
        for record in records:
            device_id, device_status = int(record[0]), int(record[1])
            server.update_binary_sensor(
                server, int(parameters[0]), device_id, device_status
            )

    if parameters[0] == str(AVE_FAMILY_ONOFFLIGHTS):
        for record in records:
            device_id, device_status = int(record[0]), int(record[1])
            if server.settings.on_off_lights_as_switch:
                server.update_switch(
                    server,
                    AVE_FAMILY_ONOFFLIGHTS,
                    device_id,
                    device_status,
                    None,
                )
            else:
                server.update_light(
                    server,
                    AVE_FAMILY_ONOFFLIGHTS,
                    device_id,
                    device_status,
                    None,
                )

    if parameters[0] == str(AVE_FAMILY_DIMMER):
        for record in records:
            device_id, device_status = int(record[0]), int(record[1])
            if server.update_light is not None:
                server.update_light(
                    server, AVE_FAMILY_DIMMER, device_id, device_status, None
                )

    if parameters[0] in [
        str(AVE_FAMILY_SHUTTER_ROLLING),
        str(AVE_FAMILY_SHUTTER_SLIDING),
        str(AVE_FAMILY_SHUTTER_HUNG),
    ]:
        for record in records:
            device_id, device_status = int(record[0]), int(record[1])
            if server.update_cover is not None:
                server.update_cover(
                    server,
                    int(parameters[0]),
                    device_id,
                    device_status,
                    None,
                )

    if parameters[0] == str(AVE_FAMILY_SCENARIO):
        for record in records:
            device_id, device_status = int(record[0]), int(record[1])
            if server.update_binary_sensor is not None:
                server.update_binary_sensor(
                    server,
                    AVE_FAMILY_SCENARIO,
                    device_id,
                    device_status,
                    None,
                )


def manage_ldi_li2(
    server: AveWebServer,
    parameters: list[Any],
    records: list[list[Any]],
    command: str,
) -> None:
    """Manage LDI/LI2 List Devices commands received from the web server."""
    _LOGGER.debug(
        "Parsing %s (List Devices) command, parameters: %s | records: %s",
        command,
        parameters,
        records,
    )
    server.raw_ldi = []
    for record in records:
        try:
            device_id, device_name, device_type, address = (
                int(record[0]),
                str(record[1]),
                int(record[2]),
                record[3],
            )
            # record[3] contains the decimal representation of the address
            address_dec = None
            address_hex = None
            if command == "li2":
                try:
                    address_dec = int(str(address).strip())
                except Exception:  # noqa: BLE001
                    _LOGGER.debug(
                        "Failed parsing address '%s'; leaving address_dec unset",
                        address,
                    )
                    address_dec = None
                # Store address as two-digit uppercase hex string when available
                address_hex = (
                    format(address_dec & 0xFF, "02X") if address_dec is not None else ""
                )
            server.raw_ldi.append(
                {
                    "device_id": device_id,
                    "device_name": device_name,
                    "device_type": device_type,
                    "address_dec": address_dec,
                    "address_hex": address_hex,
                }
            )
            if device_name and device_name[0] == "$":
                # RGBW, unhandled
                continue
            if device_name and device_name[-1] == "$":
                # DALI, unhandled
                continue
            if device_type == AVE_FAMILY_ANTITHEFT_AREA:
                # Antitheft area
                server.update_binary_sensor(
                    server,
                    AVE_FAMILY_ANTITHEFT_AREA,
                    device_id,
                    -1,
                    device_name,
                )
            elif device_type == AVE_FAMILY_KEYPAD:
                # Keypad
                pass
            elif device_type == AVE_FAMILY_ONOFFLIGHTS:
                if server.settings.on_off_lights_as_switch:
                    server.update_switch(
                        server,
                        AVE_FAMILY_ONOFFLIGHTS,
                        device_id,
                        -1,
                        device_name,
                        address_dec,
                    )
                else:
                    server.update_light(
                        server,
                        AVE_FAMILY_ONOFFLIGHTS,
                        device_id,
                        -1,
                        device_name,
                        address_dec,
                    )
            elif device_type == AVE_FAMILY_DIMMER:
                server.update_light(
                    server,
                    AVE_FAMILY_DIMMER,
                    device_id,
                    -1,
                    device_name,
                    address_dec,
                )
            elif device_type in (
                AVE_FAMILY_SHUTTER_ROLLING,
                AVE_FAMILY_SHUTTER_SLIDING,
                AVE_FAMILY_SHUTTER_HUNG,
            ):
                server.update_cover(
                    server,
                    device_type,
                    device_id,
                    -1,
                    device_name,
                    address_dec,
                )
            elif device_type == AVE_FAMILY_THERMOSTAT:
                # All thermostats
                server.all_thermostats_raw[device_id] = {
                    "device_name": device_name,
                    "address_dec": address_dec,
                    "address_hex": address_hex,
                }
            elif device_type == AVE_FAMILY_SCENARIO:
                # Scenario
                if server.settings.fetch_scenarios:
                    if server.update_button is not None:
                        server.update_button(
                            server,
                            AVE_FAMILY_SCENARIO,
                            device_id,
                            device_name,
                            address_dec,
                        )
                    if server.update_binary_sensor is not None:
                        server.update_binary_sensor(
                            server,
                            AVE_FAMILY_SCENARIO,
                            device_id,
                            -1,
                            device_name,
                        )
            elif device_type == AVE_FAMILY_CAMERA:
                # Camera
                pass
            else:
                _LOGGER.debug(
                    "Unknown device type %s for %s, skipping",
                    device_type,
                    device_name,
                )
                continue
        except Exception:
            _LOGGER.exception("Error parsing device record: %s", record)
    server.ldi_done.set()


def manage_lm(
    server: AveWebServer, parameters: list[Any], records: list[list[Any]]
) -> None:
    """Manage LM List Map commands received from the web server."""
    _LOGGER.debug(
        "Parsing LM (List Map) command, parameters: %s | records: %s",
        parameters,
        records,
    )
    server.ave_map.load_areas_from_wsrecords(records)
    server.ave_map.areas_loaded = True
    server.thermostat_lm_done.set()


def manage_lmc(
    server: AveWebServer,
    parameters: list[Any],
    records: list[list[Any]],
) -> None:
    """Manage LMC List Map Commands responses."""
    _LOGGER.debug(
        "Parsing LMC response, parameters: %s | records: %s",
        parameters,
        records,
    )
    area_id = int(parameters[0])
    server.ave_map.load_area_commands(area_id, records)
    if server.ave_map.command_loaded:
        server.thermostat_lmc_done.set()


def manage_wts(
    server: AveWebServer,
    parameters: list[Any],
    records: list[list[Any]],
) -> None:
    """Manage WTS command responses."""
    _LOGGER.debug(
        "Parsing WTS response, parameters: %s | records: %s",
        parameters,
        records,
    )
    device_id = int(parameters[0])
    thermostat_properties = AveThermostatProperties.from_wts(parameters, records)
    thermostat_properties.device_name = f"thermostat_{thermostat_properties.device_id}"
    if server.settings.get_entity_names:
        thermostat_properties.device_name = server.all_thermostats_raw[device_id][
            "device_name"
        ]

    server.update_thermostat(
        server=server,
        parameters=parameters,
        records=records,
        command=None,
        properties=thermostat_properties,
        ave_device_id=device_id,
        address_dec=server.all_thermostats_raw[device_id].get("address_dec"),
    )
    if thermostat_properties.offset is not None:
        server.update_th_offset(
            server=server,
            family=AVE_FAMILY_THERMOSTAT,
            ave_device_id=device_id,
            offset_value=thermostat_properties.offset,
            name=thermostat_properties.device_name,
            address_dec=server.all_thermostats_raw[device_id].get("address_dec"),
        )
