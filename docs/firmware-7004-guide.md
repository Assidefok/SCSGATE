# ESP32_SCSGATE 7.004 modern guide

This guide derives from the official manual and firmware by Guido
Pagani/papergion. Read the
[official manual](https://github.com/papergion/ESPscsgate_32_C3/blob/master/ESPscsgate_32_C3.pdf)
and [official repository](https://github.com/papergion/ESPscsgate_32_C3).
The PDF is linked, not redistributed here.

## Official manual index

- pages 3–5: purpose, disclaimer, board and connections;
- pages 6–8: network and initial configuration;
- pages 9–18: protocol and HTTP operations;
- pages 19–21: MQTT, topics, and device census;
- pages 31–34: historical Home Assistant procedure;
- pages 45–49: TCP, device table, and firmware maintenance;
- page 50: disclaimer.

The Home Assistant pages describe an older workflow. For Home Assistant
2026.7+, install SCSGATE through HACS, add the integration, and use Device
Manager. Do not maintain MQTT entities or browse gateway URLs for routine work.

## Hardware and safety

Follow the official board diagram and polarity. Disconnect power before wiring;
do not work on energized mains equipment. Use a certified supply and enclosure,
retain upstream protection/isolation, and use a qualified installer where local
rules require it. HTTP is unauthenticated and unencrypted: keep the gateway on
a trusted LAN/VLAN and never expose it to the Internet.

## HTTP, census, and MQTT

Firmware routes are listed in [http-api.md](http-api.md). `/mqttdevices` is the
learned inventory. A census rebuilds the global table: operate every existing
and new switch/dimmer; exercise UP, STOP, and DOWN for covers. SCSGATE compares
before/after IDs and republishes Discovery.

Commands and states use `scs/switch/...`, `scs/cover/...`, and for type 11
`scs/generic/...`. Discovery uses
`homeassistant/<component>/<id>/config`. SCSGATE enriches and retains supported
Discovery; it does not replace transport.

## Diagnosis and recovery

Use Device Manager health first, then diagnostics. Check gateway/broker
connectivity, synchronize, and restart HA once after migration. Never publish
raw pages, credentials, MAC/IP addresses, or household device names. Conflicts
create a Repair issue and are not deleted automatically.

The local `appunti_scs.pdf` was consulted only as non-redistributed research.
Alarm, thermostat, and intercom mappings are hypotheses. Alarm work requires
official sources and repeated confirmed captures before read-only sensors are
proposed; controls are out of scope.
