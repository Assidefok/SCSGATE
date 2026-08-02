# Contributing to SCSGATE

Thank you for improving SCSGATE. Small, focused pull requests are easiest to
review. Open a feature or firmware-compatibility issue before a large change.

## Development setup

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements_test.txt
ruff check .
python -m compileall -q custom_components tests
python -m pytest
```

GitHub Actions runs Ruff, pytest, Hassfest, and HACS validation on every pull
request and push to `main`, plus a scheduled daily validation.

## Architecture contract

- MQTT Discovery remains authoritative for SCS actuator entities. Do not add
  `light`, `switch`, or `cover` platforms here.
- Use Home Assistant's shared async HTTP session.
- Keep the HTTP client allowlisted and GET-only. Never add a generic HTTP proxy.
- Accept only literal private/local gateway addresses and keep redirects off.
- Never store or log Wi-Fi/MQTT passwords or sensitive query strings.
- Keep raw telegrams disabled by default and explicitly confirmed.
- Require visible typed confirmation for destructive routes and stop census
  mode on every supported completion/cancellation path.
- Target firmware `VER_7.004`; detect later capabilities instead of assuming.

## Firmware evidence and tests

Every new endpoint or parser behavior needs:

1. A source citation or redacted firmware capture.
2. A fake-gateway fixture with all credentials, addresses, MACs, SSIDs, device
   names, callbacks, and broker details replaced.
3. Positive, malformed-response, timeout, 404, and safety-negative tests where
   applicable.
4. An update to `docs/http-api.md` and all affected translations.

Never test a pull request against a live bus, actuator, or production gateway.

## Pull requests

- Keep changes scoped and explain the firmware evidence.
- Add tests before changing behavior.
- Complete the pull-request security checklist.
- Do not commit generated caches, Home Assistant `.storage`, network captures,
  diagnostics, secrets, or real gateway HTML.
- By submitting, you agree that maintainers may remove sensitive material and
  rewrite affected history if secrets are accidentally committed.
