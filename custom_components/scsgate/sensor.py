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
    entities: list[SensorEntity] = [
        ScsGateSensor(coordinator, description, getter)
        for description, getter in DESCRIPTIONS
    ]
    monitor = getattr(entry.runtime_data, "bus_monitor", None)
    if monitor is not None:
        entities.append(ScsGateBusMonitorSensor(coordinator, monitor))
    async_add_entities(entities)


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


class ScsGateBusMonitorSensor(SensorEntity):
    """Expose safe monitor counts; raw content stays out of entity state/history."""

    _attr_has_entity_name = True
    _attr_name = "Broker bus monitor"
    _attr_icon = "mdi:message-text-fast-outline"
    _attr_native_unit_of_measurement = "messages"

    def __init__(self, coordinator: ScsGateCoordinator, monitor: Any) -> None:
        self._monitor = monitor
        entry_key = (
            coordinator.config_entry.unique_id or coordinator.config_entry.entry_id
        )
        self._attr_unique_id = f"{entry_key}_bus_monitor"
        self._attr_device_info = coordinator.device_info

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._monitor.async_add_listener(self.async_write_ha_state)
        )

    @property
    def native_value(self) -> int:
        return self._monitor.retained_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        diagnostics = self._monitor.diagnostics
        return {
            "enabled": diagnostics["enabled"],
            "raw_uart_seen": diagnostics["raw_uart_seen"],
            "received_total": diagnostics["received_total"],
            "discarded_total": diagnostics["discarded_total"],
            "last_message_at": self._monitor.last_message_at,
        }
