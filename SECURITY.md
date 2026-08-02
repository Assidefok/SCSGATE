# Security policy

## Supported versions

Security fixes target the latest GitHub release and `main`. Older releases may
not receive backports.

## Report privately

Do not open a public issue for a vulnerability. Use
[GitHub private vulnerability reporting](https://github.com/Assidefok/SCSGATE/security/advisories/new).
If that form is unavailable, contact the repository owner privately through
GitHub before disclosing details.

Include a minimal reproduction using a fake gateway. Do not run raw commands,
reset operations, census clearing, Wi-Fi changes, or PIC programming against a
live installation for a report.

## Remove sensitive data

Redact all credentials and query strings, public or private IP addresses, MAC
addresses, SSIDs, MQTT broker/user details, callback URLs, device names,
diagnostics, screenshots, gateway HTML, and Home Assistant `.storage` content.
Never attach raw `/mqttcfg` or `/setting` URLs.

## Scope

In scope: integration code, parsers, diagnostics, confirmation bypasses, SSRF,
secret exposure, raw-command controls, and CI/release supply-chain behavior.

The firmware's unauthenticated plain-HTTP design, physical access to the SCS
bus, and compromise of the user's trusted LAN are upstream/environment risks
unless the integration makes their impact worse.
