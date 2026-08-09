"""Tests for the Alfen device library against the in-memory mock backend."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from modbus_connection.mock import MockModbusConnection

from custom_components.alfen_modbus.alfen import (
    AlfenCharger,
    MeterState,
    MeterType,
    Phases,
    async_read_product,
)

from .registers import STATION_UNIT, seed_socket, seed_station

CET = timezone(timedelta(minutes=60))


@pytest.fixture(name="connection")
def connection_fixture() -> MockModbusConnection:
    """A mock link carrying a one-socket station."""
    connection = MockModbusConnection()
    seed_station(connection)
    seed_socket(connection, 1)
    return connection


@pytest.fixture(name="charger")
def charger_fixture(connection: MockModbusConnection) -> AlfenCharger:
    """A charger over the seeded link, SCN enabled."""
    return AlfenCharger(connection, socket_numbers=(1, 2), read_scn=True)


async def test_reads_the_station(charger: AlfenCharger) -> None:
    """The station block decodes to identification, status and SCN."""
    await charger.async_update()

    product = charger.station.product
    assert product.name == "Alfen Eve Single Pro-line"
    assert product.manufacturer == "Alfen B.V."
    assert product.modbus_table_version == 3
    assert product.firmware_version == "5.16.0-4095"
    assert product.platform_type == "NG920-60559"
    assert product.serial_number == "ACE0108752"
    assert product.uptime == 3_600_000

    status = charger.station.status
    assert status.max_current == 32.0
    assert status.temperature == 42.5
    assert status.backoffice_connected is True
    assert status.socket_count == 1

    assert charger.station.scn is not None
    assert charger.station.scn.name == "ALF_HBW"
    assert charger.station.scn.socket_count == 4


async def test_assembles_the_station_clock(charger: AlfenCharger) -> None:
    """Six date/time registers plus the offset become one aware datetime."""
    await charger.async_update()

    assert charger.station.time == datetime(2026, 8, 9, 14, 30, 15, tzinfo=CET)
    # booted an hour (the uptime) before the station clock
    assert charger.station.last_boot == datetime(2026, 8, 9, 13, 30, 15, tzinfo=CET)


async def test_reads_the_socket_meter(charger: AlfenCharger) -> None:
    """The meter block decodes, including the energy totals past register 394."""
    await charger.async_update()

    meter = charger.sockets[1].meter
    assert meter.meter_state == MeterState.INITIALISED | MeterState.UPDATED
    assert meter.meter_timestamp == 1500
    assert meter.meter_type is MeterType.TCP_IP

    assert meter.voltage_l1_n == pytest.approx(232.5)
    assert meter.current_sum == pytest.approx(30.6)
    assert meter.frequency == pytest.approx(50.02)
    assert meter.real_power_sum == pytest.approx(6979.0)

    assert meter.real_energy_delivered_sum == pytest.approx(45745.98)
    assert meter.real_energy_consumed_sum == 0.0
    # 394 and 410, not the 392/408 the pre-migration integration read
    assert meter.apparent_energy_l1 == 15542.0
    assert meter.apparent_energy_sum == 46639.0
    assert meter.reactive_energy_l1 == 3024.0
    assert meter.reactive_energy_sum == 9169.0


async def test_reads_the_socket_status(charger: AlfenCharger) -> None:
    """The status block decodes, including the mode 3 state string."""
    await charger.async_update()

    socket = charger.sockets[1]
    assert socket.status.available is True
    assert socket.status.mode3_state == "C2"
    assert socket.status.actual_max_current == 16.0
    assert socket.status.max_current_valid_time == 60
    assert socket.status.max_current == 16.0
    assert socket.status.safe_current == 6.0
    assert socket.status.setpoint_accounted is True
    assert socket.status.phases is Phases.THREE

    assert socket.vehicle_connected is True
    assert socket.charging is True


@pytest.mark.parametrize(
    ("state", "connected", "charging"),
    [
        ("A", False, False),
        ("B1", True, False),
        ("B2", True, False),
        ("C1", True, False),
        ("C2", True, True),
        ("D2", True, True),
        ("E", False, False),
        ("F", False, False),
    ],
)
async def test_derives_vehicle_state(
    connection: MockModbusConnection, state: str, connected: bool, charging: bool
) -> None:
    """Connected and charging come out of the mode 3 state listing."""
    seed_socket(connection, 1, mode3_state=state)
    charger = AlfenCharger(connection)

    await charger.async_update()

    assert charger.sockets[1].vehicle_connected is connected
    assert charger.sockets[1].charging is charging


async def test_unreadable_registers_decode_to_none(
    connection: MockModbusConnection,
) -> None:
    """A station without a meter answers NaN, which reads back as None."""
    holding = connection.for_unit(1).holding
    holding[300] = 0  # meter never initialised
    holding[306] = [0xFFFF, 0xFFFF]  # NaN
    holding[301] = [0xFFFF] * 4
    charger = AlfenCharger(connection)

    await charger.async_update()

    assert charger.sockets[1].meter.meter_state == MeterState(0)
    assert charger.sockets[1].meter.voltage_l1_n is None
    assert charger.sockets[1].meter.meter_timestamp is None


async def test_probe_reads_identification(connection: MockModbusConnection) -> None:
    """A config-flow probe reads the identification block on its own."""
    product = await async_read_product(connection.for_unit(STATION_UNIT))

    assert product.serial_number == "ACE0108752"
