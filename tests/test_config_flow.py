"""Tests for the Alfen Modbus config flow."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from modbus_connection import IllegalDataAddressError
from modbus_connection.mock import MockModbusConnection
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alfen_modbus.const import CONF_MODBUS_ADDRESS, DOMAIN

from .registers import STATION_UNIT

USER_INPUT = {
    CONF_NAME: "alfen",
    CONF_HOST: "192.168.1.50",
    CONF_PORT: 502,
    CONF_MODBUS_ADDRESS: STATION_UNIT,
    "read_scn": False,
    "read_socket_2": False,
    "scan_interval": 30,
}


@pytest.fixture(name="probe")
def probe_fixture(mock_connection: MockModbusConnection):
    """Route the config flow's probe at the in-memory station."""
    with patch(
        "custom_components.alfen_modbus.config_flow.build_connection",
        return_value=mock_connection,
    ):
        yield mock_connection


async def test_creates_an_entry(hass: HomeAssistant, probe) -> None:
    """A station that answers its identification block is accepted."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with patch("custom_components.alfen_modbus.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "alfen"
    assert result["data"] == USER_INPUT


async def test_a_station_that_refuses_the_block_cannot_connect(
    hass: HomeAssistant, probe: MockModbusConnection
) -> None:
    """Reading is licensed and off by default, so a refusal is a setup error."""
    probe.for_unit(STATION_UNIT).fail_read(100, IllegalDataAddressError())

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_rejects_an_invalid_host(hass: HomeAssistant, probe) -> None:
    """The host is validated before anything is dialled."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: "invalid host"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_HOST: "invalid_host"}


async def test_rejects_a_host_already_set_up(
    hass: HomeAssistant, config_entry: MockConfigEntry, probe
) -> None:
    """One entry per station."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_HOST: "already_configured"}
