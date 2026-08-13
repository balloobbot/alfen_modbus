"""One failing block must not take the rest of the poll with it.

The station, its sockets and their meters are separate blocks on separate
Modbus units, and a station that is busy or missing the Active Load Balancing
licence refuses one of them while serving the others. Each component is read on
its own so that costs only its own values, and the poll says which ones.
"""

from __future__ import annotations

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from modbus_connection import ModbusConnectionError, ModbusTimeoutError
from modbus_connection.mock import MockModbusConnection
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alfen_modbus.alfen import AlfenCharger

from .registers import STATION_UNIT, f32, seed_socket, seed_station, text

POLLED_UNITS = (STATION_UNIT, 1)


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
    return AlfenCharger(connection, socket_numbers=(1,), read_scn=True)


def reads(connection: MockModbusConnection) -> int:
    """How many blocks the poll has read across every unit it talks to."""
    return sum(len(connection.for_unit(unit).read_events) for unit in POLLED_UNITS)


async def test_a_failed_component_leaves_the_rest_fresh(
    charger: AlfenCharger, connection: MockModbusConnection
) -> None:
    await charger.async_update()
    before = charger.station.product.name

    connection.for_unit(STATION_UNIT).holding[100] = text("Eve Double Pro-line", 17)
    connection.for_unit(STATION_UNIT).holding[1100] = f32(20.0)  # station derates
    connection.for_unit(STATION_UNIT).fail_read(100, ModbusTimeoutError("slow block"))
    report = await charger.async_update()

    assert not report.complete
    assert set(report.failed) == {"station.product"}
    assert isinstance(report.failed["station.product"], ModbusTimeoutError)
    assert {"station.status", "socket_1.meter"} <= report.updated
    assert charger.station.product.name == before  # previous value kept
    assert charger.station.status.max_current == 20.0


async def test_a_socket_that_stops_answering_leaves_the_station_fresh(
    charger: AlfenCharger, connection: MockModbusConnection
) -> None:
    """A socket unit is its own slave id; it can go quiet on a live station."""
    await charger.async_update()

    connection.for_unit(STATION_UNIT).holding[1102] = f32(50.0)  # board warms up
    connection.for_unit(1).fail_requests(ModbusTimeoutError("socket gone quiet"))
    report = await charger.async_update()

    assert set(report.failed) == {"socket_1.meter", "socket_1.status"}
    assert charger.station.status.temperature == 50.0
    assert charger.sockets[1].meter.voltage_l1_n == pytest.approx(232.5)


async def test_listeners_fire_at_the_end_and_only_for_fresh_components(
    charger: AlfenCharger, connection: MockModbusConnection
) -> None:
    await charger.async_update()
    seen: list[int] = []
    charger.station.status.add_update_listener(lambda: seen.append(reads(connection)))
    charger.station.product.add_update_listener(lambda: seen.append(-1))

    connection.for_unit(STATION_UNIT).fail_read(100, ModbusTimeoutError("slow block"))
    for unit in POLLED_UNITS:
        connection.for_unit(unit).read_events.clear()
    await charger.async_update()

    # One notification, after every unit was tried; none for the failure. The
    # station notifies only once the sockets have been read too, so a listener
    # never sees the station ahead of the socket values it is measured against.
    assert seen == [reads(connection)]


@pytest.mark.parametrize("unit", POLLED_UNITS)
async def test_a_dead_link_raises_instead_of_reporting(
    charger: AlfenCharger, connection: MockModbusConnection, unit: int
) -> None:
    await charger.async_update()
    connection.for_unit(unit).fail_requests(ModbusConnectionError("link down"))
    with pytest.raises(ModbusConnectionError):
        await charger.async_update()


async def test_every_component_refreshes_on_a_healthy_charger(
    charger: AlfenCharger,
) -> None:
    report = await charger.async_update()

    assert report.complete
    assert report.failed == {}
    assert report.updated == {
        "station.product",
        "station.status",
        "station.scn",
        "socket_1.meter",
        "socket_1.status",
    }


async def test_a_failed_block_keeps_its_sensors_on_their_previous_values(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_connection: MockModbusConnection,
) -> None:
    """The entities of a refused block stay put; the others still refresh."""
    mock_connection.for_unit(1).fail_read(300, ModbusTimeoutError("slow meter"))
    mock_connection.for_unit(1).holding[1201] = text("B2", 5)

    await setup_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.alfen_mode_3_state").state == "B2"
    assert hass.states.get("sensor.alfen_voltage_l1_n").state == "232.5"


async def test_a_charger_that_answers_nothing_goes_unavailable(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_connection: MockModbusConnection,
) -> None:
    """Containment is not silence: a poll that refreshed nothing has failed."""
    for unit in POLLED_UNITS:
        mock_connection.for_unit(unit).fail_requests(ModbusTimeoutError("no answer"))

    await setup_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.alfen_mode_3_state").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.alfen_voltage_l1_n").state == STATE_UNAVAILABLE
