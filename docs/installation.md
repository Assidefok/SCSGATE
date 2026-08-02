# Installation and operation

## HACS installation

SCSGATE is a public repository validated by HACS. Open HACS, select **Custom
repositories**, add `https://github.com/Assidefok/SCSGATE` as an
**Integration**, install it, and restart Home Assistant. HACS installs it under
`custom_components/scsgate`.

For a manual installation, copy only the repository's
`custom_components/scsgate` directory into the Home Assistant configuration
directory and restart Home Assistant. Do not copy the complete repository into
`custom_components`.

## First connection

The configuration flow accepts only a literal private, loopback, or link-local
IP address and an HTTP port. It identifies the gateway by its MAC address, so a
gateway cannot be added twice through a different address.

The ESP32_SCSGATE HTTP interface is unauthenticated and uses plain HTTP GET,
including for Wi-Fi and MQTT configuration. Keep it on a trusted LAN/VLAN;
never port-forward or expose it to the Internet. Home Assistant never stores
Wi-Fi or MQTT passwords submitted through the SCSGATE options flow.

## Updates and recovery

Restart Home Assistant after installing or upgrading the integration. MQTT
Discovery remains responsible for the individual light, switch, and cover
entities; if they are missing, first confirm the gateway's MQTT connection and
use **Resend MQTT Discovery** from the SCSGATE device.

The integration's options flow contains guarded actions for census, network
configuration, resets, and destructive operations. Read the confirmation text
carefully. It intentionally has no arbitrary HTTP request feature.

## Safe diagnostics and debug logging

Home Assistant can download integration diagnostics from **Settings > Devices
& services > SCSGATE > Download diagnostics**. Before export, SCSGATE redacts:

- gateway host and MAC;
- Wi-Fi SSID and MQTT broker information;
- usernames, passwords, tokens, callbacks, and URLs;
- the saved pre-clear device snapshot.

The export retains only useful non-sensitive transport metrics: request and
failure counts, the last operation ID, endpoint path, HTTP status, duration,
and response character count.

Enable temporary debug logging with:

```yaml
logger:
  default: info
  logs:
    custom_components.scsgate: debug
```

After restarting Home Assistant, reproduce the problem once and inspect
**Settings > System > Logs**. Correlate messages by `operation_id`. Logs report
endpoint paths, status codes, timings, parser counts, census stages, and
maintenance actions. They deliberately omit the host, query string, submitted
values, response body, device names, and credentials. Disable the override when
finished.

The gateway's own `/test`, `/request`, and `/help` pages remain available on
the trusted LAN. Do not attach their raw contents to a public issue because the
firmware may display network or MQTT configuration.
