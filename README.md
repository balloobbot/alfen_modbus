# Alfen Modbus for Home Assistant

[![HACS Default](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/straybiker/alfen_modbus)](https://github.com/thastealth/alfen_modbus/releases)
[![License](https://img.shields.io/github/license/thastealth/alfen_modbus)](LICENSE)

Home Assistant integration for **Alfen Eve NG9xx** series EV chargers via Modbus TCP.

![Demo](demo.png)

## Features

- 🔌 **Real-time monitoring** - Voltage, current, power, energy for all phases
- 🚗 **Car status detection** - Connected, charging, disconnected states
- ⚡ **Load balancing control** - Set maximum charging current dynamically
- �️ **Max current protection** - Prevents setting current above station limit
- �📊 **Session tracking** - Energy consumed and duration per charging session
- 🔄 **Auto-renew max current** - Prevents timeout to safe current mode
- 🏢 **Multi-socket support** - Works with dual socket chargers
- 🌐 **SCN support** - Smart Charging Network (partial)

## Requirements

- Home Assistant **2024.4.0** or newer
- Alfen Eve NG9xx charger with:
  - Firmware **4.2.0** or newer (Modbus TCP support)
  - Firmware **6.4.0+** recommended (fixes power budget reset bug)
  - **Active Load Balancing** license enabled
- Modbus TCP enabled on the charger

## Architecture

The integration talks to the charger through
[modbus-connection](https://home-assistant-libs.github.io/modbus-connection/). An
Alfen station is **one TCP link carrying several Modbus units** — the station's
own registers answer on slave 200, and each socket answers on slave 1 or 2 — so
the integration opens a single connection and addresses each unit through
`for_unit()`.

The register map lives in `custom_components/alfen_modbus/alfen/`, a device
library with no Home Assistant imports: it declares each register block as a
typed component and is tested against modbus-connection's in-memory mock, with
no charger and no Home Assistant in the loop.

A poll reads each block on its own, so one block the station refuses or is slow
to answer does not take the rest of the poll with it: `async_update()` returns
an `UpdateReport` naming the failed ones (`station.product`, `socket_1.meter`)
with their errors, and only that block's own entities go unavailable while
every other block refreshes. A dead link raises, and so does a station that
does not answer its first block at all: reading the rest would only pay a
timeout each.

Energy totals are the exception: they hold their last value and restore it
across a restart, so a charger that is off the network overnight — or a meter
answering NaN, or a counter read mid-update — does not gap its long-term
statistics.

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Search for "Alfen Modbus"
3. Click Install
4. Restart Home Assistant

### Manual

1. Copy `custom_components/alfen_modbus` to your `config/custom_components/` folder
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for **Alfen Modbus**
4. Enter your charger's IP address and port (default: 502)

## Enabling Modbus on Alfen Charger

1. Acquire the **Active Load Balancing** license from Alfen
2. Enable **Active Load Balancing** via the Alfen Service Installer app
3. Set **Data Source** to "Energy Management System" for slave mode

See the [Alfen Smart Charging Manual](https://knowledge.alfen.com/space/IN/639762449) for details.

## Sensors

| Category | Sensors |
|----------|---------|
| **Device** | Name, Manufacturer, Serial, Firmware, Platform |
| **Station** | Max Current, Temperature, Backoffice Connection |
| **Socket** | Voltages (L1-N, L2-N, L3-N, L1-L2, L2-L3, L3-L1) |
| | Currents (L1, L2, L3, N, Sum) |
| | Power (Real, Apparent, Reactive per phase + Sum) |
| | Energy (Delivered, Consumed per phase + Sum) |
| | Mode 3 State, Availability, Charging Phases |
| **Derived** | Car Connected, Car Charging, Session Wh, Session Duration |

## Controls

| Control | Description |
|---------|-------------|
| **Max Current** | Set the maximum charging current (load balancing) |
| **Phase Mode** | Select 1-phase or 3-phase charging |

## Known Issues

- Power budget may reset to 0A when no car is connected (fixed in firmware [6.4.0-4210](https://knowledge.alfen.com/space/IN/243466257))
- **Reallin power meter (post-2021)**: Chargers with a Reallin power meter produced after 2021 only export a subset of measurement values. Per-phase energy, apparent energy, and reactive energy sensors will show as "unavailable" (NaN). This is a hardware limitation, not a bug.

## Development

```bash
uv sync         # dev environment, including Home Assistant
uv run pytest   # device library + integration tests, no hardware needed
```

`simulator/` runs a fake Alfen station to test against; see
[`MIGRATION-NOTES.md`](MIGRATION-NOTES.md) for how the register map is modelled
and what changed when the integration moved to modbus-connection.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the Apache 2.0 License - see the [LICENSE](LICENSE) file for details.
