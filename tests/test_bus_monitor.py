"""MQTT bus activity monitor tests."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from types import SimpleNamespace

from homeassistant.components.mqtt.models import ReceiveMessage

from custom_components.scsgate import _async_acquire_bus_monitor
from custom_components.scsgate import bus_monitor as bus_monitor_module
from custom_components.scsgate.bus_monitor import BusMonitor


def _message(topic: str, payload: str, *, retain: bool = False) -> ReceiveMessage:
    return ReceiveMessage(topic, payload, 0, retain, topic, 0.0)


def test_monitor_is_bounded_and_classifies_standard_and_raw_topics() -> None:
    monitor = BusMonitor(SimpleNamespace(), enabled=True, message_limit=2)
    monitor._async_message_received(_message("scs/switch/state/24", "ON"))
    monitor._async_message_received(_message("scs/generic/from/41", "241201"))
    monitor._async_message_received(_message("SCSLOG", "123 - rx: F5 79 24 01"))

    exported = monitor.export(10)
    assert [item["kind"] for item in exported["messages"]] == [
        "generic_bus",
        "uart_rx",
    ]
    assert exported["raw_uart_available"] is True
    assert exported["scope"].startswith("Home Assistant MQTT broker")
    assert monitor.diagnostics == {
        "enabled": True,
        "retained_messages": 2,
        "received_total": 3,
        "discarded_total": 1,
        "raw_uart_seen": True,
        "message_kinds": {
            "generic_bus": 1,
            "interpreted_state": 1,
            "uart_rx": 1,
        },
    }
    assert "241201" not in str(monitor.diagnostics)


def test_monitor_never_writes_payload_to_logs(caplog) -> None:
    monitor = BusMonitor(SimpleNamespace(), enabled=True)
    secret_capture = "F5 79 AA BB 12 01"
    caplog.set_level(logging.DEBUG, logger="custom_components.scsgate.bus_monitor")
    monitor._async_message_received(_message("SCSLOG", secret_capture))
    assert secret_capture not in caplog.text
    assert secret_capture not in str(monitor.diagnostics)


def test_clear_removes_only_volatile_messages() -> None:
    monitor = BusMonitor(SimpleNamespace(), enabled=True)
    listener = SimpleNamespace(calls=0)

    def changed() -> None:
        listener.calls += 1

    monitor.async_add_listener(changed)
    monitor._async_message_received(_message("SCSERROR", "buffer collision"))
    monitor.clear()
    assert monitor.retained_count == 0
    assert monitor.diagnostics["received_total"] == 1
    assert listener.calls == 2


async def test_partial_subscription_failure_rolls_back(monkeypatch) -> None:
    unsubscribed: list[str] = []
    calls = 0

    async def subscribe(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("broker unavailable")
        return lambda: unsubscribed.append("done")

    monkeypatch.setattr(bus_monitor_module.mqtt, "async_subscribe", subscribe)
    monitor = BusMonitor(SimpleNamespace(), enabled=False)

    with suppress(RuntimeError):
        await monitor.async_acquire("entry", 100)

    assert unsubscribed == ["done"]
    assert monitor._unsubscribers == []


async def test_collector_is_shared_between_multiple_entry_owners(monkeypatch) -> None:
    unsubscribed: list[str] = []

    async def subscribe(*_args, **_kwargs):
        return lambda: unsubscribed.append("done")

    monkeypatch.setattr(bus_monitor_module.mqtt, "async_subscribe", subscribe)
    monitor = BusMonitor(SimpleNamespace(), enabled=False)

    await monitor.async_acquire("first", 50)
    await monitor.async_acquire("second", 200)
    assert len(monitor._unsubscribers) == 3
    assert monitor._messages.maxlen == 200

    await monitor.async_release("first")
    assert monitor.enabled is True
    assert unsubscribed == []

    await monitor.async_release("second")
    assert monitor.enabled is False
    assert unsubscribed == ["done", "done", "done"]


async def test_concurrent_entry_setup_creates_one_broker_collector(monkeypatch) -> None:
    subscribe_calls = 0

    async def subscribe(*_args, **_kwargs):
        nonlocal subscribe_calls
        subscribe_calls += 1
        await asyncio.sleep(0)
        return lambda: None

    monkeypatch.setattr(bus_monitor_module.mqtt, "async_subscribe", subscribe)
    hass = SimpleNamespace(data={})

    first, second = await asyncio.gather(
        _async_acquire_bus_monitor(hass, "first", 50),
        _async_acquire_bus_monitor(hass, "second", 100),
    )

    assert first is second
    assert subscribe_calls == 3
