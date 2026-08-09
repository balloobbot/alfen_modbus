"""Sensors for the Alfen Modbus integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
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
from homeassistant.core import HomeAssistant
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
class AlfenStationSensorDescription(SensorEntityDescription):
    """A sensor reading a value off the station's own units."""

    value_fn: Callable[[AlfenCharger], Any]


@dataclass(frozen=True, kw_only=True)
class AlfenSocketSensorDescription(SensorEntityDescription):
    """A sensor reading a value off one socket unit.

    ``key`` is a template: the socket number fills ``{n}``, which reproduces the
    unique ids the integration has used since before the sockets were modelled.
    """

    value_fn: Callable[[AlfenSocket], Any]


STATION_SENSORS: tuple[AlfenStationSensorDescription, ...] = (
    AlfenStationSensorDescription(
        key="name",
        name="Name",
        value_fn=lambda charger: charger.station.product.name,
    ),
    AlfenStationSensorDescription(
        key="manufacturer",
        name="Manufacturer",
        value_fn=lambda charger: charger.station.product.manufacturer,
    ),
    AlfenStationSensorDescription(
        key="modbustableVersion",
        name="Modbus table version",
        value_fn=lambda charger: charger.station.product.modbus_table_version,
    ),
    AlfenStationSensorDescription(
        key="firmwareVersion",
        name="Firmware version",
        value_fn=lambda charger: charger.station.product.firmware_version,
    ),
    AlfenStationSensorDescription(
        key="platformType",
        name="Platform Type",
        value_fn=lambda charger: charger.station.product.platform_type,
    ),
    AlfenStationSensorDescription(
        key="serial",
        name="Serial",
        value_fn=lambda charger: charger.station.product.serial_number,
    ),
    AlfenStationSensorDescription(
        key="stationTime",
        name="Current time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda charger: charger.station.time,
    ),
    AlfenStationSensorDescription(
        key="lastBoot",
        name="Last boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda charger: charger.station.last_boot,
    ),
    AlfenStationSensorDescription(
        key="actualMaxCurrent",
        name="Actual max current",
        icon="mdi:current-dc",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda charger: charger.station.status.max_current,
    ),
    AlfenStationSensorDescription(
        key="boardTemperature",
        name="Board temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda charger: charger.station.status.temperature,
    ),
    AlfenStationSensorDescription(
        key="backofficeConnected",
        name="Backoffice connected",
        value_fn=lambda charger: charger.station.status.backoffice_connected,
    ),
    AlfenStationSensorDescription(
        key="numberOfSockets",
        name="Number of sockets",
        value_fn=lambda charger: charger.station.status.socket_count,
    ),
)

