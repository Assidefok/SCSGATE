"""Diagnostics with secret-safe output."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from .const import DOMAIN

_REDACT = {
    "password",
    "pass",
    "ssid",
    "wifi_ssid",
    "username",
    "broker",
    "mqtt_broker",
    "url",
    "callback",
    "host",
    "mac",
    "token",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return safe, local diagnostic information."""
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    data = getattr(runtime.coordinator, "data", None) if runtime else None
    status = (
        asdict(data)
        if data is not None and is_dataclass(data)
        else {"available": data is not None}
    )
    options = dict(entry.options)
    if "last_device_snapshot" in options:
        options["last_device_snapshot"] = "[redacted]"
    transport = getattr(getattr(runtime, "client", None), "debug_metrics", {})
    protocol_debug = getattr(
        getattr(runtime, "client", None), "protocol_debug_diagnostics", {}
    )
    bus_monitor = getattr(getattr(runtime, "bus_monitor", None), "diagnostics", {})
    advanced_debug = getattr(
        getattr(runtime, "advanced_debug", None), "diagnostics", {}
    )
    return async_redact_data(
        {
            "entry": dict(entry.data),
            "options": options,
            "status": status,
            "transport": transport,
            "protocol_debug": protocol_debug,
            "bus_monitor": bus_monitor,
            "advanced_debug": advanced_debug,
        },
        _REDACT,
    )
