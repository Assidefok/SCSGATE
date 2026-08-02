"""Secret-free structural analysis of SCSGATE HTTP responses."""

from __future__ import annotations

import re
from collections import deque
from dataclasses import asdict, dataclass
from typing import Final

DEFAULT_OBSERVATION_LIMIT: Final = 25
MAX_EXPECTED_BODY_CHARS: Final = 262_144
_TAG_RE: Final = re.compile(r"<[^>]{1,256}>")
_KEY_VALUE_RE: Final = re.compile(r"\b[a-z][a-z0-9_ -]{0,40}\s*[:=]", re.I)
_SENSITIVE_LABEL_RE: Final = re.compile(
    r"\b(?:pass(?:word)?|pswd|ssid|broker|user(?:name)?|callback|token|secret)\b",
    re.I,
)


@dataclass(frozen=True, slots=True)
class ProtocolObservation:
    """A response's structure without any response values or identifiers."""

    operation_id: str
    endpoint: str
    body_chars: int
    line_count: int
    html_tag_count: int
    key_value_count: int
    sensitive_label_count: int
    anomaly_codes: tuple[str, ...]


class ProtocolDebugAnalyzer:
    """Analyze every response in memory while retaining only safe statistics."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        observation_limit: int = DEFAULT_OBSERVATION_LIMIT,
    ) -> None:
        self.enabled = enabled
        self._observations: deque[ProtocolObservation] = deque(
            maxlen=max(1, observation_limit)
        )
        self._observations_total = 0
        self._anomalies_total = 0

    def analyze(
        self, operation_id: str, endpoint: str, body: str
    ) -> ProtocolObservation | None:
        """Analyze one body and immediately discard its content."""
        if not self.enabled:
            return None

        body_lower = body.lower()
        anomaly_codes: list[str] = []
        if not body.strip():
            anomaly_codes.append("empty_response")
        if len(body) > MAX_EXPECTED_BODY_CHARS:
            anomaly_codes.append("oversized_response")
        if "\x00" in body:
            anomaly_codes.append("nul_character")
        if endpoint == "/status" and not any(
            marker in body_lower for marker in ("esp32_scsgate", "mqtt", "pic")
        ):
            anomaly_codes.append("status_markers_missing")
        if (
            endpoint == "/devicename"
            and body.strip()
            and not any(
                marker in body_lower for marker in ("busid", "bus_id", "devname")
            )
        ):
            anomaly_codes.append("device_markers_missing")

        observation = ProtocolObservation(
            operation_id=operation_id,
            endpoint=endpoint,
            body_chars=len(body),
            line_count=len(body.splitlines()) if body else 0,
            html_tag_count=len(_TAG_RE.findall(body)),
            key_value_count=len(_KEY_VALUE_RE.findall(body)),
            sensitive_label_count=len(_SENSITIVE_LABEL_RE.findall(body)),
            anomaly_codes=tuple(anomaly_codes),
        )
        self._observations.append(observation)
        self._observations_total += 1
        self._anomalies_total += len(anomaly_codes)
        return observation

    @property
    def diagnostics(self) -> dict[str, object]:
        """Return a safe diagnostic snapshot of retained observations."""
        return {
            "enabled": self.enabled,
            "observations_total": self._observations_total,
            "anomalies_total": self._anomalies_total,
            "retained_observations": [
                asdict(observation) for observation in self._observations
            ],
        }
