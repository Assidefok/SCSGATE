"""Maintenance buttons for SCSGATE."""

from __future__ import annotations

import inspect

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ScsGateCoordinator

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
        if key == "refresh":
            await self.coordinator.async_request_refresh()
            return
        try:
            if key == "query_devices":
                result = self.coordinator.client.async_query_devices()
            elif key == "resend_discovery":
                result = self.coordinator.client.async_mqtt_devices("resend")
            else:
                result = self.coordinator.client.async_reset("mqtt")
        except AttributeError as err:
            raise HomeAssistantError(
                "Gateway firmware does not support this action"
            ) from err
        if inspect.isawaitable(result):
            await result
        await self.coordinator.async_request_refresh()
