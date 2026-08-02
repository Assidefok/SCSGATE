"""SCSGATE Home Assistant integration."""

from __future__ import annotations

import inspect
import logging
import re
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    ATTR_CMD,
    ATTR_CONFIRM,
    ATTR_ENTRY_ID,
    ATTR_FROM,
    ATTR_RESPONSE,
    ATTR_TO,
    ATTR_TYPE,
    CONF_ENABLE_RAW_COMMANDS,
    CONF_HOST,
    CONF_PORT,
    DOMAIN,
    PLATFORMS,
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
    )
    coordinator = ScsGateCoordinator(hass, client, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = ScsGateRuntimeData(client=client, coordinator=coordinator)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry.runtime_data
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload entry resources and entity platforms."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if not hass.data.get(DOMAIN):
            hass.services.async_remove(DOMAIN, SERVICE_SEND_RAW_TELEGRAM)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload on option changes."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register guarded raw SCS command service once per Home Assistant instance."""
    if hass.services.has_service(DOMAIN, SERVICE_SEND_RAW_TELEGRAM):
        return

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

    hass.services.async_register(
        DOMAIN, SERVICE_SEND_RAW_TELEGRAM, handle_raw_telegram, schema=SERVICE_SCHEMA
    )
