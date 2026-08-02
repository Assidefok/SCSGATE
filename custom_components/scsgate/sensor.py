"""Diagnostic sensors for SCSGATE."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ScsGateCoordinator


def _value(*names: str) -> Callable[[Any], Any]:
    return lambda data: next(
        (
            getattr(data, name, None)
            for name in names
            if getattr(data, name, None) is not None
        ),
        None,
    )


DESCRIPTIONS: tuple[tuple[SensorEntityDescription, Callable[[Any], Any]], ...] = (
    (
        SensorEntityDescription(key="firmware_esp", name="ESP firmware"),
        _value("firmware_esp", "firmware"),
    ),
    (
        SensorEntityDescription(key="firmware_pic", name="PIC firmware"),
        _value("firmware_pic"),
    ),
    (
        SensorEntityDescription(
            key="rssi", name="Wi-Fi RSSI", native_unit_of_measurement="dBm"
        ),
        _value("rssi"),
    ),
    # Broker details may expose topology; report only configured state.
    (
        SensorEntityDescription(key="mqtt_broker", name="MQTT broker"),
        lambda data: "Configured" if getattr(data, "mqtt_broker", None) else None,
    ),
    (
        SensorEntityDescription(key="known_devices", name="Known devices"),
        _value("device_count", "known_devices"),
    ),
    (
        SensorEntityDescription(key="last_census", name="Last census"),
        _value("last_census"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up status sensors."""
    coordinator: ScsGateCoordinator = entry.runtime_data.coordinator
    async_add_entities(
        ScsGateSensor(coordinator, description, getter)
        for description, getter in DESCRIPTIONS
    )


class ScsGateSensor(CoordinatorEntity[ScsGateCoordinator], SensorEntity):
    """Expose one safe status value."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ScsGateCoordinator,
        description: SensorEntityDescription,
        getter: Callable[[Any], Any],
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
    def native_value(self) -> Any:
        return self._getter(self.coordinator.data) if self.coordinator.data else None
