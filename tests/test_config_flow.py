"""Tests for AVE dominaplus config flow."""

from __future__ import annotations

from ipaddress import ip_address
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ave_dominaplus.config_flow import (
    AveWsConfigFlow,
    CannotConnect,
    InvalidAuth,
    MacAddressNotFound,
)
from custom_components.ave_dominaplus.const import DOMAIN
from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_IP_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

MOCK_USER_INPUT: dict[str, object] = {
    CONF_IP_ADDRESS: "192.168.1.10",
    "get_entities_names": True,
    "fetch_sensor_areas": True,
    "fetch_sensors": True,
    "fetch_lights": True,
    "fetch_covers": True,
    "fetch_scenarios": True,
    "fetch_thermostats": True,
    "on_off_lights_as_switch": True,
}


def _build_discovery_info(host: str = "192.168.1.20") -> ZeroconfServiceInfo:
    """Build a Zeroconf discovery payload for tests."""
    return ZeroconfServiceInfo(
        ip_address=ip_address(host),
        ip_addresses=[ip_address(host)],
        port=80,
        hostname="ave-ws.local.",
        type="_workstation._tcp.local.",
        name="ave-ws._workstation._tcp.local.",
        properties={},
    )


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """Test successful user-initiated config flow."""
    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
        new=AsyncMock(
            return_value={
                "title": "AVE webserver aa:bb:cc:dd:ee:ff",
                "mac_address": "aa:bb:cc:dd:ee:ff",
            }
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        assert result.get("type") is data_entry_flow.FlowResultType.FORM
        assert result.get("step_id") == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MOCK_USER_INPUT,
        )

    assert result.get("type") is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result.get("title") == "AVE webserver aa:bb:cc:dd:ee:ff"
    assert result.get("data") == MOCK_USER_INPUT


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    """Test user flow cannot_connect handling."""
    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
        new=AsyncMock(side_effect=CannotConnect),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        assert result.get("type") is data_entry_flow.FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MOCK_USER_INPUT,
        )

    assert result.get("type") is data_entry_flow.FlowResultType.FORM
    assert result.get("step_id") == "user"
    assert result.get("errors") == {"base": "cannot_connect"}


async def test_zeroconf_confirm_and_configure(hass: HomeAssistant) -> None:
    """Test zeroconf discovery confirm -> configure -> create entry path."""
    discovery_info = _build_discovery_info()

    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
        new=AsyncMock(
            return_value={
                "title": "AVE webserver aa:bb:cc:dd:ee:ff",
                "mac_address": "aa:bb:cc:dd:ee:ff",
            }
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=discovery_info,
        )
        assert result.get("type") is data_entry_flow.FlowResultType.FORM
        assert result.get("step_id") == "zeroconf_confirm"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )
        assert result.get("type") is data_entry_flow.FlowResultType.FORM
        assert result.get("step_id") == "zeroconf_configure"

        user_input = dict(MOCK_USER_INPUT)
        user_input[CONF_IP_ADDRESS] = "192.168.1.20"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=user_input,
        )

    assert result.get("type") is data_entry_flow.FlowResultType.CREATE_ENTRY
    created_data = result.get("data")
    assert isinstance(created_data, dict)
    assert created_data[CONF_IP_ADDRESS] == "192.168.1.20"


async def test_reconfigure_flow_updates_entry(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Test reconfigure flow updates entry data and aborts successfully."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch.object(
            hass.config_entries, "async_reload", new=AsyncMock(return_value=True)
        ),
        patch(
            "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
            new=AsyncMock(
                return_value={"title": "AVE webserver aa:bb", "mac_address": "aa:bb"}
            ),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": mock_config_entry.entry_id,
            },
        )
        assert result.get("type") is data_entry_flow.FlowResultType.FORM
        assert result.get("step_id") == "reconfigure"

        new_data = dict(MOCK_USER_INPUT)
        new_data[CONF_IP_ADDRESS] = "192.168.1.55"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=new_data,
        )

    assert result.get("type") is data_entry_flow.FlowResultType.ABORT
    assert result.get("reason") == "reconfigure_successful"
    assert mock_config_entry.data[CONF_IP_ADDRESS] == "192.168.1.55"


