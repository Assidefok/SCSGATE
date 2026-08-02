"""Bounded, opt-in MQTT activity monitor for SCSGATE."""

from __future__ import annotations

import json
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.core import HomeAssistant, callback

MONITORED_TOPICS = ("scs/#", "SCSLOG", "SCSERROR")
MAX_PAYLOAD_CHARS = 512
MAX_EXPORT_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class BusMessage:
    """One MQTT message retained only in memory."""

    timestamp: str
    topic: str
    payload: str
    kind: str
    qos: int
    retained: bool
    truncated: bool


def _message_kind(topic: str, payload: str) -> str:
    """Classify a firmware topic without interpreting it as entity state."""
    if topic == "SCSLOG":
        lowered = payload.lower()
        if "rx:" in lowered:
            return "uart_rx"
        if "tx:" in lowered:
            return "uart_tx"
        return "uart_log"
    if topic == "SCSERROR":
        return "gateway_error"
    if "/set/" in topic or "/setlevel/" in topic or "/setposition/" in topic:
        return "command_to_gateway"
    if "/generic/from/" in topic or "/generic/to/" in topic:
        return "generic_bus"
    return "interpreted_state"


class BusMonitor:
    """Subscribe passively to documented firmware MQTT output."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        enabled: bool,
        message_limit: int = 100,
    ) -> None:
        self._hass = hass
        self.enabled = enabled
        self._messages: deque[BusMessage] = deque(maxlen=message_limit)
        self._unsubscribers: list[Callable[[], None]] = []
        self._listeners: set[Callable[[], None]] = set()
        self._owners: dict[str, int] = {}
        self._received_total = 0
        self._discarded_total = 0
        self._kind_counts: Counter[str] = Counter()
        self._raw_uart_seen = False

    async def async_start(self) -> None:
        """Start MQTT subscriptions when explicitly enabled."""
        if not self.enabled or self._unsubscribers:
            return
        try:
            for topic in MONITORED_TOPICS:
                unsubscribe = await mqtt.async_subscribe(
                    self._hass, topic, self._async_message_received, qos=0
                )
                self._unsubscribers.append(unsubscribe)
        except Exception:
            for unsubscribe in self._unsubscribers:
                unsubscribe()
            self._unsubscribers.clear()
            raise

    async def async_acquire(self, owner_id: str, message_limit: int) -> None:
        """Share one broker-wide collector between enabled config entries."""
        self._owners[owner_id] = message_limit
        new_limit = max(self._owners.values())
        if self._messages.maxlen != new_limit:
            self._messages = deque(self._messages, maxlen=new_limit)
        self.enabled = True
        try:
            await self.async_start()
        except Exception:
            self._owners.pop(owner_id, None)
            self.enabled = bool(self._owners)
            raise

    async def async_release(self, owner_id: str) -> None:
        """Release an entry and stop when the final owner unloads."""
        self._owners.pop(owner_id, None)
        if self._owners:
            new_limit = max(self._owners.values())
            if self._messages.maxlen != new_limit:
                self._messages = deque(self._messages, maxlen=new_limit)
            return
        self.enabled = False
        await self.async_stop()

    @callback
    def _async_message_received(self, message: ReceiveMessage) -> None:
        """Retain a bounded textual representation of an MQTT message."""
        payload = message.payload
        if isinstance(payload, bytes):
            payload_text = payload.decode("utf-8", errors="replace")
        else:
            payload_text = str(payload)
        payload_text = "".join(
            character if character.isprintable() else " " for character in payload_text
        )
        truncated = len(payload_text) > MAX_PAYLOAD_CHARS
        payload_text = payload_text[:MAX_PAYLOAD_CHARS]
        kind = _message_kind(message.topic, payload_text)
        if len(self._messages) == self._messages.maxlen:
            self._discarded_total += 1
        item = BusMessage(
            timestamp=datetime.now(UTC).isoformat(timespec="milliseconds"),
            topic=message.topic,
            payload=payload_text,
            kind=kind,
            qos=message.qos,
            retained=message.retain,
            truncated=truncated,
        )
        self._messages.append(item)
        self._received_total += 1
        self._kind_counts[kind] += 1
        self._raw_uart_seen |= kind.startswith("uart_")
        for listener in tuple(self._listeners):
            listener()

    async def async_stop(self) -> None:
        """Remove all subscriptions and volatile captures."""
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        self.clear()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a state listener."""
        self._listeners.add(listener)

        @callback
        def remove_listener() -> None:
            self._listeners.discard(listener)

        return remove_listener

    @callback
    def clear(self) -> None:
        """Clear volatile message content but retain lifetime counters."""
        self._messages.clear()
        for listener in tuple(self._listeners):
            listener()

    def export(self, limit: int) -> dict[str, Any]:
        """Return an explicit, user-requested raw activity log."""
        messages = list(self._messages)[-limit:]
        serialized: list[dict[str, Any]] = []
        used_bytes = 0
        omitted = 0
        for message in reversed(messages):
            item = asdict(message)
            item_bytes = len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
            if used_bytes + item_bytes > MAX_EXPORT_BYTES:
                omitted += 1
                continue
            serialized.append(item)
            used_bytes += item_bytes
        serialized.reverse()
        return {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "warning": "May contain SCS addresses, commands, and occupancy patterns",
            "raw_uart_available": self._raw_uart_seen,
            "messages": serialized,
            "omitted_due_to_size": omitted,
            "scope": "Home Assistant MQTT broker; messages are not gateway-attributed",
        }

    @property
    def retained_count(self) -> int:
        """Return the number of volatile messages."""
        return len(self._messages)

    @property
    def last_message_at(self) -> str | None:
        """Return the last message timestamp without its content."""
        return self._messages[-1].timestamp if self._messages else None

    @property
    def diagnostics(self) -> dict[str, Any]:
        """Return privacy-safe aggregate diagnostics."""
        return {
            "enabled": self.enabled,
            "retained_messages": len(self._messages),
            "received_total": self._received_total,
            "discarded_total": self._discarded_total,
            "raw_uart_seen": self._raw_uart_seen,
            "message_kinds": dict(sorted(self._kind_counts.items())),
        }
