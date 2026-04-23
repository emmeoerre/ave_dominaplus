"""WebSocket connection to the AVE web server."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
from typing import TYPE_CHECKING, Any

import aiohttp
from defusedxml import ElementTree as DefusedET

from . import ws_routing
from .ave_map import AveMap
from .ws_connection_flow import on_connect_actions as ws_on_connect_actions
from .ws_settings import AveWebServerSettings

if TYPE_CHECKING:
    from types import MappingProxyType

    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


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
            self.settings = AveWebServerSettings.from_config_entry_options(
                settings_data
            )
        except KeyError:
            _LOGGER.exception("Missing key in settings data")
        self.mac_address = ""
        self.config_entry_id: str | None = None
        self.config_entry_unique_id: str | None = None
        self.systeminfo: dict[str, str] = {}
        self.hass = hass
        self._ws_session: aiohttp.ClientSession | None = None
        self.ws_conn: Any = None
        self._connected = False
        self._has_connected_once = False
        self._logged_unavailable = False
        self._availability_entities: set[Any] = set()
        self.device_list: list[Any] = []
        self.wtstask: asyncio.Task
        self.started = False
        self.closed = False
        self.raw_ldi: list[Any] = []
        self.binary_sensors: dict = {}  # Track binary sensors by unique ID
        self.update_binary_sensor: Any = None
        self.async_add_bs_entities: Any = None
        self.switches: dict = {}  # Track switches by unique ID
        self.async_add_sw_entities: Any = None
        self.update_switch: Any = None
        self.buttons: dict = {}  # Track buttons by unique ID
        self.async_add_bt_entities: Any = None
        self.update_button: Any = None
        self.lights: dict = {}  # Track dimmer lights by unique ID
        self.async_add_lg_entities: Any = None
        self.update_light: Any = None
        self.covers: dict = {}  # Track covers by unique ID
        self.async_add_cv_entities: Any = None
        self.update_cover: Any = None
        self.thermostats: dict = {}  # Track thermostats by ID
        self.all_thermostats_raw: dict = {}  # Track thermostats that are not on the map by device ID
        self.async_add_th_entities: Any = None
        self.update_thermostat: Any = None
        self.ave_map: AveMap = AveMap()
        self.ldi_done = asyncio.Event()
        self.thermostat_lm_done = asyncio.Event()
        self.thermostat_lmc_done = asyncio.Event()
        self.connect_actions_task: asyncio.Task | None = None
        self.thermostat_fetch_task: asyncio.Task | None = None
        self.numbers: dict = {}  # Track number entities by unique ID
        self.async_add_number_entities: Any = None
        self.update_th_offset: Any = None

    async def set_update_binary_sensor(self, func) -> None:
        """Set the set_update_binary_sensor method for binary sensors."""
        self.update_binary_sensor = func

    async def set_update_switch(self, func) -> None:
        """Set the set_update_switch method for switches."""
        self.update_switch = func

    async def set_update_button(self, func) -> None:
        """Set the set_update_button method for buttons."""
        self.update_button = func

    async def set_update_light(self, func) -> None:
        """Set the set_update_light method for dimmer lights."""
        self.update_light = func

    async def set_update_cover(self, func) -> None:
        """Set the set_update_cover method for covers."""
        self.update_cover = func

    async def set_update_thermostat(self, func) -> None:
        """Set the set_update_thermostat method for thermostats."""
        self.update_thermostat = func

    async def set_async_add_bs_entities(self, func) -> None:
        """Set the async_add_entities method for binary sensors."""
        if self.async_add_bs_entities is None:
            self.async_add_bs_entities = func

    async def set_async_add_sw_entities(self, func) -> None:
        """Set the async_add_entities method for switches."""
        if self.async_add_sw_entities is None:
            self.async_add_sw_entities = func

    async def set_async_add_bt_entities(self, func) -> None:
        """Set the async_add_entities method for buttons."""
        if self.async_add_bt_entities is None:
            self.async_add_bt_entities = func

    async def set_async_add_lg_entities(self, func) -> None:
        """Set the async_add_entities method for dimmer lights."""
        if self.async_add_lg_entities is None:
            self.async_add_lg_entities = func

    async def set_async_add_cv_entities(self, func) -> None:
        """Set the async_add_entities method for covers."""
        if self.async_add_cv_entities is None:
            self.async_add_cv_entities = func

    async def set_async_add_th_entities(self, func) -> None:
        """Set the async_add_entities method for thermostats."""
        if self.async_add_th_entities is None:
            self.async_add_th_entities = func

    async def set_async_add_number_entities(self, func) -> None:
        """Set the async_add_entities method for number entities."""
        if self.async_add_number_entities is None:
            self.async_add_number_entities = func

    async def set_update_th_offset(self, func) -> None:
        """Set the method to add/update thermostat offset number entities."""
        if self.update_th_offset is None:
            self.update_th_offset = func

    async def is_connected(self) -> bool:
        """Return if the web server is connected."""
        return self._connected

    @property
    def connected(self) -> bool:
        """Return if the web server is connected (sync property)."""
        return self._connected

    def _iter_connection_entities(self):
        """Iterate all runtime entities that should refresh availability."""
        seen: set[int] = set()

        for entity in self._availability_entities:
            entity_id = id(entity)
            if entity_id in seen:
                continue
            seen.add(entity_id)
            yield entity

        for collection in (
            self.binary_sensors,
            self.switches,
            self.buttons,
            self.lights,
            self.covers,
            self.thermostats,
            self.numbers,
        ):
            for entity in collection.values():
                entity_id = id(entity)
                if entity_id in seen:
                    continue
                seen.add(entity_id)
                yield entity

    def register_availability_entity(self, entity: Any) -> None:
        """Register an entity for connectivity-driven availability updates."""
        self._availability_entities.add(entity)

    def unregister_availability_entity(self, entity: Any) -> None:
        """Unregister an entity for connectivity-driven availability updates."""
        self._availability_entities.discard(entity)

    def _notify_connection_state_changed(self) -> None:
        """Force entity state refresh when connectivity changes."""
        for entity in self._iter_connection_entities():
            if getattr(entity, "hass", None) is None:
                continue
            if getattr(entity, "entity_id", None) is None:
                continue
            try:
                entity.async_write_ha_state()
            except RuntimeError:
                _LOGGER.debug(
                    "Skipping availability refresh for entity %s due to runtime state",
                    entity,
                    exc_info=True,
                )

    def _set_connected(self, connected: bool, *, log_transition: bool = True) -> None:
        """Update connection flag and log only on edge transitions."""
        if self._connected == connected:
            return

        self._connected = connected

        if connected:
            self._has_connected_once = True
            if log_transition and self._logged_unavailable:
                _LOGGER.info(
                    "Connection to AVE web server restored",
                    extra={"host": self.settings.host},
                )
                self._logged_unavailable = False
        elif (
            log_transition and self._has_connected_once and not self._logged_unavailable
        ):
            _LOGGER.warning(
                "Connection to AVE web server unavailable",
                extra={"host": self.settings.host},
            )
            self._logged_unavailable = True

        self._notify_connection_state_changed()

    async def authenticate(self) -> bool:
        """Authenticate with the WebSocket server."""
        try:
            if self._ws_session is None or self._ws_session.closed:
                self._ws_session = aiohttp.ClientSession()

            self.ws_conn = await self._ws_session.ws_connect(
                f"ws://{self.settings.host}:14001",
                protocols=["binary"],
                heartbeat=15,
            )
            self._set_connected(True)
            self.mac_address = await self.tryget_mac_address()
            self.systeminfo = await self.tryget_systeminfo()
            _LOGGER.debug("Connected to WebSocket server at %s", self.settings.host)
        except aiohttp.ClientError as err:
            self._set_connected(False)
            if self.ws_conn:
                with suppress(Exception):
                    await self.ws_conn.close()
                self.ws_conn = None
            if self._ws_session and not self._ws_session.closed:
                with suppress(Exception):
                    await self._ws_session.close()
            self._ws_session = None
            _LOGGER.debug(
                "Failed to connect to WebSocket server at %s: %s",
                self.settings.host,
                err,
            )
            return False
        except Exception:
            self._set_connected(False)
            if self.ws_conn:
                with suppress(Exception):
                    await self.ws_conn.close()
                self.ws_conn = None
            if self._ws_session and not self._ws_session.closed:
                with suppress(Exception):
                    await self._ws_session.close()
            self._ws_session = None
            _LOGGER.exception("Unexpected error while connecting to WebSocket server")
            return False
        return True

    async def disconnect(self) -> None:
        """Disconnect from the web server."""
        self.closed = True
        if self.connect_actions_task and not self.connect_actions_task.done():
            self.connect_actions_task.cancel()
            self.connect_actions_task = None
        if self.thermostat_fetch_task and not self.thermostat_fetch_task.done():
            self.thermostat_fetch_task.cancel()
            self.thermostat_fetch_task = None
        if self.ws_conn:
            await self.ws_conn.close()
            self.ws_conn = None
            _LOGGER.info("WebSocket disconnected!", extra={"host": self.settings.host})
        if self._ws_session and not self._ws_session.closed:
            await self._ws_session.close()
        self._ws_session = None
        self._set_connected(False, log_transition=False)

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
                        await asyncio.sleep(5)
                        continue

                if self.started:
                    self.connect_actions_task = asyncio.create_task(
                        ws_on_connect_actions(self)
                    )

                async for msg in self.ws_conn:
                    if msg.type == aiohttp.WSMsgType.BINARY:
                        await self.on_message(msg.data)
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        _LOGGER.debug("WebSocket error", extra={"error": msg.data})
                        break

                self._set_connected(False)

            except Exception:
                _LOGGER.exception("WebSocket connection error")
                self._set_connected(False)
                await asyncio.sleep(5)  # Retry after a delay

        _LOGGER.debug("WebSocket connection stopped")

    def value_to_hex(self, value):
        """Return the hexadecimal value of a number."""
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

    async def on_message(self, message) -> None:
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
                await self.manage_incoming_messages(command, parameters, records)
        except Exception:
            _LOGGER.exception("Error processing message")

    async def send_ws_command(
        self,
        command: str,
        parameters: list[Any] | None = None,
        records: list[list[Any]] | None = None,
    ) -> None:
        """Send a command to the web server."""
        message = chr(0x02) + command
        payload = ""
        if parameters is not None:
            payload += chr(0x1D)
            if isinstance(parameters, (list, tuple)):
                pieces = [str(item) for item in parameters]
            else:
                pieces = str(parameters).split(",")
            payload += chr(0x1D).join(pieces)
        if records is not None:
            if not isinstance(records, (list, tuple)):
                records = str(records).split(",")
            for record in records:  # pyright: ignore[reportOptionalIterable]
                payload += chr(0x1E)
                if isinstance(record, (list, tuple)):
                    record_string = ",".join(str(item) for item in record)
                else:
                    record_string = str(record)
                pieces = record_string.split(",")
                payload += chr(0x1D).join(pieces)
        message += payload
        message += chr(0x03)
        crc = await self.build_crc(message)
        full_message = message + crc + chr(0x04)
        if not self.ws_conn or self.ws_conn.closed:
            _LOGGER.debug(
                "Skipping command %s because WebSocket is not connected", command
            )
            return

        try:
            await self.ws_conn.send_str(full_message)
        except Exception:  # noqa: BLE001
            self._set_connected(False)
            _LOGGER.debug(
                "Failed to send command %s because WebSocket is not connected",
                command,
                exc_info=True,
            )
            return

        escaped_message = full_message.encode("unicode_escape").decode("ascii")
        _LOGGER.debug("Sent command: %s", escaped_message)

    async def manage_incoming_messages(
        self, command: str, parameters: list[Any], records: list[list[Any]]
    ) -> None:
        """Manage commands received from the web server."""
        if command == "pong":
            pass
        elif command == "ack":
            _LOGGER.debug("Received ACK for command: %s", parameters[0])
        elif command == "ping":
            await self.send_ws_command("PONG")
        elif command == "gsf":
            ws_routing.manage_gsf(self, parameters, records)
        elif command == "upd":
            ws_routing.manage_upd(self, parameters, records)
        elif command in {"ldi", "li2"}:
            ws_routing.manage_ldi_li2(self, parameters, records, command)
        elif command == "lm":
            ws_routing.manage_lm(self, parameters, records)
        elif command == "lmc":
            ws_routing.manage_lmc(self, parameters, records)
        elif command == "wts":
            ws_routing.manage_wts(self, parameters, records)
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
            except Exception:
                _LOGGER.exception("Error calling bridge")
                return 900, None

    async def tryget_mac_address(self) -> str | None:
        """Try to get the MAC address of the webserver."""
        async with aiohttp.ClientSession() as session:
            try:
                url = f"http://{self.settings.host}/revealcode.php"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.text()
                        # _LOGGER.debug("revealcode response: %s", data)

                        try:
                            root = DefusedET.fromstring(data)
                            xml_mac = root.findtext("macaddress")
                            if xml_mac:
                                return xml_mac.strip().lower()
                        except DefusedET.ParseError:
                            _LOGGER.exception("Invalid XML in revealcode response")
                        _LOGGER.warning(
                            "No macaddress tag found in revealcode response"
                        )
                        return None
                    _LOGGER.error(
                        "Failed to get WebServer MAC address. Status: %s",
                        response.status,
                    )
                    return None
            except Exception:
                _LOGGER.exception("Error getting WebServer MAC ADDRESS")
                return None

    async def tryget_systeminfo(self) -> dict[str, str]:
        """Try to get selected system information from the webserver."""
        async with aiohttp.ClientSession() as session:
            try:
                url = f"http://{self.settings.host}/systeminfo.php"
                async with session.get(url) as response:
                    if response.status != 200:
                        _LOGGER.error(
                            "Failed to get WebServer system info. Status: %s",
                            response.status,
                        )
                        return {}

                    data = await response.text()
                    try:
                        root = DefusedET.fromstring(data)
                    except DefusedET.ParseError:
                        _LOGGER.exception("Invalid XML in systeminfo response")
                        return {}

                    keys = [
                        "remotesupport",
                        "os",
                        "app",
                        "launcher",
                        "DPServer",
                        "DPClient",
                        "firmware",
                        "cloud",
                        "iot",
                    ]

                    systeminfo: dict[str, str] = {}
                    for key in keys:
                        element = root.find(key)
                        if element is not None and element.text is not None:
                            systeminfo[key] = element.text.strip()

                    return systeminfo
            except Exception:
                _LOGGER.exception("Error getting WebServer system info")
                return {}

    async def get_device_list_bridge(self) -> tuple[int, str | None]:
        """Get the device list from the bridge."""
        return await self.call_bridge("LDI")
