"""Fixtures for the Home Assistant layer tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from modbus_connection.mock import MockModbusConnection
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alfen_modbus.const import (
    CONF_MODBUS_ADDRESS,
    CONF_READ_SCN,
    CONF_READ_SOCKET2,
    DOMAIN,
)

from .registers import STATION_UNIT, seed_socket, seed_station


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    """Let Home Assistant load this custom integration."""
    yield


@pytest.fixture(name="mock_connection")
def mock_connection_fixture() -> MockModbusConnection:
    """An in-memory link carrying a one-socket station."""
    connection = MockModbusConnection()
    seed_station(connection)
    seed_socket(connection, 1)
    return connection


@pytest.fixture(name="config_entry")
def config_entry_fixture(hass: HomeAssistant) -> MockConfigEntry:
    """A config entry for a one-socket station."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="alfen",
        unique_id="192.168.1.50",
        data={
            CONF_NAME: "alfen",
            CONF_HOST: "192.168.1.50",
            CONF_PORT: 502,
            CONF_MODBUS_ADDRESS: STATION_UNIT,
            CONF_READ_SCN: False,
            CONF_READ_SOCKET2: False,
            CONF_SCAN_INTERVAL: 30,
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture(name="setup_integration")
async def setup_integration_fixture(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_connection: MockModbusConnection,
) -> MockConfigEntry:
    """Set the entry up over the in-memory link."""
    with patch(
        "custom_components.alfen_modbus.build_connection", return_value=mock_connection
    ):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    return config_entry
