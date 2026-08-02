"""Protocol parser tests require no gateway or broker."""

import logging
from pathlib import Path

from custom_components.scsgate.parsers import parse_devices, parse_status

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_status_redacts_broker_secret() -> None:
    status = parse_status((FIXTURES / "status_7004.html").read_text(), "192.168.1.20")

    assert status.mac is None
    assert status.firmware_esp == "VER_7.004"
    assert status.firmware_pic == ">SCS 80.57"
    assert status.rssi == -61
    assert status.mqtt_connected is True
    assert status.mqtt_broker == "configured"
    assert status.device_count == 5


def test_parse_device_records() -> None:
    devices = parse_devices((FIXTURES / "devices_7004.html").read_text())

    assert [(item.bus_id, item.type, item.maxpos) for item in devices] == [
        ("24", 9, 100),
        ("41", 8, 255),
    ]


def test_parse_real_7004_device_list_fixture() -> None:
    devices = parse_devices(
        (FIXTURES / "devices_7004_real.html").read_text(encoding="utf-8")
    )

    assert [(item.bus_id, item.type) for item in devices] == [
        ("24", 1),
        ("34", 3),
        ("41", 8),
        ("42", 19),
        ("43", 11),
    ]
    percentage_cover = devices[3]
    assert percentage_cover.name == "Living cover"
    assert percentage_cover.maxpos == 16


def test_parse_dynamic_eleven_device_inventory_fixture() -> None:
    devices = parse_devices(
        (FIXTURES / "devices_7004_eleven.html").read_text(encoding="utf-8")
    )

    assert [(item.bus_id, item.type) for item in devices] == [
        ("24", 9),
        ("34", 9),
        ("41", 9),
        ("42", 9),
        ("43", 9),
        ("11", 3),
        ("12", 3),
        ("22", 1),
        ("23", 1),
        ("33", 1),
        ("32", 1),
    ]


def test_parser_debug_logs_counts_without_payload(
    caplog,
) -> None:
    private_name = "Unique private room"
    caplog.set_level(logging.DEBUG, logger="custom_components.scsgate.parsers")

    devices = parse_devices(
        f"busid=24,type=9,devname={private_name},maxpos=100|unparsed secret row"
    )

    assert len(devices) == 1
    assert "devices=1" in caplog.text
    assert "ignored_records=1" in caplog.text
    assert private_name not in caplog.text
    assert "unparsed secret row" not in caplog.text
