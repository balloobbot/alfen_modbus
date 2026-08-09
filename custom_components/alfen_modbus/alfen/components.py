"""The Alfen NG9xx register map, as typed components.

Addresses and types follow *Modbus Slave TCP/IP — Implementation of Modbus
Slave TCP/IP for Alfen NG9xx platform*, v2.3 (30-10-2020), sections 3.1-3.4.
Everything is a holding register (the station serves FC03/FC06/FC10 only) and
everything is big-endian, so no ``word_order`` appears below.

The three register groups live on **different Modbus units**: the station's
identification, status and SCN registers answer on slave 200, and each socket's
measurement and status registers answer on slave 1 or 2. See ``device.py``.
"""

from __future__ import annotations

from modbus_connection.model import (
    Component,
    FloatField,
    boolean,
    enum,
    flags,
    float32,
    float64,
    integer,
    string,
    uint32,
    uint64,
)

from .enums import MeterState, MeterType, Phases

# "Whenever a register is reserved or not available, the register reply is
# filled with Not a Number (NaN), which is set to 0xFFFF for a 16 bit register"
# (spec §1.2), so every numeric field maps that pattern back to None.
_NAN16 = 0xFFFF
_NAN32 = 0xFFFF_FFFF
_NAN64 = 0xFFFF_FFFF_FFFF_FFFF


def _measurement(address: int, unit: str | None = None) -> FloatField:
    """A FLOAT32 meter reading that reads as None when the meter is absent.

    For a float field ``nan`` only switches the IEEE NaN check on — any value
    does — but it is spelled as the spec's 16-bit NaN pattern to match the
    integer fields, where the value really is the sentinel being matched.
    """
    return float32(address, unit=unit, nan=_NAN16)


def _energy(address: int, unit: str) -> FloatField:
    """A FLOAT64 energy total, four registers wide."""
    return float64(address, unit=unit, nan=_NAN16)


class Product(Component):
    """Station product identification — spec §3.1, registers 100-178."""

    register_ranges = ((100, 178),)

    name = string(100, 17)
    """Model name, e.g. ``Alfen Eve Single Pro-line``."""

    manufacturer = string(117, 5)

    modbus_table_version = integer(122, nan=_NAN16)
    """Version of the register table the station implements."""

    firmware_version = string(123, 17)
    platform_type = string(140, 17)
    serial_number = string(157, 11)

    # The station clock, one SIGNED16 register per field, plus its offset from
    # UTC. ``AlfenStation.time`` assembles them into an aware datetime.
    year = integer(168, nan=_NAN16)
    month = integer(169, nan=_NAN16)
    day = integer(170, nan=_NAN16)
    hour = integer(171, nan=_NAN16)
    minute = integer(172, nan=_NAN16)
    second = integer(173, nan=_NAN16)

    uptime = uint64(174, unit="ms", nan=_NAN64)
    """Milliseconds since the station booted."""

    utc_offset = integer(178, unit="min", nan=_NAN16)


class StationStatus(Component):
    """Station status — spec §3.2, registers 1100-1105."""

    register_ranges = ((1100, 1105),)

    max_current = _measurement(1100, "A")
    """Actual overall max current the station will hand out."""

    temperature = _measurement(1102, "°C")
    """Board temperature; not the ambient temperature."""

    backoffice_connected = boolean(1104, nan=_NAN16)
    """OCPP state: whether the station reaches its back office."""

    socket_count = integer(1105, signed=False, nan=_NAN16)


class Scn(Component):
    """Smart Charging Network identity — spec §3.3, registers 1400-1404.

    The rest of the SCN block (per-phase consumption, max currents and their
    validity timers, 1405-1431) is not modelled: the integration exposes no
    SCN control, and leaving it out keeps this a five-register read.
    """

    register_ranges = ((1400, 1404),)

    name = string(1400, 4)
    socket_count = integer(1404, signed=False, nan=_NAN16)


