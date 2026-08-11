"""Tests for the Home Assistant layer."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from modbus_connection import ModbusConnectionError
from modbus_connection.mock import MockModbusConnection, WriteEvent
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alfen_modbus.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .registers import STATION_UNIT, f32


async def test_sets_up_and_polls(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A successful first poll backs entities from every unit."""
    assert setup_integration.state is ConfigEntryState.LOADED

    assert hass.states.get("sensor.alfen_serial").state == "ACE0108752"
    assert hass.states.get("sensor.alfen_board_temperature").state == "42.5"
    assert hass.states.get("sensor.alfen_voltage_l1_n").state == "232.5"
    assert hass.states.get("sensor.alfen_real_energy_delivered_sum").state == "45745.98"
    assert hass.states.get("sensor.alfen_mode_3_state").state == "C2"
    assert hass.states.get("binary_sensor.alfen_car_charging").state == STATE_ON
    assert hass.states.get("number.alfen_max_current_limit_s1").state == "16.0"
    assert hass.states.get("select.alfen_usable_phases1").state == "3 Phases"


async def test_keeps_the_established_unique_ids(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Upgrading must not orphan the entities an install already has."""
    registry = er.async_get(hass)
    for domain, unique_id in (
        ("sensor", "alfen_serial"),
        ("sensor", "alfen_socket_1_VL1-N"),
        ("sensor", "alfen_maxCurrent_socket_1"),
        ("sensor", "alfen_maxCurrentValidTime_socket_1"),
        ("binary_sensor", "alfen_socket_1_carcharging"),
        ("number", "alfen_maxCurrent_socket_1"),
        ("select", "alfen_usephases_S1"),
    ):
        assert registry.async_get_entity_id(domain, "alfen_modbus", unique_id)


async def test_unreachable_station_defers_setup(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_connection: MockModbusConnection,
) -> None:
    """A station that does not answer leaves the entry retrying, not failed."""
    mock_connection.for_unit(STATION_UNIT).fail_requests(ModbusConnectionError())

    with patch(
        "custom_components.alfen_modbus.build_connection", return_value=mock_connection
    ):
        assert not await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_number_writes_the_setpoint(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_connection: MockModbusConnection,
) -> None:
    """Setting the number writes registers 1210-1211 on the socket's unit."""
    events: list[WriteEvent] = []
    mock_connection.for_unit(1).on_write(events.append)

    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: "number.alfen_max_current_limit_s1", "value": 10},
        blocking=True,
    )

    assert events[0] == WriteEvent("holding", 1210, f32(10.0), 0x10)


async def test_number_clamps_to_the_station_limit(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_connection: MockModbusConnection,
) -> None:
    """The slider stops at the station's own max current (register 1100)."""
    state = hass.states.get("number.alfen_max_current_limit_s1")

    assert state.attributes["max"] == 32.0


async def test_select_writes_the_phase_mode_as_fc16(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_connection: MockModbusConnection,
) -> None:
    """Register 1215 is a single word the station only accepts as FC16."""
    events: list[WriteEvent] = []
    mock_connection.for_unit(1).on_write(events.append)

    await hass.services.async_call(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: "select.alfen_usable_phases1", "option": "1 Phase"},
        blocking=True,
    )

    assert events[0] == WriteEvent("holding", 1215, [1], 0x10)


async def test_diagnostics_separate_the_units(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The raw dump is keyed by unit, not by address alone."""
    diagnostics = await async_get_config_entry_diagnostics(hass, setup_integration)

    assert set(diagnostics["registers"]) == {"station/holding", "socket_1/holding"}
    assert diagnostics["entry"]["modbus_address"] == STATION_UNIT


async def test_diagnostics_say_which_field_each_address_is(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The raw dump is addresses; the layout is what makes them readable."""
    diagnostics = await async_get_config_entry_diagnostics(hass, setup_integration)

    layout = diagnostics["layout"]
    assert set(layout) == {"station", "socket_1"}
    assert layout["station"]["Product.serial_number"] == {
        "space": "holding",
        "address": 157,
        "count": 11,
    }
    # The two units both serve register 300, and the layout keeps them apart.
    assert layout["socket_1"]["SocketMeter.meter_state"]["address"] == 300
    assert "SocketMeter.meter_state" not in layout["station"]


@pytest.mark.parametrize(
    "entity_id",
    [
        "sensor.alfen_voltage_l1_n",
        "binary_sensor.alfen_car_charging",
        "number.alfen_max_current_limit_s1",
        "select.alfen_usable_phases1",
    ],
)
async def test_unload(
    hass: HomeAssistant, setup_integration: MockConfigEntry, entity_id: str
) -> None:
    """Unloading tears every platform down and closes the connection."""
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()

    assert setup_integration.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
