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

### Safe protocol analysis

When ordinary debug logs are insufficient, open **SCSGATE > Configure >
Advanced** and enable **Safe protocol analysis**. Reloading the config entry
activates an in-memory analyzer for every successful gateway response,
including status polling and administration actions.

The analyzer reports only:

- operation ID and fixed endpoint path;
- response character, line, HTML-tag, and key/value counts;
- the count of labels that may contain sensitive values;
- fixed anomaly codes for empty/oversized responses, NUL characters, or
  missing expected status/device markers.

It never stores field values, request parameters, response bodies, hashes,
device names, network identifiers, or credentials. Only the most recent 25
observations remain in memory, and they are cleared on integration reload or
Home Assistant restart. Download diagnostics after reproducing the fault, then
turn the option off.

### Bus activity monitor

The optional bus monitor subscribes passively to the broker-wide documented
MQTT namespace. It cannot attribute a message to a specific gateway when more
than one gateway shares the same broker. It keeps 10–500 recent messages in memory and clears them on
reload or restart. Use the **Bus monitor** diagnostic sensor for counts and
`scsgate.export_bus_log` with `confirm: true` to inspect the actual messages.
The response is intended for Developer Tools > Actions and can be copied into a
temporary support file. Do not call the export from an automation or forward
its response to notifications. Clear it with `scsgate.clear_bus_log` after use;
aggregate lifetime counters intentionally remain until reload.

The official 7.004 source has `MQTTLOG` commented out. Consequently, ordinary
firmware exposes interpreted `scs/...` states and `SCSERROR`, while raw UART
RX/TX on `SCSLOG` is available only in a firmware build that enables that
compile-time feature. The integration detects `SCSLOG` automatically if it
appears; it never enables a TCP debug channel or consumes the PIC's small RX
buffer.

### Guided device learning

Choose **Configure > Devices > Discover devices**, then physically operate each
required SCS device. For focused guidance choose **Discover covers**, operate
every device because firmware rebuilds one global table, and exercise
UP/STOP/DOWN on every cover. Starting the import transfers the PIC's learned
table to the ESP. SCSGATE polls without blocking Home Assistant, then shows `N`
numbered entries with exact addresses, inferred types, names and available
cover calibration. Accept the list, repeat the scan, or choose the manual-add
path for a missing light, dimmer, cover, generic device, or alarm.
If the browser flow is abandoned, a best-effort cleanup stops PIC learning
after ten minutes; **Stop an abandoned census** is also available immediately.
