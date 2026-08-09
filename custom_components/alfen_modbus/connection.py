"""Build the Modbus connection a config entry describes.

The integration owns its connection, per the modbus-connection integration
guide: construction performs no I/O, requests connect on demand, and a dropped
link re-establishes itself on the next poll — the config entry is never reloaded
for a drop. Kept in its own module so setup, the config flow and the tests all
go through one seam.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.const import CONF_HOST, CONF_PORT
from modbus_connection import ModbusConnection, ModbusTcpParams
from modbus_connection.tmodbus import ModbusConnection as TmodbusConnection

from .const import DEFAULT_PORT


def build_connection(data: Mapping[str, Any]) -> ModbusConnection:
    """Return the (unconnected) connection for a config entry's data.

    One link carries every unit: the station on its own slave id and each
    socket on its own, all addressed through ``for_unit()``.
    """
    return TmodbusConnection(
        ModbusTcpParams(host=data[CONF_HOST], port=data.get(CONF_PORT, DEFAULT_PORT))
    )
