# Changelog

## [0.4.0](https://github.com/Assidefok/SCSGATE/compare/v0.3.0...v0.4.0) (2026-08-02)


### Features

* add SCSGATE v0.4 device manager ([a65a88d](https://github.com/Assidefok/SCSGATE/commit/a65a88d1f57c61f5d85e196ccbc3fcd1071353a7))

## 0.4.0

- Add a dynamic central Device Manager with periodic discovery of new devices.
- Enrich MQTT Discovery with stable device/origin metadata and retained
  republication while preserving existing topics and unique IDs.
- Reconcile firmware payloads, MQTT birth/reconnect, census, edits, and manual
  synchronization without feedback loops.
- Add non-destructive migration, conflict Repairs, type 1 representation, and
  a Discovery-manager rollback option.
- Add firmware 7.004, migration, architecture, attribution, and safety
  documentation; retain MIT and credit Guido Pagani/papergion.

## 0.3.0

- Show device-table queries as `N` numbered entries with type, name and cover
  calibration, and add separate guided actions for device and cover discovery.
- Add opt-in advanced TCP/PIC debug on the fixed LAN port 5045, with one bounded
  temporary session, automatic stock-setting restoration, explicit recovery,
  volatile export, safe aggregate diagnostics, and no generic TCP terminal.
- Add a complete Italian translation while keeping English as the default.
- Add an opt-in, bounded MQTT bus activity monitor for `scs/#`, `SCSERROR`,
  and optional custom-firmware `SCSLOG` traffic.
- Add confirmed on-demand structured log export and volatile-log clearing.
- Show safe capture counters without storing bus messages in entity history or
  ordinary diagnostics.
- Make the guided census poll the asynchronous PIC import, parse the real 7.004
  device-list HTML, and ask users to accept, rescan, or add missing devices.
- Cap callbacks at the firmware EEPROM-safe maximum of 97 characters.
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
