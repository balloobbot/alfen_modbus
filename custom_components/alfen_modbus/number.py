"""The per-socket max-current setpoint."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import CONF_NAME, UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AlfenConfigEntry, AlfenCoordinator
from .entity import AlfenEntity

_LOGGER = logging.getLogger(__name__)

# Ceiling for the slider until the station reports its own (register 1100);
# 32 A is the largest current an NG9xx socket hands out.
FALLBACK_MAX_CURRENT = 32.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlfenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a max-current number per socket."""
    coordinator = entry.runtime_data
    platform_name = entry.data[CONF_NAME]
    async_add_entities(
        AlfenMaxCurrent(coordinator, platform_name, number)
        for number in coordinator.charger.sockets
    )


class AlfenMaxCurrent(AlfenEntity, NumberEntity):
    """The Modbus current setpoint for one socket (registers 1210-1211).

    Writing it also restarts the station's validity timer; the coordinator
    rewrites it before that timer lapses, so the socket keeps the setpoint
    instead of falling back to its safe current.
    """

    _attr_native_min_value = 0
    _attr_native_step = 0.1
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self, coordinator: AlfenCoordinator, platform_name: str, number: int
    ) -> None:
        """Initialize the setpoint for socket ``number``."""
        super().__init__(
            coordinator,
            platform_name,
            f"maxCurrent_socket_{number}",
            f"Max Current Limit S{number}",
        )
        self._number = number

    @property
    def native_max_value(self) -> float:
        """The station's own max current, which no socket may exceed."""
        return self.coordinator.charger.station.status.max_current or (
            FALLBACK_MAX_CURRENT
        )

    @property
    def native_value(self) -> float | None:
        """The setpoint the socket is currently holding."""
        return self.coordinator.charger.sockets[self._number].status.max_current

    async def async_set_native_value(self, value: float) -> None:
        """Write a new setpoint, clamped to what the station allows."""
        if value > (allowed := self.native_max_value):
            _LOGGER.warning(
                "Requested %s A exceeds the station's max current %s A, clamping",
                value,
                allowed,
            )
            value = allowed
        socket = self.coordinator.charger.sockets[self._number]
        await socket.async_set_max_current(value)
        await self.coordinator.async_request_refresh()
