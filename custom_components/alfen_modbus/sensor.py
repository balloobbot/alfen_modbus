"""Sensors for the Alfen Modbus integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property, partial
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_NAME,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfReactiveEnergy,
    UnitOfReactivePower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .alfen import AlfenCharger, AlfenSocket, MeterState, MeterType, Phases
from .coordinator import AlfenConfigEntry, AlfenCoordinator
from .entity import AlfenEntity

UNIT_APPARENT_ENERGY = "VAh"
"""Home Assistant has no apparent-energy unit constant, so spell it out."""

METER_TYPE_LABELS = {
    MeterType.RTU: "RTU",
    MeterType.TCP_IP: "TCP/IP",
    MeterType.UDP: "UDP",
    MeterType.P1: "P1",
    MeterType.OTHER: "Other",
}

PHASE_LABELS = {Phases.ONE: "1 Phase", Phases.THREE: "3 Phases"}


def _meter_state_label(state: MeterState | None) -> str | None:
    """Render the meter's state bitmask the way the register table names it."""
    if state is None:
        return None
    if not state:
        return "Unknown"
    return ", ".join(flag.name.capitalize() for flag in MeterState if flag in state)


def _availability_label(available: bool | None) -> str | None:
    """Render socket availability as the register table's wording."""
    if available is None:
        return None
    return "Operative" if available else "Inoperative"


def _seconds(value: Any) -> float | None:
    """Render a session duration as whole seconds."""
    return None if value is None else value.total_seconds()


@dataclass(frozen=True, kw_only=True)
class AlfenSensorDescription(SensorEntityDescription):
    """What every Alfen sensor description carries."""

    component: str
    """The block this sensor reads from, as the update report names it."""

    @cached_property
    def is_total(self) -> bool:
        """Whether this sensor accumulates rather than measures."""
        return self.state_class in (
            SensorStateClass.TOTAL,
            SensorStateClass.TOTAL_INCREASING,
        )


@dataclass(frozen=True, kw_only=True)
class AlfenStationSensorDescription(AlfenSensorDescription):
    """A sensor reading a value off the station's own units."""

    value_fn: Callable[[AlfenCharger], Any]


@dataclass(frozen=True, kw_only=True)
class AlfenSocketSensorDescription(AlfenSensorDescription):
    """A sensor reading a value off one socket unit.

    ``key`` is a template: the socket number fills ``{n}``, which reproduces the
    unique ids the integration has used since before the sockets were modelled.
    ``component`` is unit-local for the same reason: the socket number qualifies
    it when the entity is built.
    """

    value_fn: Callable[[AlfenSocket], Any]


STATION_SENSORS: tuple[AlfenStationSensorDescription, ...] = (
    AlfenStationSensorDescription(
        key="name",
        component="station.product",
        name="Name",
        value_fn=lambda charger: charger.station.product.name,
    ),
    AlfenStationSensorDescription(
        key="manufacturer",
        component="station.product",
        name="Manufacturer",
        value_fn=lambda charger: charger.station.product.manufacturer,
    ),
    AlfenStationSensorDescription(
        key="modbustableVersion",
        component="station.product",
        name="Modbus table version",
        value_fn=lambda charger: charger.station.product.modbus_table_version,
    ),
    AlfenStationSensorDescription(
        key="firmwareVersion",
        component="station.product",
        name="Firmware version",
        value_fn=lambda charger: charger.station.product.firmware_version,
    ),
    AlfenStationSensorDescription(
        key="platformType",
        component="station.product",
        name="Platform Type",
        value_fn=lambda charger: charger.station.product.platform_type,
    ),
    AlfenStationSensorDescription(
        key="serial",
        component="station.product",
        name="Serial",
        value_fn=lambda charger: charger.station.product.serial_number,
    ),
    AlfenStationSensorDescription(
        key="stationTime",
        component="station.product",
        name="Current time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda charger: charger.station.time,
    ),
    AlfenStationSensorDescription(
        key="lastBoot",
        component="station.product",
        name="Last boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda charger: charger.station.last_boot,
    ),
    AlfenStationSensorDescription(
        key="actualMaxCurrent",
        component="station.status",
        name="Actual max current",
        icon="mdi:current-dc",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda charger: charger.station.status.max_current,
    ),
    AlfenStationSensorDescription(
        key="boardTemperature",
        component="station.status",
        name="Board temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda charger: charger.station.status.temperature,
    ),
    AlfenStationSensorDescription(
        key="backofficeConnected",
        component="station.status",
        name="Backoffice connected",
        value_fn=lambda charger: charger.station.status.backoffice_connected,
    ),
    AlfenStationSensorDescription(
        key="numberOfSockets",
        component="station.status",
        name="Number of sockets",
        value_fn=lambda charger: charger.station.status.socket_count,
    ),
)

