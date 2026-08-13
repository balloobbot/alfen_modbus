"""Base entity for the Alfen Modbus integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_MANUFACTURER, DOMAIN
from .coordinator import AlfenCoordinator


class AlfenEntity(CoordinatorEntity[AlfenCoordinator]):
    """An entity backed by one block of one poll of the charging station.

    Names and unique ids keep the ``<config name> <label>`` shape the
    integration has always used, so upgrading does not orphan entities.
    """

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: AlfenCoordinator,
        platform_name: str,
        key: str,
        label: str,
        component: str,
    ) -> None:
        """Initialize the entity under ``platform_name``.

        ``component`` is the report key of the block this entity reads —
        unit-qualified (``station.status``, ``socket_1.meter``), because the
        station and each socket are separate units with overlapping names.
        """
        super().__init__(coordinator)
        self._component = component
        self._platform_name = platform_name
        self._attr_unique_id = f"{platform_name}_{key}"
        self._attr_name = f"{platform_name} {label}"
        product = coordinator.charger.station.product
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, platform_name)},
            name=platform_name,
            manufacturer=ATTR_MANUFACTURER,
            model=product.platform_type or "Unknown",
            sw_version=product.firmware_version or "Unknown",
            serial_number=product.serial_number or None,
        )

    @property
    def available(self) -> bool:
        """Unavailable while the block this entity reads from is failing.

        A block the station refuses keeps its previous values, but publishing
        those as if they were fresh is a lie — the poll only contains the
        failure, it does not excuse it.
        """
        return super().available and self._component not in self.coordinator.data.failed
