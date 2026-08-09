"""Constants for the Alfen Modbus integration."""

DOMAIN = "alfen_modbus"
DEFAULT_NAME = "alfen"
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_PORT = 502
DEFAULT_MODBUS_ADDRESS = 200
DEFAULT_READ_SCN = False
DEFAULT_READ_SOCKET2 = False

ATTR_MANUFACTURER = "Alfen"

CONF_MODBUS_ADDRESS = "modbus_address"
CONF_READ_SCN = "read_scn"
CONF_READ_SOCKET2 = "read_socket_2"

# Seconds of headroom on the max-current validity timer. The station reverts a
# socket to its safe current when the timer runs out, so a poll that leaves less
# than one polling interval plus this margin rewrites the setpoint (spec §1.3.1).
SETPOINT_RENEWAL_MARGIN = 10
