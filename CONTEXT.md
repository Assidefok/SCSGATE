# SCSGATE domain context

SCSGATE is the user-facing manager for one papergion ESP32_SCSGATE gateway.
Firmware 7.004 owns the learned SCS device table and publishes actuator state
and command topics. Home Assistant MQTT Discovery owns `light`, `switch`, and
`cover` entities. SCSGATE owns inventory, safe HTTP administration, Discovery
metadata reconciliation, diagnostics, and migration guidance.

## Ubiquitous language

- **Bus ID**: two-digit hexadecimal address used by firmware.
- **Gateway device**: one row returned by `/mqttdevices`.
- **Managed device**: gateway row plus MQTT entity, MQTT device, and health.
- **Poor Discovery**: firmware payload with topics and `unique_id`, but no
  `device` or SCSGATE `origin` metadata.
- **Reconciliation**: retained republication of enriched metadata on the same
  Discovery topic and `unique_id`.
- **Conflict**: duplicate `unique_id`, stale topic, or unsafe global namespace;
  never deleted automatically.

## Invariants

- Inventory size is dynamic; nine or eleven devices are observations, not
  limits.
- Existing `unique_id` and topics remain unchanged.
- SCSGATE never edits Home Assistant `.storage`.
- Type 11 and 14 remain visible but uncontrolled.
- A second managed gateway is blocked while firmware uses global `scs` topics.
- Alarm behavior remains research/read-only roadmap work.