class SocketMeter(Component):
    """Socket energy measurements — spec §3.4, registers 300-425.

    126 registers: one past the 125-register FC03 ceiling, so this can never be
    a single read. The planner splits it at ``max_span`` without cutting a
    field, into 300-421 and the last FLOAT64 at 422-425.
    """

    register_ranges = ((300, 425),)

    meter_state = flags(300, MeterState, nan=_NAN16)
    meter_timestamp = uint64(301, unit="ms", nan=_NAN64)
    """Milliseconds since the meter's last received measurement."""

    meter_type = enum(305, MeterType, nan=_NAN16)

    voltage_l1_n = _measurement(306, "V")
    voltage_l2_n = _measurement(308, "V")
    voltage_l3_n = _measurement(310, "V")
    voltage_l1_l2 = _measurement(312, "V")
    voltage_l2_l3 = _measurement(314, "V")
    voltage_l3_l1 = _measurement(316, "V")

    current_n = _measurement(318, "A")
    current_l1 = _measurement(320, "A")
    current_l2 = _measurement(322, "A")
    current_l3 = _measurement(324, "A")
    current_sum = _measurement(326, "A")

    power_factor_l1 = _measurement(328)
    power_factor_l2 = _measurement(330)
    power_factor_l3 = _measurement(332)
    power_factor_sum = _measurement(334)

    frequency = _measurement(336, "Hz")

    real_power_l1 = _measurement(338, "W")
    real_power_l2 = _measurement(340, "W")
    real_power_l3 = _measurement(342, "W")
    real_power_sum = _measurement(344, "W")

    apparent_power_l1 = _measurement(346, "VA")
    apparent_power_l2 = _measurement(348, "VA")
    apparent_power_l3 = _measurement(350, "VA")
    apparent_power_sum = _measurement(352, "VA")

    reactive_power_l1 = _measurement(354, "var")
    reactive_power_l2 = _measurement(356, "var")
    reactive_power_l3 = _measurement(358, "var")
    reactive_power_sum = _measurement(360, "var")

    real_energy_delivered_l1 = _energy(362, "Wh")
    real_energy_delivered_l2 = _energy(366, "Wh")
    real_energy_delivered_l3 = _energy(370, "Wh")
    real_energy_delivered_sum = _energy(374, "Wh")

    real_energy_consumed_l1 = _energy(378, "Wh")
    real_energy_consumed_l2 = _energy(382, "Wh")
    real_energy_consumed_l3 = _energy(386, "Wh")
    real_energy_consumed_sum = _energy(390, "Wh")

    apparent_energy_l1 = _energy(394, "VAh")
    apparent_energy_l2 = _energy(398, "VAh")
    apparent_energy_l3 = _energy(402, "VAh")
    apparent_energy_sum = _energy(406, "VAh")

    reactive_energy_l1 = _energy(410, "varh")
    reactive_energy_l2 = _energy(414, "varh")
    reactive_energy_l3 = _energy(418, "varh")
    reactive_energy_sum = _energy(422, "varh")


class SocketStatus(Component):
    """Socket status and transaction registers — spec §3.4, 1200-1215."""

    register_ranges = ((1200, 1215),)

    available = boolean(1200, nan=_NAN16)
    """1: operative, 0: inoperative."""

    mode3_state = string(1201, 5)
    """IEC 61851 mode 3 state, e.g. ``A``, ``B2``, ``C2``."""

    actual_max_current = _measurement(1206, "A")
    """What the socket is actually applying, all setpoints considered."""

    max_current_valid_time = uint32(1208, unit="s", nan=_NAN32)
    """Seconds left before ``max_current`` lapses to the safe current."""

    max_current = float32(1210, unit="A", writable=True, nan=_NAN16)
    """The Modbus setpoint. Two registers, so it writes as FC16 anyway."""

    safe_current = _measurement(1212, "A")
    """Where the socket falls back when the setpoint lapses."""

    setpoint_accounted = boolean(1214, nan=_NAN16)
    """Whether the station is taking ``max_current`` into account."""

    phases = enum(1215, Phases, writable=Phases, force_fc16=True, nan=_NAN16)
    """Charge with 1 or 3 phases.

    A single UNSIGNED16 register, which ``auto`` would write as FC06 — the
    station only honours FC16 here, hence ``force_fc16``. ``writable=Phases``
    doubles as the validator: the spec defines 1 and 3, and nothing else.
    """