SCN_SENSORS: tuple[AlfenStationSensorDescription, ...] = (
    AlfenStationSensorDescription(
        key="scnName",
        name="SCN Name",
        value_fn=lambda charger: charger.station.scn and charger.station.scn.name,
    ),
    AlfenStationSensorDescription(
        key="scnSockets",
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
        name="Meter state",
        value_fn=lambda socket: _meter_state_label(socket.meter.meter_state),
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_meterAge",
        name="Meter reading age",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda socket: socket.meter.meter_timestamp,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_meterType",
        name="Meter Type",
        value_fn=lambda socket: METER_TYPE_LABELS.get(socket.meter.meter_type),
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_VL1-N",
        name="Voltage L1-N",
        value_fn=lambda socket: socket.meter.voltage_l1_n,
        **_VOLTAGE,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_VL2-N",
        name="Voltage L2-N",
        value_fn=lambda socket: socket.meter.voltage_l2_n,
        **_VOLTAGE,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_VL3-N",
        name="Voltage L3-N",
        value_fn=lambda socket: socket.meter.voltage_l3_n,
        **_VOLTAGE,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_VL1-L2",
        name="Voltage L1-L2",
        value_fn=lambda socket: socket.meter.voltage_l1_l2,
        **_VOLTAGE,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_VL2-L3",
        name="Voltage L2-L3",
        value_fn=lambda socket: socket.meter.voltage_l2_l3,
        **_VOLTAGE,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_VL3-L1",
        name="Voltage L3-L1",
        value_fn=lambda socket: socket.meter.voltage_l3_l1,
        **_VOLTAGE,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_currentN",
        name="Current N",
        value_fn=lambda socket: socket.meter.current_n,
        **_CURRENT,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_currentL1",
        name="Current L1",
        value_fn=lambda socket: socket.meter.current_l1,
        **_CURRENT,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_currentL2",
        name="Current L2",
        value_fn=lambda socket: socket.meter.current_l2,
        **_CURRENT,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_currentL3",
        name="Current L3",
        value_fn=lambda socket: socket.meter.current_l3,
        **_CURRENT,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_currentSum",
        name="Current Total",
        value_fn=lambda socket: socket.meter.current_sum,
        **_CURRENT,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_powerL1",
        name="Power factor L1",
        value_fn=lambda socket: socket.meter.power_factor_l1,
        **_POWER_FACTOR,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_powerL2",
        name="Power factor L2",
        value_fn=lambda socket: socket.meter.power_factor_l2,
        **_POWER_FACTOR,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_powerL3",
        name="Power factor L3",
        value_fn=lambda socket: socket.meter.power_factor_l3,
        **_POWER_FACTOR,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_powerSum",
        name="Power factor sum",
        value_fn=lambda socket: socket.meter.power_factor_sum,
        **_POWER_FACTOR,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_frequency",
        name="Frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda socket: socket.meter.frequency,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realPowerL1",
        name="Real power L1",
        value_fn=lambda socket: socket.meter.real_power_l1,
        **_REAL_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realPowerL2",
        name="Real power L2",
        value_fn=lambda socket: socket.meter.real_power_l2,
        **_REAL_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realPowerL3",
        name="Real power L3",
        value_fn=lambda socket: socket.meter.real_power_l3,
        **_REAL_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realPowerSum",
        name="Real power sum",
        value_fn=lambda socket: socket.meter.real_power_sum,
        **_REAL_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_apparantPowerL1",
        name="Apparant power L1",
        value_fn=lambda socket: socket.meter.apparent_power_l1,
        **_APPARENT_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_apparantPowerL2",
        name="Apparant power L2",
        value_fn=lambda socket: socket.meter.apparent_power_l2,
        **_APPARENT_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_apparantPowerL3",
        name="Apparant power L3",
        value_fn=lambda socket: socket.meter.apparent_power_l3,
        **_APPARENT_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_apparantPowerSum",
        name="Apparant power sum",
        value_fn=lambda socket: socket.meter.apparent_power_sum,
        **_APPARENT_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_reactivePowerL1",
        name="Reactive power L1",
        value_fn=lambda socket: socket.meter.reactive_power_l1,
        **_REACTIVE_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_reactivePowerL2",
        name="Reactive power L2",
        value_fn=lambda socket: socket.meter.reactive_power_l2,
        **_REACTIVE_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_reactivePowerL3",
        name="Reactive power L3",
        value_fn=lambda socket: socket.meter.reactive_power_l3,
        **_REACTIVE_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_reactivePowerSum",
        name="Reactive power sum",
        value_fn=lambda socket: socket.meter.reactive_power_sum,
        **_REACTIVE_POWER,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realEnergyDeliveredL1",
        name="Real energy delivered L1",
        value_fn=lambda socket: socket.meter.real_energy_delivered_l1,
        **_REAL_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realEnergyDeliveredL2",
        name="Real energy delivered L2",
        value_fn=lambda socket: socket.meter.real_energy_delivered_l2,
        **_REAL_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realEnergyDeliveredL3",
        name="Real energy delivered L3",
        value_fn=lambda socket: socket.meter.real_energy_delivered_l3,
        **_REAL_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realEnergyDeliveredSum",
        name="Real energy delivered sum",
        value_fn=lambda socket: socket.meter.real_energy_delivered_sum,
        **_REAL_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realEnergyConsumedL1",
        name="Real energy consumed L1",
        value_fn=lambda socket: socket.meter.real_energy_consumed_l1,
        **_REAL_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realEnergyConsumedL2",
        name="Real energy consumed L2",
        value_fn=lambda socket: socket.meter.real_energy_consumed_l2,
        **_REAL_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realEnergyConsumedL3",
        name="Real energy consumed L3",
        value_fn=lambda socket: socket.meter.real_energy_consumed_l3,
        **_REAL_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_realEnergyConsumedSum",
        name="Real energy consumed sum",
        value_fn=lambda socket: socket.meter.real_energy_consumed_sum,
        **_REAL_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_apparantEnergyL1",
        name="Apparant energy L1",
        value_fn=lambda socket: socket.meter.apparent_energy_l1,
        **_APPARENT_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_apparantEnergyL2",
        name="Apparant energy L2",
        value_fn=lambda socket: socket.meter.apparent_energy_l2,
        **_APPARENT_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_apparantEnergyL3",
        name="Apparant energy L3",
        value_fn=lambda socket: socket.meter.apparent_energy_l3,
        **_APPARENT_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_apparantEnergySum",
        name="Apparant energy sum",
        value_fn=lambda socket: socket.meter.apparent_energy_sum,
        **_APPARENT_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_reactiveEnergyL1",
        name="Reactive energy L1",
        value_fn=lambda socket: socket.meter.reactive_energy_l1,
        **_REACTIVE_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_reactiveEnergyL2",
        name="Reactive energy L2",
        value_fn=lambda socket: socket.meter.reactive_energy_l2,
        **_REACTIVE_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_reactiveEnergyL3",
        name="Reactive energy L3",
        value_fn=lambda socket: socket.meter.reactive_energy_l3,
        **_REACTIVE_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_reactiveEnergySum",
        name="Reactive energy sum",
        value_fn=lambda socket: socket.meter.reactive_energy_sum,
        **_REACTIVE_ENERGY,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_available",
        name="Availability",
        value_fn=lambda socket: _availability_label(socket.status.available),
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_mode3state",
        name="Mode 3 State",
        value_fn=lambda socket: socket.status.mode3_state,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_actualMaxCurrent",
        name="Actual applied max current",
        value_fn=lambda socket: socket.status.actual_max_current,
        **_CURRENT,
    ),
    AlfenSocketSensorDescription(
        key="maxCurrentValidTime_socket_{n}",
        name="Max current valid time",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda socket: socket.status.max_current_valid_time,
    ),
    AlfenSocketSensorDescription(
        key="maxCurrent_socket_{n}",
        name="Max current",
        value_fn=lambda socket: socket.status.max_current,
        **_CURRENT,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_saveCurrent",
        name="Active load balacing safe current",
        value_fn=lambda socket: socket.status.safe_current,
        **_CURRENT,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_setpointAccounted",
        name="Received SP accounted for",
        value_fn=lambda socket: socket.status.setpoint_accounted,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_chargephases",
        name="Charging Mode",
        value_fn=lambda socket: PHASE_LABELS.get(socket.status.phases),
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_carcharging",
        name="Car charging",
        value_fn=lambda socket: socket.charging,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_carconnected",
        name="Car connected",
        value_fn=lambda socket: socket.vehicle_connected,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_currentSession",
        name="Current session Wh",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda socket: socket.session_energy,
    ),
    AlfenSocketSensorDescription(
        key="socket_{n}_currentSessionDuration",
        name="Current session duration",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda socket: _seconds(socket.session_duration),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlfenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Alfen sensors."""
    coordinator = entry.runtime_data
    platform_name = entry.data[CONF_NAME]
    charger = coordinator.charger

    entities: list[SensorEntity] = [
        AlfenStationSensor(coordinator, platform_name, description)
        for description in STATION_SENSORS
    ]
    if charger.station.scn is not None:
        entities += [
            AlfenStationSensor(coordinator, platform_name, description)
            for description in SCN_SENSORS
        ]
    # Every configured socket gets its entities, even one the station is not
    # reporting yet: a socket that never answers stays unknown rather than
    # disappearing from the dashboard.
    entities += [
        AlfenSocketSensor(coordinator, platform_name, description, number)
        for number in charger.sockets
        for description in SOCKET_SENSORS
    ]
    async_add_entities(entities)


class AlfenSensor(AlfenEntity, SensorEntity):
    """Shared rounding for the station's float readings."""

    def _rounded(self, value: Any) -> Any:
        """Round a reading to two decimals, as this integration always has.

        The registers are IEEE floats, so an exact 232.5 V arrives as
        232.50000762939453; two decimals is all the meter resolves anyway.
        """
        return round(value, 2) if isinstance(value, float) else value


class AlfenStationSensor(AlfenSensor):
    """A sensor over the station's identification, status or SCN registers."""

    entity_description: AlfenStationSensorDescription

    def __init__(
        self,
        coordinator: AlfenCoordinator,
        platform_name: str,
        description: AlfenStationSensorDescription,
    ) -> None:
        """Initialize the sensor from its description."""
        super().__init__(coordinator, platform_name, description.key, description.name)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the station reading."""
        return self._rounded(self.entity_description.value_fn(self.coordinator.charger))


class AlfenSocketSensor(AlfenSensor):
    """A sensor over one socket unit's registers."""

    entity_description: AlfenSocketSensorDescription

    def __init__(
        self,
        coordinator: AlfenCoordinator,
        platform_name: str,
        description: AlfenSocketSensorDescription,
        number: int,
    ) -> None:
        """Initialize the sensor for socket ``number``."""
        # A single-socket station has nothing to disambiguate, so it keeps the
        # bare label the integration showed before dual sockets were supported.
        label = description.name
        if len(coordinator.charger.sockets) > 1:
            label = f"S{number} {label}"
        super().__init__(
            coordinator, platform_name, description.key.format(n=number), label
        )
        self.entity_description = description
        self._number = number

    @property
    def native_value(self) -> Any:
        """Return the socket reading."""
        socket = self.coordinator.charger.sockets[self._number]
        return self._rounded(self.entity_description.value_fn(socket))
