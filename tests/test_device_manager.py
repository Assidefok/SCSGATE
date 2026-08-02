"""SCSGATE v0.4 Discovery and migration contract."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.mqtt.models import ReceiveMessage

from custom_components.scsgate import device_manager as module
from custom_components.scsgate.device_manager import (
    DeviceManager,
    build_discovery_payload,
    claim_global_namespace,
    discovery_component,
    discovery_topic,
    find_existing_mqtt_identity,
    needs_reconciliation,
)
from custom_components.scsgate.models import GatewayDevice


@pytest.mark.parametrize(
    ("device_type", "mode", "component"),
    [
        (1, "switch", "switch"),
        (1, "light", "light"),
        (3, "switch", "light"),
        (4, "switch", "light"),
        (8, "switch", "cover"),
        (18, "switch", "cover"),
        (9, "switch", "cover"),
        (19, "switch", "cover"),
        (11, "switch", None),
        (14, "switch", None),
        (99, "switch", None),
    ],
)
def test_firmware_type_matrix(device_type, mode, component) -> None:
    assert discovery_component(device_type, mode) == component


def test_dimmer_payload_preserves_identity_topics_and_adds_metadata() -> None:
    device = GatewayDevice(bus_id="11", type=3, name="Dining")

    payload = build_discovery_payload(device, "AABBCC")

    assert payload is not None
    assert discovery_topic(device) == "homeassistant/light/11/config"
    assert payload["unique_id"] == "scsgate_11"
    assert payload["command_topic"] == "scs/switch/set/11"
    assert payload["state_topic"] == "scs/switch/state/11"
    assert payload["brightness_command_topic"] == "scs/switch/setlevel/11"
    assert payload["brightness_state_topic"] == "scs/switch/value/11"
    assert payload["device"]["identifiers"] == ["scsgate_aabbcc_11"]
    assert payload["origin"]["name"] == "SCSGATE"


def test_position_cover_payload_uses_firmware_7004_topics() -> None:
    payload = build_discovery_payload(
        GatewayDevice(bus_id="43", type=19, name="Bedroom"), "gateway"
    )

    assert payload is not None
    assert payload["command_topic"] == "scs/cover/set/43"
    assert payload["state_topic"] == "scs/cover/state/43"
    assert payload["position_command_topic"] == "scs/cover/setposition/43"
    assert payload["position_topic"] == "scs/cover/value/43"


def test_poor_firmware_payload_is_repaired_but_ours_does_not_loop() -> None:
    poor = {"name": "11", "unique_id": "scsgate_11"}
    rich = build_discovery_payload(GatewayDevice("11", 3, "Dining"), "gateway")

    assert needs_reconciliation(poor, "11") is True
    assert rich is not None
    assert needs_reconciliation(rich, "11") is False


def test_mqtt_birth_and_poor_firmware_republish_schedule_sync(monkeypatch) -> None:
    monkeypatch.setattr(module.ir, "async_delete_issue", lambda *_args: None)
    manager = DeviceManager(SimpleNamespace(), "entry", "gateway", AsyncMock())
    manager._devices = {"11": GatewayDevice("11", 3, "Dimmer")}
    schedule = Mock()
    monkeypatch.setattr(manager, "_schedule_reconciliation", schedule)

    manager._async_birth_received(
        ReceiveMessage(
            "homeassistant/status", "online", 0, False, "homeassistant/status", 0.0
        )
    )
    manager._async_discovery_received(
        _message(
            "homeassistant/light/11/config",
            {"unique_id": "scsgate_11", "name": "11"},
        )
    )

    assert schedule.call_args_list[0].args == ("mqtt_birth",)
    assert schedule.call_args_list[1].args == ("firmware_republish",)


def test_second_gateway_is_blocked_on_global_namespace() -> None:
    data: dict = {}

    assert claim_global_namespace(data, "first") is True
    assert claim_global_namespace(data, "first") is True
    assert claim_global_namespace(data, "second") is False


async def test_sync_publishes_supported_devices_retained(monkeypatch) -> None:
    published = AsyncMock()
    monkeypatch.setattr(module.mqtt, "async_publish", published)
    monkeypatch.setattr(
        module.er, "async_get", lambda _hass: SimpleNamespace(entities={})
    )
    monkeypatch.setattr(module.dr, "async_get", lambda _hass: SimpleNamespace())
    monkeypatch.setattr(module.ir, "async_delete_issue", lambda *_args: None)
    devices = [
        GatewayDevice("24", 8, "Kitchen cover"),
        GatewayDevice("11", 3, "Dining dimmer"),
        GatewayDevice("12", 11, "Generic"),
        GatewayDevice("14", 14, "Alarm"),
    ]
    manager = DeviceManager(
        SimpleNamespace(), "entry", "gateway", AsyncMock(return_value=devices)
    )

    await manager.async_sync()

    assert published.await_count == 2
    assert all(call.kwargs["retain"] is True for call in published.await_args_list)
    sent = [json.loads(call.args[2]) for call in published.await_args_list]
    assert {item["unique_id"] for item in sent} == {"scsgate_24", "scsgate_11"}
    assert manager.diagnostics["inventory_count"] == 4


async def test_broker_or_gateway_outage_is_reported_without_mutation(
    monkeypatch,
) -> None:
    issue = Mock()
    monkeypatch.setattr(module.ir, "async_create_issue", issue)
    manager = DeviceManager(
        SimpleNamespace(),
        "entry",
        "gateway",
        AsyncMock(side_effect=OSError("offline")),
    )

    with pytest.raises(OSError):
        await manager.async_sync()

    assert manager.diagnostics["inventory_count"] == 0
    assert manager.diagnostics["last_error"] == "OSError"
    assert issue.call_count == 1


def test_existing_identity_can_be_reused_without_changing_unique_id() -> None:
    payload = build_discovery_payload(
        GatewayDevice("24", 8, "Kitchen"),
        "new-gateway",
        existing_identifier="old_mqtt_device",
    )

    assert payload is not None
    assert payload["unique_id"] == "scsgate_24"
    assert payload["device"]["identifiers"] == ["old_mqtt_device"]


def test_registry_lookup_preserves_entity_customization() -> None:
    entry = SimpleNamespace(
        platform="mqtt",
        unique_id="scsgate_24",
        entity_id="cover.persiana_cuina",
        device_id="mqtt-device",
        name="Persiana Cuina",
        area_id="kitchen",
        labels={"important"},
    )
    entity_registry = SimpleNamespace(entities={entry.entity_id: entry})
    device_registry = SimpleNamespace(
        async_get=lambda _device_id: SimpleNamespace(
            identifiers={("mqtt", "existing_identifier")}
        )
    )

    identity = find_existing_mqtt_identity(entity_registry, device_registry, "24")

    assert identity == (
        "cover.persiana_cuina",
        "mqtt-device",
        "existing_identifier",
        False,
    )
    assert entry.name == "Persiana Cuina"
    assert entry.area_id == "kitchen"
    assert entry.labels == {"important"}


def test_current_eleven_device_inventory_has_no_fixed_limit() -> None:
    devices = [
        *(
            GatewayDevice(bus_id, 9, f"Cover {bus_id}")
            for bus_id in ("24", "34", "41", "42", "43")
        ),
        *(GatewayDevice(bus_id, 3, f"Dimmer {bus_id}") for bus_id in ("11", "12")),
        *(
            GatewayDevice(bus_id, 1, f"Switch {bus_id}")
            for bus_id in ("22", "23", "32", "33")
        ),
    ]

    payloads = [build_discovery_payload(device, "gateway") for device in devices]

    assert len(devices) == 11
    assert all(payload is not None for payload in payloads)
    assert {payload["unique_id"] for payload in payloads if payload} == {
        f"scsgate_{device.bus_id}" for device in devices
    }


def _message(topic: str, payload: dict) -> ReceiveMessage:
    return ReceiveMessage(topic, json.dumps(payload), 0, True, topic, 0.0)


def test_observed_duplicate_topics_become_guided_repair_candidates(
    monkeypatch,
) -> None:
    monkeypatch.setattr(module.ir, "async_create_issue", lambda *_args, **_kw: None)
    monkeypatch.setattr(module.ir, "async_delete_issue", lambda *_args: None)
    manager = DeviceManager(SimpleNamespace(), "entry", "gateway", AsyncMock())
    manager._devices = {"11": GatewayDevice("11", 3, "Dimmer")}
    payload = build_discovery_payload(manager._devices["11"], "gateway")
    assert payload is not None

    manager._async_discovery_received(
        _message("homeassistant/light/11/config", payload)
    )
    manager._async_discovery_received(
        _message("homeassistant/switch/11/config", payload)
    )

    assert manager.repair_candidates == ["homeassistant/switch/11/config"]
    assert manager.diagnostics["conflict_count"] == 1


async def test_guided_repair_clears_only_selected_stale_topic(
    monkeypatch,
) -> None:
    published = AsyncMock()
    monkeypatch.setattr(module.mqtt, "async_publish", published)
    monkeypatch.setattr(
        module.er, "async_get", lambda _hass: SimpleNamespace(entities={})
    )
    monkeypatch.setattr(module.dr, "async_get", lambda _hass: SimpleNamespace())
    monkeypatch.setattr(module.ir, "async_delete_issue", lambda *_args: None)
    monkeypatch.setattr(module.ir, "async_create_issue", lambda *_args, **_kwargs: None)
    device = GatewayDevice("11", 3, "Dimmer")
    manager = DeviceManager(
        SimpleNamespace(), "entry", "gateway", AsyncMock(return_value=[device])
    )
    rich = build_discovery_payload(device, "gateway")
    assert rich is not None
    manager._devices = {"11": device}
    manager._async_discovery_received(_message("homeassistant/light/11/config", rich))
    manager._async_discovery_received(_message("homeassistant/switch/11/config", rich))

    await manager.async_clear_stale_topic("homeassistant/switch/11/config")

    clear_call = published.await_args_list[0]
    assert clear_call.args[1:3] == ("homeassistant/switch/11/config", "")
    assert clear_call.kwargs["retain"] is True
    assert all(
        call.args[1] != "homeassistant/light/11/config" or call.args[2] != ""
        for call in published.await_args_list
    )
