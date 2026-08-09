"""The Alfen charging station as a device object over its Modbus units.

An Alfen station is one TCP endpoint carrying several Modbus units: the station
itself answers on slave 200 (configurable) and each socket answers on slave 1 or
2. ``ModbusConnection.for_unit()`` hands out a unit per slave id over the single
shared link; each unit gets its own ``ComponentGroup``, because a group pools
the reads of components that share one unit.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime, timedelta, timezone

from modbus_connection import ModbusConnection, ModbusUnit
from modbus_connection.model import ComponentGroup

from .components import Product, Scn, SocketMeter, SocketStatus, StationStatus
from .enums import CHARGING_STATES, DISCONNECTED_STATES, Phases

DEFAULT_STATION_UNIT = 200
"""Slave id the spec assigns to the station's own registers."""


async def async_read_product(unit: ModbusUnit) -> Product:
    """Read the identification block, for a config flow probing a station.

    Raises ``ModbusError`` if the station cannot be reached, or does not serve
    the block — reading is off by default and needs the Active Load Balancing
    licence, so a refusal here is the useful "not set up" signal.
    """
    product = Product(unit)
    await product.async_update()
    return product


class AlfenStation:
    """The station unit: identification, status, and optionally SCN."""

    def __init__(self, unit: ModbusUnit, *, read_scn: bool = False) -> None:
        """Set up the station's components on ``unit``."""
        self.product = Product(unit)
        self.status = StationStatus(unit)
        self.scn = Scn(unit) if read_scn else None
        components = [self.product, self.status]
        if self.scn is not None:
            components.append(self.scn)
        self._group = ComponentGroup(unit, components)

    async def async_update(self) -> None:
        """Refresh the station in one pooled read per register block."""
        await self._group.async_update()

    async def async_read_raw(self) -> dict[str, dict[int, int | bool]]:
        """Read every station register undecoded, keyed by space and address."""
        return await self._group.async_read_raw()

    @property
    def time(self) -> datetime | None:
        """The station clock, assembled from its six date/time registers.

        None while any part is unread, or when the station reports a clock it
        has not set yet (a fresh boot answers with an impossible date).
        """
        parts = (
            self.product.year,
            self.product.month,
            self.product.day,
            self.product.hour,
            self.product.minute,
            self.product.second,
            self.product.utc_offset,
        )
        if any(part is None for part in parts):
            return None
        year, month, day, hour, minute, second, offset = parts
        try:
            return datetime(
                year,
                month,
                day,
                hour,
                minute,
                second,
                tzinfo=timezone(timedelta(minutes=offset)),
            )
        except ValueError:
            return None

    @property
    def last_boot(self) -> datetime | None:
        """When the station booted: its clock less its uptime."""
        now = self.time
        uptime = self.product.uptime
        if now is None or uptime is None:
            return None
        return (now - timedelta(milliseconds=uptime)).replace(microsecond=0)


