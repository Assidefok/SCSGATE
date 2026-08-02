"""Safe, GET-only HTTP client for ESP_SCSGATE firmware 7.004."""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Mapping
from itertools import count
from time import monotonic
from typing import Final
from urllib.parse import urlsplit

import aiohttp

from .models import VALID_DEVICE_TYPES, GatewayDevice, GatewayStatus
from .parsers import parse_devices, parse_status

DEFAULT_TIMEOUT: Final = 10.0
_LOGGER = logging.getLogger(__name__)
_SAFE_DEVICE_REQUESTS: Final = frozenset(
    {"query", "prepare", "start", "stop", "resend", "clear"}
)
_SAFE_RESET_DEVICES: Final = frozenset({"mqtt", "esp", "pic", "all"})


class GatewayError(Exception):
    """Transport or non-success response; contains no host query or credentials."""


class GatewayConnectionError(GatewayError):
    """Gateway did not answer."""


class GatewayResponseError(GatewayError):
    """Gateway returned an unexpected HTTP response."""


class GatewayValidationError(GatewayError):
    """Caller requested an unsupported or unsafe operation."""


def _is_local_address(value: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        (value.is_private or value.is_loopback or value.is_link_local)
        and not value.is_unspecified
        and not value.is_multicast
        and not value.is_reserved
    )


