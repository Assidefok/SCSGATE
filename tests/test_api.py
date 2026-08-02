"""Gateway transport safety tests.  These use no sockets."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
import pytest

from custom_components.scsgate.api import (
    GatewayClient,
    GatewayConnectionError,
    GatewayResponseError,
    GatewayValidationError,
)


class FakeResponse:
    """Small async aiohttp response substitute."""

    def __init__(self, status: int = 200, body: str = "") -> None:
        self.status = status
        self._body = body

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def text(self) -> str:
        return self._body


class FakeSession:
    """Record requests rather than touching a gateway."""

    def __init__(self, response: FakeResponse | Exception | None = None) -> None:
        self.response = response or FakeResponse()
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.fixture
def client() -> tuple[GatewayClient, FakeSession]:
    session = FakeSession()
    return GatewayClient(session, "192.168.1.20"), session  # type: ignore[arg-type]


async def _bypass_host_validation() -> None:
    """Keep endpoint tests isolated from DNS and network state."""


async def test_request_disables_redirects_and_uses_only_known_path(
    client: tuple[GatewayClient, FakeSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway, session = client
    monkeypatch.setattr(gateway, "async_validate_host", _bypass_host_validation)

    await gateway.async_reset("mqtt")

    url, kwargs = session.calls[0]
    assert url == "http://192.168.1.20:80/reset"
    assert kwargs["params"] == {"device": "mqtt"}
    assert kwargs["allow_redirects"] is False


@pytest.mark.parametrize(
    "action", ["query", "prepare", "start", "stop", "resend", "clear"]
)
async def test_device_management_allows_only_documented_requests(
    client: tuple[GatewayClient, FakeSession],
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    gateway, session = client
    monkeypatch.setattr(gateway, "async_validate_host", _bypass_host_validation)

    await gateway.async_mqtt_devices(action)

    assert session.calls[0][0].endswith("/mqttdevices")
    assert session.calls[0][1]["params"] == {"request": action}


@pytest.mark.parametrize("action", ["term", "delete", "resend&clear"])
async def test_device_management_rejects_undocumented_requests(
    client: tuple[GatewayClient, FakeSession], action: str
) -> None:
    gateway, session = client

    with pytest.raises(GatewayValidationError, match="Unsupported"):
        await gateway.async_mqtt_devices(action)

    assert session.calls == []


async def test_mqtt_password_not_leaked_by_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "highly-secret-password"
    session = FakeSession(aiohttp.ClientError(secret))
    gateway = GatewayClient(session, "192.168.1.20")  # type: ignore[arg-type]
    monkeypatch.setattr(gateway, "async_validate_host", _bypass_host_validation)

    with pytest.raises(GatewayConnectionError) as error:
        await gateway.async_configure_mqtt(
            broker="192.168.1.2", port=1883, password=secret
        )

    assert secret not in str(error.value)
    assert session.calls[0][1]["params"]["pswd"] == secret


async def test_http_errors_do_not_include_sensitive_query_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "mqtt-secret"
    session = FakeSession(FakeResponse(status=500))
    gateway = GatewayClient(session, "192.168.1.20")  # type: ignore[arg-type]
    monkeypatch.setattr(gateway, "async_validate_host", _bypass_host_validation)

    with pytest.raises(GatewayResponseError) as error:
        await gateway.async_configure_mqtt(
            broker="192.168.1.2", port=1883, password=secret
        )

    assert secret not in str(error.value)
    assert "mqttcfg" in str(error.value)


async def test_debug_log_and_metrics_never_retain_request_values(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "unique-debug-password"
    broker = "192.168.44.99"
    response_body = "private gateway response"
    session = FakeSession(FakeResponse(body=response_body))
    gateway = GatewayClient(session, "192.168.44.20")  # type: ignore[arg-type]
    monkeypatch.setattr(gateway, "async_validate_host", _bypass_host_validation)
    caplog.set_level(logging.DEBUG, logger="custom_components.scsgate.api")

    await gateway.async_configure_mqtt(
        broker=broker,
        port=1883,
        username="private-user",
        password=secret,
    )

    log_text = caplog.text
    assert "operation_id=http-000001" in log_text
    assert "endpoint=/mqttcfg" in log_text
    assert "status=200" in log_text
    assert secret not in log_text
    assert broker not in log_text
    assert "private-user" not in log_text
    assert response_body not in log_text
    assert "192.168.44.20" not in log_text
    assert gateway.debug_metrics == {
        "requests_total": 1,
        "failures_total": 0,
        "last_operation_id": "http-000001",
        "last_endpoint": "/mqttcfg",
        "last_status": 200,
        "last_duration_ms": gateway.debug_metrics["last_duration_ms"],
        "last_response_chars": len(response_body),
    }


async def test_failed_request_updates_secret_free_metrics(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "transport-error-secret"
    session = FakeSession(aiohttp.ClientError(secret))
    gateway = GatewayClient(session, "192.168.44.20")  # type: ignore[arg-type]
    monkeypatch.setattr(gateway, "async_validate_host", _bypass_host_validation)
    caplog.set_level(logging.DEBUG, logger="custom_components.scsgate.api")

    with pytest.raises(GatewayConnectionError):
        await gateway.async_configure_mqtt(
            broker="192.168.44.99", port=1883, password=secret
        )

    assert secret not in caplog.text
    assert gateway.debug_metrics["requests_total"] == 1
    assert gateway.debug_metrics["failures_total"] == 1
    assert gateway.debug_metrics["last_status"] is None
    assert gateway.debug_metrics["last_response_chars"] is None


@pytest.mark.parametrize("host", ["8.8.8.8", "1.1.1.1", "2001:4860:4860::8888"])
def test_public_gateway_addresses_are_rejected(host: str) -> None:
    with pytest.raises(GatewayValidationError, match="private or local"):
        GatewayClient(FakeSession(), host)  # type: ignore[arg-type]


@pytest.mark.parametrize("response", ["bad", "yes", "x"])
async def test_raw_telegram_rejects_unknown_response_mode(
    client: tuple[GatewayClient, FakeSession], response: str
) -> None:
    gateway, session = client

    with pytest.raises(GatewayValidationError, match="response"):
        await gateway.async_send_raw_telegram("1", "1", "2", "F", response)

    assert session.calls == []


async def test_save_device_sends_only_expected_parameters(
    client: tuple[GatewayClient, FakeSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway, session = client
    monkeypatch.setattr(gateway, "async_validate_host", _bypass_host_validation)

    await gateway.async_save_device("24", 9, "Living cover", 100)

    assert session.calls[0][0].endswith("/devicename")
    assert session.calls[0][1]["params"] == {
        "busid": "24",
        "type": 9,
        "devname": "Living cover",
        "maxpos": 100,
    }


async def test_raw_telegram_uses_firmware_parameter_names(
    client: tuple[GatewayClient, FakeSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway, session = client
    monkeypatch.setattr(gateway, "async_validate_host", _bypass_host_validation)

    await gateway.async_send_raw_telegram("1", "A", "24", "F", "i")

    assert session.calls[0][0].endswith("/gate")
    assert session.calls[0][1]["params"] == {
        "type": "1",
        "from": "A",
        "to": "24",
        "cmd": "F",
        "resp": "i",
    }


async def test_mqtt_configuration_uses_exact_firmware_parameters(
    client: tuple[GatewayClient, FakeSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway, session = client
    monkeypatch.setattr(gateway, "async_validate_host", _bypass_host_validation)

    await gateway.async_configure_mqtt(
        broker="192.168.1.2",
        port=1883,
        username="ha",
        password="secret",
        discovery_options="retain",
        log=True,
        persistent=True,
        alexa=False,
    )

    assert session.calls[0][0].endswith("/mqttcfg")
    assert session.calls[0][1]["params"] == {
        "broker": "192.168.1.2",
        "port": 1883,
        "user": "ha",
        "pswd": "secret",
        "dom": "h",
        "dopt": "retain",
        "log": "y",
        "persistence": "y",
        "alexa": "n",
    }


async def test_network_configuration_uses_exact_firmware_parameters(
    client: tuple[GatewayClient, FakeSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway, session = client
    monkeypatch.setattr(gateway, "async_validate_host", _bypass_host_validation)

    await gateway.async_configure_network(
        ssid="IoT",
        password="secret",
        ip="192.168.1.20",
        gateway="192.168.1.1",
        udp_port=20000,
    )

    assert session.calls[0][0].endswith("/setting")
    assert session.calls[0][1]["params"] == {
        "ssid": "IoT",
        "pass": "secret",
        "ip": "192.168.1.20",
        "rip": "192.168.1.1",
        "uport": 20000,
    }


@pytest.mark.parametrize(
    "callback", ["http://8.8.8.8/hook", "http://user@192.168.1.2/hook"]
)
async def test_callback_rejects_public_or_credentialed_urls(
    client: tuple[GatewayClient, FakeSession], callback: str
) -> None:
    gateway, session = client

    with pytest.raises(GatewayValidationError, match=r"Callback|callback"):
        await gateway.async_set_callback(callback)

    assert session.calls == []
