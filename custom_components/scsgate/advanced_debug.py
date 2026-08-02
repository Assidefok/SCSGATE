"""Guarded, volatile TCP/PIC monitor for stock SCSGATE firmware 7.004."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Final

TCP_DEBUG_PORT: Final = 5045
SETUP_COMMAND: Final = b'#setup {"uart":"tcp"}'
CAPTURE_COMMANDS: Final = b"@\x15@MA@Y0@F0@A0000@B0000@l"
RESTORE_COMMANDS: Final = b"@\x15@MX@Y1@F3@l"
DISABLE_COMMAND: Final = b'#setup {"debug":"no"}'
MAX_LINE_CHARS: Final = 512
MAX_PENDING_BYTES: Final = 4096
MAX_EXPORT_BYTES: Final = 65536

ConnectFactory = Callable[
    [str, int], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]
]


class AdvancedDebugError(RuntimeError):
    """Base exception with no peer-supplied content."""


class AdvancedDebugBusyError(AdvancedDebugError):
    """A capture is already active."""


class AdvancedDebugProtocolError(AdvancedDebugError):
    """The fixed TCP debug handshake failed."""


@dataclass(frozen=True, slots=True)
class AdvancedDebugRecord:
    """One sanitized record retained only in memory."""

    timestamp: str
    kind: str
    text: str
    truncated: bool = False


class AdvancedTcpDebugMonitor:
    """Run one bounded, temporary, read-only PIC log session."""

    def __init__(
        self,
        host: str,
        *,
        message_limit: int = 200,
        duration: int = 120,
        connect_factory: ConnectFactory = asyncio.open_connection,
    ) -> None:
        self._host = host
        self._records: deque[AdvancedDebugRecord] = deque(maxlen=message_limit)
        self._message_limit = message_limit
        self._duration = duration
        self._connect = connect_factory
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._listeners: set[Callable[[], None]] = set()
        self._state = "idle"
        self._received_total = 0
        self._discarded_total = 0
        self._started_at: str | None = None
        self._expires_at: str | None = None
        self._restoration_required = False
        self._last_error_type: str | None = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def retained_count(self) -> int:
        return len(self._records)

    @property
    def diagnostics(self) -> dict[str, Any]:
        """Return aggregate data only; captured payloads never enter diagnostics."""
        return {
            "state": self._state,
            "retained_count": len(self._records),
            "retained_messages": len(self._records),
            "received_total": self._received_total,
            "discarded_total": self._discarded_total,
            "started_at": self._started_at,
            "expires_at": self._expires_at,
            "restoration_required": self._restoration_required,
            "last_error_type": self._last_error_type,
        }

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    def _set_state(self, state: str) -> None:
        self._state = state
        self._notify()

    async def async_start(self) -> None:
        """Enter the firmware's UART bridge and start a temporary capture."""
        async with self._lock:
            if self._task is not None and not self._task.done():
                raise AdvancedDebugBusyError
            if self._restoration_required:
                raise AdvancedDebugBusyError
            self._set_state("starting")
            try:
                self._reader, self._writer = await asyncio.wait_for(
                    self._connect(self._host, TCP_DEBUG_PORT), timeout=5
                )
                await self._enter_uart_bridge()
                self._restoration_required = True
                self._writer.write(CAPTURE_COMMANDS)
                await asyncio.wait_for(self._writer.drain(), timeout=3)
            except (
                OSError,
                TimeoutError,
                asyncio.IncompleteReadError,
                asyncio.LimitOverrunError,
            ) as err:
                self._last_error_type = type(err).__name__
                await self._cleanup_failed_start()
                self._set_state(
                    "restore_required" if self._restoration_required else "error"
                )
                raise AdvancedDebugProtocolError from err
            except Exception:
                await self._cleanup_failed_start()
                self._set_state(
                    "restore_required" if self._restoration_required else "error"
                )
                raise

            now = datetime.now(UTC)
            self._started_at = now.isoformat()
            self._expires_at = datetime.fromtimestamp(
                now.timestamp() + self._duration, UTC
            ).isoformat()
            self._last_error_type = None
            self._set_state("capturing")
            self._task = asyncio.create_task(
                self._run_capture(), name="scsgate-advanced-debug"
            )

    async def _run_capture(self) -> None:
        pending = bytearray()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._duration
        connection_lost = False
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                assert self._reader is not None
                chunk = await asyncio.wait_for(self._reader.read(1024), remaining)
                if not chunk:
                    connection_lost = True
                    raise ConnectionError
                pending.extend(chunk)
                self._consume_lines(pending)
                if len(pending) > MAX_PENDING_BYTES:
                    self._append_record(bytes(pending[:MAX_LINE_CHARS]), True)
                    pending.clear()
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            pass
        except (OSError, ConnectionError) as err:
            self._last_error_type = type(err).__name__
            connection_lost = True
        finally:
            if pending:
                self._append_record(bytes(pending), len(pending) > MAX_LINE_CHARS)
            self._set_state("stopping")
            restored = (
                False if connection_lost else await self._restore_current_connection()
            )
            if not restored:
                await self._close()
            self._restoration_required = not restored
            self._set_state("idle" if restored else "restore_required")

    def _consume_lines(self, pending: bytearray) -> None:
        while True:
            cr = pending.find(b"\r")
            lf = pending.find(b"\n")
            positions = [position for position in (cr, lf) if position >= 0]
            if not positions:
                return
            end = min(positions)
            raw = bytes(pending[:end])
            consume = end + 1
            while consume < len(pending) and pending[consume] in (10, 13):
                consume += 1
            del pending[:consume]
            if raw:
                self._append_record(raw, len(raw) > MAX_LINE_CHARS)

    def _append_record(self, raw: bytes, truncated: bool) -> None:
        decoded = raw[:MAX_LINE_CHARS].decode("ascii", errors="replace")
        text = "".join(char if char.isprintable() else "?" for char in decoded)
        if len(self._records) == self._message_limit:
            self._discarded_total += 1
        self._received_total += 1
        kind = "scs_telegram" if text.startswith("SCS[") else "pic_status"
        self._records.append(
            AdvancedDebugRecord(datetime.now(UTC).isoformat(), kind, text, truncated)
        )
        self._notify()

    async def async_stop(self) -> None:
        """Stop capture and restore the gateway's stock PIC settings."""
        async with self._lock:
            task = self._task
            if task is not None and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            self._task = None
            if self._restoration_required and self._writer is not None:
                restored = await self._restore_current_connection()
                self._restoration_required = not restored
                self._set_state("idle" if restored else "restore_required")
            if self._restoration_required:
                await self.async_recover(_lock_held=True)

    async def async_recover(self, *, _lock_held: bool = False) -> None:
        """Reconnect and send only the fixed stock restoration sequence."""
        if not _lock_held:
            async with self._lock:
                await self.async_recover(_lock_held=True)
                return
        self._set_state("stopping")
        try:
            self._reader, self._writer = await asyncio.wait_for(
                self._connect(self._host, TCP_DEBUG_PORT), timeout=5
            )
            await self._enter_uart_bridge()
            restored = await self._restore_current_connection()
        except (
            OSError,
            TimeoutError,
            RuntimeError,
            AdvancedDebugProtocolError,
        ) as err:
            self._last_error_type = type(err).__name__
            restored = False
            await self._close()
        self._restoration_required = not restored
        self._set_state("idle" if restored else "restore_required")
        if not restored:
            raise AdvancedDebugProtocolError

    async def _enter_uart_bridge(self) -> None:
        """Select the fixed UART bridge after a bounded firmware handshake."""
        if self._reader is None or self._writer is None:
            raise AdvancedDebugProtocolError
        self._writer.write(SETUP_COMMAND)
        await asyncio.wait_for(self._writer.drain(), timeout=3)
        response = await asyncio.wait_for(self._reader.read(256), timeout=3)
        if len(response) > 256 or b"#ok" not in response:
            raise AdvancedDebugProtocolError

    async def _cleanup_failed_start(self) -> bool:
        if not self._restoration_required:
            await self._close()
            return True
        restored = await self._restore_current_connection()
        self._restoration_required = not restored
        return restored

    async def _restore_current_connection(self) -> bool:
        writer = self._writer
        if writer is None:
            return False
        try:
            writer.write(RESTORE_COMMANDS)
            await asyncio.wait_for(writer.drain(), timeout=3)
            writer.write(DISABLE_COMMAND)
            await asyncio.wait_for(writer.drain(), timeout=3)
            await self._close()
            return True
        except (OSError, ConnectionError, TimeoutError, RuntimeError):
            await self._close()
            return False

    async def _close(self) -> None:
        writer, self._writer, self._reader = self._writer, None, None
        if writer is not None:
            writer.close()
            with suppress(OSError, ConnectionError, TimeoutError, RuntimeError):
                await asyncio.wait_for(writer.wait_closed(), timeout=2)

    async def async_shutdown(self) -> None:
        """Restore before unload; failure keeps recovery controls available."""
        await self.async_stop()

    def clear(self) -> None:
        self._records.clear()
        self._notify()

    def export(self, limit: int) -> dict[str, Any]:
        """Explicitly disclose a capped subset of volatile records."""
        selected = list(self._records)[-max(0, min(limit, self._message_limit)) :]
        records: list[dict[str, Any]] = []
        size = 0
        for record in selected:
            item = asdict(record)
            item_size = len(
                json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
            if size + item_size > MAX_EXPORT_BYTES:
                break
            records.append(item)
            size += item_size
        return {
            "warning": "Contains volatile SCS bus activity and may reveal occupancy",
            "state": self._state,
            "messages": records,
            "truncated": len(records) < len(selected),
        }
