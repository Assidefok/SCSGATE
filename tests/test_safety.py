"""Integration-level guard and coordinator tests with Home Assistant test fixtures."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import voluptuous as vol
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.scsgate import ScsGateRuntimeData, _async_register_services
from custom_components.scsgate.bus_monitor import BusMonitor
from custom_components.scsgate.config_flow import ScsGateOptionsFlow, _is_private_host
from custom_components.scsgate.const import (
    ATTR_CMD,
    ATTR_CONFIRM,
    ATTR_ENTRY_ID,
    ATTR_FROM,
    ATTR_LIMIT,
    ATTR_RESPONSE,
    ATTR_TO,
    ATTR_TYPE,
    CONF_ENABLE_RAW_COMMANDS,
    DOMAIN,
    SERVICE_EXPORT_BUS_LOG,
    SERVICE_SEND_RAW_TELEGRAM,
    SERVICE_START_ADVANCED_DEBUG,
    SERVICE_STOP_ADVANCED_DEBUG,
)
from custom_components.scsgate.coordinator import ScsGateCoordinator
from custom_components.scsgate.diagnostics import async_get_config_entry_diagnostics
from custom_components.scsgate.models import GatewayStatus


@pytest.mark.parametrize("host", ["192.168.1.1", "10.0.0.1", "127.0.0.1", "fe80::1"])
def test_config_flow_accepts_only_local_literal_hosts(host: str) -> None:
    assert _is_private_host(host)


@pytest.mark.parametrize("host", ["8.8.8.8", "gateway.example", "", "192.168.1.999"])
def test_config_flow_rejects_public_or_unresolved_hosts(host: str) -> None:
    assert not _is_private_host(host)


async def test_coordinator_reads_status_and_preserves_result(hass) -> None:
    status = GatewayStatus(host="192.168.1.20", mac="AA:BB")
    client = SimpleNamespace(async_get_status=AsyncMock(return_value=status))
    entry = SimpleNamespace(
        options={}, entry_id="entry", unique_id="AA:BB", data={"host": "192.168.1.20"}
    )
    coordinator = ScsGateCoordinator(hass, client, entry)

    assert await coordinator._async_update_data() is status
    client.async_get_status.assert_awaited_once()


async def test_coordinator_turns_transport_failure_into_update_failed(hass) -> None:
    client = SimpleNamespace(async_get_status=AsyncMock(side_effect=OSError("offline")))
    entry = SimpleNamespace(
        options={}, entry_id="entry", unique_id=None, data={"host": "192.168.1.20"}
    )
    coordinator = ScsGateCoordinator(hass, client, entry)

    with pytest.raises(UpdateFailed, match="Unable to reach"):
        await coordinator._async_update_data()


async def test_diagnostics_redact_identity_and_include_safe_transport_metrics(
    hass,
) -> None:
    status = GatewayStatus(
        host="192.168.1.20",
        mac="AA:BB:CC:DD:EE:FF",
        wifi_ssid="Private SSID",
        mqtt_broker="configured",
    )
    metrics = {
        "requests_total": 2,
        "failures_total": 1,
        "last_operation_id": "http-000002",
        "last_endpoint": "/status",
        "last_status": 200,
        "last_duration_ms": 12,
        "last_response_chars": 300,
    }
    protocol_debug = {
        "enabled": True,
        "observations_total": 1,
        "anomalies_total": 0,
        "retained_observations": [
            {
                "operation_id": "http-000002",
                "endpoint": "/status",
                "body_chars": 300,
                "line_count": 8,
                "html_tag_count": 10,
                "key_value_count": 5,
                "sensitive_label_count": 2,
                "anomaly_codes": (),
            }
        ],
    }
    entry = SimpleNamespace(
        entry_id="entry",
        data={"host": "192.168.1.20", "port": 80},
        options={"last_device_snapshot": ["private device"]},
    )
    hass.data[DOMAIN] = {
        "entry": SimpleNamespace(
            client=SimpleNamespace(
                debug_metrics=metrics,
                protocol_debug_diagnostics=protocol_debug,
            ),
            coordinator=SimpleNamespace(data=status),
        )
    }

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entry"]["host"] == "**REDACTED**"
    assert diagnostics["status"]["host"] == "**REDACTED**"
    assert diagnostics["status"]["mac"] == "**REDACTED**"
    assert diagnostics["status"]["wifi_ssid"] == "**REDACTED**"
    assert diagnostics["status"]["mqtt_broker"] == "**REDACTED**"
    assert diagnostics["options"]["last_device_snapshot"] == "[redacted]"
    assert diagnostics["transport"] == metrics
    assert diagnostics["protocol_debug"] == protocol_debug


async def test_admin_operation_logs_only_safe_counts(caplog) -> None:
    private_value = "private device name"

    async def operation() -> list[str]:
        return [private_value]

    caplog.set_level(logging.DEBUG, logger="custom_components.scsgate.config_flow")
    flow = object.__new__(ScsGateOptionsFlow)

    result = await flow._run_operation("census", "query", operation())

    assert result == [private_value]
    assert "operation_id=admin-" in caplog.text
    assert "category=census" in caplog.text
    assert "action=query" in caplog.text
    assert "result_count=1" in caplog.text
    assert private_value not in caplog.text


async def test_raw_service_requires_gateway_option_and_confirmation(hass) -> None:
    client = SimpleNamespace(async_send_raw_telegram=AsyncMock())
    entry = SimpleNamespace(options={CONF_ENABLE_RAW_COMMANDS: False})
    coordinator = SimpleNamespace(config_entry=entry)
    hass.data[DOMAIN] = {
        "entry": ScsGateRuntimeData(client=client, coordinator=coordinator)
    }
    _async_register_services(hass)
    data = {
        ATTR_ENTRY_ID: "entry",
        ATTR_TYPE: "1",
        ATTR_FROM: "1",
        ATTR_TO: "2",
        ATTR_CMD: "F",
        ATTR_RESPONSE: "none",
        ATTR_CONFIRM: True,
    }

    with pytest.raises(HomeAssistantError, match="disabled"):
        await hass.services.async_call(
            DOMAIN, SERVICE_SEND_RAW_TELEGRAM, data, blocking=True
        )
    client.async_send_raw_telegram.assert_not_awaited()

    entry.options[CONF_ENABLE_RAW_COMMANDS] = True
    data[ATTR_CONFIRM] = False
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, SERVICE_SEND_RAW_TELEGRAM, data, blocking=True
        )
    client.async_send_raw_telegram.assert_not_awaited()


async def test_raw_service_forwards_valid_confirmed_command(hass) -> None:
    client = SimpleNamespace(async_send_raw_telegram=AsyncMock())
    entry = SimpleNamespace(options={CONF_ENABLE_RAW_COMMANDS: True})
    coordinator = SimpleNamespace(config_entry=entry)
    hass.data[DOMAIN] = {
        "entry": ScsGateRuntimeData(client=client, coordinator=coordinator)
    }
    _async_register_services(hass)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_RAW_TELEGRAM,
        {
            ATTR_ENTRY_ID: "entry",
            ATTR_TYPE: "1",
            ATTR_FROM: "A",
            ATTR_TO: "2",
            ATTR_CMD: "F",
            ATTR_CONFIRM: True,
        },
        blocking=True,
    )

    client.async_send_raw_telegram.assert_awaited_once_with("1", "A", "2", "F", "none")


async def test_bus_log_export_requires_confirmation_and_returns_response(hass) -> None:
    monitor = BusMonitor(hass, enabled=True)
    monitor._async_message_received(
        ReceiveMessage("scs/switch/state/24", "ON", 0, False, "scs/#", 0.0)
    )
    coordinator = SimpleNamespace(config_entry=SimpleNamespace(options={}))
    hass.data[DOMAIN] = {
        "entry": ScsGateRuntimeData(
            client=SimpleNamespace(), coordinator=coordinator, bus_monitor=monitor
        )
    }
    _async_register_services(hass)

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_EXPORT_BUS_LOG,
            {ATTR_ENTRY_ID: "entry", ATTR_LIMIT: 10, ATTR_CONFIRM: False},
            blocking=True,
            return_response=True,
        )

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_EXPORT_BUS_LOG,
        {ATTR_ENTRY_ID: "entry", ATTR_LIMIT: 10, ATTR_CONFIRM: True},
        blocking=True,
        return_response=True,
    )

    assert response["messages"][0]["topic"] == "scs/switch/state/24"
    assert response["scope"].startswith("Home Assistant MQTT broker")


async def test_advanced_debug_services_require_typed_start_confirmation(hass) -> None:
    monitor = SimpleNamespace(
        async_start=AsyncMock(),
        async_stop=AsyncMock(),
        async_recover=AsyncMock(),
        export=lambda _limit: {"messages": []},
        clear=lambda: None,
    )
    entry = SimpleNamespace(entry_id="entry", unique_id="AA:BB", options={})
    coordinator = SimpleNamespace(config_entry=entry, data=SimpleNamespace(mac="AA:BB"))
    hass.data[DOMAIN] = {
        "entry": ScsGateRuntimeData(
            client=SimpleNamespace(),
            coordinator=coordinator,
            advanced_debug=monitor,
        )
    }
    _async_register_services(hass)

    with pytest.raises(HomeAssistantError, match="confirmation"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_START_ADVANCED_DEBUG,
            {ATTR_ENTRY_ID: "entry", ATTR_CONFIRM: "DEBUG WRONG"},
            blocking=True,
        )
    monitor.async_start.assert_not_awaited()

    await hass.services.async_call(
        DOMAIN,
        SERVICE_START_ADVANCED_DEBUG,
        {ATTR_ENTRY_ID: "entry", ATTR_CONFIRM: "DEBUG AA:BB"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        SERVICE_STOP_ADVANCED_DEBUG,
        {ATTR_ENTRY_ID: "entry", ATTR_CONFIRM: True},
        blocking=True,
    )
    monitor.async_start.assert_awaited_once()
    monitor.async_stop.assert_awaited_once()
