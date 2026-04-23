"""Additional branch-focused tests for AVE webserver logic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from custom_components.ave_dominaplus import ws_commands, ws_routing
from custom_components.ave_dominaplus.const import (
    AVE_FAMILY_ANTITHEFT,
    AVE_FAMILY_ANTITHEFT_AREA,
    AVE_FAMILY_CAMERA,
    AVE_FAMILY_DIMMER,
    AVE_FAMILY_KEYPAD,
    AVE_FAMILY_ONOFFLIGHTS,
    AVE_FAMILY_SCENARIO,
    AVE_FAMILY_SHUTTER_HUNG,
    AVE_FAMILY_SHUTTER_ROLLING,
    AVE_FAMILY_THERMOSTAT,
)
from custom_components.ave_dominaplus.web_server import AveWebServer
from custom_components.ave_dominaplus.ws_connection_flow import (
    start_thermostats_fetch_flow,
    thermostats_fetch_flow,
)
from homeassistant.core import HomeAssistant

from .web_server_harness import FakeWSConnection, make_server


class _FakeResponse:
    """Minimal async-context response for aiohttp helper tests."""

    def __init__(self, status: int, text_value: str) -> None:
        self.status = status
        self._text_value = text_value

    async def text(self) -> str:
        return self._text_value

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    """Minimal async-context session for aiohttp helper tests."""

    def __init__(
        self, response: _FakeResponse | None = None, exc: Exception | None = None
    ):
        self._response = response
        self._exc = exc

    def get(self, url, params=None):
        del url, params
        if self._exc is not None:
            raise self._exc
        if self._response is None:
            raise RuntimeError("No fake response configured")
        return self._response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_init_with_missing_keys_keeps_defaults(hass: HomeAssistant) -> None:
    """Missing keys in settings should not raise and should keep defaults."""
    server = AveWebServer({"ip_address": "192.168.1.10"}, hass)

    assert server.settings.host == "192.168.1.10"
    assert server.settings.fetch_lights is True


async def test_setter_helpers_assign_callbacks_and_keep_first_adders(
    hass: HomeAssistant,
) -> None:
    """Setter helpers should assign update callbacks and preserve first adders."""
    server = make_server(hass)
    first = Mock()
    second = Mock()

    await server.set_update_binary_sensor(first)
    await server.set_update_switch(first)
    await server.set_update_button(first)
    await server.set_update_light(first)
    await server.set_update_cover(first)
    await server.set_update_thermostat(first)
    await server.set_update_th_offset(first)
    assert await server.is_connected() is False

    await server.set_async_add_bs_entities(first)
    await server.set_async_add_bs_entities(second)
    await server.set_async_add_sw_entities(first)
    await server.set_async_add_sw_entities(second)
    await server.set_async_add_bt_entities(first)
    await server.set_async_add_bt_entities(second)
    await server.set_async_add_lg_entities(first)
    await server.set_async_add_lg_entities(second)
    await server.set_async_add_cv_entities(first)
    await server.set_async_add_cv_entities(second)
    await server.set_async_add_th_entities(first)
    await server.set_async_add_th_entities(second)
    await server.set_async_add_number_entities(first)
    await server.set_async_add_number_entities(second)
    await server.set_update_th_offset(second)

    assert server.update_binary_sensor is first
    assert server.update_switch is first
    assert server.update_button is first
    assert server.update_light is first
    assert server.update_cover is first
    assert server.update_thermostat is first
    assert server.update_th_offset is first
    assert server.async_add_bs_entities is first
    assert server.async_add_sw_entities is first
    assert server.async_add_bt_entities is first
    assert server.async_add_lg_entities is first
    assert server.async_add_cv_entities is first
    assert server.async_add_th_entities is first
    assert server.async_add_number_entities is first


def test_unregister_availability_entity_removes_from_registry(
    hass: HomeAssistant,
) -> None:
    """Unregister helper should drop entity from availability tracking set."""
    server = make_server(hass)
    entity = object()
    server.register_availability_entity(entity)
    server.unregister_availability_entity(entity)

    assert entity not in server._availability_entities


async def test_start_thermostat_flow_cancels_previous_pending_task(
    hass: HomeAssistant,
) -> None:
    """Thermostat flow starter should cancel stale background task before respawn."""
    server = make_server(hass)
    pending_task = Mock()
    pending_task.done.return_value = False
    pending_task.cancel = Mock()
    server.thermostat_fetch_task = pending_task
    server.send_ws_command = AsyncMock()
    fake_task = Mock()

    def _create_task(coro):
        coro.close()
        return fake_task

    with patch(
        "custom_components.ave_dominaplus.ws_connection_flow.asyncio.create_task",
        side_effect=_create_task,
    ):
        await start_thermostats_fetch_flow(server)

    pending_task.cancel.assert_called_once()
    server.send_ws_command.assert_awaited_once_with("LM")


async def test_thermostat_fetch_flow_returns_when_map_has_no_areas(
    hass: HomeAssistant,
) -> None:
    """Thermostat fetch flow should stop when map is loaded but empty."""
    server = make_server(hass)
    server.send_ws_command = AsyncMock()
    server.ws_conn = SimpleNamespace(closed=False)
    server.ave_map.areas_loaded = True
    server.ave_map.areas = {}
    server.thermostat_lm_done.set()

    await thermostats_fetch_flow(server)

    server.send_ws_command.assert_not_awaited()


async def test_thermostat_fetch_flow_returns_when_map_not_ready_or_ws_disconnected(
    hass: HomeAssistant,
) -> None:
    """Thermostat fetch flow should stop before LMC requests when map/ws is unavailable."""
    server = make_server(hass)
    server.send_ws_command = AsyncMock()
    server.ws_conn = SimpleNamespace(closed=True)
    server.ave_map.areas_loaded = True
    server.ave_map.areas = {1: object()}
    server.thermostat_lm_done.set()

    await thermostats_fetch_flow(server)

    server.send_ws_command.assert_not_awaited()


async def test_thermostat_fetch_flow_continues_when_lmc_wait_times_out(
    hass: HomeAssistant,
) -> None:
    """Timeout waiting for LMC responses should still trigger WTS snapshots."""
    server = make_server(hass)
    server.send_ws_command = AsyncMock()
    server.ws_conn = SimpleNamespace(closed=False)
    server.ave_map.areas_loaded = True
    server.ave_map.areas = {1: object()}
    server.all_thermostats_raw = {4: {}, 5: {}}
    server.thermostat_lm_done.set()

    call_count = {"n": 0}

    async def _wait_for(coro, _timeout):
        call_count["n"] += 1
        if call_count["n"] == 2:
            coro.close()
            raise TimeoutError
        return await coro

    with patch(
        "custom_components.ave_dominaplus.ws_connection_flow.asyncio.wait_for",
        new=AsyncMock(side_effect=_wait_for),
    ):
        await thermostats_fetch_flow(server)

    server.send_ws_command.assert_any_await("LMC", [1])
    server.send_ws_command.assert_any_await("WTS", ["4"])
    server.send_ws_command.assert_any_await("WTS", ["5"])


async def test_send_ws_command_supports_string_params_and_records(
    hass: HomeAssistant,
) -> None:
    """send_ws_command should accept comma-separated string payloads."""
    server = make_server(hass)
    ws_conn = FakeWSConnection()
    server.ws_conn = ws_conn

    await server.send_ws_command("CMD", "1,2", "a,b")

    assert len(ws_conn.sent_messages) == 1
    sent_message = ws_conn.sent_messages[0]
    assert sent_message.startswith(chr(0x02) + "CMD")
    assert sent_message.endswith(chr(0x04))


async def test_manage_incoming_dispatches_all_known_and_unknown_commands(
    hass: HomeAssistant,
) -> None:
    """Incoming command dispatcher should route all known command families."""
    server = make_server(hass)
    server.send_ws_command = AsyncMock()

    with (
        patch.object(ws_routing, "manage_gsf") as manage_gsf,
        patch.object(ws_routing, "manage_upd") as manage_upd,
        patch.object(ws_routing, "manage_ldi_li2") as manage_ldi_li2,
        patch.object(ws_routing, "manage_lm") as manage_lm,
        patch.object(ws_routing, "manage_lmc") as manage_lmc,
        patch.object(ws_routing, "manage_wts") as manage_wts,
    ):
        await server.manage_incoming_messages("pong", [], [])
        await server.manage_incoming_messages("ack", ["LI2"], [])
        await server.manage_incoming_messages("ping", [], [])
        await server.manage_incoming_messages("gsf", ["1"], [])
        await server.manage_incoming_messages("upd", ["WS"], [])
        await server.manage_incoming_messages("ldi", [], [])
        await server.manage_incoming_messages("li2", [], [])
        await server.manage_incoming_messages("lm", [], [])
        await server.manage_incoming_messages("lmc", ["1"], [])
        await server.manage_incoming_messages("wts", ["4"], [])
        await server.manage_incoming_messages("cld", [], [])
        await server.manage_incoming_messages("net", [], [])
        await server.manage_incoming_messages("nack", [], [])
        await server.manage_incoming_messages("unknown", [], [])

    server.send_ws_command.assert_awaited_once_with("PONG")
    manage_gsf.assert_called_once_with(server, ["1"], [])
    manage_upd.assert_called_once_with(server, ["WS"], [])
    assert manage_ldi_li2.call_count == 2
    manage_lm.assert_called_once_with(server, [], [])
    manage_lmc.assert_called_once_with(server, ["1"], [])
    manage_wts.assert_called_once_with(server, ["4"], [])


def test_manage_upd_covers_remaining_noop_and_unknown_branches(
    hass: HomeAssistant,
) -> None:
    """UPD routing should handle no-op and unknown branches without callback errors."""
    server = make_server(hass, fetch_sensor_areas=False, fetch_sensors=False)
    server.update_binary_sensor = Mock()
    server.update_button = Mock()
    server.update_switch = Mock()
    server.update_light = Mock()
    server.update_cover = Mock()
    server.update_thermostat = Mock()
    server.update_th_offset = Mock()

    ws_routing.manage_upd(server, ["WS", "1", "200001", "1"], [])
    ws_routing.manage_upd(server, ["X", "A", "7", "0", "0", "0", "1"], [])
    ws_routing.manage_upd(server, ["X", "S", "12", "0", "1"], [])
    ws_routing.manage_upd(server, ["X", "U", "2"], [])
    ws_routing.manage_upd(server, ["TM", "1", "2"], [])
    ws_routing.manage_upd(server, ["HO"], [])
    ws_routing.manage_upd(server, ["UNHANDLED"], [])

    server.update_binary_sensor.assert_not_called()
    server.update_thermostat.assert_called_once()
    server.update_th_offset.assert_not_called()
    server.update_button.assert_not_called()
    server.update_switch.assert_not_called()
    server.update_light.assert_not_called()
    server.update_cover.assert_not_called()


def test_manage_upd_tt_unknown_command_is_ignored(hass: HomeAssistant) -> None:
    """TT/TR/TL updates should be skipped if map command id is unknown."""
    server = make_server(hass)
    server.update_thermostat = Mock()
    server.ave_map.areas_loaded = True
    server.ave_map.command_loaded = True
    server.ave_map.get_command_by_id_and_family = Mock(return_value=None)

    ws_routing.manage_upd(server, ["TR", "99", "205"], [])

    server.update_thermostat.assert_not_called()


def test_manage_gsf_routes_antitheft_dimmer_cover_and_light_mode(
    hass: HomeAssistant,
) -> None:
    """GSF handler should route families to the expected callbacks."""
    server = make_server(hass, on_off_lights_as_switch=False)
    server.update_binary_sensor = Mock()
    server.update_switch = Mock()
    server.update_light = Mock()
    server.update_cover = Mock()

    ws_routing.manage_gsf(server, [str(AVE_FAMILY_ANTITHEFT)], [["10", "1"]])
    ws_routing.manage_gsf(server, [str(AVE_FAMILY_ONOFFLIGHTS)], [["11", "0"]])
    ws_routing.manage_gsf(server, [str(AVE_FAMILY_DIMMER)], [["12", "15"]])
    ws_routing.manage_gsf(server, [str(AVE_FAMILY_SHUTTER_HUNG)], [["13", "2"]])

    server.update_binary_sensor.assert_called_once_with(
        server, AVE_FAMILY_ANTITHEFT, 10, 1
    )
    server.update_switch.assert_not_called()
    assert server.update_light.call_count == 2
    server.update_cover.assert_called_once_with(
        server, AVE_FAMILY_SHUTTER_HUNG, 13, 2, None
    )


def test_manage_ldi_li2_covers_special_names_types_and_bad_address(
    hass: HomeAssistant,
) -> None:
    """LI2 parser should handle special names, passthrough types, and bad addresses."""
    server = make_server(hass, on_off_lights_as_switch=False)
    server.update_binary_sensor = Mock()
    server.update_button = Mock()
    server.update_switch = Mock()
    server.update_light = Mock()
    server.update_cover = Mock()

    records = [
        ["1", "$rgb", str(AVE_FAMILY_ONOFFLIGHTS), "7"],
        ["2", "dali$", str(AVE_FAMILY_ONOFFLIGHTS), "7"],
        ["3", "Area", str(AVE_FAMILY_ANTITHEFT_AREA), "8"],
        ["4", "Keypad", str(AVE_FAMILY_KEYPAD), "9"],
        ["5", "Light", str(AVE_FAMILY_ONOFFLIGHTS), "10"],
        ["6", "Dim", str(AVE_FAMILY_DIMMER), "11"],
        ["7", "Cover", str(AVE_FAMILY_SHUTTER_ROLLING), "12"],
        ["8", "Therm", str(AVE_FAMILY_THERMOSTAT), "x"],
        ["9", "Scene", str(AVE_FAMILY_SCENARIO), "13"],
        ["10", "Cam", str(AVE_FAMILY_CAMERA), "14"],
        ["11", "Unknown", "999", "15"],
    ]

    ws_routing.manage_ldi_li2(server, [], records, "li2")

    server.update_binary_sensor.assert_any_call(
        server, AVE_FAMILY_ANTITHEFT_AREA, 3, -1, "Area"
    )
    server.update_binary_sensor.assert_any_call(
        server, AVE_FAMILY_SCENARIO, 9, -1, "Scene"
    )
    server.update_button.assert_called_once_with(
        server, AVE_FAMILY_SCENARIO, 9, "Scene", 13
    )
    server.update_switch.assert_not_called()
    assert server.update_light.call_count == 2
    server.update_cover.assert_called_once_with(
        server, AVE_FAMILY_SHUTTER_ROLLING, 7, -1, "Cover", 12
    )
    assert server.all_thermostats_raw[8] == {
        "device_name": "Therm",
        "address_dec": None,
        "address_hex": "",
    }
    assert server.ldi_done.is_set()


def test_manage_lm_and_lmc_update_events(hass: HomeAssistant) -> None:
    """LM/LMC handlers should load map data and set completion events."""
    server = make_server(hass)
    server.ave_map.load_areas_from_wsrecords = Mock()
    server.ave_map.load_area_commands = Mock()

    ws_routing.manage_lm(server, [], [["1", "Area"]])
    assert server.ave_map.areas_loaded is True
    assert server.thermostat_lm_done.is_set()

    server.ave_map.command_loaded = True
    ws_routing.manage_lmc(server, ["2"], [["cmd"]])

    server.ave_map.load_area_commands.assert_called_once_with(2, [["cmd"]])
    assert server.thermostat_lmc_done.is_set()


async def test_disconnected_command_helpers_cover_remaining_error_paths(
    hass: HomeAssistant,
) -> None:
    """Disconnected helpers should no-op for remaining command methods."""
    server = make_server(hass)
    server.ws_conn = None
    server.send_ws_command = AsyncMock()

    await ws_commands.switch_turn_off(server, 1)
    await ws_commands.switch_toggle(server, 1)
    await ws_commands.dimmer_turn_on(server, 2, 8)
    await ws_commands.dimmer_toggle(server, 2)
    await ws_commands.cover_close(server, 3)
    await ws_commands.cover_stop(server, 3, "9")
    await ws_commands.thermostat_on_off(server, 4, 1)

    server.send_ws_command.assert_not_awaited()


async def test_tryget_mac_address_non_200_and_exception(hass: HomeAssistant) -> None:
    """MAC helper should return None for non-200 responses and request errors."""
    server = make_server(hass)
    non_200_session = _FakeSession(_FakeResponse(503, "unavailable"))

    with patch(
        "custom_components.ave_dominaplus.web_server.aiohttp.ClientSession",
        return_value=non_200_session,
    ):
        assert await server.tryget_mac_address() is None

    error_session = _FakeSession(exc=RuntimeError("boom"))
    with patch(
        "custom_components.ave_dominaplus.web_server.aiohttp.ClientSession",
        return_value=error_session,
    ):
        assert await server.tryget_mac_address() is None


async def test_tryget_systeminfo_exception_returns_empty_dict(
    hass: HomeAssistant,
) -> None:
    """System info helper should return empty dict when request errors occur."""
    server = make_server(hass)
    error_session = _FakeSession(exc=RuntimeError("boom"))

    with patch(
        "custom_components.ave_dominaplus.web_server.aiohttp.ClientSession",
        return_value=error_session,
    ):
        assert await server.tryget_systeminfo() == {}
