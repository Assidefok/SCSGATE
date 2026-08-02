# SCSGATE HTTP API (firmware 7.004)

All observed routes use unauthenticated HTTP GET. Keep gateway reachable only on a trusted LAN/VLAN.

| Route | Client method | Risk |
| --- | --- | --- |
| `/`, `/status`, `/help`, `/test`, `/request` | read pages | low |
| `/devicename` | list/save device | medium |
| `/mqttdevices?request=query` | list devices | low |
| `/mqttdevices?request=prepare,start,stop,resend` | guided census / discovery | medium |
| `/mqttdevices?request=clear` | erase census | destructive |
| `/mqttcfg` | broker settings: `broker`, `port`, `user`, `pswd`, `dom`, `dopt`, `log`, `persistence`, `alexa`; GET includes password | secret/high |
| `/setting` | Wi-Fi settings: `ssid`, `pass`, `ip`, `rip`, `uport`; GET includes password | secret/high |
| `/callback`, `/backsetting` | read/write callback | medium |
| `/reset?device=mqtt,esp,pic,all` | reboot subsystem | high except MQTT |
| `/picprog?program=T,Y` | test/flash PIC | destructive for `Y` |

`/scan` intentionally has no client method: firmware can reveal stored Wi-Fi data. `/gate` exposes only typed raw-telegram parameters (`type`, `from`, `to`, `cmd`, `resp`); no generic request proxy exists.
