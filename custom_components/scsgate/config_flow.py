"""Config and protected administration flows for SCSGATE."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from collections.abc import Awaitable, Mapping
from datetime import UTC, datetime
from itertools import count
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    GatewayClient,
    GatewayConnectionError,
    GatewayResponseError,
    GatewayValidationError,
)
from .const import (
    CONF_ADVANCED_TCP_DEBUG,
    CONF_ADVANCED_TCP_DEBUG_DURATION,
    CONF_ADVANCED_TCP_DEBUG_LIMIT,
    CONF_BUS_MONITOR,
    CONF_BUS_MONITOR_LIMIT,
    CONF_LAST_CENSUS,
    CONF_PROTOCOL_DEBUG,
    DEFAULT_ADVANCED_TCP_DEBUG_DURATION,
    DEFAULT_ADVANCED_TCP_DEBUG_LIMIT,
    DEFAULT_BUS_MONITOR_LIMIT,
    DOMAIN,
    MAX_CALLBACK_LENGTH,
)
from .models import GatewayDevice

CONF_SCAN_INTERVAL = "scan_interval"
CONF_ENABLE_RAW = "enable_raw_commands"
CONF_LAST_SNAPSHOT = "last_device_snapshot"
DEFAULT_PORT = 80
DEFAULT_SCAN_INTERVAL = 300
DEVICE_TYPES = {1, 3, 4, 8, 9, 11, 14, 18, 19}
COVER_DEVICE_TYPES = frozenset({8, 9, 18, 19})
DEVICE_TYPE_LABELS = {
    1: "switch/light",
    3: "dimmer",
    4: "dimmer",
    8: "cover",
    9: "percentage cover",
    11: "generic",
    14: "alarm",
    18: "cover U",
    19: "percentage cover U",
}
_LOGGER = logging.getLogger(__name__)
_ADMIN_OPERATION_COUNTER = count(1)


def _field(value: Any, name: str, default: Any = None) -> Any:
    """Read a status value from a model or mapping."""
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _is_private_host(host: str) -> bool:
    """Allow only literal loopback or RFC1918/link-local IP addresses."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(address.is_private or address.is_loopback or address.is_link_local)


def _safe_device_name(name: str | None) -> str:
    """Bound a firmware-provided name before presenting it in a flow."""
    if not name:
        return ""
    return "".join(character for character in str(name) if character.isprintable())[:64]


def _format_device_lines(devices: list[GatewayDevice]) -> str:
    """Render one stable, human-readable line for every firmware table entry."""
    lines: list[str] = []
    for index, device in enumerate(devices, start=1):
        device_type = device.type
        type_name = DEVICE_TYPE_LABELS.get(device_type, "unknown")
        line = f"{index}. {device.bus_id} — type {device_type or '?'} ({type_name})"
        name = _safe_device_name(device.name)
        if name:
            line += f" — {name}"
        if device.maxpos is not None:
            line += f" — maxpos {device.maxpos}"
        lines.append(line)
    return "\n".join(lines) or "—"


class ScsGateConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one local, unauthenticated SCSGATE."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            if not _is_private_host(host):
                errors[CONF_HOST] = "private_host_required"
            else:
                client = GatewayClient(
                    async_get_clientsession(self.hass), host, user_input[CONF_PORT]
                )
                try:
                    status = await client.async_get_status()
                    mac = _field(status, "mac")
                    firmware = str(_field(status, "firmware_esp", ""))
                    if firmware and "7." not in firmware and "VER_" not in firmware:
                        errors["base"] = "unsupported_firmware"
                    else:
                        unique_id = (
                            str(mac).upper()
                            if mac
                            else f"{host}:{user_input[CONF_PORT]}"
                        )
                        await self.async_set_unique_id(unique_id)
                        self._abort_if_unique_id_configured()
                        return self.async_create_entry(
                            title=f"SCSGATE {str(mac).upper() if mac else host}",
                            data={CONF_HOST: host, CONF_PORT: user_input[CONF_PORT]},
                        )
                except GatewayConnectionError:
                    errors["base"] = "cannot_connect"
                except (
                    Exception
                ):  # Gateway HTML can be malformed; do not reveal response.
                    errors["base"] = "invalid_status"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_PORT, default=DEFAULT_PORT): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=65535)
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ScsGateOptionsFlow:
        return ScsGateOptionsFlow()


