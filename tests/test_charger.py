"""Tests for how the charger reads its units, writes, and derives state."""

from __future__ import annotations

from datetime import timedelta

import pytest
from modbus_connection.mock import MockModbusConnection, WriteEvent

from custom_components.alfen_modbus.alfen import AlfenCharger, Phases

from .registers import STATION_UNIT, f32, f64, seed_socket, seed_station, text, u32


@pytest.fixture(name="connection")
def connection_fixture() -> MockModbusConnection:
    """A mock link carrying a two-socket station."""
    connection = MockModbusConnection()
    seed_station(connection, sockets=2)
    seed_socket(connection, 1)
    seed_socket(connection, 2)
    return connection


def writes(connection: MockModbusConnection, unit: int) -> list[WriteEvent]:
    """Collect every write a unit receives."""
    events: list[WriteEvent] = []
    connection.for_unit(unit).on_write(events.append)
    return events


# -- read planning -----------------------------------------------------------


async def test_reads_each_declared_block_once(
    connection: MockModbusConnection,
) -> None:
    """Each declared readable range becomes its own block read."""
    charger = AlfenCharger(connection, socket_numbers=(1,), read_scn=True)

    await charger.async_update()

    station = connection.for_unit(STATION_UNIT).read_events
    assert [(event.address, event.count) for event in station] == [
        (100, 79),  # product identification
        (1100, 6),  # station status
        (1400, 5),  # SCN identity
    ]


async def test_splits_the_meter_block_at_the_read_ceiling(
    connection: MockModbusConnection,
) -> None:
    """The 126-register meter map cannot be one FC03, so the planner splits it.

    It splits between fields rather than through one: the trailing FLOAT64 at
    422-425 becomes its own read instead of being cut at 424, which is where
    the pre-migration single ``read(300, 125)`` stopped.
    """
    charger = AlfenCharger(connection, socket_numbers=(1,))

    await charger.async_update()

    socket = connection.for_unit(1).read_events
    assert [(event.address, event.count) for event in socket] == [
        (300, 122),
        (422, 4),
        (1200, 16),
    ]
    assert all(event.count <= 125 for event in socket)


async def test_addresses_every_unit_over_one_connection(
    connection: MockModbusConnection,
) -> None:
    """Station and sockets are separate units whose registers do not collide."""
    connection.for_unit(1).holding[306] = f32(230.0)
    connection.for_unit(2).holding[306] = f32(240.0)
    charger = AlfenCharger(connection, socket_numbers=(1, 2))

    await charger.async_update()

    assert charger.sockets[1].meter.voltage_l1_n == pytest.approx(230.0)
    assert charger.sockets[2].meter.voltage_l1_n == pytest.approx(240.0)
    assert connection.for_unit(STATION_UNIT).read_events
    assert connection.for_unit(1).read_events
    assert connection.for_unit(2).read_events


async def test_skips_a_socket_the_station_does_not_report(
    connection: MockModbusConnection,
) -> None:
    """Socket 2 is a unit that does not answer on a single-socket station."""
    seed_station(connection, sockets=1)
    charger = AlfenCharger(connection, socket_numbers=(1, 2))

    await charger.async_update()

    assert not connection.for_unit(2).read_events
    assert charger.sockets[2].meter.voltage_l1_n is None


async def test_every_field_fits_inside_a_declared_readable_range(
    connection: MockModbusConnection,
) -> None:
    """A declared map must contain every field, or the planner refuses to plan.

    Since 4.4 a field the map cannot hold raises at plan-build time rather than
    being read as its own block the station would refuse. Every component here
    declares ``register_ranges``, so this checks the map against where the
    fields actually resolve — and names the offender when it does not.
    """
    charger = AlfenCharger(connection, socket_numbers=(1,), read_scn=True)
    components = [
        charger.station.product,
        charger.station.status,
        charger.station.scn,
        charger.sockets[1].meter,
        charger.sockets[1].status,
    ]

    for component in components:
        ranges = component.register_ranges
        assert ranges is not None
        for name, resolved in component.resolved_fields.items():
            last = resolved.address + resolved.count - 1
            assert any(
                low <= resolved.address and last <= high for low, high in ranges
            ), (
                f"{type(component).__name__}.{name} at "
                f"{resolved.address}-{last} is outside {ranges}"
            )


async def test_raw_registers_are_keyed_by_unit(
    connection: MockModbusConnection,
) -> None:
    """A raw dump keeps each unit's registers apart, address alone does not."""
    charger = AlfenCharger(connection, socket_numbers=(1, 2))

    raw = await charger.async_read_raw()

    assert set(raw) == {"station/holding", "socket_1/holding", "socket_2/holding"}
    assert 300 in raw["socket_1/holding"]
    assert 300 in raw["socket_2/holding"]
    assert 300 not in raw["station/holding"]


async def test_a_raw_dump_refreshes_without_notifying(
    connection: MockModbusConnection,
) -> None:
    """Downloading diagnostics is not a poll, so no listener may see it."""
    charger = AlfenCharger(connection, socket_numbers=(1,))
    fired: list[str] = []
    charger.station.status.add_update_listener(lambda: fired.append("station.status"))
    charger.sockets[1].meter.add_update_listener(lambda: fired.append("socket_1.meter"))

    await charger.async_read_raw()

    assert not fired
    assert charger.sockets[1].meter.voltage_l1_n == pytest.approx(232.5)


