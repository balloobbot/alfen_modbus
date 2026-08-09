"""Seed a mock connection with the registers a real Alfen station serves.

The values come from the bundled simulator, which mirrors an Eve Single Pro-line
with one socket charging at 3 x 10 A.
"""

from __future__ import annotations

import struct

from modbus_connection.mock import MockModbusConnection

STATION_UNIT = 200


def f32(value: float) -> list[int]:
    """A FLOAT32 as two big-endian registers."""
    return list(struct.unpack(">HH", struct.pack(">f", value)))


def f64(value: float) -> list[int]:
    """A FLOAT64 as four big-endian registers."""
    return list(struct.unpack(">HHHH", struct.pack(">d", value)))


def u32(value: int) -> list[int]:
    """An UNSIGNED32 as two big-endian registers."""
    return [value >> 16 & 0xFFFF, value & 0xFFFF]


def u64(value: int) -> list[int]:
    """An UNSIGNED64 as four big-endian registers."""
    return [value >> shift & 0xFFFF for shift in (48, 32, 16, 0)]


def text(value: str, length: int) -> list[int]:
    """A null-padded ASCII string over ``length`` registers."""
    raw = value.encode("ascii").ljust(length * 2, b"\x00")[: length * 2]
    return list(struct.unpack(f">{length}H", raw))


def seed_station(connection: MockModbusConnection, *, sockets: int = 1) -> None:
    """Seed the station unit: identification, status and SCN."""
    holding = connection.for_unit(STATION_UNIT).holding
    holding[100] = text("Alfen Eve Single Pro-line", 17)
    holding[117] = text("Alfen B.V.", 5)
    holding[122] = 3
    holding[123] = text("5.16.0-4095", 17)
    holding[140] = text("NG920-60559", 17)
    holding[157] = text("ACE0108752", 11)
    holding[168] = [2026, 8, 9, 14, 30, 15]  # year, month, day, hour, minute, second
    holding[174] = u64(3_600_000)  # up one hour
    holding[178] = 60  # UTC+01:00

    holding[1100] = f32(32.0)
    holding[1102] = f32(42.5)
    holding[1104] = 1
    holding[1105] = sockets

    holding[1400] = text("ALF_HBW", 4)
    holding[1404] = 4


def seed_socket(
    connection: MockModbusConnection,
    unit: int,
    *,
    mode3_state: str = "C2",
    delivered: float = 45745.98,
    max_current: float = 16.0,
    valid_time: int = 60,
    phases: int = 3,
) -> None:
    """Seed one socket unit: its meter block and its status block."""
    holding = connection.for_unit(unit).holding
    holding[300] = 0b0011  # initialised | updated
    holding[301] = u64(1500)
    holding[305] = 1  # TCP/IP meter

    holding[306] = f32(232.5)
    holding[308] = f32(231.8)
    holding[310] = f32(233.2)
    holding[312] = f32(401.2)
    holding[314] = f32(400.8)
    holding[316] = f32(402.1)

    holding[318] = f32(0.12)
    holding[320] = f32(10.2)
    holding[322] = f32(10.1)
    holding[324] = f32(10.3)
    holding[326] = f32(30.6)

    holding[328] = f32(0.98)
    holding[330] = f32(0.97)
    holding[332] = f32(0.98)
    holding[334] = f32(0.98)

    holding[336] = f32(50.02)

    holding[338] = f32(2325.0)
    holding[340] = f32(2298.0)
    holding[342] = f32(2356.0)
    holding[344] = f32(6979.0)

    holding[346] = f32(2372.0)
    holding[348] = f32(2348.0)
    holding[350] = f32(2404.0)
    holding[352] = f32(7124.0)

    holding[354] = f32(465.0)
    holding[356] = f32(502.0)
    holding[358] = f32(454.0)
    holding[360] = f32(1421.0)

    holding[362] = f64(15234.67)
    holding[366] = f64(15198.42)
    holding[370] = f64(15312.89)
    holding[374] = f64(delivered)

    holding[378] = f64(0.0)
    holding[382] = f64(0.0)
    holding[386] = f64(0.0)
    holding[390] = f64(0.0)

    holding[394] = f64(15542.0)
    holding[398] = f64(15485.0)
    holding[402] = f64(15612.0)
    holding[406] = f64(46639.0)

    holding[410] = f64(3024.0)
    holding[414] = f64(3189.0)
    holding[418] = f64(2956.0)
    holding[422] = f64(9169.0)

    holding[1200] = 1
    holding[1201] = text(mode3_state, 5)
    holding[1206] = f32(16.0)
    holding[1208] = u32(valid_time)
    holding[1210] = f32(max_current)
    holding[1212] = f32(6.0)
    holding[1214] = 1
    holding[1215] = phases
