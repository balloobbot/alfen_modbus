"""Base entity for the Alfen Modbus integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_MANUFACTURER, DOMAIN
from .coordinator import AlfenCoordinator


class AlfenEntity(CoordinatorEntity[AlfenCoordinator]):
    """An entity backed by one poll of the charging station.

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
    ) -> None:
        """Initialize the entity under ``platform_name``."""
        super().__init__(coordinator)
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