SCN_SENSORS: tuple[AlfenStationSensorDescription, ...] = (
    AlfenStationSensorDescription(
        key="scnName",
        component="station.scn",
        name="SCN Name",
        value_fn=lambda charger: charger.station.scn and charger.station.scn.name,
    ),
    AlfenStationSensorDescription(
        key="scnSockets",
        component="station.scn",
        name="Number of SCN sockets",
        value_fn=(
            lambda charger: charger.station.scn and charger.station.scn.socket_count
        ),
    ),
)

_VOLTAGE = {
    "native_unit_of_measurement": UnitOfElectricPotential.VOLT,
    "device_class": SensorDeviceClass.VOLTAGE,
    "state_class": SensorStateClass.MEASUREMENT,
}
_CURRENT = {
    "icon": "mdi:current-ac",
    "native_unit_of_measurement": UnitOfElectricCurrent.AMPERE,
    "device_class": SensorDeviceClass.CURRENT,
    "state_class": SensorStateClass.MEASUREMENT,
}
_POWER_FACTOR = {
    "device_class": SensorDeviceClass.POWER_FACTOR,
    "state_class": SensorStateClass.MEASUREMENT,
}
_REAL_POWER = {
    "native_unit_of_measurement": UnitOfPower.WATT,
    "device_class": SensorDeviceClass.POWER,
    "state_class": SensorStateClass.MEASUREMENT,
}
_APPARENT_POWER = {
    "native_unit_of_measurement": "VA",
    "device_class": SensorDeviceClass.APPARENT_POWER,
    "state_class": SensorStateClass.MEASUREMENT,
}
_REACTIVE_POWER = {
    "native_unit_of_measurement": UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
    "device_class": SensorDeviceClass.REACTIVE_POWER,
    "state_class": SensorStateClass.MEASUREMENT,
}
_REAL_ENERGY = {
    "native_unit_of_measurement": UnitOfEnergy.WATT_HOUR,
    "device_class": SensorDeviceClass.ENERGY,
    "state_class": SensorStateClass.TOTAL_INCREASING,
}
_APPARENT_ENERGY = {
    "native_unit_of_measurement": UNIT_APPARENT_ENERGY,
    "state_class": SensorStateClass.TOTAL_INCREASING,
}
_REACTIVE_ENERGY = {
    "native_unit_of_measurement": UnitOfReactiveEnergy.VOLT_AMPERE_REACTIVE_HOUR,
    "device_class": SensorDeviceClass.REACTIVE_ENERGY,
    "state_class": SensorStateClass.TOTAL_INCREASING,
}

