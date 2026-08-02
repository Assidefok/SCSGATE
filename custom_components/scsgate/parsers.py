"""Tolerant parsers for SCSGATE's human-oriented HTTP pages."""

from __future__ import annotations

import html
import logging
import re
from typing import Final

from .models import GatewayDevice, GatewayStatus

_TAG_RE: Final = re.compile(r"<[^>]+>")
_SPACE_RE: Final = re.compile(r"[ \t\r\f\v]+")
_MAC_RE: Final = re.compile(r"\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b", re.I)
_INT_RE: Final = re.compile(r"-?\d+")
_LOGGER = logging.getLogger(__name__)


def _plain(value: str) -> str:
    value = re.sub(r"</?(?:br|tr|p|li|div)\b[^>]*>", "\n", value, flags=re.I)
    return _SPACE_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", value))).strip()


def _value_after(text: str, *labels: str) -> str | None:
    for label in labels:
        match = re.search(
            rf"(?:^|[\n;|])\s*{re.escape(label)}\s*[:=]\s*([^\n;|<]+)",
            text,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
    return None


def _int_after(text: str, *labels: str) -> int | None:
    value = _value_after(text, *labels)
    match = _INT_RE.search(value or "")
    return int(match.group()) if match else None


def _bool_after(text: str, *labels: str) -> bool | None:
    value = _value_after(text, *labels)
    if value is None:
        return None
    value = value.lower()
    if (
        any(word in value for word in ("connected", "on", "true", "yes", "ok"))
        and "not" not in value
        and "disconnected" not in value
    ):
        return True
    if any(word in value for word in ("disconnected", "off", "false", "no", "fail")):
        return False
    return None


def redact_broker(value: str | None) -> str | None:
    """Never retain broker addresses or userinfo in runtime diagnostic state."""
    if not value:
        return None
    return "configured"


def parse_status(body: str, host: str) -> GatewayStatus:
    """Parse /status without assuming stable HTML markup."""
    text = _plain(body)
    mac_match = _MAC_RE.search(text)
    firmware_match = re.search(r"ESP32_SCSGATE\s+(VER[_ ]?\d+(?:\.\d+)*)", text, re.I)
    pic_match = re.search(r"PIC\s+fw\s+version\s*:\s*([^\n]+)", text, re.I)
    rssi_match = re.search(r"\((-?\d+)\s*dBm\)", text, re.I)
    mqtt_open = re.search(r"MQTT\s+connection\s+is\s+(OPEN|CLOSED)", text, re.I)
    broker_match = re.search(r"MQTT\s+broker\s+is\s*:\s*([^\n]+)", text, re.I)
    known_match = re.search(r"known\s+devices\s+in\s+eeprom\s*:\s*([^\n]*)", text, re.I)
    known_ids = (
        re.findall(r"\b[0-9A-Fa-f]{2,4}\b", known_match.group(1)) if known_match else []
    )
    status = GatewayStatus(
        host=host,
        mac=mac_match.group().replace("-", ":").upper()
        if mac_match
        else _value_after(text, "mac"),
        firmware_esp=firmware_match.group(1)
        if firmware_match
        else _value_after(text, "firmware esp", "esp firmware", "version", "ver"),
        firmware_pic=pic_match.group(1).strip()
        if pic_match
        else _value_after(text, "firmware pic", "pic firmware", "pic version"),
        wifi_ssid=_value_after(text, "wifi connection ssid", "ssid", "wifi", "wi-fi"),
        rssi=int(rssi_match.group(1)) if rssi_match else _int_after(text, "rssi"),
        mqtt_connected=(mqtt_open.group(1).upper() == "OPEN")
        if mqtt_open
        else _bool_after(text, "mqtt connected", "mqtt status", "mqtt"),
        mqtt_broker=redact_broker(
            broker_match.group(1)
            if broker_match
            else _value_after(text, "mqtt broker", "broker")
        ),
        device_count=len(known_ids)
        if known_match
        else _int_after(text, "devices", "device count"),
    )
    fields_present = tuple(
        field
        for field, value in (
            ("mac", status.mac),
            ("firmware_esp", status.firmware_esp),
            ("firmware_pic", status.firmware_pic),
            ("wifi", status.wifi_ssid),
            ("rssi", status.rssi),
            ("mqtt", status.mqtt_connected),
            ("broker", status.mqtt_broker),
            ("device_count", status.device_count),
        )
        if value is not None
    )
    _LOGGER.debug(
        "Parsed gateway status fields=%s known_devices=%s",
        ",".join(fields_present),
        status.device_count,
    )
    return status


def parse_devices(body: str) -> list[GatewayDevice]:
    """Parse device records from /devicename or mqttdevices query responses.

    Firmware versions return key/value rows or short delimited records.
    Unknown rows are ignored, keeping the parser safe with changing HTML.
    """
    text = _plain(body)
    devices: list[GatewayDevice] = []
    records = re.split(r"(?:\r?\n|\|)+", text)
    ignored_records = 0
    for record in records:
        pairs = {
            key.lower(): value.strip()
            for key, value in re.findall(
                r"\b(busid|bus_id|id|type|devname|name|maxpos)\s*[:=]\s*([^,;]+)",
                record,
                re.I,
            )
        }
        bus_id = pairs.get("busid") or pairs.get("bus_id") or pairs.get("id")
        if not bus_id:
            firmware_row = re.match(
                r"^\s*([0-9A-Fa-f]{2})\s*"
                r"(coverpct\s+U|cover\s+U|alarm\s+board|coverpct|switch|dimmer|cover|generic)\b"
                r"(.*)$",
                record,
                re.I,
            )
            if firmware_row:
                label = re.sub(r"\s+", " ", firmware_row.group(2).lower())
                type_by_label = {
                    "switch": 1,
                    "dimmer": 3,
                    "cover": 8,
                    "coverpct": 9,
                    "generic": 11,
                    "alarm board": 14,
                    "cover u": 18,
                    "coverpct u": 19,
                }
                device_type = type_by_label[label]
                name = firmware_row.group(3).strip() or None
                maxpos = None
                if device_type in {9, 19} and name:
                    calibration = re.match(
                        r"^([0-9A-Fa-f]{4})\s+[0-9A-Fa-f]{4}\s+"
                        r"[0-9A-Fa-f]{2}\s+[0-9A-Fa-f]{4}\s+"
                        r"[0-9A-Fa-f]{2}(?:\s+(.*))?$",
                        name,
                    )
                    if calibration:
                        maxpos = int(calibration.group(1), 16)
                        name = (calibration.group(2) or "").strip() or None
                devices.append(
                    GatewayDevice(
                        bus_id=firmware_row.group(1).upper(),
                        type=device_type,
                        name=name,
                        maxpos=maxpos,
                    )
                )
                continue
        if not bus_id:
            if record.strip():
                ignored_records += 1
            continue
        type_value = pairs.get("type")
        maxpos_value = pairs.get("maxpos")
        devices.append(
            GatewayDevice(
                bus_id=bus_id,
                type=int(type_value)
                if type_value and type_value.strip().lstrip("-").isdigit()
                else None,
                name=pairs.get("devname") or pairs.get("name"),
                maxpos=int(maxpos_value)
                if maxpos_value and maxpos_value.strip().lstrip("-").isdigit()
                else None,
            )
        )
    _LOGGER.debug(
        "Parsed gateway devices devices=%s ignored_records=%s",
        len(devices),
        ignored_records,
    )
    return devices
