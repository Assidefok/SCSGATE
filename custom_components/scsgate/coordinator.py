"""Data coordination for SCSGATE."""

from __future__ import annotations

import inspect
import logging
from dataclasses import replace
from datetime import timedelta
from time import monotonic
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_LAST_CENSUS, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .models import GatewayStatus

_LOGGER = logging.getLogger(__name__)


async def _maybe_await(value: Any) -> Any:
    """Await a value only when protocol client made it awaitable."""
    if inspect.isawaitable(value):
        return await value
    return value


class ScsGateCoordinator(DataUpdateCoordinator[Any]):
    """Fetch gateway status while keeping transport details in api.py."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, client: Any, entry: ConfigEntry) -> None:
        self.client = client
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )
        # DataUpdateCoordinator initializes this attribute itself; assign the
        # owning entry afterwards so current Home Assistant cannot reset it.
        self.config_entry = entry

    async def _async_update_data(self) -> Any:
        """Read status through the protocol client's stable public method."""
        started = monotonic()
        _LOGGER.debug("Coordinator refresh started")
        try:
            method = getattr(self.client, "async_get_status", None)
            if method is None:
                method = self.client.get_status
            status = await _maybe_await(method())
            last_census = self.config_entry.options.get(CONF_LAST_CENSUS)
            if last_census and isinstance(status, GatewayStatus):
                status = replace(status, last_census=last_census)
            _LOGGER.debug(
                "Coordinator refresh completed duration_ms=%s status_available=%s",
                max(0, round((monotonic() - started) * 1000)),
                status is not None,
            )
            return status
        except (HomeAssistantError, OSError, TimeoutError) as err:
            _LOGGER.debug(
                "Coordinator refresh failed duration_ms=%s error_type=%s",
                max(0, round((monotonic() - started) * 1000)),
                type(err).__name__,
            )
            raise UpdateFailed("Unable to reach SCSGATE") from err
        except (
            Exception
        ) as err:  # API parser/transport implementations are isolated here.
            _LOGGER.debug(
                "Coordinator refresh rejected duration_ms=%s error_type=%s",
                max(0, round((monotonic() - started) * 1000)),
                type(err).__name__,
            )
            raise UpdateFailed("Unable to update SCSGATE status") from err

    @property
    def device_info(self) -> DeviceInfo:
        """Return common Home Assistant device metadata."""
        data = self.data
        mac = (
            getattr(data, "mac", None)
            or self.config_entry.unique_id
            or self.config_entry.entry_id
        )
        firmware = getattr(data, "firmware_esp", None) or getattr(
            data, "firmware", None
        )
        return DeviceInfo(
            identifiers={(DOMAIN, str(mac))},
            name=f"SCSGATE {mac}",
            manufacturer="SCSGATE",
            model="ESP32_SCSGATE",
            sw_version=str(firmware) if firmware else None,
            configuration_url=(
                f"http://{self.config_entry.data.get('host')}:"
                f"{self.config_entry.data.get('port', 80)}"
            ),
        )