SOCKET_SENSORS: tuple[AlfenSocketSensorDescription, ...] = (
    AlfenSocketSensorDescription(
        key="socket_{n}_meterstate",
        component="meter",
        name="Meter state",
        value_fn=lambda socket: _meter_state_label(socket.meter.meter_state),
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_meterAge",
        component="meter",
        name="Meter reading age",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda socket: socket.meter.meter_timestamp,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_meterType",
        component="meter",
        name="Meter Type",
        value_fn=lambda socket: METER_TYPE_LABELS.get(socket.meter.meter_type),
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_VL1-N",
        component="meter",
        name="Voltage L1-N",
        value_fn=lambda socket: socket.meter.voltage_l1_n,
        **_VOLTAGE,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_VL2-N",
        component="meter",
        name="Voltage L2-N",
        value_fn=lambda socket: socket.meter.voltage_l2_n,
        **_VOLTAGE,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_VL3-N",
        component="meter",
        name="Voltage L3-N",
        value_fn=lambda socket: socket.meter.voltage_l3_n,
        **_VOLTAGE,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_VL1-L2",
        component="meter",
        name="Voltage L1-L2",
        value_fn=lambda socket: socket.meter.voltage_l1_l2,
        **_VOLTAGE,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_VL2-L3",
        component="meter",
        name="Voltage L2-L3",
        value_fn=lambda socket: socket.meter.voltage_l2_l3,
        **_VOLTAGE,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_VL3-L1",
        component="meter",
        name="Voltage L3-L1",
        value_fn=lambda socket: socket.meter.voltage_l3_l1,
        **_VOLTAGE,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_currentN",
        component="meter",
        name="Current N",
        value_fn=lambda socket: socket.meter.current_n,
        **_CURRENT,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_currentL1",
        component="meter",
        name="Current L1",
        value_fn=lambda socket: socket.meter.current_l1,
        **_CURRENT,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_currentL2",
        component="meter",
        name="Current L2",
        value_fn=lambda socket: socket.meter.current_l2,
        **_CURRENT,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_currentL3",
        component="meter",
        name="Current L3",
        value_fn=lambda socket: socket.meter.current_l3,
        **_CURRENT,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_currentSum",
        component="meter",
        name="Current Total",
        value_fn=lambda socket: socket.meter.current_sum,
        **_CURRENT,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_powerL1",
        component="meter",
        name="Power factor L1",
        value_fn=lambda socket: socket.meter.power_factor_l1,
        **_POWER_FACTOR,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_powerL2",
        component="meter",
        name="Power factor L2",
        value_fn=lambda socket: socket.meter.power_factor_l2,
        **_POWER_FACTOR,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_powerL3",
        component="meter",
        name="Power factor L3",
        value_fn=lambda socket: socket.meter.power_factor_l3,
        **_POWER_FACTOR,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_powerSum",
        component="meter",
        name="Power factor sum",
        value_fn=lambda socket: socket.meter.power_factor_sum,
        **_POWER_FACTOR,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_frequency",
        component="meter",
        name="Frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda socket: socket.meter.frequency,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realPowerL1",
        component="meter",
        name="Real power L1",
        value_fn=lambda socket: socket.meter.real_power_l1,
        **_REAL_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realPowerL2",
        component="meter",
        name="Real power L2",
        value_fn=lambda socket: socket.meter.real_power_l2,
        **_REAL_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realPowerL3",
        component="meter",
        name="Real power L3",
        value_fn=lambda socket: socket.meter.real_power_l3,
        **_REAL_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realPowerSum",
        component="meter",
        name="Real power sum",
        value_fn=lambda socket: socket.meter.real_power_sum,
        **_REAL_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_apparantPowerL1",
        component="meter",
        name="Apparant power L1",
        value_fn=lambda socket: socket.meter.apparent_power_l1,
        **_APPARENT_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_apparantPowerL2",
        component="meter",
        name="Apparant power L2",
        value_fn=lambda socket: socket.meter.apparent_power_l2,
        **_APPARENT_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_apparantPowerL3",
        component="meter",
        name="Apparant power L3",
        value_fn=lambda socket: socket.meter.apparent_power_l3,
        **_APPARENT_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_apparantPowerSum",
        component="meter",
        name="Apparant power sum",
        value_fn=lambda socket: socket.meter.apparent_power_sum,
        **_APPARENT_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_reactivePowerL1",
        component="meter",
        name="Reactive power L1",
        value_fn=lambda socket: socket.meter.reactive_power_l1,
        **_REACTIVE_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_reactivePowerL2",
        component="meter",
        name="Reactive power L2",
        value_fn=lambda socket: socket.meter.reactive_power_l2,
        **_REACTIVE_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_reactivePowerL3",
        component="meter",
        name="Reactive power L3",
        value_fn=lambda socket: socket.meter.reactive_power_l3,
        **_REACTIVE_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_reactivePowerSum",
        component="meter",
        name="Reactive power sum",
        value_fn=lambda socket: socket.meter.reactive_power_sum,
        **_REACTIVE_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realEnergyDeliveredL1",
        component="meter",
        name="Real energy delivered L1",
        value_fn=lambda socket: socket.meter.real_energy_delivered_l1,
        **_REAL_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realEnergyDeliveredL2",
        component="meter",
        name="Real energy delivered L2",
        value_fn=lambda socket: socket.meter.real_energy_delivered_l2,
        **_REAL_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realEnergyDeliveredL3",
        component="meter",
        name="Real energy delivered L3",
        value_fn=lambda socket: socket.meter.real_energy_delivered_l3,
        **_REAL_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realEnergyDeliveredSum",
        component="meter",
        name="Real energy delivered sum",
        value_fn=lambda socket: socket.meter.real_energy_delivered_sum,
        **_REAL_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realEnergyConsumedL1",
        component="meter",
        name="Real energy consumed L1",
        value_fn=lambda socket: socket.meter.real_energy_consumed_l1,
        **_REAL_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realEnergyConsumedL2",
        component="meter",
        name="Real energy consumed L2",
        value_fn=lambda socket: socket.meter.real_energy_consumed_l2,
        **_REAL_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realEnergyConsumedL3",
        component="meter",
        name="Real energy consumed L3",
        value_fn=lambda socket: socket.meter.real_energy_consumed_l3,
        **_REAL_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realEnergyConsumedSum",
        component="meter",
        name="Real energy consumed sum",
        value_fn=lambda socket: socket.meter.real_energy_consumed_sum,
        **_REAL_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_apparantEnergyL1",
        component="meter",
        name="Apparant energy L1",
        value_fn=lambda socket: socket.meter.apparent_energy_l1,
        **_APPARENT_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_apparantEnergyL2",
        component="meter",
        name="Apparant energy L2",
        value_fn=lambda socket: socket.meter.apparent_energy_l2,
        **_APPARENT_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_apparantEnergyL3",
        component="meter",
        name="Apparant energy L3",
        value_fn=lambda socket: socket.meter.apparent_energy_l3,
        **_APPARENT_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_apparantEnergySum",
        component="meter",
        name="Apparant energy sum",
        value_fn=lambda socket: socket.meter.apparent_energy_sum,
        **_APPARENT_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_reactiveEnergyL1",
        component="meter",
        name="Reactive energy L1",
        value_fn=lambda socket: socket.meter.reactive_energy_l1,
        **_REACTIVE_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_reactiveEnergyL2",
        component="meter",
        name="Reactive energy L2",
        value_fn=lambda socket: socket.meter.reactive_energy_l2,
        **_REACTIVE_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_reactiveEnergyL3",
        component="meter",
        name="Reactive energy L3",
        value_fn=lambda socket: socket.meter.reactive_energy_l3,
        **_REACTIVE_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_reactiveEnergySum",
        component="meter",
        name="Reactive energy sum",
        value_fn=lambda socket: socket.meter.reactive_energy_sum,
        **_REACTIVE_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_available",
        component="status",
        name="Availability",
        value_fn=lambda socket: _availability_label(socket.status.available),
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_mode3state",
        component="status",
        name="Mode 3 State",
        value_fn=lambda socket: socket.status.mode3_state,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_actualMaxCurrent",
        component="status",
        name="Actual applied max current",
        value_fn=lambda socket: socket.status.actual_max_current,
        **_CURRENT,
    ),
    AlfenSocketSensorDescription(
        key="maxCurrentValidTime_socket_{n}",
        component="status",
        name="Max current valid time",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda socket: socket.status.max_current_valid_time,
    ),
    AlfenSocketSensorDescription(
        key="maxCurrent_socket_{n}",
        component="status",
        name="Max current",
        value_fn=lambda socket: socket.status.max_current,
        **_CURRENT,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_saveCurrent",
        component="status",
        name="Active load balacing safe current",
        value_fn=lambda socket: socket.status.safe_current,
        **_CURRENT,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_setpointAccounted",
        component="status",
        name="Received SP accounted for",
        value_fn=lambda socket: socket.status.setpoint_accounted,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_chargephases",
        component="status",
        name="Charging Mode",
        value_fn=lambda socket: PHASE_LABELS.get(socket.status.phases),
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_carcharging",
        component="status",
        name="Car charging",
        value_fn=lambda socket: socket.charging,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_carconnected",
        component="status",
        name="Car connected",
        value_fn=lambda socket: socket.vehicle_connected,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_currentSession",
        component="meter",
        name="Current session Wh",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda socket: socket.session_energy,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_currentSessionDuration",
        component="status",
        name="Current session duration",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda socket: _seconds(socket.session_duration),
    ),
)


