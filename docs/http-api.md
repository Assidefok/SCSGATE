# SCSGATE HTTP API (firmware 7.004)

All observed routes use unauthenticated HTTP GET. Keep gateway reachable only on a trusted LAN/VLAN.

| Route | Client method | Risk |
| --- | --- | --- |
| `/`, `/status`, `/help`, `/test`, `/request` | read pages | low |
| `/devicename` | list/save device | medium |
| `/mqttdevices?request=query` | list devices | low |
| `/mqttdevices?request=prepare,start,stop,resend` | PIC learn mode, asynchronous table import, stop/save, Discovery republish | medium |
| `/mqttdevices?request=clear` | erase census | destructive |
| `/mqttcfg` | broker settings: `broker`, `port`, `user`, `pswd`, `dom`, `dopt`, `log`, `persistence`, `alexa`; GET includes password | secret/high |
| `/setting` | Wi-Fi settings: `ssid`, `pass`, `ip`, `rip`, `uport`; GET includes password | secret/high |
| `/callback`, `/backsetting` | read/write callback | medium |
| `/reset?device=mqtt,esp,pic,all` | reboot subsystem | high except MQTT |
| `/picprog?program=T,Y` | test/flash PIC | destructive for `Y` |

`/scan` intentionally has no client method: firmware can reveal stored Wi-Fi data. `/gate` exposes only typed raw-telegram parameters (`type`, `from`, `to`, `cmd`, `resp`); no generic request proxy exists.

`/request` is an HTML form for sending `/gate` commands; it is not a received
message viewer. The `log` field in `/mqttcfg` is stored by firmware, but its
`SCSLOG` publisher is enclosed in `#ifdef MQTTLOG` and the official 7.004 source
leaves that define commented out. The integration therefore monitors the
normal `scs/#` output and `SCSERROR`, while accepting `SCSLOG` when a compatible
custom firmware build publishes it.

Firmware exposes one global `prepare/start/query/stop` census. It does not
provide a separate cover-only discovery request. The integration's
**Discover covers** action therefore supplies cover-specific UP/STOP/DOWN
instructions while still preserving and presenting the complete global result.

The integration caps callback strings at 97 visible characters. Firmware starts
the callback at EEPROM offset 102 and the next field at 200, so the apparent
128-character web form can overwrite adjacent EEPROM fields.
