# Changelog

## 0.2.0

- Show device-table queries as `N` numbered entries with type, name and cover
  calibration, and add separate guided actions for device and cover discovery.
- Add a complete Italian translation while keeping English as the default.
- Add an opt-in, bounded MQTT bus activity monitor for `scs/#`, `SCSERROR`,
  and optional custom-firmware `SCSLOG` traffic.
- Add confirmed on-demand structured log export and volatile-log clearing.
- Show safe capture counters without storing bus messages in entity history or
  ordinary diagnostics.
- Make the guided census poll the asynchronous PIC import, parse the real 7.004
  device-list HTML, and ask users to accept, rescan, or add missing devices.
- Cap callbacks at the firmware EEPROM-safe maximum of 97 characters.

## 0.1.3

- Add secret-free operation IDs, HTTP timing/status metrics, parser counts,
  census progress, maintenance logging, and redacted transport diagnostics.
- Add opt-in, bounded, in-memory protocol analysis for every HTTP response,
  retaining only structural counters and fixed anomaly codes.
- Redact exact `wifi_ssid`, `mqtt_broker`, and `mac` diagnostic fields.
- Update HACS installation and safe-debug documentation for the public repo.

## 0.1.2

- Replace the solid blue application-icon background with verified alpha
  transparency while retaining the blue/cyan and copper gateway artwork.

## 0.1.1

- Make private-repository GitHub Actions checkout work with read-only contents.
- Fix pytest package discovery on GitHub-hosted Linux runners.
- Correct the HACS manifest and add required repository topics and brand icon.
- Add daily HACS, Hassfest, Ruff, compile, and pytest validation.
- Pin CI actions and add Dependabot updates.
- Add contribution, security, issue, firmware, and pull-request templates.
- Add the original blue SCS bus and ESP32 gateway application icon.

## 0.1.0

- Initial SCSGATE Home Assistant integration for firmware `VER_7.004`.
