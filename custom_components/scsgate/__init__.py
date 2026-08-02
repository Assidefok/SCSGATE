"""SCSGATE Home Assistant integration."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .bus_monitor import BusMonitor
from .const import (
    ATTR_CMD,
    ATTR_CONFIRM,
    ATTR_ENTRY_ID,
    ATTR_FROM,
    ATTR_LIMIT,
    ATTR_RESPONSE,
    ATTR_TO,
    ATTR_TYPE,
    CONF_BUS_MONITOR,
    CONF_BUS_MONITOR_LIMIT,
    CONF_ENABLE_RAW_COMMANDS,
    CONF_HOST,
    CONF_PORT,
    CONF_PROTOCOL_DEBUG,
    DATA_BUS_MONITOR,
    DATA_BUS_MONITOR_LOCK,
    DEFAULT_BUS_MONITOR_LIMIT,
    DOMAIN,
    PLATFORMS,
    SERVICE_CLEAR_BUS_LOG,
    SERVICE_EXPORT_BUS_LOG,
    SERVICE_SEND_RAW_TELEGRAM,
    VALID_RESPONSES,
)
from .coordinator import ScsGateCoordinator

_HEX = re.compile(r"^[0-9A-Fa-f]+$")
_LOGGER = logging.getLogger(__name__)


@dataclass
class ScsGateRuntimeData:
    """Runtime-only entry resources."""

    client: Any
    coordinator: ScsGateCoordinator
    bus_monitor: BusMonitor | None = None


async def _async_acquire_bus_monitor(
    hass: HomeAssistant, entry_id: str, message_limit: int
) -> BusMonitor:
    """Atomically create or share the single broker-wide monitor."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    monitor_lock = domain_data.setdefault(DATA_BUS_MONITOR_LOCK, asyncio.Lock())
    async with monitor_lock:
        monitor = domain_data.get(DATA_BUS_MONITOR)
        if not isinstance(monitor, BusMonitor):
            monitor = BusMonitor(hass, enabled=False)
        await monitor.async_acquire(entry_id, message_limit)
        domain_data[DATA_BUS_MONITOR] = monitor
        return monitor


def _valid_hex(value: str) -> str:
    """Validate a non-empty hexadecimal telegram component."""
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise vol.Invalid("must be a non-empty hexadecimal string")
    return value.upper()


SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTRY_ID): str,
        vol.Required(ATTR_TYPE): _valid_hex,
        vol.Required(ATTR_FROM): _valid_hex,
        vol.Required(ATTR_TO): _valid_hex,
        vol.Required(ATTR_CMD): _valid_hex,
        vol.Optional(ATTR_RESPONSE, default="none"): vol.In(VALID_RESPONSES),
        vol.Required(ATTR_CONFIRM): True,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a SCSGATE config entry."""
    from .api import GatewayClient

    client = GatewayClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, 80),
        protocol_debug=entry.options.get(CONF_PROTOCOL_DEBUG, False),
    )
    coordinator = ScsGateCoordinator(hass, client, entry)
    await coordinator.async_config_entry_first_refresh()
    bus_monitor: BusMonitor | None = None
    if entry.options.get(CONF_BUS_MONITOR, False):
        bus_monitor = await _async_acquire_bus_monitor(
            hass,
            entry.entry_id,
            entry.options.get(CONF_BUS_MONITOR_LIMIT, DEFAULT_BUS_MONITOR_LIMIT),
        )
    entry.runtime_data = ScsGateRuntimeData(
        client=client, coordinator=coordinator, bus_monitor=bus_monitor
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry.runtime_data
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        _async_register_services(hass)
        entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    except Exception:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if bus_monitor is not None:
            async with hass.data[DOMAIN][DATA_BUS_MONITOR_LOCK]:
                await bus_monitor.async_release(entry.entry_id)
                if not bus_monitor.enabled:
                    hass.data[DOMAIN].pop(DATA_BUS_MONITOR, None)
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload entry resources and entity platforms."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        monitor = getattr(runtime, "bus_monitor", None)
        if monitor is not None:
            async with hass.data[DOMAIN][DATA_BUS_MONITOR_LOCK]:
                await monitor.async_release(entry.entry_id)
                if not monitor.enabled:
                    hass.data[DOMAIN].pop(DATA_BUS_MONITOR, None)
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if not any(
            isinstance(value, ScsGateRuntimeData)
            for value in hass.data.get(DOMAIN, {}).values()
        ):
            hass.services.async_remove(DOMAIN, SERVICE_SEND_RAW_TELEGRAM)
            hass.services.async_remove(DOMAIN, SERVICE_EXPORT_BUS_LOG)
            hass.services.async_remove(DOMAIN, SERVICE_CLEAR_BUS_LOG)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload on option changes."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register guarded raw SCS command service once per Home Assistant instance."""

    async def handle_raw_telegram(call: ServiceCall) -> None:
        runtime = hass.data.get(DOMAIN, {}).get(call.data[ATTR_ENTRY_ID])
        if runtime is None:
            raise HomeAssistantError("Unknown SCSGATE entry")
        entry = runtime.coordinator.config_entry
        if not entry.options.get(CONF_ENABLE_RAW_COMMANDS, False):
            raise HomeAssistantError("Raw SCS commands are disabled for this gateway")
        method = getattr(runtime.client, "async_send_raw_telegram", None)
        if method is None:
            raise HomeAssistantError("Gateway firmware does not support raw telegrams")
        try:
            # Positional call intentionally matches GatewayClient's public contract.
            result = method(
                call.data[ATTR_TYPE],
                call.data[ATTR_FROM],
                call.data[ATTR_TO],
                call.data[ATTR_CMD],
                call.data[ATTR_RESPONSE],
            )
            if inspect.isawaitable(result):
                await result
            hass.bus.async_fire(
                f"{DOMAIN}_raw_telegram",
                {
                    "entry_id": call.data[ATTR_ENTRY_ID],
                    "response": call.data[ATTR_RESPONSE],
                    "field_lengths": {
                        "type": len(call.data[ATTR_TYPE]),
                        "from": len(call.data[ATTR_FROM]),
                        "to": len(call.data[ATTR_TO]),
                        "cmd": len(call.data[ATTR_CMD]),
                    },
                },
            )
            _LOGGER.info(
                "Sent confirmed raw SCS telegram for entry %s", call.data[ATTR_ENTRY_ID]
            )
        except (HomeAssistantError, OSError, TimeoutError) as err:
            raise HomeAssistantError("Raw SCS telegram failed") from err
        except Exception as err:
            raise HomeAssistantError("Raw SCS telegram rejected by gateway") from err

    def get_monitor(call: ServiceCall) -> BusMonitor:
        runtime = hass.data.get(DOMAIN, {}).get(call.data[ATTR_ENTRY_ID])
        monitor = getattr(runtime, "bus_monitor", None)
        if monitor is None or not monitor.enabled:
            raise HomeAssistantError("Bus monitor is disabled for this gateway")
        return monitor

    async def handle_export_bus_log(call: ServiceCall) -> dict[str, Any]:
        return get_monitor(call).export(call.data[ATTR_LIMIT])

    async def handle_clear_bus_log(call: ServiceCall) -> None:
        get_monitor(call).clear()

    if not hass.services.has_service(DOMAIN, SERVICE_SEND_RAW_TELEGRAM):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_RAW_TELEGRAM,
            handle_raw_telegram,
            schema=SERVICE_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_EXPORT_BUS_LOG):
        hass.services.async_register(
            DOMAIN,
            SERVICE_EXPORT_BUS_LOG,
            handle_export_bus_log,
            schema=vol.Schema(
                {
                    vol.Required(ATTR_ENTRY_ID): str,
                    vol.Optional(
                        ATTR_LIMIT, default=DEFAULT_BUS_MONITOR_LIMIT
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=500)),
                    vol.Required(ATTR_CONFIRM): True,
                }
            ),
            supports_response=SupportsResponse.ONLY,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_CLEAR_BUS_LOG):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CLEAR_BUS_LOG,
            handle_clear_bus_log,
            schema=vol.Schema(
                {
                    vol.Required(ATTR_ENTRY_ID): str,
                    vol.Required(ATTR_CONFIRM): True,
                }
            ),
        )