class AlfenSocket:
    """One socket unit: its energy meter, its status, and its session."""

    def __init__(self, unit: ModbusUnit, number: int) -> None:
        """Set up socket ``number``'s components on its own unit."""
        self.number = number
        self.meter = SocketMeter(unit)
        self.status = SocketStatus(unit)
        self._group = ComponentGroup(unit, [self.meter, self.status])
        self.session_energy: float | None = None
        self.session_duration: timedelta | None = None
        self._session_start: datetime | None = None
        self._session_start_energy: float | None = None
        self._charging = False

    async def async_update(self) -> None:
        """Refresh this socket in one pooled read per register block."""
        await self._group.async_update()

    async def async_read_raw(self) -> dict[str, dict[int, int | bool]]:
        """Read every socket register undecoded, keyed by space and address."""
        return await self._group.async_read_raw()

    @property
    def vehicle_connected(self) -> bool | None:
        """Whether a vehicle is plugged in, per the mode 3 state."""
        state = self.status.mode3_state
        if not state:
            return None
        return state not in DISCONNECTED_STATES

    @property
    def charging(self) -> bool | None:
        """Whether current is actually flowing, per the mode 3 state."""
        state = self.status.mode3_state
        if not state:
            return None
        return state in CHARGING_STATES

    def update_session(self, station_time: datetime | None) -> None:
        """Track the running charge session against the station clock.

        The station exposes no session counters, so they are derived here: the
        delivered-energy total and the clock are snapshotted when the mode 3
        state first reports current flowing, and the session figures track the
        difference until it stops. They then hold their final value until the
        next session starts, which is what makes them readable after unplugging.
        """
        charging = bool(self.charging)
        energy = self.meter.real_energy_delivered_sum
        if not charging:
            self._charging = False
            return
        if not self._charging:
            self._charging = True
            self._session_start = station_time
            self._session_start_energy = energy
        if energy is not None and self._session_start_energy is not None:
            self.session_energy = energy - self._session_start_energy
        if station_time is not None and self._session_start is not None:
            self.session_duration = station_time - self._session_start

    async def async_set_max_current(self, amps: float) -> None:
        """Write the Modbus current setpoint (registers 1210-1211)."""
        await self.status.write("max_current", amps)

    async def async_set_phases(self, phases: Phases) -> None:
        """Write the phase mode (register 1215, forced to FC16)."""
        await self.status.write("phases", phases)

    async def async_renew_max_current(self, *, within: float) -> bool:
        """Rewrite the setpoint before its validity window lapses.

        The station falls back to its configured safe current unless a Modbus
        master rewrites the max current before register 1208 counts down to
        zero (spec §1.3.1) — so a poll that sees less than ``within`` seconds
        left writes the setpoint the station is already holding straight back,
        which is what restarts the timer. Returns whether it wrote.

        A setpoint of zero, or none at all, is left alone: the station has
        never been given one, and writing zero back would pin the socket at no
        current rather than keep an existing setpoint alive.
        """
        valid_time = self.status.max_current_valid_time
        setpoint = self.status.max_current
        if valid_time is None or not setpoint or valid_time >= within:
            return False
        await self.async_set_max_current(setpoint)
        return True


class AlfenCharger:
    """An Alfen NG9xx charging station across all of its Modbus units."""

    def __init__(
        self,
        connection: ModbusConnection,
        *,
        station_unit: int = DEFAULT_STATION_UNIT,
        socket_numbers: Sequence[int] = (1,),
        read_scn: bool = False,
    ) -> None:
        """Bind the station and each socket to its own unit on ``connection``.

        A socket's number *is* its slave id, per the spec. Constructing this
        performs no I/O; the first update opens the link.
        """
        self.station = AlfenStation(
            connection.for_unit(station_unit), read_scn=read_scn
        )
        self.sockets = {
            number: AlfenSocket(connection.for_unit(number), number)
            for number in socket_numbers
        }

    def __iter__(self) -> Iterator[AlfenSocket]:
        """Iterate the sockets the station actually reports."""
        count = self.station.status.socket_count
        for number, socket in self.sockets.items():
            # Socket 1 always exists; a second socket is a separate Modbus unit
            # that simply does not answer on a single-socket station, so it is
            # skipped until register 1105 says it is there.
            if number == 1 or (count is not None and number <= count):
                yield socket

    async def async_update(self) -> None:
        """Refresh the station, then every socket it reports.

        The station goes first: its socket count decides which socket units are
        worth talking to, and its clock is what the session figures are
        measured against.

        Raises ``ModbusError`` if any unit fails to answer.
        """
        await self.station.async_update()
        station_time = self.station.time
        for socket in self:
            await socket.async_update()
            socket.update_session(station_time)

    async def async_renew_setpoints(self, *, within: float) -> None:
        """Keep every socket's current setpoint from lapsing."""
        for socket in self:
            await socket.async_renew_max_current(within=within)

    async def async_read_raw(self) -> dict[str, dict[int, int | bool]]:
        """Every register this device reads, keyed by unit and address.

        ``Component.async_read_raw()`` keys by address space alone, which is
        ambiguous here: the station and both sockets are separate units on one
        link, and socket 1's register 300 is not socket 2's. The unit id is
        folded into the key to keep them apart.
        """
        raw: dict[str, dict[int, int | bool]] = {}
        # The station goes first here too: its socket count is what decides
        # which socket units to read, so iterating them before it is read would
        # dump whatever the last poll happened to see.
        for space, values in (await self.station.async_read_raw()).items():
            raw[f"station/{space}"] = values
        for socket in self:
            for space, values in (await socket.async_read_raw()).items():
                raw[f"socket_{socket.number}/{space}"] = values
        return raw
