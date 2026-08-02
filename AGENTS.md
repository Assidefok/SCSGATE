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

## File ownership during initial parallel implementation

- Protocol agent: `custom_components/scsgate/api.py`, `models.py`, `parsers.py`, protocol fixtures/docs.
- HA core agent: `__init__.py`, `const.py`, `coordinator.py`, entity platforms, `diagnostics.py`, `services.yaml`.
- Admin agent: `config_flow.py`, `strings.json`, `translations/`.
- Parent agent integrates shared contracts and resolves conflicts.
