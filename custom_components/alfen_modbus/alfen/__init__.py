"""Alfen NG9xx charging station over Modbus TCP.

A device library on top of modbus-connection: no Home Assistant imports, so the
register map, the decoding and the write sequencing are testable on their own
against the in-memory mock backend.
"""

from .components import Product, Scn, SocketMeter, SocketStatus, StationStatus
from .device import (
    DEFAULT_STATION_UNIT,
    AlfenCharger,
    AlfenSocket,
    AlfenStation,
    async_read_product,
)
from .enums import CHARGING_STATES, DISCONNECTED_STATES, MeterState, MeterType, Phases
from .model import UpdateReport

__all__ = [
    "CHARGING_STATES",
    "DEFAULT_STATION_UNIT",
    "DISCONNECTED_STATES",
    "AlfenCharger",
    "AlfenSocket",
    "AlfenStation",
    "MeterState",
    "MeterType",
    "Phases",
    "Product",
    "Scn",
    "SocketMeter",
    "SocketStatus",
    "StationStatus",
    "UpdateReport",
    "async_read_product",
]
