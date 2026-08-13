"""The per-socket phase-mode selector."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .alfen import Phases
from .coordinator import AlfenConfigEntry, AlfenCoordinator
from .entity import AlfenEntity

PHASE_OPTIONS = {"1 Phase": Phases.ONE, "3 Phases": Phases.THREE}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlfenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a phase-mode select per socket."""
    coordinator = entry.runtime_data
    platform_name = entry.data[CONF_NAME]
    async_add_entities(
        AlfenPhaseSelect(coordinator, platform_name, number)
        for number in coordinator.charger.sockets
    )


class AlfenPhaseSelect(AlfenEntity, SelectEntity):
    """Whether a socket charges on one phase or three (register 1215).

    The station only accepts this single register written as FC16, which the
    model handles: the field is declared ``force_fc16``.
    """

    _attr_options = list(PHASE_OPTIONS)

    def __init__(
        self, coordinator: AlfenCoordinator, platform_name: str, number: int
    ) -> None:
        """Initialize the selector for socket ``number``."""
        super().__init__(
            coordinator,
            platform_name,
            f"usephases_S{number}",
            f"Usable phases{number}",
            f"socket_{number}.status",
        )
        self._number = number

    @property
    def current_option(self) -> str | None:
        """The phase mode the socket reports."""
        phases = self.coordinator.charger.sockets[self._number].status.phases
        return next(
            (label for label, value in PHASE_OPTIONS.items() if value is phases), None
        )

    async def async_select_option(self, option: str) -> None:
        """Write the selected phase mode."""
        socket = self.coordinator.charger.sockets[self._number]
        await socket.async_set_phases(PHASE_OPTIONS[option])
        await self.coordinator.async_request_refresh()