async def test_user_flow_aborts_on_duplicate_unique_id(hass: HomeAssistant) -> None:
    """Test user flow aborts if unique ID is already configured."""
    existing_data = dict(MOCK_USER_INPUT)
    existing_data[CONF_IP_ADDRESS] = "192.168.1.99"
    existing_entry = MockConfigEntry(
        domain=DOMAIN,
        title="AVE webserver aa:bb:cc:dd:ee:ff",
        data=existing_data,
        unique_id="aa:bb:cc:dd:ee:ff",
    )
    existing_entry.add_to_hass(hass)

    async def _validate_with_unique_id(self, _user_input, require_mac_address=False):
        del require_mac_address
        await self.async_set_unique_id("aa:bb:cc:dd:ee:ff")
        return {
            "title": "AVE webserver aa:bb:cc:dd:ee:ff",
            "mac_address": "aa:bb:cc:dd:ee:ff",
        }

    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
        new=_validate_with_unique_id,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MOCK_USER_INPUT,
        )

    assert result.get("type") is data_entry_flow.FlowResultType.ABORT
    assert result.get("reason") == "already_configured"


async def test_user_flow_invalid_auth_error(hass: HomeAssistant) -> None:
    """Test user flow returns invalid_auth error when validation fails auth."""
    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
        new=AsyncMock(side_effect=InvalidAuth),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MOCK_USER_INPUT,
        )

    assert result.get("type") is data_entry_flow.FlowResultType.FORM
    assert result.get("errors") == {"base": "invalid_auth"}


async def test_user_flow_unknown_error(hass: HomeAssistant) -> None:
    """Test user flow returns unknown error on unexpected exceptions."""
    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MOCK_USER_INPUT,
        )

    assert result.get("type") is data_entry_flow.FlowResultType.FORM
    assert result.get("errors") == {"base": "unknown"}


async def test_zeroconf_abort_cannot_connect(hass: HomeAssistant) -> None:
    """Test zeroconf flow aborts with cannot_connect."""
    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
        new=AsyncMock(side_effect=CannotConnect),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_build_discovery_info(),
        )

    assert result.get("type") is data_entry_flow.FlowResultType.ABORT
    assert result.get("reason") == "cannot_connect"


async def test_zeroconf_abort_not_ave_webserver(hass: HomeAssistant) -> None:
    """Test zeroconf flow aborts when no AVE MAC is found."""
    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
        new=AsyncMock(side_effect=MacAddressNotFound),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_build_discovery_info(),
        )

    assert result.get("type") is data_entry_flow.FlowResultType.ABORT
    assert result.get("reason") == "not_ave_webserver"


async def test_zeroconf_abort_already_in_progress(hass: HomeAssistant) -> None:
    """Test zeroconf flow converts already_in_progress into abort result."""
    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
        new=AsyncMock(side_effect=data_entry_flow.AbortFlow("already_in_progress")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_build_discovery_info(),
        )

    assert result.get("type") is data_entry_flow.FlowResultType.ABORT
    assert result.get("reason") == "already_in_progress"


async def test_zeroconf_reraises_unhandled_abortflow(hass: HomeAssistant) -> None:
    """Test zeroconf flow re-raises AbortFlow reasons it does not handle."""
    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
        new=AsyncMock(side_effect=data_entry_flow.AbortFlow("different_reason")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_build_discovery_info(),
        )

    assert result.get("type") is data_entry_flow.FlowResultType.ABORT
    assert result.get("reason") == "different_reason"


async def test_zeroconf_abort_unknown_on_unexpected_error(hass: HomeAssistant) -> None:
    """Test zeroconf flow aborts unknown on unexpected exceptions."""
    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_build_discovery_info(),
        )

    assert result.get("type") is data_entry_flow.FlowResultType.ABORT
    assert result.get("reason") == "unknown"