class ScsGateOptionsFlow(config_entries.OptionsFlow):
    """Deliberately narrow admin UI; no generic HTTP request escape hatch."""

    def __init__(self) -> None:
        self._pending: dict[str, Any] = {}
        self._census_devices: list[GatewayDevice] = []
        self._census_focus = "all"
        self._census_active = False
        self._census_cleanup_task: asyncio.Task[None] | None = None

    @property
    def _client(self) -> GatewayClient:
        runtime = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        runtime_client = getattr(runtime, "client", None)
        if isinstance(runtime_client, GatewayClient):
            return runtime_client
        return GatewayClient(
            async_get_clientsession(self.hass),
            self.config_entry.data[CONF_HOST],
            self.config_entry.data[CONF_PORT],
            protocol_debug=self.config_entry.options.get(CONF_PROTOCOL_DEBUG, False),
        )

    async def _status(self) -> Any:
        return await self._client.async_get_status()

    async def _run_operation(
        self, category: str, action: str, operation: Awaitable[Any]
    ) -> Any:
        """Track an admin operation without logging its submitted values."""
        operation_id = f"admin-{next(_ADMIN_OPERATION_COUNTER):06d}"
        _LOGGER.debug(
            "Gateway admin operation started operation_id=%s category=%s action=%s",
            operation_id,
            category,
            action,
        )
        try:
            result = await operation
        except Exception as err:
            _LOGGER.debug(
                "Gateway admin operation failed operation_id=%s category=%s "
                "action=%s error_type=%s",
                operation_id,
                category,
                action,
                type(err).__name__,
            )
            raise
        result_count = len(result) if isinstance(result, list) else None
        _LOGGER.debug(
            "Gateway admin operation completed operation_id=%s category=%s "
            "action=%s result_count=%s",
            operation_id,
            category,
            action,
            result_count,
        )
        return result

    def _identifier(self, status: Any) -> str:
        """Return the stable confirmation identifier exposed to the user."""
        return str(
            _field(status, "mac")
            or self.config_entry.unique_id
            or (
                f"{self.config_entry.data[CONF_HOST]}:"
                f"{self.config_entry.data[CONF_PORT]}"
            )
        ).upper()

    def _finish(self, extra_options: Mapping[str, Any] | None = None) -> FlowResult:
        """Finish an action without discarding previously selected options."""
        return self.async_create_entry(
            title="",
            data={
                **self.config_entry.options,
                **self._pending.get("options", {}),
                **(extra_options or {}),
            },
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "status",
                "devices",
                "census",
                "mqtt",
                "network",
                "callback",
                "maintenance",
                "danger",
                "advanced",
            ],
        )

    async def async_step_status(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self._status()
                return self._finish()
            except (GatewayConnectionError, GatewayResponseError):
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="status",
            data_schema=vol.Schema({vol.Required("refresh", default=True): bool}),
            errors=errors,
        )

    async def async_step_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_show_menu(
            step_id="devices",
            menu_options=[
                "device_query",
                "discover_devices",
                "discover_covers",
                "device_add",
                "device_edit",
            ],
        )

    async def async_step_device_query(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            try:
                self._census_devices = await self._client.async_query_devices()
                return await self.async_step_device_query_results()
            except (
                GatewayConnectionError,
                GatewayResponseError,
                GatewayValidationError,
            ):
                return self.async_show_form(
                    step_id="device_query",
                    data_schema=vol.Schema({}),
                    errors={"base": "cannot_connect"},
                )
        return self.async_show_form(
            step_id="device_query",
            data_schema=vol.Schema({vol.Required("query", default=True): bool}),
        )

    async def async_step_device_query_results(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Present one visible entry per device instead of discarding the query."""
        if user_input is not None:
            return self._finish()
        cover_count = sum(
            device.type in COVER_DEVICE_TYPES for device in self._census_devices
        )
        return self.async_show_form(
            step_id="device_query_results",
            data_schema=vol.Schema({vol.Required("done", default=True): bool}),
            description_placeholders={
                "count": str(len(self._census_devices)),
                "cover_count": str(cover_count),
                "devices": _format_device_lines(self._census_devices),
            },
        )

    def _device_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("busid"): vol.All(str, vol.Match(r"^[0-9A-Fa-f]{2}$")),
                vol.Required("type"): vol.All(vol.Coerce(int), vol.In(DEVICE_TYPES)),
                vol.Required("devname"): vol.All(str, vol.Length(min=1, max=64)),
                vol.Optional("maxpos", default=100): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=10000)
                ),
                vol.Required("resend", default=True): bool,
            }
        )

    async def _save_device(self, user_input: dict[str, Any]) -> FlowResult:
        try:
            await self._client.async_update_device(
                user_input["busid"],
                device_type=user_input["type"],
                name=user_input["devname"],
                max_position=user_input["maxpos"],
            )
            if user_input["resend"]:
                await self._client.async_mqtt_devices("resend")
            return self._finish()
        except GatewayConnectionError:
            return self.async_show_form(
                step_id="device_add",
                data_schema=self._device_schema(),
                errors={"base": "cannot_connect"},
            )

    async def async_step_device_add(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return await self._save_device(user_input)
        return self.async_show_form(
            step_id="device_add", data_schema=self._device_schema()
        )

    async def async_step_device_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return await self._save_device(user_input)
        return self.async_show_form(
            step_id="device_edit", data_schema=self._device_schema()
        )

    async def async_step_census(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_show_menu(
            step_id="census",
            menu_options=[
                "discover_devices",
                "discover_covers",
                "census_recovery_stop",
                "census_resend",
            ],
        )

    async def _census(
        self, step_id: str, request: str, user_input: dict[str, Any] | None
    ) -> FlowResult:
        if user_input is not None:
            try:
                if request == "query":
                    operation = self._client.async_query_devices()
                elif request == "__reset_mqtt":
                    operation = self._client.async_reset("mqtt")
                elif request == "__picprog_test":
                    operation = self._client.async_pic_program("T")
                else:
                    operation = self._client.async_mqtt_devices(request)
                category = "census" if not request.startswith("__") else "maintenance"
                await self._run_operation(
                    category, request.removeprefix("__"), operation
                )
                return self._finish()
            except (GatewayConnectionError, GatewayResponseError):
                return self.async_show_form(
                    step_id=step_id,
                    data_schema=vol.Schema({}),
                    errors={"base": "cannot_connect"},
                )
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {vol.Required("confirm", default=False): vol.In([True])}
            ),
        )

    async def _async_prepare_census(
        self,
        step_id: str,
        focus: str,
        user_input: dict[str, Any] | None,
    ) -> FlowResult:
        """Prepare the one real firmware census with an explicit UI focus."""
        self._census_focus = focus
        if user_input is not None:
            if self._census_active:
                return self._census_recovery_error("census_recovery_required")
            try:
                await self._run_operation(
                    "census",
                    "prepare",
                    self._client.async_mqtt_devices("prepare"),
                )
            except (GatewayConnectionError, GatewayResponseError):
                return self.async_show_form(
                    step_id=step_id,
                    data_schema=vol.Schema(
                        {vol.Required("confirm", default=False): vol.In([True])}
                    ),
                    errors={"base": "cannot_connect"},
                )
            self._census_active = True
            self._schedule_census_cleanup()
            return await self.async_step_census_start()
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {vol.Required("confirm", default=False): vol.In([True])}
            ),
        )

    async def async_step_discover_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Expose the firmware's global discovery as a visible guided action."""
        return await self._async_prepare_census("discover_devices", "all", user_input)

    async def async_step_discover_covers(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Guide a global census with additional cover-specific instructions."""
        return await self._async_prepare_census("discover_covers", "covers", user_input)

    async def async_step_census_prepare(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._async_prepare_census("census_prepare", "all", user_input)

    async def async_step_census_start(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            if not self._census_active:
                return await self.async_step_census_prepare()
            try:
                await self._run_operation(
                    "census", "start", self._client.async_mqtt_devices("start")
                )
                return await self._poll_census()
            except (GatewayConnectionError, GatewayResponseError):
                if not await self._stop_census_best_effort():
                    return self._census_recovery_error()
                return self.async_show_form(
                    step_id="census_prepare",
                    data_schema=vol.Schema(
                        {vol.Required("confirm", default=False): vol.In([True])}
                    ),
                    errors={"base": "cannot_connect"},
                )
        return self.async_show_form(
            step_id="census_start",
            data_schema=vol.Schema(
                {vol.Required("confirm", default=False): vol.In([True])}
            ),
        )

    async def async_step_census_query(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            if not self._census_active:
                return await self.async_step_census_prepare()
            return await self._poll_census()
        return self.async_show_form(
            step_id="census_query",
            data_schema=vol.Schema(
                {vol.Required("confirm", default=False): vol.In([True])}
            ),
        )

    async def _poll_census(self) -> FlowResult:
        """Poll the firmware's asynchronous PIC-table import without blocking HA."""
        try:
            for _ in range(10):
                complete, devices = await self._client.async_query_devices_with_state()
                if complete:
                    self._census_devices = devices
                    return await self.async_step_census_review()
                await asyncio.sleep(0.25)
        except (GatewayConnectionError, GatewayResponseError, GatewayValidationError):
            if not await self._stop_census_best_effort():
                return self._census_recovery_error()
            return self.async_show_form(
                step_id="census_prepare",
                data_schema=vol.Schema(
                    {vol.Required("confirm", default=False): vol.In([True])}
                ),
                errors={"base": "cannot_connect"},
            )
        if not await self._stop_census_best_effort():
            return self._census_recovery_error()
        return self.async_show_form(
            step_id="census_prepare",
            data_schema=vol.Schema(
                {vol.Required("confirm", default=False): vol.In([True])}
            ),
            errors={"base": "census_still_running"},
        )

    def _schedule_census_cleanup(self) -> None:
        """Ensure abandoned browser flows eventually restore firmware state."""
        if self._census_cleanup_task is not None:
            self._census_cleanup_task.cancel()
        self._census_cleanup_task = self.hass.async_create_task(
            self._async_census_timeout_cleanup(), "SCSGATE census timeout cleanup"
        )

    async def _async_census_timeout_cleanup(self) -> None:
        await asyncio.sleep(600)
        await self._stop_census_best_effort()

    async def _stop_census_best_effort(self) -> bool:
        """Stop PIC learning without leaking submitted values or masking errors."""
        stopped = True
        if self._census_active:
            try:
                await self._client.async_mqtt_devices("stop")
            except Exception as err:
                stopped = False
                _LOGGER.debug("Census cleanup failed error_type=%s", type(err).__name__)
        if stopped:
            self._census_active = False
        task = self._census_cleanup_task
        self._census_cleanup_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        return stopped

    def _census_recovery_error(self, error: str = "cannot_connect") -> FlowResult:
        return self.async_show_form(
            step_id="census_recovery_stop",
            data_schema=vol.Schema(
                {vol.Required("confirm", default=True): vol.In([True])}
            ),
            errors={"base": error},
        )

    async def async_step_census_review(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show exactly what the firmware learned before accepting the census."""
        if user_input is not None:
            action = user_input["action"]
            if action == "scan_again":
                if not await self._stop_census_best_effort():
                    return self._census_recovery_error()
                if self._census_focus == "covers":
                    return await self.async_step_discover_covers()
                return await self.async_step_discover_devices()
            if action == "add_manual":
                if not await self._stop_census_best_effort():
                    return self._census_recovery_error()
                return await self.async_step_device_add()
            return await self.async_step_census_stop({"confirm": True})
        cover_count = sum(
            device.type in COVER_DEVICE_TYPES for device in self._census_devices
        )
        return self.async_show_form(
            step_id="census_review",
            data_schema=vol.Schema(
                {
                    vol.Required("action", default="accept"): vol.In(
                        ["accept", "scan_again", "add_manual"]
                    )
                }
            ),
            description_placeholders={
                "count": str(len(self._census_devices)),
                "cover_count": str(cover_count),
                "devices": _format_device_lines(self._census_devices),
            },
        )

    async def async_step_census_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            try:
                await self._run_operation(
                    "census", "stop", self._client.async_mqtt_devices("stop")
                )
                self._census_active = False
                await self._run_operation(
                    "census", "resend", self._client.async_mqtt_devices("resend")
                )
            except (GatewayConnectionError, GatewayResponseError):
                await self._stop_census_best_effort()
                return self._census_recovery_error()
            await self._stop_census_best_effort()
            return self._finish(
                {CONF_LAST_CENSUS: datetime.now(UTC).isoformat(timespec="seconds")}
            )
        return self.async_show_form(
            step_id="census_stop",
            data_schema=vol.Schema(
                {vol.Required("confirm", default=False): vol.In([True])}
            ),
        )

    async def async_step_census_recovery_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Stop a census abandoned in another browser flow."""
        if user_input is not None:
            self._census_active = True
            if not await self._stop_census_best_effort():
                return self._census_recovery_error()
            return self._finish()
        return self.async_show_form(
            step_id="census_recovery_stop",
            data_schema=vol.Schema(
                {vol.Required("confirm", default=False): vol.In([True])}
            ),
        )

    async def async_step_census_resend(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._census("census_resend", "resend", user_input)

    async def async_step_mqtt(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            try:
                # Password only exists in this form submission; never options/data.
                await self._client.async_configure_mqtt(
                    broker=user_input["broker"],
                    port=user_input["port"],
                    username=user_input["username"],
                    password=user_input["password"],
                    domain=user_input["domain"],
                    discovery_options=user_input["discovery_options"],
                    log=user_input["log"],
                    persistent=user_input["persistent"],
                    alexa=user_input["alexa"],
                )
                return self._finish()
            except GatewayConnectionError:
                return self.async_show_form(
                    step_id="mqtt",
                    data_schema=self._mqtt_schema(),
                    errors={"base": "cannot_connect"},
                )
        return self.async_show_form(
            step_id="mqtt",
            data_schema=self._mqtt_schema(),
            description_placeholders={"warning": "GET HTTP without TLS"},
        )

    def _mqtt_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("broker"): str,
                vol.Required("port", default=1883): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
                vol.Optional("username", default=""): str,
                vol.Optional("password", default=""): str,
                vol.Optional("domain", default="h"): str,
                vol.Optional("discovery_options", default=""): str,
                vol.Optional("log", default=False): bool,
                vol.Optional("persistent", default=False): bool,
                vol.Optional("alexa", default=False): bool,
            }
        )

    async def async_step_network(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            identifier = self._identifier(await self._status())
            if user_input.pop("confirm_mac").upper() != identifier:
                return self.async_show_form(
                    step_id="network",
                    data_schema=self._network_schema(),
                    errors={"confirm_mac": "confirmation_required"},
                )
            await self._client.async_configure_network(
                ssid=user_input["ssid"],
                password=user_input["password"],
                ip=user_input["ip"],
                gateway=user_input["gateway"],
                udp_port=user_input["udp_port"],
            )
            return self._finish()
        return self.async_show_form(
            step_id="network", data_schema=self._network_schema()
        )

    def _network_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("ssid"): str,
                vol.Optional("password", default=""): str,
                vol.Required("ip"): str,
                vol.Required("gateway"): str,
                vol.Required("udp_port", default=1883): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
                vol.Required("confirm_mac"): str,
            }
        )

    async def async_step_callback(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            callback_url = user_input["callback"].strip()
            try:
                identifier = self._identifier(await self._status())
            except (GatewayConnectionError, GatewayResponseError):
                return self.async_show_form(
                    step_id="callback",
                    data_schema=self._callback_schema(),
                    errors={"base": "cannot_connect"},
                )
            if user_input["confirm_mac"].upper() != f"CALLBACK {identifier}":
                return self.async_show_form(
                    step_id="callback",
                    data_schema=self._callback_schema(),
                    errors={"confirm_mac": "confirmation_required"},
                )
            if len(callback_url) > MAX_CALLBACK_LENGTH:
                return self.async_show_form(
                    step_id="callback",
                    data_schema=self._callback_schema(),
                    errors={"callback": "invalid_callback"},
                )
            try:
                await self._client.async_set_callback(callback_url)
            except GatewayValidationError:
                return self.async_show_form(
                    step_id="callback",
                    data_schema=self._callback_schema(),
                    errors={"callback": "invalid_callback"},
                )
            except (GatewayConnectionError, GatewayResponseError):
                return self.async_show_form(
                    step_id="callback",
                    data_schema=self._callback_schema(),
                    errors={"base": "cannot_connect"},
                )
            return self._finish()
        return self.async_show_form(
            step_id="callback", data_schema=self._callback_schema()
        )

    def _callback_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("callback"): str,
                vol.Required("confirm_mac"): str,
            }
        )

    async def async_step_maintenance(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_show_menu(
            step_id="maintenance",
            menu_options=[
                "reset_mqtt",
                "reset_advanced",
                "picprog_test",
                "picprog_flash",
            ],
        )

    async def async_step_reset_mqtt(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._census("reset_mqtt", "__reset_mqtt", user_input)

    async def async_step_reset_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            identifier = self._identifier(await self._status())
            if user_input["confirm_mac"].upper() != identifier:
                return self.async_show_form(
                    step_id="reset_advanced",
                    data_schema=vol.Schema(
                        {
                            vol.Required("device"): vol.In(["esp", "pic", "all"]),
                            vol.Required("confirm_mac"): str,
                        }
                    ),
                    errors={"confirm_mac": "confirmation_required"},
                )
            await self._client.async_reset(user_input["device"])
            return self._finish()
        return self.async_show_form(
            step_id="reset_advanced",
            data_schema=vol.Schema(
                {
                    vol.Required("device"): vol.In(["esp", "pic", "all"]),
                    vol.Required("confirm_mac"): str,
                }
            ),
        )

    async def async_step_picprog_test(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._census("picprog_test", "__picprog_test", user_input)

    async def async_step_picprog_flash(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            identifier = self._identifier(await self._status())
            if user_input["confirm"].upper() != f"FLASH {identifier}":
                return self.async_show_form(
                    step_id="picprog_flash",
                    data_schema=vol.Schema({vol.Required("confirm"): str}),
                    errors={"confirm": "confirmation_required"},
                )
            await self._client.async_pic_program("Y")
            return self._finish()
        return self.async_show_form(
            step_id="picprog_flash",
            data_schema=vol.Schema({vol.Required("confirm"): str}),
        )

    async def async_step_danger(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            status = await self._status()
            identifier = self._identifier(status)
            if user_input["confirm"].upper() != f"CLEAR {identifier}":
                return self.async_show_form(
                    step_id="danger",
                    data_schema=vol.Schema({vol.Required("confirm"): str}),
                    errors={"confirm": "confirmation_required"},
                )
            devices = await self._client.async_query_devices()
            self._pending["options"] = {CONF_LAST_SNAPSHOT: str(devices)[:4096]}
            await self._client.async_mqtt_devices("clear")
            await self._client.async_mqtt_devices("prepare")
            self._census_active = True
            self._schedule_census_cleanup()
            return await self.async_step_census_start()
        return self.async_show_form(
            step_id="danger", data_schema=vol.Schema({vol.Required("confirm"): str})
        )

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    **self.config_entry.options,
                    CONF_ENABLE_RAW: user_input[CONF_ENABLE_RAW],
                    CONF_PROTOCOL_DEBUG: user_input[CONF_PROTOCOL_DEBUG],
                    CONF_BUS_MONITOR: user_input[CONF_BUS_MONITOR],
                    CONF_BUS_MONITOR_LIMIT: user_input[CONF_BUS_MONITOR_LIMIT],
                    CONF_ADVANCED_TCP_DEBUG: user_input[CONF_ADVANCED_TCP_DEBUG],
                    CONF_ADVANCED_TCP_DEBUG_LIMIT: user_input[
                        CONF_ADVANCED_TCP_DEBUG_LIMIT
                    ],
                    CONF_ADVANCED_TCP_DEBUG_DURATION: user_input[
                        CONF_ADVANCED_TCP_DEBUG_DURATION
                    ],
                    CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                },
            )
        return self.async_show_form(
            step_id="advanced",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENABLE_RAW,
                        default=self.config_entry.options.get(CONF_ENABLE_RAW, False),
                    ): bool,
                    vol.Required(
                        CONF_PROTOCOL_DEBUG,
                        default=self.config_entry.options.get(
                            CONF_PROTOCOL_DEBUG, False
                        ),
                    ): bool,
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
                    vol.Required(
                        CONF_BUS_MONITOR,
                        default=self.config_entry.options.get(CONF_BUS_MONITOR, False),
                    ): bool,
                    vol.Required(
                        CONF_BUS_MONITOR_LIMIT,
                        default=self.config_entry.options.get(
                            CONF_BUS_MONITOR_LIMIT, DEFAULT_BUS_MONITOR_LIMIT
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=500)),
                    vol.Required(
                        CONF_ADVANCED_TCP_DEBUG,
                        default=self.config_entry.options.get(
                            CONF_ADVANCED_TCP_DEBUG, False
                        ),
                    ): bool,
                    vol.Required(
                        CONF_ADVANCED_TCP_DEBUG_LIMIT,
                        default=self.config_entry.options.get(
                            CONF_ADVANCED_TCP_DEBUG_LIMIT,
                            DEFAULT_ADVANCED_TCP_DEBUG_LIMIT,
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=50, max=1000)),
                    vol.Required(
                        CONF_ADVANCED_TCP_DEBUG_DURATION,
                        default=self.config_entry.options.get(
                            CONF_ADVANCED_TCP_DEBUG_DURATION,
                            DEFAULT_ADVANCED_TCP_DEBUG_DURATION,
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=30, max=600)),
                }
            ),
        )
