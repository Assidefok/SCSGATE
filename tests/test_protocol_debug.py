"""Safe full-response protocol analyzer tests."""

from custom_components.scsgate.protocol_debug import (
    MAX_EXPECTED_BODY_CHARS,
    ProtocolDebugAnalyzer,
)


def test_protocol_debug_disabled_retains_nothing() -> None:
    analyzer = ProtocolDebugAnalyzer(enabled=False)

    assert analyzer.analyze("http-000001", "/status", "private body") is None
    assert analyzer.diagnostics == {
        "enabled": False,
        "observations_total": 0,
        "anomalies_total": 0,
        "retained_observations": [],
    }


def test_protocol_debug_analyzes_full_body_without_retaining_values() -> None:
    analyzer = ProtocolDebugAnalyzer(enabled=True)
    private_values = (
        "My Secret WiFi",
        "mqtt-user",
        "mqtt-password",
        "192.168.50.25",
    )
    body = (
        "<html><body>ESP32_SCSGATE VER_7.004<br>"
        f"ssid: {private_values[0]}<br>"
        f"broker: mqtt://{private_values[1]}:{private_values[2]}@"
        f"{private_values[3]}<br>MQTT connection is OPEN</body></html>"
    )

    observation = analyzer.analyze("http-000001", "/status", body)
    diagnostics = analyzer.diagnostics

    assert observation is not None
    assert observation.body_chars == len(body)
    assert observation.html_tag_count > 0
    assert observation.key_value_count > 0
    assert observation.sensitive_label_count > 0
    assert observation.anomaly_codes == ()
    serialized = str(diagnostics)
    for private_value in private_values:
        assert private_value not in serialized


def test_protocol_debug_detects_malformed_structures_and_bounds_history() -> None:
    analyzer = ProtocolDebugAnalyzer(enabled=True, observation_limit=2)

    analyzer.analyze("http-000001", "/status", "")
    analyzer.analyze("http-000002", "/status", "unknown format\x00")
    analyzer.analyze("http-000003", "/devicename", "unexpected device page")
    diagnostics = analyzer.diagnostics

    assert diagnostics["observations_total"] == 3
    assert diagnostics["anomalies_total"] == 5
    retained = diagnostics["retained_observations"]
    assert isinstance(retained, list)
    assert [item["operation_id"] for item in retained] == [
        "http-000002",
        "http-000003",
    ]
    assert retained[0]["anomaly_codes"] == (
        "nul_character",
        "status_markers_missing",
    )
    assert retained[1]["anomaly_codes"] == ("device_markers_missing",)


def test_protocol_debug_flags_oversized_response_without_storing_it() -> None:
    analyzer = ProtocolDebugAnalyzer(enabled=True)
    private_body = "x" * (MAX_EXPECTED_BODY_CHARS + 1)

    observation = analyzer.analyze("http-000001", "/help", private_body)

    assert observation is not None
    assert observation.anomaly_codes == ("oversized_response",)
    assert private_body not in str(analyzer.diagnostics)
