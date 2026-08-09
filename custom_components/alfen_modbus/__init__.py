"""The Alfen Modbus integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .alfen import AlfenCharger
from .connection import build_connection
from .const import (
    CONF_MODBUS_ADDRESS,
    CONF_READ_SCN,
    CONF_READ_SOCKET2,
    DEFAULT_MODBUS_ADDRESS,
)
from .coordinator import AlfenConfigEntry, AlfenCoordinator

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: AlfenConfigEntry) -> bool:
    """Set up an Alfen charging station from a config entry."""
    connection = build_connection(entry.data)
    entry.async_on_unload(connection.close)

    # The station and each socket are separate Modbus units on this one link.
    # Socket 2 is offered when configured; the charger drops it if the station
    # reports a single socket.
    socket_numbers = (1, 2) if entry.data.get(CONF_READ_SOCKET2) else (1,)
    charger = AlfenCharger(
        connection,
        station_unit=entry.data.get(CONF_MODBUS_ADDRESS, DEFAULT_MODBUS_ADDRESS),
        socket_numbers=socket_numbers,
        read_scn=bool(entry.data.get(CONF_READ_SCN)),
    )

    coordinator = AlfenCoordinator(hass, entry, charger, connection)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AlfenConfigEntry) -> bool:
    """Unload a config entry; the connection closes via async_on_unload."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
