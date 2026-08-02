"""Maintenance buttons for SCSGATE."""

from __future__ import annotations

import inspect
import logging
from itertools import count

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ScsGateCoordinator

_LOGGER = logging.getLogger(__name__)
_BUTTON_OPERATION_COUNTER = count(1)

DESCRIPTIONS = (
    ButtonEntityDescription(key="refresh", name="Refresh status", icon="mdi:refresh"),
    ButtonEntityDescription(
        key="query_devices", name="Query devices", icon="mdi:format-list-bulleted"
    ),
    ButtonEntityDescription(
        key="resend_discovery", name="Resend MQTT discovery", icon="mdi:publish"
    ),
    ButtonEntityDescription(
        key="reconnect_mqtt", name="Reconnect MQTT", icon="mdi:connection"
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up safe maintenance buttons."""
    coordinator: ScsGateCoordinator = entry.runtime_data.coordinator
    async_add_entities(
        ScsGateButton(coordinator, description) for description in DESCRIPTIONS
    )


class ScsGateButton(CoordinatorEntity[ScsGateCoordinator], ButtonEntity):
    """Call a fixed, non-destructive gateway operation."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: ScsGateCoordinator, description: ButtonEntityDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        entry_key = (
            coordinator.config_entry.unique_id or coordinator.config_entry.entry_id
        )
        self._attr_unique_id = f"{entry_key}_{description.key}"
        self._attr_device_info = coordinator.device_info

    async def async_press(self) -> None:
        key = self.entity_description.key
        operation_id = f"button-{next(_BUTTON_OPERATION_COUNTER):06d}"
        _LOGGER.debug(
            "Maintenance button started operation_id=%s action=%s",
            operation_id,
            key,
        )
        try:
            if key == "refresh":
                await self.coordinator.async_request_refresh()
            else:
                if key == "query_devices":
                    result = self.coordinator.client.async_query_devices()
                elif key == "resend_discovery":
                    result = self.coordinator.client.async_mqtt_devices("resend")
                else:
                    result = self.coordinator.client.async_reset("mqtt")
                if inspect.isawaitable(result):
                    await result
                manager = getattr(
                    self.coordinator.config_entry.runtime_data,
                    "device_manager",
                    None,
                )
                if manager is not None and key in {
                    "query_devices",
                    "resend_discovery",
                    "reconnect_mqtt",
                }:
                    await manager.async_sync(f"button_{key}")
                await self.coordinator.async_request_refresh()
        except AttributeError as err:
            _LOGGER.debug(
                "Maintenance button failed operation_id=%s action=%s error_type=%s",
                operation_id,
                key,
                type(err).__name__,
            )
            raise HomeAssistantError(
                "Gateway firmware does not support this action"
            ) from err
        except Exception as err:
            _LOGGER.debug(
                "Maintenance button failed operation_id=%s action=%s error_type=%s",
                operation_id,
                key,
                type(err).__name__,
            )
            raise
        _LOGGER.debug(
            "Maintenance button completed operation_id=%s action=%s",
            operation_id,
            key,
        )
