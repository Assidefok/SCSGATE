# SCSGATE contributor contract

- Target Home Assistant custom integration domain: `scsgate`.
- Firmware target: ESP32_SCSGATE `VER_7.004`; HTTP API is GET-only and unauthenticated.
- MQTT Discovery remains authoritative for actuator entities. Do not create light, cover, or switch platforms.
- Never persist Wi-Fi or MQTT passwords. Never include sensitive query strings in logs or exceptions.
- Validate gateway hosts as private/local addresses and disable HTTP redirects.
- Destructive actions require explicit confirmation in an options flow. No generic HTTP passthrough service.
- Use async Home Assistant APIs and the HA shared aiohttp session.
- Keep modules typed and independently testable. User-facing strings belong in translation files.
- Tests must not contact a real gateway, broker, or Home Assistant instance.

## Contribution requirements

- Add or update a redacted fixture and tests for every parser or firmware route.
- Update `docs/http-api.md` when endpoint behavior or risk changes.
- Update English, Catalan, and Spanish strings for every user-visible flow.
- Run Ruff, compileall, pytest, Hassfest, and HACS validation before release.
- Never commit real gateway captures, diagnostics, credentials, MAC/IP addresses,
  SSIDs, callback URLs, broker details, or Home Assistant `.storage` data.
