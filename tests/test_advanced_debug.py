"""Tests for the opt-in, read-only TCP SCS diagnostic capture."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from custom_components.scsgate.advanced_debug import AdvancedTcpDebugMonitor


class _Reader:
    """Small controllable replacement for an asyncio stream reader."""

    def __init__(self, chunks: list[bytes] | None = None) -> None:
        self._chunks: asyncio.Queue[bytes] = asyncio.Queue()
        for chunk in chunks or []:
            self._chunks.put_nowait(chunk)

    async def read(self, _size: int) -> bytes:
        return await self._chunks.get()

    async def feed(self, chunk: bytes) -> None:
        await self._chunks.put(chunk)


class _Writer:
    """Capture writes without opening a TCP connection."""

    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


def _factory(
    reader: _Reader, writer: _Writer
) -> Callable[[str, int], Awaitable[tuple[_Reader, _Writer]]]:
    async def connect(host: str, port: int) -> tuple[_Reader, _Writer]:
        assert host == "192.168.1.20"
        assert port == 5045
        return reader, writer

    return connect


async def _wait_for(predicate: Callable[[], bool]) -> None:
    for _ in range(50):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("monitor did not reach expected state")


async def test_start_sends_temporary_capture_and_restores_stock_pic_mode() -> None:
    reader = _Reader([b"#ok\n"])
    writer = _Writer()
    monitor = AdvancedTcpDebugMonitor(
        "192.168.1.20", connect_factory=_factory(reader, writer), duration=60
    )

    await monitor.async_start()
    await _wait_for(lambda: len(writer.writes) >= 2)
    assert writer.writes[0] == b'#setup {"uart":"tcp"}'
    assert writer.writes[1] == b"@\x15@MA@Y0@F0@A0000@B0000@l"

    await monitor.async_stop()

    written = b"".join(writer.writes)
    assert b"@\x15@MX@Y1@F3@l" in written
    assert b'#setup {"debug":"no"}' in written
    assert writer.closed is True
    assert monitor.state == "idle"
    assert monitor.diagnostics["restoration_required"] is False


async def test_fragmented_telegram_lines_are_retained_as_complete_records() -> None:
    reader = _Reader([b"#ok\n"])
    writer = _Writer()
    monitor = AdvancedTcpDebugMonitor(
        "192.168.1.20", connect_factory=_factory(reader, writer), duration=60
    )

    await monitor.async_start()
    await _wait_for(lambda: monitor.state == "capturing")
    await reader.feed(b"SCS[0]: A8 32")
    await reader.feed(b" 00 12\r\nSCS[1]: F5")
    await reader.feed(b" 79 24\n")
    await _wait_for(lambda: monitor.diagnostics["received_total"] == 2)

    exported = monitor.export(10)
    assert [item["text"] for item in exported["messages"]] == [
        "SCS[0]: A8 32 00 12",
        "SCS[1]: F5 79 24",
    ]
    assert [item["kind"] for item in exported["messages"]] == [
        "scs_telegram",
        "scs_telegram",
    ]

    await monitor.async_stop()


async def test_disconnect_requires_explicit_recovery_and_never_leaks_capture() -> None:
    reader = _Reader([b"#ok\n", b"SCS[0]: private-address\n", b""])
    writer = _Writer()
    monitor = AdvancedTcpDebugMonitor(
        "192.168.1.20", connect_factory=_factory(reader, writer), duration=60
    )

    await monitor.async_start()
    await _wait_for(lambda: monitor.state == "restore_required")

    diagnostics = monitor.diagnostics
    assert diagnostics["restoration_required"] is True
    assert "private-address" not in str(diagnostics)
    assert writer.closed is True


async def test_retention_and_export_are_bounded_and_clear_is_volatile_only() -> None:
    reader = _Reader([b"#ok\n"])
    writer = _Writer()
    monitor = AdvancedTcpDebugMonitor(
        "192.168.1.20",
        message_limit=2,
        connect_factory=_factory(reader, writer),
        duration=60,
    )

    await monitor.async_start()
    await _wait_for(lambda: monitor.state == "capturing")
    for number in range(3):
        await reader.feed(f"SCS[0]: {number}\n".encode())
    await _wait_for(lambda: monitor.diagnostics["received_total"] == 3)

    exported = monitor.export(99)
    assert [item["text"] for item in exported["messages"]] == [
        "SCS[0]: 1",
        "SCS[0]: 2",
    ]
    assert monitor.diagnostics["discarded_total"] == 1
    monitor.clear()
    assert monitor.diagnostics["retained_messages"] == 0
    assert monitor.diagnostics["received_total"] == 3

    await monitor.async_stop()


async def test_explicit_recovery_uses_a_new_connection_and_stock_restore() -> None:
    disconnected_reader = _Reader([b"#ok\n", b""])
    disconnected_writer = _Writer()
    recovery_reader = _Reader([b"#ok\n"])
    recovery_writer = _Writer()
    calls = 0

    async def connect(_host: str, _port: int) -> tuple[_Reader, _Writer]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return disconnected_reader, disconnected_writer
        return recovery_reader, recovery_writer

    monitor = AdvancedTcpDebugMonitor(
        "192.168.1.20", connect_factory=connect, duration=60
    )
    await monitor.async_start()
    await _wait_for(lambda: monitor.state == "restore_required")

    await monitor.async_recover()

    assert b"@\x15@MX@Y1@F3@l" in recovery_writer.writes
    assert b'#setup {"debug":"no"}' in recovery_writer.writes
    assert recovery_writer.closed is True
    assert monitor.state == "idle"
    assert monitor.diagnostics["restoration_required"] is False


async def test_second_start_is_rejected_while_single_client_session_is_active() -> None:
    reader = _Reader([b"#ok\n"])
    writer = _Writer()
    monitor = AdvancedTcpDebugMonitor(
        "192.168.1.20", connect_factory=_factory(reader, writer), duration=60
    )
    await monitor.async_start()
    await _wait_for(lambda: monitor.state == "capturing")

    with pytest.raises(RuntimeError):
        await monitor.async_start()

    await monitor.async_shutdown()


async def test_duration_expiry_restores_without_marking_connection_lost() -> None:
    reader = _Reader([b"#ok\n"])
    writer = _Writer()
    monitor = AdvancedTcpDebugMonitor(
        "192.168.1.20",
        connect_factory=_factory(reader, writer),
        duration=0.01,
    )

    await monitor.async_start()
    await asyncio.sleep(0.05)

    assert monitor.state == "idle"
    assert b"@\x15@MX@Y1@F3@l" in writer.writes
    assert b'#setup {"debug":"no"}' in writer.writes
    assert monitor.diagnostics["restoration_required"] is False