# -- writes ------------------------------------------------------------------


async def test_writes_the_phase_mode_as_fc16(
    connection: MockModbusConnection,
) -> None:
    """Register 1215 is one word, but the station only honours FC16."""
    charger = AlfenCharger(connection, socket_numbers=(1,))
    events = writes(connection, 1)

    await charger.sockets[1].async_set_phases(Phases.ONE)

    assert events == [WriteEvent("holding", 1215, [1], 0x10)]


async def test_rejects_a_phase_count_the_spec_does_not_define(
    connection: MockModbusConnection,
) -> None:
    """Only 1 and 3 are phase modes; the field's validator refuses the rest."""
    charger = AlfenCharger(connection, socket_numbers=(1,))
    events = writes(connection, 1)

    with pytest.raises(ValueError):
        await charger.sockets[1].status.write("phases", 2)

    assert events == []


async def test_writes_the_setpoint_over_both_registers(
    connection: MockModbusConnection,
) -> None:
    """A FLOAT32 setpoint spans 1210-1211 and must go out in one request."""
    charger = AlfenCharger(connection, socket_numbers=(1,))
    events = writes(connection, 1)

    await charger.sockets[1].async_set_max_current(10.0)

    assert events == [WriteEvent("holding", 1210, f32(10.0), 0x10)]


async def test_writes_reach_the_socket_that_was_addressed(
    connection: MockModbusConnection,
) -> None:
    """A per-socket write goes to that socket's unit, not the station's."""
    charger = AlfenCharger(connection, socket_numbers=(1, 2))
    socket_1 = writes(connection, 1)
    socket_2 = writes(connection, 2)

    await charger.sockets[2].async_set_max_current(8.0)

    assert socket_1 == []
    assert socket_2 == [WriteEvent("holding", 1210, f32(8.0), 0x10)]


# -- the setpoint watchdog ---------------------------------------------------


async def test_renews_a_setpoint_about_to_lapse(
    connection: MockModbusConnection,
) -> None:
    """The station reverts to its safe current unless the setpoint is rewritten."""
    connection.for_unit(1).holding[1208] = u32(20)
    charger = AlfenCharger(connection, socket_numbers=(1,))
    await charger.async_update()
    events = writes(connection, 1)

    await charger.async_renew_setpoints(within=40)

    assert events == [WriteEvent("holding", 1210, f32(16.0), 0x10)]


async def test_leaves_a_setpoint_with_time_left_alone(
    connection: MockModbusConnection,
) -> None:
    """No write while the validity window is comfortably open."""
    charger = AlfenCharger(connection, socket_numbers=(1,))
    await charger.async_update()
    events = writes(connection, 1)

    await charger.async_renew_setpoints(within=40)

    assert events == []


async def test_never_renews_a_setpoint_the_station_never_got(
    connection: MockModbusConnection,
) -> None:
    """A station with no setpoint reads back zero; writing it back would pin
    the socket at no current instead of keeping a setpoint alive."""
    seed_socket(connection, 1, max_current=0.0, valid_time=0)
    charger = AlfenCharger(connection, socket_numbers=(1,))
    await charger.async_update()
    events = writes(connection, 1)

    await charger.async_renew_setpoints(within=40)

    assert events == []


# -- derived session state ---------------------------------------------------


async def test_tracks_a_charge_session(connection: MockModbusConnection) -> None:
    """Session energy and duration count from when current started flowing."""
    seed_socket(connection, 1, mode3_state="B2", delivered=1000.0)
    charger = AlfenCharger(connection, socket_numbers=(1,))
    await charger.async_update()
    assert charger.sockets[1].session_energy is None

    # the vehicle starts drawing current
    holding = connection.for_unit(1).holding
    holding[1201] = text("C2", 5)
    await charger.async_update()
    assert charger.sockets[1].session_energy == 0.0

    # a minute and 500 Wh later
    holding[374] = f64(1500.0)
    connection.for_unit(STATION_UNIT).holding[172] = 31  # the clock's minute
    await charger.async_update()

    assert charger.sockets[1].session_energy == pytest.approx(500.0)
    assert charger.sockets[1].session_duration == timedelta(minutes=1)


async def test_a_finished_session_keeps_its_final_figures(
    connection: MockModbusConnection,
) -> None:
    """Unplugging freezes the session totals rather than clearing them."""
    seed_socket(connection, 1, mode3_state="C2", delivered=1000.0)
    charger = AlfenCharger(connection, socket_numbers=(1,))
    await charger.async_update()
    holding = connection.for_unit(1).holding
    holding[374] = f64(1200.0)
    await charger.async_update()

    holding[1201] = text("A", 5)  # unplugged
    await charger.async_update()

    assert charger.sockets[1].session_energy == pytest.approx(200.0)


async def test_a_new_session_restarts_the_totals(
    connection: MockModbusConnection,
) -> None:
    """Plugging back in re-snapshots the meter instead of continuing."""
    seed_socket(connection, 1, mode3_state="C2", delivered=1000.0)
    charger = AlfenCharger(connection, socket_numbers=(1,))
    holding = connection.for_unit(1).holding
    await charger.async_update()
    holding[1201] = text("A", 5)
    holding[374] = f64(1200.0)
    await charger.async_update()

    holding[1201] = text("C2", 5)
    await charger.async_update()

    assert charger.sockets[1].session_energy == 0.0
