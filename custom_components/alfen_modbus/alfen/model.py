"""What one poll of the charger refreshed."""

from __future__ import annotations

from dataclasses import dataclass

from modbus_connection import ModbusError


@dataclass(frozen=True)
class UpdateReport:
    """What one poll refreshed, by component name.

    A unit reports its own component attribute names (``meter``, ``status``);
    the charger prefixes each with the unit it sits on (``station.product``,
    ``socket_1.meter``), because the same name lives on more than one unit. A
    failed component kept its previous values and did not notify; the error
    that failed it rides along. A dead link is never in here — the update
    raises ``ModbusConnectionError`` instead of reporting partial silence.
    """

    updated: set[str]
    failed: dict[str, ModbusError]

    @property
    def complete(self) -> bool:
        """Whether every polled component refreshed."""
        return not self.failed
