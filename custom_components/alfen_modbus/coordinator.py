"""DataUpdateCoordinator polling an Alfen charging station."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from modbus_connection import ModbusConnection, ModbusError

from .alfen import AlfenCharger, UpdateReport
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, SETPOINT_RENEWAL_MARGIN

_LOGGER = logging.getLogger(__name__)

type AlfenConfigEntry = ConfigEntry[AlfenCoordinator]


class AlfenCoordinator(DataUpdateCoordinator[UpdateReport]):
    """Poll the station and its sockets, and keep their setpoints alive.

    The data is the poll's own ``UpdateReport``, which is what lets an entity
    ask whether the block it reads from refreshed.

    A dropped link is not an entry reload: the connection re-establishes itself
    on the next request, so a failed poll marks the instantaneous entities
    unavailable and the next successful one brings them back. Totals are exempt
    and hold their last value, to keep long-term statistics unbroken.
    """

    _failed: frozenset[str] = frozenset()

    def __init__(
        self,
        hass: HomeAssistant,
        entry: AlfenConfigEntry,
        charger: AlfenCharger,
        connection: ModbusConnection,
    ) -> None:
        """Initialize the coordinator over a charger."""
        scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.charger = charger
        self.connection = connection
        # A setpoint written now stays valid for the station's validity time
        # (60 s by default), so renew once less than one poll plus a margin is
        # left — the window the pre-migration integration used.
        self._renewal_margin = scan_interval + SETPOINT_RENEWAL_MARGIN

    async def _async_update_data(self) -> UpdateReport:
        """Read every unit, then renew any setpoint about to lapse."""
        try:
            report = await self.charger.async_update()
            await self.charger.async_renew_setpoints(within=self._renewal_margin)
        except ModbusError as err:
            raise UpdateFailed(f"Error talking to the charging station: {err}") from err
        if not report.updated:
            # Home Assistant logs str(err) at error level and the traceback at
            # debug, so name a block that failed rather than only the silence.
            errors = list(report.failed.values())
            raise UpdateFailed(
                f"The charging station answered nothing: {errors[0]}"
            ) from ExceptionGroup("every block failed", errors)

        for name in sorted(report.failed.keys() - self._failed):
            _LOGGER.warning("Failed to fetch %s: %s", name, report.failed[name])
        self._failed = frozenset(report.failed)
        return report
