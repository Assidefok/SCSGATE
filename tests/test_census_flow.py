"""Guided census flow presentation tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from custom_components.scsgate.config_flow import ScsGateOptionsFlow
from custom_components.scsgate.models import GatewayDevice


async def test_census_review_shows_every_detected_type() -> None:
    entry = SimpleNamespace()
    flow = ScsGateOptionsFlow()
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_get_known_entry=lambda _entry_id: entry)
    )
    flow.handler = "entry"
    flow._census_devices = [
        GatewayDevice(bus_id="24", type=1, name="Kitchen\x00\nprivate"),
        GatewayDevice(bus_id="34", type=3, name="Dining"),
        GatewayDevice(bus_id="41", type=8, name=None),
    ]

    result = await flow.async_step_census_review()

    assert result["type"] == "form"
    assert result["step_id"] == "census_review"
    placeholders = result["description_placeholders"]
    assert placeholders["count"] == "3"
    assert "24: type 1" in placeholders["devices"]
    assert "34: type 3" in placeholders["devices"]
    assert "41: type 8" in placeholders["devices"]
    assert "\x00" not in placeholders["devices"]


async def test_census_poll_timeout_stops_firmware(monkeypatch) -> None:
    client = SimpleNamespace(
        async_query_devices_with_state=AsyncMock(return_value=(False, [])),
        async_mqtt_devices=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(ScsGateOptionsFlow, "_client", property(lambda _flow: client))
    monkeypatch.setattr(
        "custom_components.scsgate.config_flow.asyncio.sleep", AsyncMock()
    )
    flow = ScsGateOptionsFlow()
    flow._census_active = True

    result = await flow._poll_census()

    assert result["step_id"] == "census_prepare"
    assert result["errors"] == {"base": "census_still_running"}
    client.async_mqtt_devices.assert_awaited_once_with("stop")


async def test_explicit_recovery_does_not_claim_success_when_stop_fails(
    monkeypatch,
) -> None:
    client = SimpleNamespace(
        async_mqtt_devices=AsyncMock(side_effect=OSError("offline"))
    )
    monkeypatch.setattr(ScsGateOptionsFlow, "_client", property(lambda _flow: client))
    flow = ScsGateOptionsFlow()

    result = await flow.async_step_census_recovery_stop({"confirm": True})

    assert result["step_id"] == "census_recovery_stop"
    assert result["errors"] == {"base": "cannot_connect"}
    assert flow._census_active is True


async def test_prepare_is_blocked_until_uncertain_census_is_stopped(
    monkeypatch,
) -> None:
    client = SimpleNamespace(async_mqtt_devices=AsyncMock())
    monkeypatch.setattr(ScsGateOptionsFlow, "_client", property(lambda _flow: client))
    flow = ScsGateOptionsFlow()
    flow._census_active = True

    result = await flow.async_step_census_prepare({"confirm": True})

    assert result["step_id"] == "census_recovery_stop"
    assert result["errors"] == {"base": "census_recovery_required"}
    client.async_mqtt_devices.assert_not_awaited()
