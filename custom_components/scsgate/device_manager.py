"""Central SCS device inventory and MQTT Discovery reconciliation."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from homeassistant.components import mqtt
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from .const import DATA_DISCOVERY_OWNER, DOMAIN
from .models import GatewayDevice

_LOGGER = logging.getLogger(__name__)
DISCOVERY_PREFIX: Final = "homeassistant"
ORIGIN: Final = {
    "name": "SCSGATE",
    "sw_version": "0.4.0",
    "support_url": "https://github.com/Assidefok/SCSGATE",
}
SUPPORTED_TYPES: Final = frozenset({1, 3, 4, 8, 9, 18, 19})


def claim_global_namespace(domain_data: dict[str, Any], entry_id: str) -> bool:
    """Claim firmware's single global scs namespace for one config entry."""
    owner = domain_data.get(DATA_DISCOVERY_OWNER)
    if owner is not None and owner != entry_id:
        return False
    domain_data[DATA_DISCOVERY_OWNER] = entry_id
    return True


@dataclass(frozen=True, slots=True)
class ManagedDevice:
    """One row in the SCSGATE Device Manager."""

    bus_id: str
    device_type: int | None
    name: str
    component: str | None
    entity_id: str | None
    mqtt_device_id: str | None
    health: str


def discovery_component(
    device_type: int | None, type1_mode: str = "switch"
) -> str | None:
    """Map firmware 7.004 device types to supported HA MQTT components."""
    if device_type == 1:
        return "light" if type1_mode == "light" else "switch"
    if device_type in {3, 4}:
        return "light"
    if device_type in {8, 9, 18, 19}:
        return "cover"
    return None


def discovery_topic(device: GatewayDevice, type1_mode: str = "switch") -> str | None:
    """Return the authoritative firmware Discovery topic."""
    component = discovery_component(device.type, type1_mode)
    if component is None:
        return None
    return f"{DISCOVERY_PREFIX}/{component}/{device.bus_id}/config"


def _device_identifier(gateway_id: str, bus_id: str) -> str:
    safe_gateway = "".join(char for char in gateway_id.lower() if char.isalnum())[-24:]
    return f"scsgate_{safe_gateway}_{bus_id.lower()}"


def build_discovery_payload(
    device: GatewayDevice,
    gateway_id: str,
    *,
    type1_mode: str = "switch",
    existing_identifier: str | None = None,
) -> dict[str, Any] | None:
    """Build enriched Discovery while preserving firmware identity and topics."""
    component = discovery_component(device.type, type1_mode)
    if component is None:
        return None
    bus_id = device.bus_id.upper()
    payload: dict[str, Any] = {
        "name": device.name or bus_id,
        "unique_id": f"scsgate_{bus_id}",
        "origin": dict(ORIGIN),
        "device": {
            "identifiers": [
                existing_identifier or _device_identifier(gateway_id, bus_id)
            ],
            "name": device.name or f"SCS {bus_id}",
            "manufacturer": "BTicino/Legrand via papergion ESP32_SCSGATE",
            "model": f"SCS type {device.type}",
            "configuration_url": (
                "homeassistant://config/integrations/integration/scsgate"
            ),
        },
    }
    if component in {"switch", "light"}:
        payload |= {
            "command_topic": f"scs/switch/set/{bus_id}",
            "state_topic": f"scs/switch/state/{bus_id}",
        }
    if device.type in {3, 4}:
        payload |= {
            "brightness_command_topic": f"scs/switch/setlevel/{bus_id}",
            "brightness_state_topic": f"scs/switch/value/{bus_id}",
        }
    if component == "cover":
        payload |= {
            "command_topic": f"scs/cover/set/{bus_id}",
            "state_topic": f"scs/cover/state/{bus_id}",
        }
    if device.type in {9, 19}:
        payload |= {
            "position_command_topic": f"scs/cover/setposition/{bus_id}",
            "position_topic": f"scs/cover/value/{bus_id}",
        }
    return payload


def needs_reconciliation(payload: Mapping[str, Any], bus_id: str) -> bool:
    """Detect firmware's metadata-poor payload without reacting to our own."""
    return payload.get("unique_id") == f"scsgate_{bus_id.upper()}" and (
        not payload.get("device") or payload.get("origin", {}).get("name") != "SCSGATE"
    )


