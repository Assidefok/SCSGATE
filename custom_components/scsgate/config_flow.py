"""Config and protected administration flows for SCSGATE."""

from __future__ import annotations

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

from .api import GatewayClient, GatewayConnectionError, GatewayValidationError
from .const import CONF_LAST_CENSUS, CONF_PROTOCOL_DEBUG, DOMAIN

CONF_SCAN_INTERVAL = "scan_interval"
CONF_ENABLE_RAW = "enable_raw_commands"
CONF_LAST_SNAPSHOT = "last_device_snapshot"
DEFAULT_PORT = 80
DEFAULT_SCAN_INTERVAL = 300
DEVICE_TYPES = {1, 3, 4, 8, 9, 11, 14, 18, 19}
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
        return ScsGateOptionsFlow(config_entry)


class ScsGateOptionsFlow(config_entries.OptionsFlow):
    """Deliberately narrow admin UI; no generic HTTP request escape hatch."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry
        self._pending: dict[str, Any] = {}

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

    def _finish(self) -> FlowResult:
        """Finish an action without discarding previously selected options."""
        return self.async_create_entry(title="", data=dict(self.config_entry.options))

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
            except GatewayConnectionError:
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
            menu_options=["device_query", "device_add", "device_edit"],
        )

    async def async_step_device_query(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            try:
                await self._client.async_query_devices()
                return self._finish()
            except GatewayConnectionError:
                return self.async_show_form(
                    step_id="device_query",
                    data_schema=vol.Schema({}),
                    errors={"base": "cannot_connect"},
                )
        return self.async_show_form(
            step_id="device_query",
            data_schema=vol.Schema({vol.Required("query", default=True): bool}),
        )

    def _device_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("busid"): vol.All(str, vol.Length(min=1, max=32)),
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
                "census_prepare",
                "census_start",
                "census_query",
                "census_stop",
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
            except GatewayConnectionError:
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

    async def async_step_census_prepare(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            try:
                await self._run_operation(
                    "census",
                    "prepare",
                    self._client.async_mqtt_devices("prepare"),
                )
            except GatewayConnectionError:
                return self.async_show_form(
                    step_id="census_prepare",
                    data_schema=vol.Schema(
                        {vol.Required("confirm", default=False): vol.In([True])}
                    ),
                    errors={"base": "cannot_connect"},
                )
            return await self.async_step_census_start()
        return self.async_show_form(
            step_id="census_prepare",
            data_schema=vol.Schema(
                {vol.Required("confirm", default=False): vol.In([True])}
            ),
        )

    async def async_step_census_start(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            await self._run_operation(
                "census", "start", self._client.async_mqtt_devices("start")
            )
            return await self.async_step_census_query()
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
            await self._run_operation(
                "census", "query", self._client.async_query_devices()
            )
            return await self.async_step_census_stop()
        return self.async_show_form(
            step_id="census_query",
            data_schema=vol.Schema(
                {vol.Required("confirm", default=False): vol.In([True])}
            ),
        )

    async def async_step_census_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            await self._run_operation(
                "census", "stop", self._client.async_mqtt_devices("stop")
            )
            await self._run_operation(
                "census", "resend", self._client.async_mqtt_devices("resend")
            )
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                options={
                    **self.config_entry.options,
                    CONF_LAST_CENSUS: datetime.now(UTC).isoformat(timespec="seconds"),
                },
            )
            return self._finish()
        return self.async_show_form(
            step_id="census_stop",
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
            if len(callback_url) > 200:
                return self.async_show_form(
                    step_id="callback",
                    data_schema=vol.Schema({vol.Required("callback"): str}),
                    errors={"callback": "invalid_callback"},
                )
            try:
                await self._client.async_set_callback(callback_url)
            except GatewayValidationError:
                return self.async_show_form(
                    step_id="callback",
                    data_schema=vol.Schema({vol.Required("callback"): str}),
                    errors={"callback": "invalid_callback"},
                )
            return self._finish()
        return self.async_show_form(
            step_id="callback", data_schema=vol.Schema({vol.Required("callback"): str})
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
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                options={
                    **self.config_entry.options,
                    CONF_LAST_SNAPSHOT: str(devices)[:4096],
                },
            )
            await self._client.async_mqtt_devices("clear")
            await self._client.async_mqtt_devices("prepare")
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
                }
            ),
        )