class GatewayClient:
    """Explicit SCSGATE operations; never expose a generic request function publicly."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int = 80,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._session = session
        self.host = host.strip().strip("[]")
        self.port = port
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._operation_counter = count(1)
        self._debug_metrics: dict[str, int | str | None] = {
            "requests_total": 0,
            "failures_total": 0,
            "last_operation_id": None,
            "last_endpoint": None,
            "last_status": None,
            "last_duration_ms": None,
            "last_response_chars": None,
        }
        if not self.host or not 1 <= port <= 65535:
            raise GatewayValidationError("Invalid gateway address")
        try:
            address = ipaddress.ip_address(self.host)
        except ValueError as err:
            raise GatewayValidationError("Gateway host must be an IP address") from err
        if not _is_local_address(address):
            raise GatewayValidationError("Gateway must use a private or local address")
        self.host = address.compressed

    async def async_validate_host(self) -> None:
        """Re-check the pinned literal address before each request."""
        if not _is_local_address(ipaddress.ip_address(self.host)):
            raise GatewayValidationError("Gateway must use a private or local address")

    @property
    def _base_url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"

    @property
    def debug_metrics(self) -> dict[str, int | str | None]:
        """Return secret-free, in-memory transport metrics for diagnostics."""
        return dict(self._debug_metrics)

    def _record_request(
        self,
        *,
        operation_id: str,
        endpoint: str,
        started: float,
        status: int | None,
        response_chars: int | None,
        failed: bool,
    ) -> int:
        """Update transport metrics without retaining host, params, or payloads."""
        duration_ms = max(0, round((monotonic() - started) * 1000))
        self._debug_metrics.update(
            {
                "last_operation_id": operation_id,
                "last_endpoint": endpoint,
                "last_status": status,
                "last_duration_ms": duration_ms,
                "last_response_chars": response_chars,
            }
        )
        if failed:
            self._debug_metrics["failures_total"] = (
                int(self._debug_metrics["failures_total"] or 0) + 1
            )
        return duration_ms

    async def _async_request(
        self,
        path: str,
        params: Mapping[str, str | int] | None = None,
        *,
        sensitive: bool = False,
    ) -> str:
        """Issue one known path. Do not include params in exception text."""
        await self.async_validate_host()
        url = f"{self._base_url}{path}"
        operation_id = f"http-{next(self._operation_counter):06d}"
        self._debug_metrics["requests_total"] = (
            int(self._debug_metrics["requests_total"] or 0) + 1
        )
        started = monotonic()
        _LOGGER.debug(
            "HTTP operation started operation_id=%s endpoint=%s",
            operation_id,
            path,
        )
        try:
            async with self._session.get(
                url,
                params=params,
                allow_redirects=False,
                timeout=self._timeout,
                headers={"Accept": "text/html, text/plain, application/json"},
            ) as response:
                if response.status != 200:
                    duration_ms = self._record_request(
                        operation_id=operation_id,
                        endpoint=path,
                        started=started,
                        status=response.status,
                        response_chars=None,
                        failed=True,
                    )
                    _LOGGER.debug(
                        "HTTP operation failed operation_id=%s endpoint=%s "
                        "status=%s duration_ms=%s",
                        operation_id,
                        path,
                        response.status,
                        duration_ms,
                    )
                    raise GatewayResponseError(
                        f"SCSGATE {path} returned HTTP {response.status}"
                    )
                body = await response.text()
                duration_ms = self._record_request(
                    operation_id=operation_id,
                    endpoint=path,
                    started=started,
                    status=response.status,
                    response_chars=len(body),
                    failed=False,
                )
                _LOGGER.debug(
                    "HTTP operation completed operation_id=%s endpoint=%s "
                    "status=%s duration_ms=%s response_chars=%s",
                    operation_id,
                    path,
                    response.status,
                    duration_ms,
                    len(body),
                )
                return body
        except GatewayError:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            duration_ms = self._record_request(
                operation_id=operation_id,
                endpoint=path,
                started=started,
                status=None,
                response_chars=None,
                failed=True,
            )
            _LOGGER.debug(
                "HTTP operation unavailable operation_id=%s endpoint=%s "
                "duration_ms=%s error_type=%s",
                operation_id,
                path,
                duration_ms,
                type(err).__name__,
            )
            if sensitive:
                raise GatewayConnectionError(f"SCSGATE {path} unavailable") from None
            raise GatewayConnectionError(f"SCSGATE {path} unavailable") from err

    async def async_get_root(self) -> str:
        return await self._async_request("/")

    async def async_get_status(self) -> GatewayStatus:
        return parse_status(await self._async_request("/status"), self.host)

    async def async_get_help(self) -> str:
        return await self._async_request("/help")

    async def async_get_test(self) -> str:
        return await self._async_request("/test")

    async def async_get_request_page(self) -> str:
        return await self._async_request("/request")

    async def async_list_devices(self) -> list[GatewayDevice]:
        return parse_devices(await self._async_request("/devicename"))

    async def async_query_devices(self) -> list[GatewayDevice]:
        """Request firmware's current MQTT device table."""
        return await self.async_mqtt_devices("query")

    async def async_mqtt_devices(self, request: str) -> list[GatewayDevice]:
        if request not in _SAFE_DEVICE_REQUESTS:
            raise GatewayValidationError("Unsupported device management request")
        return parse_devices(
            await self._async_request("/mqttdevices", {"request": request})
        )

    async def async_save_device(
        self, bus_id: str, device_type: int, name: str, maxpos: int | None = None
    ) -> str:
        if (
            not bus_id
            or device_type not in VALID_DEVICE_TYPES
            or not name
            or len(name) > 80
        ):
            raise GatewayValidationError("Invalid device values")
        if maxpos is not None and not 0 <= maxpos <= 10000:
            raise GatewayValidationError("Invalid maximum position")
        params: dict[str, str | int] = {
            "busid": bus_id,
            "type": device_type,
            "devname": name,
        }
        if maxpos is not None:
            params["maxpos"] = maxpos
        return await self._async_request("/devicename", params)

    async def async_update_device(
        self,
        bus_id: str,
        device_type: int | None = None,
        name: str | None = None,
        max_position: int | None = None,
    ) -> str:
        """Create or update one firmware device record.

        The firmware endpoint has one save operation. Supplying all supported values
        prevents accidental resets of fields during an edit.
        """
        if device_type is None or name is None:
            raise GatewayValidationError(
                "Device type and name are required by firmware"
            )
        return await self.async_save_device(bus_id, device_type, name, max_position)

    async def async_reset(self, device: str) -> str:
        if device not in _SAFE_RESET_DEVICES:
            raise GatewayValidationError("Unsupported reset device")
        return await self._async_request("/reset", {"device": device})

    async def async_configure_callback(self, callback: str) -> str:
        if (
            not callback
            or len(callback) > 200
            or any(char.isspace() for char in callback)
        ):
            raise GatewayValidationError("Invalid callback")
        if callback.startswith(":"):
            port_text, separator, path = callback[1:].partition("/")
            if (
                not separator
                or not port_text.isdigit()
                or not 1 <= int(port_text) <= 65535
                or not path
            ):
                raise GatewayValidationError("Invalid callback")
        elif callback.startswith("/") and not callback.startswith("//"):
            pass
        else:
            parsed = urlsplit(callback)
            if (
                parsed.scheme != "http"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.fragment
            ):
                raise GatewayValidationError("Invalid callback")
            try:
                callback_address = ipaddress.ip_address(parsed.hostname)
            except ValueError as err:
                raise GatewayValidationError(
                    "Callback host must be an IP address"
                ) from err
            if not _is_local_address(callback_address):
                raise GatewayValidationError(
                    "Callback must target a private or local address"
                )
        return await self._async_request("/backsetting", {"callback": callback})

    async def async_set_callback(self, callback: str) -> str:
        return await self.async_configure_callback(callback)

    async def async_get_callback(self) -> str:
        return await self._async_request("/callback")

    async def async_program_pic(self, program: str) -> str:
        if program not in {"T", "Y"}:
            raise GatewayValidationError("Invalid PIC programming operation")
        return await self._async_request("/picprog", {"program": program})

    async def async_pic_program(self, mode: str) -> str:
        return await self.async_program_pic(mode)

    async def async_send_raw_telegram(
        self,
        type_hex: str,
        from_hex: str,
        to_hex: str,
        command_hex: str,
        response: str,
    ) -> str:
        if response not in {"none", "y", "i"}:
            raise GatewayValidationError("Invalid telegram response mode")
        for value in (type_hex, from_hex, to_hex, command_hex):
            if (
                not value
                or len(value) > 32
                or any(char not in "0123456789abcdefABCDEF*#" for char in value)
            ):
                raise GatewayValidationError("Invalid raw telegram value")
        return await self._async_request(
            "/gate",
            {
                "type": type_hex,
                "from": from_hex,
                "to": to_hex,
                "cmd": command_hex,
                "resp": response,
            },
        )

    async def async_configure_mqtt(
        self,
        *,
        broker: str | None = None,
        server: str | None = None,
        port: int,
        username: str = "",
        user: str | None = None,
        password: str = "",
        domain: str = "h",
        dom: str | None = None,
        discovery_options: str = "",
        dopt: str | None = None,
        log: bool = False,
        persistent: bool = False,
        persist: bool | None = None,
        alexa: bool = False,
    ) -> str:
        """Send credentials once. Callers must not retain or log provided password."""
        broker = broker or server
        username = user if user is not None else username
        domain = dom if dom is not None else domain
        discovery_options = dopt if dopt is not None else discovery_options
        persistent = persist if persist is not None else persistent
        if not broker or len(broker) > 253 or not 1 <= port <= 65535 or domain != "h":
            raise GatewayValidationError("Invalid MQTT configuration")
        params: dict[str, str | int] = {
            "broker": broker,
            "port": port,
            "user": username,
            "pswd": password,
            "dom": domain,
            "dopt": discovery_options,
            "log": "y" if log else "n",
            "persistence": "y" if persistent else "n",
            "alexa": "y" if alexa else "n",
        }
        return await self._async_request("/mqttcfg", params, sensitive=True)

    async def async_configure_network(
        self,
        *,
        ssid: str,
        password: str,
        ip: str,
        gateway: str,
        udp_port: int | None = None,
        udpport: int | None = None,
    ) -> str:
        """Send Wi-Fi secret once. It must never be placed in config entry data."""
        udp_port = udpport if udpport is not None else udp_port
        if not ssid or len(ssid) > 32 or udp_port is None or not 1 <= udp_port <= 65535:
            raise GatewayValidationError("Invalid network configuration")
        try:
            ipaddress.ip_address(ip)
            ipaddress.ip_address(gateway)
        except ValueError as err:
            raise GatewayValidationError("Invalid network address") from err
        return await self._async_request(
            "/setting",
            {
                "ssid": ssid,
                "pass": password,
                "ip": ip,
                "rip": gateway,
                "uport": udp_port,
            },
            sensitive=True,
        )
