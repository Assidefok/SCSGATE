"""Constants for SCSGATE."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "scsgate"
PLATFORMS: Final = ["binary_sensor", "button", "sensor"]

CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_ENABLE_RAW_COMMANDS: Final = "enable_raw_commands"
CONF_PROTOCOL_DEBUG: Final = "enable_protocol_debug"
CONF_BUS_MONITOR: Final = "enable_bus_monitor"
CONF_BUS_MONITOR_LIMIT: Final = "bus_monitor_limit"
CONF_LAST_CENSUS: Final = "last_census"

DEFAULT_PORT: Final = 80
DEFAULT_SCAN_INTERVAL: Final = 300
DEFAULT_BUS_MONITOR_LIMIT: Final = 100
MAX_CALLBACK_LENGTH: Final = 97

DATA_CLIENT: Final = "client"
DATA_COORDINATOR: Final = "coordinator"
DATA_BUS_MONITOR: Final = "_broker_bus_monitor"
DATA_BUS_MONITOR_LOCK: Final = "_broker_bus_monitor_lock"

SERVICE_SEND_RAW_TELEGRAM: Final = "send_raw_telegram"
SERVICE_EXPORT_BUS_LOG: Final = "export_bus_log"
SERVICE_CLEAR_BUS_LOG: Final = "clear_bus_log"
ATTR_LIMIT: Final = "limit"
ATTR_ENTRY_ID: Final = "entry_id"
ATTR_TYPE: Final = "type"
ATTR_FROM: Final = "from"
ATTR_TO: Final = "to"
ATTR_CMD: Final = "cmd"
ATTR_RESPONSE: Final = "response"
ATTR_CONFIRM: Final = "confirm"

VALID_RESPONSES: Final = frozenset({"none", "y", "i"})
