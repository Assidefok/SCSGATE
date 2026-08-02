# Device Manager

Open **Settings > Devices & services > SCSGATE > Configure > Device Manager**.
The table is generated from the gateway. It is not hard-coded and has no nine-
or eleven-device limit.

Rows show bus ID, firmware type, name, MQTT component, entity, and health:

- `grouped`: entity is attached to an MQTT device;
- `pending_restart`: enriched Discovery was published; plan one HA restart;
- `unsupported`: visible inventory only (types 11 and 14);
- `conflict`: duplicate identity needs guided review.

## Automatic synchronization

SCSGATE synchronizes at setup, Home Assistant MQTT birth/reconnect, after
census, after edits, manually, after poor firmware Discovery, and every
**Status interval** (default five minutes). New devices therefore appear
without entering their IDs manually.

Payloads use `retain: true`, a stable `device` block, SCSGATE `origin`, and a
link to the integration. Firmware topics and `unique_id` remain unchanged.
Reconciliation is coalesced to prevent loops.

## Type matrix

| Firmware type | Home Assistant representation |
|---|---|
| 1 | switch by default; per-device light option |
| 3, 4 | dimmable light |
| 8, 18 | cover |
| 9, 19 | position cover |
| 11 | inventory only; no control |
| 14 | inventory only; alarm roadmap |

Changing type 1 between `switch` and `light` changes entity domain. Review
automations and dashboards first.

## v0.4 migration and repair

SCSGATE republishes supported devices non-destructively. The same Discovery
topic and `unique_id` preserve the MQTT entity and registry customization.
Existing MQTT device identifiers are reused when unambiguous. SCSGATE never
edits `.storage` and never automatically deletes duplicates or stale topics.

For a conflict, create a full Home Assistant backup, open **Device Manager >
Repair**, review, confirm, synchronize, and perform one planned HA restart. To
roll back, disable **Manage MQTT Discovery in SCSGATE** under Advanced options.

Firmware 7.004 uses global `scs/...` topics. The manager blocks a second entry
because two gateways cannot be attributed safely.
