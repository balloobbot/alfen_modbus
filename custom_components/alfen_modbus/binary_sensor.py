"""Binary sensors for the Alfen Modbus integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .alfen import AlfenSocket
from .coordinator import AlfenConfigEntry, AlfenCoordinator
from .entity import AlfenEntity


@dataclass(frozen=True, kw_only=True)
class AlfenBinarySensorDescription(BinarySensorEntityDescription):
    """A binary sensor derived from one socket's mode 3 state.

    ``key`` is a template filled with the socket number, as in ``sensor.py``.
    """

    is_on_fn: Callable[[AlfenSocket], bool | None]
    icon_on: str
    icon_off: str


BINARY_SENSORS: tuple[AlfenBinarySensorDescription, ...] = (
    AlfenBinarySensorDescription(
        key="socket_{n}_carconnected",
        name="Car Connected",
        device_class=BinarySensorDeviceClass.PLUG,
        icon_on="mdi:power-plug",
        icon_off="mdi:power-plug-off",
        is_on_fn=lambda socket: socket.vehicle_connected,
    ),
    AlfenBinarySensorDescription(
        key="socket_{n}_carcharging",
        name="Car Charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        icon_on="mdi:battery-charging",
        icon_off="mdi:battery-off",
        is_on_fn=lambda socket: socket.charging,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlfenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Alfen binary sensors."""
    coordinator = entry.runtime_data
    platform_name = entry.data[CONF_NAME]
    async_add_entities(
        AlfenBinarySensor(coordinator, platform_name, description, number)
        for number in coordinator.charger.sockets
        for description in BINARY_SENSORS
    )


class AlfenBinarySensor(AlfenEntity, BinarySensorEntity):
    """Whether a vehicle is plugged in, or drawing current."""

    entity_description: AlfenBinarySensorDescription

    def __init__(
        self,
        coordinator: AlfenCoordinator,
        platform_name: str,
        description: AlfenBinarySensorDescription,
        number: int,
    ) -> None:
        """Initialize the binary sensor for socket ``number``."""
        label = description.name
        if len(coordinator.charger.sockets) > 1:
            label = f"S{number} {label}"
        super().__init__(
            coordinator,
            platform_name,
            description.key.format(n=number),
            label,
            f"socket_{number}.status",  # both read the mode 3 state
        )
        self.entity_description = description
        self._number = number

    @property
    def is_on(self) -> bool:
        """Return whether the socket reports this state."""
        socket = self.coordinator.charger.sockets[self._number]
        return bool(self.entity_description.is_on_fn(socket))

    @property
    def icon(self) -> str:
        """Return the icon matching the current state."""
        description = self.entity_description
        return description.icon_on if self.is_on else description.icon_off
