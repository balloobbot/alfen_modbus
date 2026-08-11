"""Diagnostics for the Alfen Modbus integration."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from modbus_connection import ModbusError

from .coordinator import AlfenConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AlfenConfigEntry
) -> dict[str, Any]:
    """Return every register the integration reads, undecoded.

    Read fresh from the device, and keyed by unit as well as address space —
    the station and each socket are separate units whose register numbers
    overlap, so an address alone does not identify a register here.

    ``layout`` says which field each of those addresses belongs to, straight
    off the register map, so a dump can be read without the vendor table. It
    needs no I/O, so it is there even when the read fails.
    """
    coordinator = entry.runtime_data
    try:
        registers: Any = await coordinator.charger.async_read_raw()
    except ModbusError as err:
        registers = {"error": str(err)}
    return {
        "entry": {
            "port": entry.data.get("port"),
            "modbus_address": entry.data.get("modbus_address"),
            "read_scn": entry.data.get("read_scn"),
            "read_socket_2": entry.data.get("read_socket_2"),
            "scan_interval": entry.data.get("scan_interval"),
        },
        "layout": coordinator.charger.layout,
        "registers": registers,
    }