async def test_zeroconf_legacy_entry_adoption_updates_entry(
    hass: HomeAssistant,
) -> None:
    """Test zeroconf adopts legacy entry with matching MAC and updates host."""
    legacy_data = dict(MOCK_USER_INPUT)
    legacy_data[CONF_IP_ADDRESS] = "192.168.1.9"
    legacy_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Legacy AVE",
        data=legacy_data,
        unique_id=None,
    )
    legacy_entry.add_to_hass(hass)

    mock_legacy_webserver = AsyncMock()
    mock_legacy_webserver.tryget_mac_address = AsyncMock(
        return_value="AA:BB:CC:DD:EE:FF"
    )

    with (
        patch(
            "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
            new=AsyncMock(
                return_value={
                    "title": "AVE webserver aa:bb:cc:dd:ee:ff",
                    "mac_address": "aa:bb:cc:dd:ee:ff",
                }
            ),
        ),
        patch(
            "custom_components.ave_dominaplus.config_flow.AveWebServer",
            return_value=mock_legacy_webserver,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_build_discovery_info("192.168.1.20"),
        )

    assert result.get("type") is data_entry_flow.FlowResultType.ABORT
    assert result.get("reason") == "already_configured"
    assert legacy_entry.unique_id == "aa:bb:cc:dd:ee:ff"
    assert legacy_entry.data[CONF_IP_ADDRESS] == "192.168.1.20"
    assert legacy_entry.title == "AVE webserver aa:bb:cc:dd:ee:ff"


async def test_zeroconf_configure_abort_already_in_progress(
    hass: HomeAssistant,
) -> None:
    """Test zeroconf configure step aborts when setup is already in progress."""
    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
        new=AsyncMock(
            side_effect=[
                {
                    "title": "AVE webserver aa:bb:cc:dd:ee:ff",
                    "mac_address": "aa:bb:cc:dd:ee:ff",
                },
                data_entry_flow.AbortFlow("already_in_progress"),
            ]
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_build_discovery_info(),
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MOCK_USER_INPUT,
        )

    assert result.get("type") is data_entry_flow.FlowResultType.ABORT
    assert result.get("reason") == "already_in_progress"


async def test_zeroconf_configure_reraises_unhandled_abortflow(
    hass: HomeAssistant,
) -> None:
    """Test zeroconf configure re-raises AbortFlow reasons it does not handle."""
    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
        new=AsyncMock(
            side_effect=[
                {
                    "title": "AVE webserver aa:bb:cc:dd:ee:ff",
                    "mac_address": "aa:bb:cc:dd:ee:ff",
                },
                data_entry_flow.AbortFlow("different_reason"),
            ]
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_build_discovery_info(),
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MOCK_USER_INPUT,
        )

    assert result.get("type") is data_entry_flow.FlowResultType.ABORT
    assert result.get("reason") == "different_reason"


async def test_zeroconf_configure_invalid_auth_error(hass: HomeAssistant) -> None:
    """Test zeroconf configure step shows invalid_auth on auth failures."""
    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
        new=AsyncMock(
            side_effect=[
                {
                    "title": "AVE webserver aa:bb:cc:dd:ee:ff",
                    "mac_address": "aa:bb:cc:dd:ee:ff",
                },
                InvalidAuth,
            ]
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_build_discovery_info(),
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MOCK_USER_INPUT,
        )

    assert result.get("type") is data_entry_flow.FlowResultType.FORM
    assert result.get("step_id") == "zeroconf_configure"
    assert result.get("errors") == {"base": "invalid_auth"}


async def test_reconfigure_flow_cannot_connect_error(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Test reconfigure flow returns cannot_connect error when validation fails."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
        new=AsyncMock(side_effect=CannotConnect),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": mock_config_entry.entry_id,
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MOCK_USER_INPUT,
        )

    assert result.get("type") is data_entry_flow.FlowResultType.FORM
    assert result.get("step_id") == "reconfigure"
    assert result.get("errors") == {"base": "cannot_connect"}


def _new_flow(hass: HomeAssistant) -> AveWsConfigFlow:
    """Create a flow instance bound to Home Assistant for direct method tests."""
    flow = AveWsConfigFlow()
    flow.hass = hass
    return flow


async def test_zeroconf_confirm_unknown_without_discovery_context(
    hass: HomeAssistant,
) -> None:
    """Test zeroconf confirm aborts unknown when discovery context is missing."""
    result = await _new_flow(hass).async_step_zeroconf_confirm()
    assert result.get("type") is data_entry_flow.FlowResultType.ABORT
    assert result.get("reason") == "unknown"


async def test_zeroconf_configure_unknown_without_discovery_context(
    hass: HomeAssistant,
) -> None:
    """Test zeroconf configure aborts unknown when discovery context is missing."""
    result = await _new_flow(hass).async_step_zeroconf_configure(MOCK_USER_INPUT)
    assert result.get("type") is data_entry_flow.FlowResultType.ABORT
    assert result.get("reason") == "unknown"


async def test_zeroconf_configure_cannot_connect_error(hass: HomeAssistant) -> None:
    """Test zeroconf configure shows cannot_connect error."""
    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
        new=AsyncMock(
            side_effect=[
                {
                    "title": "AVE webserver aa:bb:cc:dd:ee:ff",
                    "mac_address": "aa:bb:cc:dd:ee:ff",
                },
                CannotConnect,
            ]
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_build_discovery_info(),
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MOCK_USER_INPUT,
        )

    assert result.get("type") is data_entry_flow.FlowResultType.FORM
    assert result.get("errors") == {"base": "cannot_connect"}


async def test_zeroconf_configure_not_ave_webserver_error(
    hass: HomeAssistant,
) -> None:
    """Test zeroconf configure shows not_ave_webserver error."""
    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
        new=AsyncMock(
            side_effect=[
                {
                    "title": "AVE webserver aa:bb:cc:dd:ee:ff",
                    "mac_address": "aa:bb:cc:dd:ee:ff",
                },
                MacAddressNotFound,
            ]
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_build_discovery_info(),
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MOCK_USER_INPUT,
        )

    assert result.get("type") is data_entry_flow.FlowResultType.FORM
    assert result.get("errors") == {"base": "not_ave_webserver"}


async def test_zeroconf_configure_unknown_error(hass: HomeAssistant) -> None:
    """Test zeroconf configure maps unexpected exceptions to unknown error."""
    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
        new=AsyncMock(
            side_effect=[
                {
                    "title": "AVE webserver aa:bb:cc:dd:ee:ff",
                    "mac_address": "aa:bb:cc:dd:ee:ff",
                },
                RuntimeError("boom"),
            ]
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_build_discovery_info(),
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MOCK_USER_INPUT,
        )

    assert result.get("type") is data_entry_flow.FlowResultType.FORM
    assert result.get("errors") == {"base": "unknown"}


async def test_reconfigure_flow_invalid_auth_error(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Test reconfigure flow returns invalid_auth error."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
        new=AsyncMock(side_effect=InvalidAuth),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": mock_config_entry.entry_id,
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MOCK_USER_INPUT,
        )

    assert result.get("type") is data_entry_flow.FlowResultType.FORM
    assert result.get("errors") == {"base": "invalid_auth"}


async def test_reconfigure_flow_unknown_error(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Test reconfigure flow returns unknown error on unexpected exceptions."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWsConfigFlow.validate_input",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": mock_config_entry.entry_id,
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MOCK_USER_INPUT,
        )

    assert result.get("type") is data_entry_flow.FlowResultType.FORM
    assert result.get("errors") == {"base": "unknown"}


async def test_validate_input_cannot_connect_on_900(hass: HomeAssistant) -> None:
    """Test validate_input raises CannotConnect when bridge response is 900."""
    flow = _new_flow(hass)
    mock_webserver = AsyncMock()
    mock_webserver.get_device_list_bridge = AsyncMock(return_value=(900, ""))

    with (
        patch(
            "custom_components.ave_dominaplus.config_flow.AveWebServer",
            return_value=mock_webserver,
        ),
        pytest.raises(CannotConnect),
    ):
        await flow.validate_input(MOCK_USER_INPUT)


async def test_validate_input_cannot_connect_on_non_200(hass: HomeAssistant) -> None:
    """Test validate_input raises CannotConnect when bridge response is not 200."""
    flow = _new_flow(hass)
    mock_webserver = AsyncMock()
    mock_webserver.get_device_list_bridge = AsyncMock(return_value=(500, ""))

    with (
        patch(
            "custom_components.ave_dominaplus.config_flow.AveWebServer",
            return_value=mock_webserver,
        ),
        pytest.raises(CannotConnect),
    ):
        await flow.validate_input(MOCK_USER_INPUT)


async def test_validate_input_requires_mac_for_discovery(hass: HomeAssistant) -> None:
    """Test validate_input raises MacAddressNotFound when discovery requires MAC."""
    flow = _new_flow(hass)
    mock_webserver = AsyncMock()
    mock_webserver.get_device_list_bridge = AsyncMock(return_value=(200, "ok"))

    with (
        patch(
            "custom_components.ave_dominaplus.config_flow.AveWebServer",
            return_value=mock_webserver,
        ),
        patch.object(flow, "_configure_unique_id", new=AsyncMock(return_value="")),
        pytest.raises(MacAddressNotFound),
    ):
        await flow.validate_input(MOCK_USER_INPUT, require_mac_address=True)


async def test_validate_input_returns_with_empty_mac_when_not_required(
    hass: HomeAssistant,
) -> None:
    """Test validate_input succeeds with empty MAC when discovery requirement is disabled."""
    flow = _new_flow(hass)
    mock_webserver = AsyncMock()
    mock_webserver.get_device_list_bridge = AsyncMock(return_value=(200, "ok"))

    with (
        patch(
            "custom_components.ave_dominaplus.config_flow.AveWebServer",
            return_value=mock_webserver,
        ),
        patch.object(flow, "_configure_unique_id", new=AsyncMock(return_value="")),
    ):
        result = await flow.validate_input(MOCK_USER_INPUT, require_mac_address=False)

    assert result == {"title": "AVE webserver ", "mac_address": ""}


async def test_configure_unique_id_returns_empty_when_mac_missing(
    hass: HomeAssistant,
) -> None:
    """Test _configure_unique_id returns empty string when no MAC is available."""
    flow = _new_flow(hass)
    mock_webserver = AsyncMock()
    mock_webserver.tryget_mac_address = AsyncMock(return_value=None)

    with patch.object(flow, "async_set_unique_id", new=AsyncMock()) as set_unique_id:
        assert await flow._configure_unique_id(mock_webserver) == ""
        set_unique_id.assert_not_awaited()


async def test_configure_unique_id_sets_unique_id_from_mac(hass: HomeAssistant) -> None:
    """Test _configure_unique_id formats MAC and sets flow unique ID."""
    flow = _new_flow(hass)
    mock_webserver = AsyncMock()
    mock_webserver.tryget_mac_address = AsyncMock(return_value="AA-BB-CC-DD-EE-FF")

    with patch.object(flow, "async_set_unique_id", new=AsyncMock()) as set_unique_id:
        mac = await flow._configure_unique_id(mock_webserver)

    assert mac == "aa:bb:cc:dd:ee:ff"
    set_unique_id.assert_awaited_once_with("aa:bb:cc:dd:ee:ff")


async def test_adopt_legacy_entry_skips_non_legacy_entries(hass: HomeAssistant) -> None:
    """Test legacy adoption skips entries that already have a unique_id."""
    flow = _new_flow(hass)
    existing_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Configured",
        data=MOCK_USER_INPUT,
        unique_id="aa:bb:cc:dd:ee:ff",
    )
    existing_entry.add_to_hass(hass)

    result = await flow._async_adopt_legacy_entry_by_mac(
        discovered_mac="aa:bb:cc:dd:ee:ff",
        discovered_host="192.168.1.20",
    )
    assert result is None


