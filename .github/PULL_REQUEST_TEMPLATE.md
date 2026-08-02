## Summary

Describe the change and why it is needed.

## Firmware evidence

Link the source or describe the fully redacted fixture/capture used.

## Security impact

Choose one: **none** / **explain below**.

## Checklist

- [ ] Change is focused and tests were added or updated.
- [ ] `ruff check .`, compileall, and `python -m pytest` pass.
- [ ] No credentials, URLs, query strings, captures, IP/MAC addresses, SSIDs,
      callback/broker details, diagnostics, or `.storage` data are included.
- [ ] HTTP routes remain explicitly allowlisted; redirects and public hosts stay blocked.
- [ ] Sensitive values cannot appear in logs, exceptions, or diagnostics.
- [ ] Destructive actions have typed confirmation and safe cancellation cleanup.
- [ ] MQTT Discovery remains authoritative; no actuator entities are duplicated.
- [ ] HTTP API documentation and English/Catalan/Spanish strings were updated.
