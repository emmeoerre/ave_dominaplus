"""WebSocket connection to the AVE web server."""

import asyncio
import logging
from types import MappingProxyType
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class AveWebServerSettings:
    """AVE web server settings class."""

    host: str
    get_entity_names: bool
    fetch_sensor_areas: bool
    fetch_sensors: bool
    fetch_lights: bool
    fetch_scenarios: bool

    def __init__(self) -> None:
        """Initialize the settings."""
        self.host = ""
        self.get_entity_names = False
        self.fetch_sensor_areas = False
        self.fetch_sensors = False
        self.fetch_lights = False
        self.fetch_scenarios = False


class AveWebServer:
    """AVE web server class."""

    def __init__(
        self,
        settings_data: MappingProxyType[str, Any],
        hass: HomeAssistant,
    ) -> None:
        """Initialize."""
        self.settings = AveWebServerSettings()
        try:
            self.settings = AveWebServerSettings()
            self.settings.host = settings_data["ip_address"]
            self.settings.get_entity_names = settings_data["get_entities_names"]
            self.settings.fetch_sensor_areas = settings_data["fetch_sensor_areas"]
            self.settings.fetch_sensors = settings_data["fetch_sensors"]
            self.settings.fetch_lights = settings_data["fetch_lights"]
        except KeyError as e:
            _LOGGER.error("Missing key in settings data: %s", e)
        self.hass = hass
        self.ws_conn: Any = None
        self._connected = False
        self.device_list: list[Any] = []
        self.wstask: asyncio.Task
        self.started = False
        self.closed = False
        self.binary_sensors: dict = {}  # Track binary sensors by unique ID
        self.update_binary_sensor: Any = None
        self.async_add_bs_entities: Any = None
        self.switches: dict = {}  # Track switches by unique ID
        self.async_add_sw_entities: Any = None
        self.update_switch: Any = None

    async def set_update_binary_sensor(self, func) -> None:
        """Set the set_update_binary_sensor method for binary sensors."""
        self.update_binary_sensor = func

    async def set_update_switch(self, func) -> None:
        """Set the set_update_switch method for switches."""
        self.update_switch = func

    async def set_async_add_bs_entities(self, func) -> None:
        """Set the async_add_entities method for binary sensors."""
        if self.async_add_bs_entities is None:
            self.async_add_bs_entities = func

    async def set_async_add_sw_entities(self, func) -> None:
        """Set the async_add_entities method for switches."""
        if self.async_add_sw_entities is None:
            self.async_add_sw_entities = func

    async def is_connected(self) -> bool:
        """Return if the web server is connected."""
        return self._connected

    async def authenticate(self) -> bool:
        """Authenticate with the WebSocket server."""
        try:
            session = aiohttp.ClientSession()
            self.ws_conn = await session.ws_connect(
                f"ws://{self.settings.host}:14001",
                protocols=["binary"],
            )
            self._connected = True
            _LOGGER.debug("Connected to WebSocket server at %s", self.settings.host)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to connect to WebSocket server: %s", err)
            return False
        return True

    async def disconnect(self) -> None:
        """Disconnect from the web server."""
        self.closed = True
        if self.ws_conn:
            await self.ws_conn.close()
            self.ws_conn = None
            self._connected = False
            _LOGGER.info("WebSocket disconnected!", extra={"host": self.settings.host})

    async def start(self) -> None:
        """Start the WebSocket connection and listen for messages."""
        if self.started:
            _LOGGER.debug("WebSocket connection already started")
            return

        self.started = True
        _LOGGER.debug("Starting WebSocket connection")

        while not self.closed:
            try:
                if not self._connected or self.ws_conn is None or self.ws_conn.closed:
                    _LOGGER.debug("Attempting to connect to WebSocket server")
                    if not await self.authenticate():
                        _LOGGER.error("Failed to authenticate with WebSocket server")
                        await asyncio.sleep(5)
                        continue

                if self.started:
                    await self.on_connect_actions()

                async for msg in self.ws_conn:
                    if msg.type == aiohttp.WSMsgType.BINARY:
                        await self.on_message(msg.data)
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        _LOGGER.error("WebSocket error", extra={"error": msg.data})
                        break

            except Exception as err:  # noqa: BLE001
                _LOGGER.error("WebSocket connection error: %s", err)
                self._connected = False
                await asyncio.sleep(5)  # Retry after a delay

        _LOGGER.debug("WebSocket connection stopped")

    async def on_connect_actions(self):
        """Actions to perform after connecting to the web server."""
        if self.ws_conn is None or self.ws_conn.closed:
            return
        await self.send_ws_command("LDI")  # Get device list

        if self.settings.fetch_lights:
            # Get status by family type 1 (lights)
            await self.send_ws_command("GSF", "1")

        # Get status by family type 12 (motion detection areas)
        if self.settings.fetch_sensor_areas:
            await self.send_ws_command("GSF", ["12"])
            await self.send_ws_command("WSF", "12")

        await self.send_ws_command("SU3")  # Start streaming updates (most of them)
        # await self.send_ws_command("SU2") # Starts streaming some other updates (UPD for TLO and XU , NET and CLD messages)

    def value_to_hex(self, value):
        """Return the herawstringalue of a number."""
        return hex(value)[2:].upper()

    async def build_crc(self, rawstring):
        """Build CRC for the given string."""
        crc = 0
        for char in rawstring:
            crc ^= ord(char)
        crc = 0xFF - crc
        msb = self.value_to_hex(crc >> 4)
        lsb = self.value_to_hex(crc & 0xF)
        return msb + lsb

    async def on_message(self, message):
        """Handle incoming messages from the web server."""
        # _LOGGER.debug("Received message: %s", message)
        try:
            # Ensure the message is decoded if it's in bytes
            if isinstance(message, bytes):
                message = message.decode("utf-8")  # Decode bytes to string using UTF-8
            # log_with_timestamp(message)
            messages = message.split(chr(0x04))
            for msg in messages:
                if len(msg) < 3:
                    continue
                str_msg = msg[1:-3]
                cmd_params, *records_data = str_msg.split(chr(0x1E))
                command, *parameters = cmd_params.split(chr(0x1D))
                records = [record.split(chr(0x1D)) for record in records_data]
                await self.manage_commands(command, parameters, records)
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Error processing message", exc_info=e)

    async def send_ws_command(self, command, parameters=None):
        """Send a command to the web server."""
        message = chr(0x02) + command
        if parameters:
            message += chr(0x1D) + chr(0x1D).join(parameters)
        message += chr(0x03)
        crc = await self.build_crc(message)
        full_message = message + crc + chr(0x04)
        if self.ws_conn and not self.ws_conn.closed:
            await self.ws_conn.send_str(full_message)
            # _LOGGER.debug("Sent command: %s", full_message)
        else:
            _LOGGER.error("WebSocket is not connected")

    async def manage_commands(self, command, parameters, records):
        """Manage commands received from the web server."""
        if command == "pong":
            pass
        elif command == "ack":
            _LOGGER.debug("Received ACK for command: %s", parameters[0])
        elif command == "ping":
            await self.send_ws_command("PONG")
        elif command == "gsf":
            self.manage_gsf(parameters, records)
        elif command == "upd":
            self.manage_upd(parameters, records)
        elif command == "ldi":
            self.manage_ldi(parameters, records)
        elif command == "cld":
            # cloud commands received from SU2
            pass
        elif command == "net":
            # IOT commands received from SU2
            pass
        elif command == "nack":
            _LOGGER.warning(
                "Received NACK for command: %s",
                parameters[0] if len(parameters) > 0 else "Unknown",
            )
        else:
            _LOGGER.warning(
                "Received unknown command %s",
                command,
                extra={
                    "command": command,
                    "parameters": parameters,
                    "records": records,
                },
            )

    def manage_upd(self, parameters, records):
        """Manage UPD commands received from the web server."""
        # _LOGGER.debug(
        #     "Received UPD command. Parameters: %s Records: %s", parameters, records
        # )
        if parameters[0] == "WS":
            device_type, device_id, device_status = (
                int(parameters[1]),
                int(parameters[2]),
                int(parameters[3]),
            )
            if device_id > 200000:
                # Devices with ID > 2000000 must be scenarios or something...
                pass
            elif device_type == 1 and self.settings.fetch_lights:
                self.update_switch(self, device_type, device_id, device_status, None)
            # if device_type in [12, 13]:
            #     log_with_timestamp(f"Received async Antitheft status update. Device ID: {device_id}, Device Type: {device_type}, Status: {device_status}")
            # else:
            #     if device_type in [1, 2, 22, 9, 3, 16, 19, 6]:  # Limited to [Lighting / Energy / Shutters / Scenarios] for security reasons ---
        elif parameters[0] == "X" and parameters[1] == "A":  # ANTITHEFT AREA
            if not self.settings.fetch_sensor_areas:
                # If the user doesn't want to fetch sensor areas, skip this
                return

            # parameters[2] is the area ID. all other parameters are == 0 when triggered, parameters[6] == 1 when cleared
            area_progressive = int(parameters[2])
            # area_engaged = int(parameters[3])
            # area_in_alarm = int(parameters[5])
            area_clear = int(parameters[6])
            status = 1
            if area_clear > 0:
                status = 0
            self.update_binary_sensor(self, 12, area_progressive, status)
            # (f"{ANTITHEFT_PREFIX} XA - areaID: {area_progressive} - engaged: {area_engaged} - clear: {area_clear} - alarm: {area_in_alarm}")
        elif parameters[0] == "X" and parameters[1] == "S":  # ANTITHEFT SENSOR
            if not self.settings.fetch_sensors:
                # If the user doesn't want to fetch sensors, skip this
                return
            self.update_binary_sensor(
                self, 1007, int(parameters[2]), int(parameters[4])
            )
        elif parameters[0] == "X" and parameters[1] == "U":
            # ANTITHEFT UNIT (requires SU2)
            _LOGGER.debug("XU Antitheft Unit - engaged", extra={"id": parameters[2]})
        elif parameters[0] == "WT":
            if parameters[1] == "O":  # THERMOSTAT OFFSET  # noqa: SIM114
                pass
            elif parameters[1] == "S":  # THERMOSTAT SEASON # noqa: SIM114
                pass
            elif parameters[1] == "T":  # THERMOSTAT TEMPERATURE # noqa: SIM114
                pass
            elif parameters[1] == "L":  # DAIKIN FAN LEVEL # noqa: SIM114
                pass
            elif parameters[1] == "Z":  # DAIKIN LOCALOFF
                pass
        elif (
            parameters[0] == "TT" or parameters[0] == "TP" or parameters[0] == "TR"
        ):  # THERMOSTAT TEMPERATURE
            pass
        elif (
            parameters[0] == "TLO" or parameters[0] == "D"
        ):  # THERMOSTAT LOCAL OFF (requires SU2)
            pass
        elif parameters[0] == "GUI":
            # Reload gui
            pass
        else:
            _LOGGER.warning(
                "Not yet handled UPD %s",
                parameters[0],
                extra={"parameters": parameters},
            )

    def manage_gsf(self, parameters, records):
        """Manage GSF Get Status by Family commands received from the web server."""
        _LOGGER.info(
            "Received GSF (Get status by family) command for family %s",
            parameters[0],
            extra={"parameters": parameters, "records": records},
        )
        if parameters[0] in ["7", "12"]:  # Motion detection types
            for record in records:
                device_id, device_status = int(record[0]), int(record[1])
                self.update_binary_sensor(
                    self, int(parameters[0]), device_id, device_status
                )

        if parameters[0] == "1":
            for record in records:
                device_id, device_status = int(record[0]), int(record[1])
                self.update_switch(self, 1, device_id, device_status, None)
                # send_mqtt_message(device_id, device_status)

    def manage_ldi(self, parameters, records):
        """Manage LDI List Devices commands received from the web server."""
        _LOGGER.info(
            "Parsing LDI (List Devices) command",
            extra={"parameters": parameters, "records": records},
        )
        for record in records:
            device_id, device_name, device_type = (
                int(record[0]),
                str(record[1]),
                int(record[2]),
            )
            if device_type == 12:
                # Antitheft area
                self.update_binary_sensor(self, 12, device_id, -1, device_name)
            elif device_type == 11:
                # Keypad
                pass
            elif device_type == 1:
                self.update_switch(self, 1, device_id, -1, device_name)
                # Light
            elif device_type == 4:
                # Thermostat
                pass
            elif device_type == 6:
                # Scenario
                pass
            elif device_type == 8:
                # Camera
                pass
            else:
                _LOGGER.debug(
                    "Unknown device type %s for %s, skipping", device_type, device_name
                )
                continue

    async def switch_turn_on(self, device_id: int):
        """Turn on the switch."""
        if self.ws_conn and not self.ws_conn.closed:
            await self.send_ws_command("EBI", [str(device_id), "11"])
        else:
            _LOGGER.error("WebSocket is not connected")

    async def switch_turn_off(self, device_id: int):
        """Turn off the switch."""
        if self.ws_conn and not self.ws_conn.closed:
            await self.send_ws_command("EBI", [str(device_id), "12"])
        else:
            _LOGGER.error("WebSocket is not connected")

    async def switch_toggle(self, device_id: int):
        """Turn off the switch."""
        if self.ws_conn and not self.ws_conn.closed:
            await self.send_ws_command("EBI", [str(device_id), "10"])
        else:
            _LOGGER.error("WebSocket is not connected")

    async def call_bridge(self, command: str) -> tuple[int, str | None]:
        """Call a xml "rest" bridge for common commands."""
        async with aiohttp.ClientSession() as session:
            try:
                url = f"http://{self.settings.host}/bridge.php"
                params = {"command": command}
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.text()
                        _LOGGER.debug("Bridge response: %s", data)
                        return response.status, data
                    _LOGGER.error("Failed to call bridge. Status: %s", response.status)
                    return response.status, None
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Error calling bridge: %s", err)
                return 900, None

    async def get_device_list_bridge(self) -> tuple[int, str | None]:
        """Get the device list from the bridge."""
        return await self.call_bridge("LDI")