async def test_adopt_legacy_entry_skips_missing_host(hass: HomeAssistant) -> None:
    """Test legacy adoption skips entries without a valid IP host field."""
    flow = _new_flow(hass)
    legacy_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Legacy",
        data={"get_entities_names": True},
        unique_id=None,
    )
    legacy_entry.add_to_hass(hass)

    result = await flow._async_adopt_legacy_entry_by_mac(
        discovered_mac="aa:bb:cc:dd:ee:ff",
        discovered_host="192.168.1.20",
    )
    assert result is None


async def test_adopt_legacy_entry_skips_when_mac_unavailable(
    hass: HomeAssistant,
) -> None:
    """Test legacy adoption skips entries when legacy MAC cannot be fetched."""
    flow = _new_flow(hass)
    legacy_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Legacy",
        data=MOCK_USER_INPUT,
        unique_id=None,
    )
    legacy_entry.add_to_hass(hass)

    mock_legacy_webserver = AsyncMock()
    mock_legacy_webserver.tryget_mac_address = AsyncMock(return_value=None)

    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWebServer",
        return_value=mock_legacy_webserver,
    ):
        result = await flow._async_adopt_legacy_entry_by_mac(
            discovered_mac="aa:bb:cc:dd:ee:ff",
            discovered_host="192.168.1.20",
        )
    assert result is None


async def test_adopt_legacy_entry_skips_when_mac_mismatch(hass: HomeAssistant) -> None:
    """Test legacy adoption skips entries when discovered and legacy MAC differ."""
    flow = _new_flow(hass)
    legacy_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Legacy",
        data=MOCK_USER_INPUT,
        unique_id=None,
    )
    legacy_entry.add_to_hass(hass)

    mock_legacy_webserver = AsyncMock()
    mock_legacy_webserver.tryget_mac_address = AsyncMock(
        return_value="11:22:33:44:55:66"
    )

    with patch(
        "custom_components.ave_dominaplus.config_flow.AveWebServer",
        return_value=mock_legacy_webserver,
    ):
        result = await flow._async_adopt_legacy_entry_by_mac(
            discovered_mac="aa:bb:cc:dd:ee:ff",
            discovered_host="192.168.1.20",
        )
    assert result is None
