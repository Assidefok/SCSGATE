# SCSGATE monitoring and logging research

## Scope

This note records what the published ESP32 SCSGATE firmware actually exposes for observing received SCS traffic. It targets `VER_7.004` at commit [`16c49fcd799adbf6445dcac6597e8dcab94950c8`](https://github.com/papergion/ESPscsgate_32_C3/commit/16c49fcd799adbf6445dcac6597e8dcab94950c8), where the version is declared in the source ([firmware lines 1-4](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L1-L4)).

Primary sources reviewed:

- The complete firmware sketch and bundled libraries at the pinned commit.
- The bundled first-party `ESPscsgate_32_C3.pdf` manual, especially pages 7-21 ([manual PDF](https://raw.githubusercontent.com/papergion/ESPscsgate_32_C3/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.pdf#page=7)).

## Bottom line

The stock `7.004` firmware has **no HTTP endpoint that can be polled to capture received telegrams**. `/request` is a form for sending a `/gate` command, and `/test` is a page of actuator controls. The complete registered-route list contains no log, capture, stream, or event-history route ([route registry](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L3146-L3176), [`/request`](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L1162-L1181), [`/test`](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L2105-L2241)).

The usable stock interfaces are therefore:

1. decoded MQTT state topics for supported or explicitly censused devices;
2. outgoing HTTP callbacks for a narrow class of abbreviated state messages;
3. the low-level TCP/UDP UART bridge and PIC commands for an advanced, exclusive monitor;
4. `SCSERROR` for one firmware error condition.

None of these is a passive, complete, persistent bus capture API.

## Exposure matrix

| Interface | What is observable | Complete bus? | Pollable? | Persistence / limit |
| --- | --- | --- | --- | --- |
| `/request` | HTML form that sends `/gate` | No | Page only | None |
| `/test` | HTML controls that send `/gate` | No | Page only | None |
| HTTP callback | `type`, `from`, `to`, `cmd` from an exact abbreviated state frame | No | Push GET | Callback configuration persists in ESP EEPROM |
| MQTT state topics | Decoded state for recognised/censused device classes | No | Push via broker | Retain follows `mqtt_persistence` |
| MQTT `SCSLOG` | Raw-ish UART RX/TX log in source | No in stock build | Push via broker | Compiled out; if enabled, QoS 0, not retained, 250-byte formatting buffer |
| MQTT `SCSERROR` | Firmware error text | No | Push via broker | QoS 0, not retained, 250-byte formatting buffer |
| TCP port 5045, UART mode | Raw PIC protocol and continuous `@l` monitor | Potentially, subject to PIC filters/mode | Stream | One TCP client; changes shared gateway/PIC state |
| PIC `@r` / `@R` over TCP or UDP | Next buffered telegram | Potentially, subject to PIC filters/mode | Yes, but not HTTP | Ten telegrams; reads remove entries; oldest data is lost on overflow |
| USB `Serial` | Debug console only in debug builds | No in stock build | Stream | `DEBUG` and `VERBOSE` are disabled |

## HTTP pages are not a message monitor

`/request` renders only a GET form whose action is `/gate`; submitting it transmits a command to the bus. `/test` builds buttons for known lights and covers and its JavaScript also sends `/gate?...&resp=y` ([request implementation](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L1162-L1181), [test controls](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L2105-L2231)). The bundled manual says the same: `request` is a test page that launches a `gate` request ([manual pp. 17-18](https://raw.githubusercontent.com/papergion/ESPscsgate_32_C3/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.pdf#page=17)).

`/gate` accepts `type`, `from`, `to`, `cmd`, and `resp`, writes the corresponding abbreviated command to the PIC UART, and only returns an immediate HTTP response for `resp=i` or `resp=y` ([firmware lines 1183-1321](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L1183-L1321)). It does not return subsequently received bus traffic in its response.

## HTTP callback behaviour

The callback is an outgoing plaintext HTTP GET, not stored capture data. For the normal `resp=a|y` path, it runs only when the received UART message is exactly six bytes with prefix `0xF5`, second byte `y`, then appends `type`, `from`, `to`, and `cmd` as hexadecimal query parameters ([callback dispatch](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L5320-L5348)). Cover percentage-position events are therefore not part of this callback format; the manual also warns that callbacks report only open/close/stop for percentage covers ([manual p. 18](https://raw.githubusercontent.com/papergion/ESPscsgate_32_C3/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.pdf#page=18)).

Normal callback activation is not passive. A caller must issue `/gate?...&resp=y` or `resp=a`, which also transmits a bus command. The firmware saves the caller's IP in a global and uses it as the callback host; another `/gate` caller can replace that destination. The global callback mode has no timer and remains set until another `/gate` changes it or an incoming UDP packet clears it ([global state](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L397-L410), [caller capture and mode](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L1205-L1218), [UDP reset](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L5110-L5126)).

`/callback` displays the current callback string and `/backsetting` persists a replacement in EEPROM ([firmware lines 2257-2281](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L2257-L2281)). There is a firmware storage defect that integration validation must compensate for:

- the callback starts at EEPROM offset 102 and the next field starts at 200, leaving 98 bytes including the terminating NUL ([EEPROM map](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L429-L448));
- the form and RAM buffer allow up to 127 visible characters;
- the selected EEPROM writer has no maximum-length argument ([unbounded writer](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L900-L912)).

The integration must cap callback configuration at **97 visible characters**. Longer input can overwrite the EEPROM signature and later MQTT settings.

The source also contains a separate `resp=W` branch which treats the callback value as a complete URL rather than prefixing the `/gate` caller's IP ([firmware lines 5355-5383](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L5355-L5383)). It is not described as a public monitoring API and must not be exposed as a generic request mechanism.

## MQTT: useful decoded events, not every telegram

The firmware publishes recognised SCS state changes to per-device topics such as:

- `scs/switch/state/<address>`;
- `scs/switch/value/<address>`;
- `scs/cover/state/<address>`;
- `scs/cover/value/<address>`;
- `scs/sensor/temp/state/<address>`.

The topic constants are defined in the firmware ([lines 246-298](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L246-L298)), and publication is conditional on abbreviated `F5/F6 y` messages and recognised device/action mappings ([lines 5542-5793](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L5542-L5793)). The first-party manual describes these as publications for each recognised state notification, not as a raw bus feed ([manual pp. 20-21](https://raw.githubusercontent.com/papergion/ESPscsgate_32_C3/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.pdf#page=20)).

A device censused as type `11` (generic) exposes a closer-to-wire subset:

- `scs/generic/to/<destination>` with payload `<source><type><command>`;
- `scs/generic/from/<source>` with payload `<destination><type><command>`.

The payload is three hexadecimal bytes and is published only when the destination or source address has been explicitly censused as generic. It omits framing, checksum, ACKs, duplicates, and traffic for uncensused addresses ([generic implementation](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L5801-L5844), [manual p. 21](https://raw.githubusercontent.com/papergion/ESPscsgate_32_C3/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.pdf#page=21)).

### `log=y` discrepancy

The manual and `/mqttconfig` UI say `log=y` publishes UART traffic to MQTT ([manual p. 18](https://raw.githubusercontent.com/papergion/ESPscsgate_32_C3/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.pdf#page=18), [configuration handler](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L1324-L1436)). In the pinned `7.004` source, however, `MQTTLOG` is commented out ([firmware lines 98-104](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L98-L104)). Consequently, saving `log=y` persists a flag but the raw UART log calls are absent from the compiled stock build.

If a custom firmware is compiled with `MQTTLOG`, `WriteLog` publishes to topic `SCSLOG` with payload `<milliseconds-since-boot> - <log text>`. It uses a 250-byte formatting buffer, QoS 0, and retain false ([`WriteLog`](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L2284-L2297)). UART receive entries are hexadecimal and start with `s2 rx:`; internal PIC frames include a `>` marker after the prefix ([RX construction](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L5171-L5265)). These logs contain both gateway/PIC protocol traffic and bus-derived data, so `SCSLOG` should not be presented as an exact physical-bus packet capture.

`SCSERROR` is compiled in and uses the same millisecond prefix and 250-byte buffer, QoS 0, retain false ([`WriteError`](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L2299-L2312)). In this source it is called for a UART output-buffer collision ([lines 2601-2610](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L2601-L2610)).

## TCP, UDP, and PIC buffer access

The low-level, first-party documented monitor path is the PIC protocol carried over TCP port 5045 or the configured UDP port. TCP accepts only one client at a time. `#setup {"uart":"tcp"}` opens the TCP-to-UART bridge, and the channel remains selected until a UDP packet is received ([manual pp. 7-9](https://raw.githubusercontent.com/papergion/ESPscsgate_32_C3/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.pdf#page=7), [TCP accept loop](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L4594-L4624), [UART setup](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L4888-L4951)).

The PIC commands relevant to monitoring are documented as follows:

- `@r`: return and remove the next buffered telegram; length `0` means none is waiting;
- `@R`: return and remove the next telegram, deferring the response until one arrives;
- `@c`: cancel a deferred `@R` wait;
- `@l`: enable a continuous text/hex log of received and transmitted messages;
- `@d`: dump receive buffers in ASCII mode;
- `@F`: configure duplicate, ACK, and state-message filters;
- `@Y`: select full or abbreviated telegram format.

The PIC has a ten-telegram receive buffer. Unread traffic overflows it and loses the oldest telegrams; reads are destructive ([manual pp. 9-14](https://raw.githubusercontent.com/papergion/ESPscsgate_32_C3/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.pdf#page=9)). The manual's TCP monitor example uses ASCII mode and `@l` and shows complete-looking lines such as `SCS[0]: A8 32 00 12 01 21 A3` ([manual pp. 7-8](https://raw.githubusercontent.com/papergion/ESPscsgate_32_C3/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.pdf#page=7)).

Normal HTTP/MQTT initialisation deliberately configures the PIC temporarily for hexadecimal mode, abbreviated four-byte messages, filter `3` (deduplicate and suppress ACK), and continuous logging ([`setFirst`](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L821-L848)). Therefore the gateway's normal decoded stream is intentionally not all physical traffic.

### Source-only TCP debug switch

The source recognises unauthenticated `#setup {"debug":"tcp"}` and sets `tcpuart=2` ([firmware lines 4888-4931](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L4888-L4931)). In stock `7.004`, raw RX/TX forwarding for this mode is compiled out because `DEBUG_FAUXMO_TCP` is commented in `fauxmoESP.h` ([macro](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/fauxmoESP.h#L39-L44), [guarded RX forwarding](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L5199-L5274)). It can still emit decoded MQTT `sub:` and `pub:` lines because those blocks are not behind that macro ([incoming MQTT](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L2367-L2377), [outgoing MQTT](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L5771-L5793)). It is not a complete bus monitor in the published build.

## USB serial output

The stock build does not initialise the USB debug console. Both `DEBUG` and `VERBOSE` are commented, and `Serial.begin()` is conditional on one of them. `Serial1` is the internal 115200 8N2 link to the PIC, not a user-facing log ([build flags](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L28-L32), [serial setup](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L3716-L3746)).

## Security and privacy implications

- HTTP, outgoing callbacks, TCP, UDP, and the default MQTT client are plaintext. The firmware uses `WiFiClient`, not a secure MQTT transport ([client construction](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L313-L331)).
- No authentication is applied to the route registry or TCP command channel; even the dormant HTTP authentication calls in `handleGate` are commented ([firmware lines 1190-1194](https://github.com/papergion/ESPscsgate_32_C3/blob/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.ino#L1190-L1194)).
- Bus events can reveal device addresses, room activity, occupancy patterns, alarm events, and control commands. Raw captures should be treated as sensitive even when Wi-Fi and broker credentials are removed.
- Callback paths may themselves contain tokens or identifiers, are returned by `/callback`, and persist in EEPROM.
- A TCP monitor competes for the single TCP client and changes shared PIC UART mode/filter state. HTTP, MQTT, TCP, and UDP can reset or reinterpret those settings; the manual explicitly warns against mixing modes ([manual pp. 18 and 21](https://raw.githubusercontent.com/papergion/ESPscsgate_32_C3/16c49fcd799adbf6445dcac6597e8dcab94950c8/ESPscsgate_32_C3.pdf#page=18)).

## Implementation implications for the Home Assistant integration

1. **Implement a safe decoded-event monitor first.** Subscribe through Home Assistant's MQTT integration to the known `scs/...` state topics plus `SCSERROR`. Label it “Gateway MQTT events”, not “complete SCS bus capture”. Do not create duplicate actuator entities.
2. **Make capture explicit and temporary.** Default off; bounded in-memory ring (for example, 200-1,000 events), maximum session duration, clear-on-reload, and a visible stop/clear action. Do not write every event to Home Assistant's persistent logger.
3. **Generate logs on demand.** Export a timestamped JSONL or text report only after explicit user action. Include capture mode, firmware, dropped-event count, parser outcome, and decoded fields. Remove Wi-Fi/MQTT credentials, host addresses, callback values, and query strings. Warn that bus addresses and activity remain sensitive.
4. **Treat `SCSLOG` as an optional capability.** Listen for it only when the user enables advanced raw logging. Its presence indicates a custom/debug firmware; `log=y` alone is not proof. Bound and truncate payloads before display/export.
5. **Do not claim raw support on stock `7.004`.** A complete raw monitor requires either a custom firmware with logging enabled or an experimental exclusive TCP-UART session. The latter must be disabled by default, guarded by strong warnings, restore the firmware's `@MX`, `@Y1`, `@F3`, `@l` working mode, release TCP mode, and handle disconnects without leaving the gateway reconfigured.
6. **Do not use callbacks as the primary monitor.** They are incomplete, armed through a bus-writing `/gate` call, globally mutable, persistent, and plaintext. Enforce the 97-character callback maximum immediately.
7. **Prefer an upstream firmware capability for true capture.** A read-only, bounded stream (or documented MQTT raw topic) with explicit enable/disable and no credential-bearing configuration would be safer than driving the shared PIC UART protocol from Home Assistant.
