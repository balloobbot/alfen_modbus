"""Coded values from the Alfen Modbus Slave TCP/IP register table."""

from __future__ import annotations

from enum import IntEnum, IntFlag


class MeterState(IntFlag):
    """Bitmask reported by the socket's energy meter (register 300)."""

    INITIALISED = 0x01
    UPDATED = 0x02
    WARNING = 0x04
    ERROR = 0x08


class MeterType(IntEnum):
    """How the socket's energy meter is attached (register 305)."""

    RTU = 0
    TCP_IP = 1
    UDP = 2
    P1 = 3
    OTHER = 4


class Phases(IntEnum):
    """Number of phases the socket charges with (register 1215)."""

    ONE = 1
    THREE = 3


# Mode 3 (IEC 61851) states, register 1201. The station reports far more codes
# than these two sets name, so both are membership tests rather than an enum:
# an unlisted state simply means "connected but not charging".
DISCONNECTED_STATES = frozenset({"A", "E", "F"})
"""No vehicle attached (A), socket disabled (E), or error (F)."""

CHARGING_STATES = frozenset({"C2", "D2"})
"""Vehicle connected, PWM applied, current flowing."""
