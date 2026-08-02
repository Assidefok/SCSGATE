# SCSGATE

Home Assistant custom integration for ESP32_SCSGATE firmware `VER_7.004`.
It keeps the firmware's native MQTT Discovery entities and adds safe gateway
setup, diagnostics, device census, and guarded HTTP administration.

> The gateway HTTP server has no active authentication and sends configuration
> values through plain HTTP GET requests. Keep it on a trusted LAN/VLAN. Never
> expose it to the Internet.

## Features

- Gateway, firmware, Wi-Fi, and MQTT diagnostics.
- Guided MQTT device census and Discovery republish.
- Manual device naming, type selection, and cover calibration.
- Transient MQTT/Wi-Fi configuration; Home Assistant never stores passwords.
- Guarded gateway/PIC reset, callback, and firmware tools.
- Opt-in raw SCS telegram service with strict validation and confirmation.
- No duplicate `light`, `switch`, or `cover` entities: native MQTT owns them.

## Install and configure

This repository is private. HACS supports public GitHub repositories only, so
install this version manually:

1. Copy `custom_components/scsgate` into your Home Assistant configuration
   directory as `custom_components/scsgate`.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration**, choose
   **SCSGATE**, and enter the gateway's private LAN IP address and HTTP port.

When the repository becomes public, add it in HACS as a custom **Integration**
repository, install it, restart Home Assistant, then use the same setup flow.
See [installation notes](docs/installation.md) for upgrade and troubleshooting
guidance.

## Safety model

- Safe reads and MQTT republish are direct actions.
- Census, network changes, EEPROM clearing, processor resets, and PIC
  programming use explicit confirmation flows.
- Wi-Fi and MQTT passwords exist only for the duration of the submitted form.
- Raw SCS telegrams are disabled by default and require `confirm: true`.
- There is no generic HTTP passthrough service.

See [HTTP API coverage](docs/http-api.md) for the firmware route matrix and
[the primary sources](docs/research/scsgate-primary-sources.md) for the
firmware/manual versions used by this integration.

## Development

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements_test.txt
ruff check .
pytest
```

## Credits

Based on the ESP32_SCSGATE firmware and documentation by papergion. SCSGATE,
SCS, and BTicino/Legrand product names belong to their respective owners.
