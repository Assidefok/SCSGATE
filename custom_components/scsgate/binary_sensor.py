"""Connectivity binary sensors for SCSGATE."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ScsGateCoordinator

DESCRIPTIONS: tuple[
    tuple[BinarySensorEntityDescription, Callable[[Any], bool]], ...
] = (
    (
        BinarySensorEntityDescription(
            key="gateway_connected",
            name="Gateway connected",
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
        ),
        lambda data: data is not None,
    ),
    (
        BinarySensorEntityDescription(
            key="mqtt_connected",
            name="MQTT connected",
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
        ),
        lambda data: bool(getattr(data, "mqtt_connected", False)),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up connectivity sensors."""
    coordinator: ScsGateCoordinator = entry.runtime_data.coordinator
    async_add_entities(
        ScsGateBinarySensor(coordinator, description, getter)
        for description, getter in DESCRIPTIONS
    )


class ScsGateBinarySensor(CoordinatorEntity[ScsGateCoordinator], BinarySensorEntity):
    """Expose gateway connectivity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ScsGateCoordinator,
        description: BinarySensorEntityDescription,
        getter: Callable[[Any], bool],
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._getter = getter
        entry_key = (
            coordinator.config_entry.unique_id or coordinator.config_entry.entry_id
        )
        self._attr_unique_id = f"{entry_key}_{description.key}"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        return self._getter(self.coordinator.data)