def find_existing_mqtt_identity(
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
    bus_id: str,
) -> tuple[str | None, str | None, str | None, bool]:
    """Reuse existing MQTT entity/device links when Home Assistant has them."""
    matches = [
        entry
        for entry in entity_registry.entities.values()
        if entry.platform == "mqtt" and entry.unique_id == f"scsgate_{bus_id.upper()}"
    ]
    if len(matches) != 1:
        return None, None, None, len(matches) > 1
    entity = matches[0]
    if not entity.device_id:
        return entity.entity_id, None, None, False
    registry_device = device_registry.async_get(entity.device_id)
    identifiers = (
        [value for domain, value in registry_device.identifiers if domain == "mqtt"]
        if registry_device
        else []
    )
    return (
        entity.entity_id,
        entity.device_id,
        identifiers[0] if len(identifiers) == 1 else None,
        False,
    )


class DeviceManager:
    """Own enriched Discovery metadata while firmware remains transport owner."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        gateway_id: str,
        query_devices: Callable[[], Any],
        type_overrides: Mapping[str, str] | None = None,
    ) -> None:
        self._hass = hass
        self.entry_id = entry_id
        self.gateway_id = gateway_id
        self._query_devices = query_devices
        self._type_overrides = {
            key.upper(): value for key, value in (type_overrides or {}).items()
        }
        self._devices: dict[str, GatewayDevice] = {}
        self._unsubs: list[Callable[[], None]] = []
        self._conflicts: set[str] = set()
        self._observed_topics: dict[str, set[str]] = {}
        self._topic_unique_ids: dict[str, str] = {}
        self._published = 0
        self._last_error: str | None = None
        self._reconcile_pending = False

    async def async_start(self) -> None:
        """Subscribe before initial sync so firmware republish cannot win."""
        try:
            self._unsubs.append(
                await mqtt.async_subscribe(
                    self._hass,
                    f"{DISCOVERY_PREFIX}/+/+/config",
                    self._async_discovery_received,
                    qos=0,
                )
            )
            self._unsubs.append(
                await mqtt.async_subscribe(
                    self._hass,
                    f"{DISCOVERY_PREFIX}/status",
                    self._async_birth_received,
                    qos=0,
                )
            )
            await self.async_sync("setup")
        except Exception:
            self.async_stop()
            raise

    async def async_ensure_started(self, reason: str = "periodic") -> None:
        """Retry subscriptions after outages, otherwise perform a normal sync."""
        if self._unsubs:
            await self.async_sync(reason)
        else:
            await self.async_start()

    @callback
    def async_stop(self) -> None:
        for unsubscribe in self._unsubs:
            unsubscribe()
        self._unsubs.clear()

    async def async_sync(self, reason: str = "manual") -> None:
        """Refresh inventory and retain all supported Discovery documents."""
        del reason  # Deliberately never logged with device data.
        try:
            devices: Iterable[GatewayDevice] = await self._query_devices()
            self._devices = {device.bus_id.upper(): device for device in devices}
            self._conflicts = {
                unique_id.removeprefix("scsgate_").upper()
                for unique_id, topics in self._observed_topics.items()
                if len(topics) > 1
            }
            entity_registry = er.async_get(self._hass)
            device_registry = dr.async_get(self._hass)
            for bus_id, device in self._devices.items():
                _entity_id, _device_id, identifier, conflict = (
                    find_existing_mqtt_identity(
                        entity_registry, device_registry, bus_id
                    )
                )
                if conflict:
                    self._conflicts.add(bus_id)
                    continue
                mode = self._type_overrides.get(bus_id, "switch")
                topic = discovery_topic(device, mode)
                payload = build_discovery_payload(
                    device,
                    self.gateway_id,
                    type1_mode=mode,
                    existing_identifier=identifier,
                )
                if topic and payload:
                    await mqtt.async_publish(
                        self._hass,
                        topic,
                        json.dumps(payload, separators=(",", ":")),
                        qos=0,
                        retain=True,
                    )
                    self._published += 1
            self._last_error = None
            self._update_repairs()
        except Exception as err:
            self._last_error = type(err).__name__
            self._create_issue("broker_or_gateway_offline", "device_manager_offline")
            raise

    def set_type_overrides(self, overrides: Mapping[str, str]) -> None:
        """Replace validated per-device type 1 presentation choices."""
        self._type_overrides = {
            key.upper(): value
            for key, value in overrides.items()
            if value in {"switch", "light"}
        }

    @callback
    def _async_discovery_received(self, message: ReceiveMessage) -> None:
        raw_payload = (
            message.payload.decode()
            if isinstance(message.payload, bytes)
            else str(message.payload)
        )
        if not raw_payload:
            unique_id = self._topic_unique_ids.pop(message.topic, None)
            if unique_id:
                self._observed_topics.get(unique_id, set()).discard(message.topic)
            return
        try:
            payload = json.loads(raw_payload)
        except (TypeError, ValueError, UnicodeDecodeError):
            return
        unique_id = payload.get("unique_id")
        if isinstance(unique_id, str) and unique_id.startswith("scsgate_"):
            self._topic_unique_ids[message.topic] = unique_id
            self._observed_topics.setdefault(unique_id, set()).add(message.topic)
            if len(self._observed_topics[unique_id]) > 1:
                self._conflicts.add(unique_id.removeprefix("scsgate_").upper())
                self._update_repairs()
        bus_id = str(payload.get("unique_id", "")).removeprefix("scsgate_").upper()
        if bus_id in self._devices and needs_reconciliation(payload, bus_id):
            self._schedule_reconciliation("firmware_republish")

    @callback
    def _async_birth_received(self, message: ReceiveMessage) -> None:
        payload = (
            message.payload.decode()
            if isinstance(message.payload, bytes)
            else str(message.payload)
        )
        if payload.lower() == "online":
            self._schedule_reconciliation("mqtt_birth")

    @callback
    def _schedule_reconciliation(self, reason: str) -> None:
        """Coalesce firmware bursts so one republish cannot create a loop."""
        if self._reconcile_pending:
            return
        self._reconcile_pending = True

        async def reconcile() -> None:
            try:
                await self.async_ensure_started(reason)
            except Exception:
                return
            finally:
                self._reconcile_pending = False

        self._hass.async_create_task(reconcile())

    @property
    def repair_candidates(self) -> list[str]:
        """Return only observed non-canonical Discovery topics safe to preview."""
        candidates: list[str] = []
        for unique_id, topics in self._observed_topics.items():
            bus_id = unique_id.removeprefix("scsgate_").upper()
            device = self._devices.get(bus_id)
            if device is None:
                continue
            canonical = discovery_topic(
                device, self._type_overrides.get(bus_id, "switch")
            )
            candidates.extend(topic for topic in topics if topic != canonical)
        return sorted(candidates)

    async def async_clear_stale_topic(self, topic: str) -> None:
        """Clear one previewed stale retained topic after UI confirmation."""
        if topic not in self.repair_candidates:
            raise ValueError("topic is not a current stale candidate")
        await mqtt.async_publish(self._hass, topic, "", qos=0, retain=True)
        unique_id = self._topic_unique_ids.pop(topic, None)
        if unique_id:
            self._observed_topics.get(unique_id, set()).discard(topic)
        await self.async_sync("guided_repair")

    def _create_issue(self, issue_id: str, translation_key: str) -> None:
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            f"{issue_id}_{self.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=translation_key,
        )

    def _update_repairs(self) -> None:
        if self._conflicts:
            self._create_issue("discovery_conflict", "discovery_conflict")
        else:
            ir.async_delete_issue(
                self._hass, DOMAIN, f"discovery_conflict_{self.entry_id}"
            )
        ir.async_delete_issue(
            self._hass, DOMAIN, f"broker_or_gateway_offline_{self.entry_id}"
        )

    @property
    def inventory(self) -> list[ManagedDevice]:
        entity_registry = er.async_get(self._hass)
        device_registry = dr.async_get(self._hass)
        rows: list[ManagedDevice] = []
        for bus_id, device in sorted(self._devices.items()):
            entity_id, device_id, _identifier, conflict = find_existing_mqtt_identity(
                entity_registry, device_registry, bus_id
            )
            component = discovery_component(
                device.type, self._type_overrides.get(bus_id, "switch")
            )
            health = (
                "conflict"
                if conflict or bus_id in self._conflicts
                else "unsupported"
                if component is None
                else "grouped"
                if device_id
                else "pending_restart"
            )
            rows.append(
                ManagedDevice(
                    bus_id,
                    device.type,
                    device.name or bus_id,
                    component,
                    entity_id,
                    device_id,
                    health,
                )
            )
        return rows

    @property
    def diagnostics(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "inventory_count": len(self._devices),
            "published_total": self._published,
            "conflict_count": len(self._conflicts),
            "last_error": self._last_error,
        }
