# Installation and operation

## Private repository

HACS validates and installs public GitHub repositories. While SCSGATE is
private, install it manually: copy the repository's
`custom_components/scsgate` directory into the Home Assistant configuration
directory, restart Home Assistant, then add **SCSGATE** in **Settings → Devices
& services**.

Do not copy the complete repository into `custom_components`; Home Assistant
loads the integration from the `scsgate` directory.

## HACS after publication

Once the GitHub repository is public, add `Assidefok/SCSGATE` in HACS as a
custom repository of type **Integration**, install it, and restart Home
Assistant. HACS installs it under `custom_components/scsgate`. Releases should
be published as GitHub releases using the same SemVer version as
`custom_components/scsgate/manifest.json`.

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
