"""Typed values shared by SCSGATE transport and Home Assistant layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Final


class DeviceType(IntEnum):
    """Device types understood by ESP_SCSGATE 7.004."""

    SWITCH = 1
    DIMMER = 3
    DIMMER_ALT = 4
    COVER = 8
    COVER_ALT = 18
    COVER_POSITION = 9
    COVER_POSITION_ALT = 19
    GENERIC = 11
    ALARM = 14


VALID_DEVICE_TYPES: Final[frozenset[int]] = frozenset(item.value for item in DeviceType)


@dataclass(frozen=True, slots=True)
class GatewayCapabilities:
    """HTTP operations established for the target firmware."""

    device_management: bool = True
    mqtt_management: bool = True
    callback_management: bool = True
    pic_programming: bool = True
    raw_telegram: bool = True


@dataclass(frozen=True, slots=True)
class GatewayDevice:
    """One device entry maintained by firmware."""

    bus_id: str
    type: int | None = None
    name: str | None = None
    maxpos: int | None = None


@dataclass(frozen=True, slots=True)
class GatewayStatus:
    """Best-effort parsed gateway state; absent firmware fields stay None."""

    host: str
    mac: str | None = None
    firmware_esp: str | None = None
    firmware_pic: str | None = None
    wifi_ssid: str | None = None
    rssi: int | None = None
    mqtt_connected: bool | None = None
    mqtt_broker: str | None = None
    device_count: int | None = None
    last_census: str | None = None
    capabilities: GatewayCapabilities = field(default_factory=GatewayCapabilities)