def _sensor_class(description: AlfenSensorDescription) -> type[_AlfenSensor]:
    """The entity class this description calls for.

    Only a total has to survive a restart, and Home Assistant writes every
    entity inheriting ``RestoreEntity`` to its restore store on a timer — so a
    plain reading does not carry the machinery.
    """
    return AlfenTotalSensor if description.is_total else AlfenSensor


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlfenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Alfen sensors."""
    coordinator = entry.runtime_data
    platform_name = entry.data[CONF_NAME]
    charger = coordinator.charger

    station_descriptions = list(STATION_SENSORS)
    if charger.station.scn is not None:
        station_descriptions += SCN_SENSORS
    entities: list[SensorEntity] = [
        _sensor_class(description)(
            coordinator,
            platform_name,
            description,
            key=description.key,
            label=description.name,
            component=description.component,
            read=partial(description.value_fn, charger),
        )
        for description in station_descriptions
    ]
    # Every configured socket gets its entities, even one the station is not
    # reporting yet: a socket that never answers stays unknown rather than
    # disappearing from the dashboard.
    for number, socket in charger.sockets.items():
        # A single-socket station has nothing to disambiguate, so it keeps the
        # bare label the integration showed before dual sockets were supported.
        prefix = f"S{number} " if len(charger.sockets) > 1 else ""
        entities += [
            _sensor_class(description)(
                coordinator,
                platform_name,
                description,
                key=description.key.format(n=number),
                label=f"{prefix}{description.name}",
                component=f"socket_{number}.{description.component}",
                read=partial(description.value_fn, socket),
            )
            for description in SOCKET_SENSORS
        ]
    async_add_entities(entities)


class _AlfenSensor(AlfenEntity, SensorEntity):
    """What both kinds of Alfen sensor share: the reading they are over.

    The station and each socket are separate units, so where a sensor reads
    from is settled when it is built — ``read`` is the description's value
    function bound to the charger or to one socket, and the key, label and
    report key are resolved the same way.
    """

    entity_description: AlfenSensorDescription

    def __init__(
        self,
        coordinator: AlfenCoordinator,
        platform_name: str,
        description: AlfenSensorDescription,
        *,
        key: str,
        label: str,
        component: str,
        read: Callable[[], Any],
    ) -> None:
        """Initialize the sensor over the reading ``read`` returns."""
        super().__init__(coordinator, platform_name, key, label, component)
        self.entity_description = description
        self._read = read

    def _reading(self) -> Any:
        """This sensor's value, rounded as this integration always has.

        The registers are IEEE floats, so an exact 232.5 V arrives as
        232.50000762939453; two decimals is all the meter resolves anyway.
        """
        value = self._read()
        return round(value, 2) if isinstance(value, float) else value


class AlfenSensor(_AlfenSensor):
    """An instantaneous reading, straight off the last poll."""

    @property
    def native_value(self) -> Any:
        """Whatever the last poll left on the device object."""
        return self._reading()


class AlfenTotalSensor(_AlfenSensor, RestoreSensor):
    """A counter, which holds its last value and outlives the charger.

    An unavailable counter gaps its long-term statistics and its energy
    dashboard, and a charger is legitimately off the network for a night. The
    trade: a total never reads unavailable even if the charger is gone for
    good. That is intended — for a counter, statistics continuity beats
    liveness, which belongs on a connectivity entity.
    """

    @property
    def available(self) -> bool:
        """Always available.

        A property rather than ``_attr_available``, because
        ``CoordinatorEntity.available`` is a property too — a class attribute
        would never be consulted, and the total would go unavailable exactly
        when the charger answers nothing.
        """
        return True

    async def async_added_to_hass(self) -> None:
        """Seed the total from the state it had before the restart."""
        await super().async_added_to_hass()
        if (last_data := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = last_data.native_value
        self._process_data()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._process_data()
        super()._handle_coordinator_update()

    def _process_data(self) -> None:
        """Take the reading, unless there is nothing to take.

        A reserved or absent register answers NaN, which decodes to None (spec
        §1.2) — through a *successful* poll, so staying available never covers
        it. Unknown gaps statistics just as badly as unavailable, so the total
        keeps what it had.
        """
        if (value := self._reading()) is not None:
            self._attr_native_value = value
